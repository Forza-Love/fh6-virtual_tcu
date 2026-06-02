# 升降挡算法与模式优化计划

> 日期：2026-05-27（2026-05-31 更新）
>
> 范围：`virtual_tcu/logic/tcu.py`、`virtual_tcu/detectors/airtime.py`、模式枚举/配置、前端模式展示与输入输出层。

## 进度状态（2026-05-31）

- **P0 / P1 已完成**：Race 动力降挡、腾空/落地状态机、对应测试与回放指标均已落地（见第七节清单勾选项）。
- **P2-new 已完成**：vgamepad LT 刹车中断修复（虚拟 LT 镜像物理刹车，方案 B）已实现并通过 mock 验证。
- **P3-new 已撤销**：Race 高转不升挡，经回放实测推翻原假设（升挡反而更慢），不做修复，详见第六节。
- **现状变化**：`Mode` 枚举/`MODE_ORDER`/前端 `DRIVE_MODES` 已新增 `MANUAL` 模式；输出层接口已从 `shift_up/shift_down/shift_down_double` 重构为统一的 `shift_to(from_gear, target_gear)`；vjoy 输出已落地并自带一套（直选 + 可选离合）实现。下面的 P5/P6 旧描述按新接口重写。
- **当前待办**：P4-new vjoy 配置面板、P5 Dynamic 合并、P6 离合辅助（重写）。

## 结论先行

1. **Dynamic 冗余分析基本成立**：当前 `DYNAMIC` 没有独立换挡算法，只是在 `COMFORT` 与 `RACE` 行为之间按 `DriveStyleTracker.regime` 做参数切换。它适合合并，但不应作为当前用户反馈的第一修复点。
2. **Race 降挡不积极是真问题**：现有 Race 的非制动降挡几乎只在爬坡触发，平路出弯、落地后低转大油门不会主动补挡，且上/下挡冷却会放大迟滞。（P0 已修，保留作背景）
3. **腾空锁挡可能失效或落地后恢复慢**：`AirtimeDetector` 依赖“低垂向加速度 + 四轮全部高 slip”，触发条件偏窄；落地后没有专门的 recovery 状态，普通 Race 逻辑又受 `climb_only`、`_no_downshift_until`、post-shift lock 影响。（P0 已修，保留作背景）
4. **离合按键不应作为 P0 修复**：离合只能降低游戏内换挡执行延迟，不能解决“该不该降挡”的算法问题。可作为 opt-in 实验功能，对使用 “Manual with Clutch” 且按键映射正确的玩家可能有实际提升；默认开启风险较高。
5. **vgamepad LT 刹车中断是高优先级回归**：虚拟手柄每次 `update()` 发送完整设备状态包，包内 LT=0 会覆盖物理手柄持续输入的 LT（刹车）信号，导致刹车中断、刹车灯闪烁。属于直接影响现有手柄用户的体验 bug，优先级高于 P2/P3。
6. **Race 高转不升挡——经实测已撤销**：原假设「早峰值车功率下降仍不升挡」被回放数据推翻。跨挡功率对比表明该车在限速器附近保持低挡才最快，升挡反而损失 16–35 kW；且现有代码本就会在 ~99% rpm 升挡。日志来自旧发行版（P0/P1 之前）。**不做修复**，详见第六节。

推荐实施顺序（2026-05-31 修订）：

1. ~~P0：修复 Race 降挡积极性、腾空/落地状态机与落地补降挡。~~（已完成）
2. ~~P1：基于回放/实车日志调参并补测试。~~（已完成）
3. **P2-new：vgamepad LT 刹车中断修复**（用户反馈中的明确回归，改动小、收益直接，建议最先做）。
4. ~~P3-new：Race 高转不升挡修复~~（经实测撤销，详见第六节）。
5. **P4-new：vjoy 输出配置面板**（让 vjoy 模式对用户可选、可配置，补齐 PR 遗留的前端缺口）。
6. P5：合并 Dynamic 到 Comfort/Race，减少模式困惑（原 P2，无紧迫性）。
7. P6：离合辅助跨输出统一（原 P3，重写为 `shift_to` 接口；vjoy 已有简版实现）。


---

## 一、现状核对

### 1. 模式分发链

`TCULogic._process_internal()` 统一处理：

- 暂停/菜单恢复状态清理
- `td.is_shifting` 早退
- 玩家/游戏自身挡位变化导致的上下挡锁
- 历史油门/刹车/速度更新
- 齿比、功率曲线、rev limiter、腾空、yaw transient、drive style 学习
- 倒挡、起步、post-shift lock、挡位不匹配、低速、弯道锁
- 最后按 `Mode` 分发到 `COMFORT / DYNAMIC / RACE / DRIFT / OFFROAD`

这说明模式函数只负责“自动模式核心换挡策略”，不少影响 Race 体验的锁定逻辑发生在模式分发之前或 `_shift_up/_shift_down` 内。

### 2. Race 当前降挡路径

`_mode_race()` 的关键链路：

```text
ANTI-STALL
→ _blocked_by_transient()
→ _track_brake_down(brake_thr = brake_thr * 0.6)
→ wheelspin upshift
→ _track_out_of_band_kickdown(climb_only=True)
→ _track_upshift_in_band(offset=0.03)
→ RACE in band
```

主要问题：

- `_track_out_of_band_kickdown(..., climb_only=True)` 要求 `_on_climb(td)` 成立。用户常见场景“平路出弯 / 落地后大油门低转”不会进入降挡。
- `_should_brake_downshift()` 在 `feat_brake_curve=True` 时，Race 传入的低 `brake_thr` 经常被二次条件抵消：需要刹车 spike 或持续大于约 0.55。结果是 `brake_thr * 0.6` 的意义不足。
- `_shift_down()` 对 `KICKDOWN / PREDICTIVE / TORQUE DOWN / BAND DOWN` 设置 0.70s 串联降挡锁。Race 快速降 2-3 个挡时会显得拖沓。
- `_shift_up()` 所有模式统一设置 `self._no_downshift_until = now + 1.0`。Race 刚升挡后遇到坡顶/落地/出弯低转，1 秒内不能纠正。
- `_track_brake_down()` 只有制动场景会用齿比选择目标挡位；动力需求降挡仍是单挡试探。

### 3. 腾空锁挡当前风险

`AirtimeDetector` 当前条件：

```text
speed_kmh > 20
and abs(accel_y) < 3.0
and all(abs(wheel_slip) > 1.2)
连续 3 帧进入腾空，连续 2 帧退出
```

风险点：

- 四轮 slip 全部大于阈值过严。部分车辆有 TCS、AWD 或轮速变化不明显时，真实腾空可能无法满足。
- 只用 `accel_y` 与 slip，未利用 `vel_y`。坡顶、跳台、落地过程中的垂向速度对状态转换很有价值。
- 退出腾空后只恢复普通模式，没有 `just_landed` / `landing_recovery_until`。落地时如果挡位过高，Race 仍按普通 `climb_only` 规则判断，可能不降挡。
- `_process_internal()` 中检测到非 TCU 的挡位变化时，在 airborne 下不会增加 `_no_downshift_until/_no_upshift_until`，但如果上一次 TCU 自己升挡或其他锁已经存在，落地后仍可能被锁住。

### 4. Dynamic 冗余程度

当前 `DYNAMIC` 的价值主要是 `DriveStyleTracker`：

- `CRUISE / ADAPTIVE` 分支接近 Comfort，差异是阈值与是否开启 transient block。
- `SPORT` 分支接近 Race，差异是制动阈值、upshift offset 与 fallback。
- 没有独有的目标挡位选择、腾空恢复、功率带策略或特殊场景规则。

因此“删除 Dynamic，保留 DriveStyleTracker 并服务 Comfort/Race”的方向正确。但删除模式涉及后端枚举、配置迁移、前端模式列表、HUD 颜色、历史配置兼容，建议排在 Race/腾空 P0 修复之后。

---

## 二、P0 修复方案：Race 降挡更积极

### 目标

Race 模式应在以下场景更快回到动力带：

- 出弯低转大油门
- 高挡巡航后突然全油门
- 落地后车速仍高但挡位过高
- 重刹后准备重新加速

同时必须保留：

- over-rev 保护
- 弯中不乱升挡
- 腾空时不误触发换挡
- 轮胎严重空转时避免误把打滑当成加速需求

### 方案 A：新增 Race 专用动力需求降挡

在 `_mode_race()` 中，把“动力需求降挡”放在制动降挡之后、wheelspin upshift 之前或之后按实测调整：

```text
ANTI-STALL
→ AIRBORNE / TRANSIENT BLOCK
→ LANDING RECOVERY（见下一节）
→ TRACK BRAKE DOWN
→ RACE POWER DOWN
→ WHEELSPIN UPSHIFT
→ CLIMB BAND DOWN
→ UPSHIFT IN BAND
```

新增 helper 建议：

```python
def _track_power_demand_downshift(
    self,
    td: Telemetry,
    now: float,
    *,
    min_throttle: float = 0.68,
    target_floor: float = 0.60,
    lock_ms: int = 300,
    allow_skip: bool = True,
) -> bool:
    ...
```

触发建议：

- `td.throttle >= 0.68`
- `td.brake < 0.08`
- `td.gear > 2`
- `td.speed_kmh > 25`
- `td.rpm_pct < threshold`
  - 有功率曲线：`threshold = max(0.58, peak_torque_rpm - 0.05)`
  - 无功率曲线：`threshold = 0.60`
- 如果刚重刹结束 2 秒内，可把 `min_throttle` 降到 `0.45`，因为这通常是弯后补油。

目标挡位选择：

- 优先用齿比表算目标挡位，而不是单挡试探。
- 目标转速区间：
  - 自吸/普通：峰值扭矩到峰值功率之间偏扭矩侧，例如 `peak_torque + (peak_power - peak_torque) * 0.45`
  - 无功率曲线：`0.72 * engine_max_rpm`
  - turbo lag 存在时可更接近 `0.75-0.80`，避免升挡后低增压。
- 只选择 projected RPM `< real_redline * 0.98` 的挡位。
- 如果目标挡位小于当前挡位 2 个以上，允许 skip down，但建议先限制为最多双降，避免输入堆叠。

### 方案 B：Race 下调降挡锁

把 `_shift_down()` 的锁定时间从“按 state 写死”改为可选参数：

```python
def _shift_down(
    self,
    td: Telemetry,
    lock_ms: int,
    state: str,
    sub: str = "",
    *,
    cascade_lock_s: float | None = None,
) -> bool:
```

Race 专用建议：

- `BRAKE DOWN`: 0.22-0.30s
- `RACE POWER DOWN`: 0.30-0.40s
- `BAND DOWN`: 0.35-0.45s
- 普通 Comfort/Dynamic 保持当前 0.60-0.90s，避免日常驾驶 hunting。

同时考虑给 `_shift_up()` 增加 `downshift_lock_s` 参数：

```python
def _shift_up(..., *, downshift_lock_s: float = 1.0) -> bool:
```

Race upshift 可降到 `0.45-0.60s`；如果处于 landing recovery，可进一步允许“低转大油门 override”。

### 方案 C：Race 制动降挡绕开过严 brake curve

当前 `brake_thr` 在 Race 中乘以 0.6，但 `_should_brake_downshift()` 又要求刹车 spike 或持续重刹。建议给 track brake down 单独入口：

```python
def _should_track_brake_downshift(self, td: Telemetry, base_thr: float) -> bool:
    if td.brake < base_thr:
        return False
    if self._brake_is_spike():
        return True
    if td.brake > 0.30 and self._speed_decreasing(delta=0.8):
        return True
    if td.brake > 0.45:
        return True
    return False
```

这样 Race/Offroad 的制动降挡不再被 Comfort 的平顺策略束缚。

---

## 三、P0 修复方案：腾空锁挡与落地补降挡

### 目标

- 腾空期间可靠锁住自动换挡，避免空中乱升/乱降。
- 落地后短时间内优先恢复动力带，尤其 Race/Offroad。
- 对坡顶、路肩、短暂颠簸避免误判。

### 方案 A：扩展 AirtimeDetector 状态机

建议把 `AirtimeDetector` 从单一 `is_airborne` 扩展为：

```python
class AirtimeDetector:
    @property
    def is_airborne(self) -> bool: ...

    @property
    def just_landed(self) -> bool: ...

    @property
    def landing_until(self) -> float: ...
```

`update(td, now)` 返回状态变化：

```python
AirState(
    airborne: bool,
    just_landed: bool,
    airborne_started: bool,
    landing_started: bool,
)
```

检测条件建议从“必须全部满足”改为加权投票：

- 强条件：
  - `speed_kmh > 20`
  - `abs(accel_y) < 3.0` 或 `abs(vel_y) > 1.0`
- 轮胎条件：
  - 四轮 slip 全部高：强证据
  - 至少 2-3 个轮高 slip：中证据
  - slip 不高但 `vel_y` 明显且垂向加速度低：短暂候选，最多允许 2-3 帧
- 进入：
  - 强证据连续 2 帧即可进入
  - 中证据连续 3 帧进入
- 退出：
  - `abs(vel_y) < 0.6` 且不再低 G/高 slip，连续 2-3 帧
  - 退出瞬间设置 `landing_until = now + 0.75`

这样比当前“四轮全部 slip > 1.2 连续 3 帧”更能覆盖真实跳跃。

### 方案 B：落地 recovery 钩子

在 `_process_internal()` 更新 airtime 后记录边沿：

```python
air_state = self._airtime.update(td, now)
if air_state.landing_started:
    self._landing_recovery_until = now + 0.90
    self._no_downshift_until = 0.0
    self._no_predictive_until = 0.0
    self._no_upshift_until = max(self._no_upshift_until, now + 0.80)
```

设计意图：

- 清掉降挡锁，让落地后可以立刻补挡。
- 短暂禁止升挡，防止落地轮速/RPM 尖峰触发误升挡。
- 保留 over-rev 检查，不允许危险降挡。

### 方案 C：Race/Offroad 落地补挡规则

在 Race/Offroad 的 transient block 之后、普通规则之前加入：

```python
if self._landing_recovery_until > now:
    if self._landing_recovery_downshift(td, now):
        return
```

触发建议：

- `td.gear > 1`
- `td.speed_kmh > 20`
- `td.throttle > 0.35` 或最近 0.8s 内油门 ramp 明显
- `td.rpm_pct < target_floor`
  - Race：`target_floor = peak_torque - 0.03`，fallback `0.62`
  - Offroad：fallback `0.58`，更重视扭矩
- 如果刹车仍大于 `0.25`，优先走 `_track_brake_down()` 的目标挡位。

状态文案：

- 腾空中：`AIRBORNE / holding decisions`
- 刚落地：`LANDING / recovering power`
- 补降挡：`LANDING DOWN / →target`

前端 snapshot 可继续使用现有 `airborne`，建议增加：

- `landing_recovery: bool`
- `airtime_state: "GROUND" | "AIRBORNE" | "LANDING"`

---

## 四、P1 验证与调参

### 单元测试

建议新增 Python 测试覆盖：

1. `AirtimeDetector`
   - 真实腾空：低 G + 高 `vel_y` + 部分 wheel slip，能进入 airborne。
   - 短路肩/坡顶：1 帧异常不进入 airborne。
   - 落地边沿：从 airborne 到 grounded 时产生一次 `just_landed`，并维持 landing window。
2. Race power down
   - 高挡、低 RPM、70%+ throttle、非爬坡：应触发降挡。
   - projected RPM 超红线：必须阻止。
   - 刚升挡后低转大油门：Race override 能在合理锁定后纠正。
3. Race brake down
   - 中高强度持续刹车但非 spike：Race 应降挡。
   - Comfort 保持原平顺行为。

### 回放验证

使用 telemetry replay 增加对比指标：

- 从落地帧到第一次有效降挡的延迟
- 从全油门低转到第一次降挡的延迟
- Race 模式每分钟误降挡次数
- 过转保护触发次数
- wheelspin upshift 与 landing down 的冲突次数

建议验收标准：

- Race 平路低转大油门在 0.3-0.5s 内开始降挡。
- 落地后若 RPM 低于目标动力带，在 0.2-0.4s 内开始补降挡。
- 腾空期间不再触发普通 upshift/downshift。
- Comfort 日常巡航行为不发生明显变化。

---

## 五、P2-new 修复：vgamepad 模式下物理手柄刹车中断

### 现象（用户反馈）

使用 vgamepad（虚拟 Xbox360）输出模式时，物理手柄的刹车会被中断：刹车时连续降挡，刹车灯一闪一闪，影响观感。

### 根因（用户诊断）

虚拟手柄在发送按键时，每次 `update()` 会附带一个**完整的设备状态包**。该包内 `LT`（左扳机 = 刹车）值为 `0`，会覆盖物理手柄持续输入的 LT 信号 → 游戏在那一帧把刹车判为松开 → 刹车中断。连续降挡时每次 `update()` 都触发一次，于是刹车灯闪烁。

对应代码 `virtual_tcu/input/gamepad_output.py:_press_release`：每次换挡做 `press_button → update() → sleep → release_button → update()`，两次 `update()` 各发一个 LT=0 的完整状态包。`GamepadOutput` 从未设置过 LT，所以虚拟设备的 LT 恒为 0。

### 方案 A（用户建议，最小改动）

在虚拟手柄注入降挡键的同时，把它的 LT 设为一个非零值（例如 `20`），使 LT 信号不中断，游戏就不会中断刹车。

`vgamepad` 已提供 API（已确认存在）：

```python
self._gamepad.left_trigger(value=20)        # 0-255 整数
# 或 self._gamepad.left_trigger_float(value_float=0.08)
```

在 `_press_release`（或换挡前后）设置 LT，并在换挡结束后清零或恢复。

### 方案 B（推荐，避免“幽灵刹车”）

方案 A 的固定 `LT=20` 有副作用：**未踩刹车时也会注入一点刹车**（升挡、巡航时也按 `_press_release` 走，会凭空给 8% 刹车）。更稳妥的做法是**让虚拟 LT 镜像遥测里的真实刹车值**：

- `Telemetry` 已有 `brake`（0-1）。在换挡注入时，把 LT 设为 `int(td.brake * 255)`（或带个下限，仅当 `td.brake > 0` 时设非零）。
- 这样：玩家在踩刹车 → 虚拟包 LT 跟随真实刹车，不中断；玩家没踩刹车 → LT=0，不会凭空刹车。
- 需要把当前 `td`（或至少 `td.brake`）传进 `shift_to`/`_press_release`，或在 `GamepadOutput` 上缓存最近一次刹车值（由 `TCULogic.process` 每帧更新）。

### 实现注意

- LT 的设置必须在 `update()` **之前**，否则那一帧仍是 0。
- `press_button` 与 `release_button` 两次 `update()` 都要带上 LT 值，否则 release 那一帧又会清零。
- 仅影响 `gamepad` 模式；`keyboard`/`vjoy` 不涉及（vjoy 走 DirectInput，不与物理手柄抢 XInput 状态）。
- 升挡键同样走 `_press_release`，理论上也会清 LT，但升挡通常不在刹车时发生；方案 B 的镜像逻辑天然覆盖升挡场景。
- 是否需要对 RT（油门）做同样处理？升挡多在全油门时发生，若实测发现升挡也打断油门，可对称处理 `right_trigger` 镜像 `td.throttle`。

### 新增配置（可选）

```python
"gamepad_preserve_brake": True,   # 换挡时镜像物理刹车到虚拟 LT，避免刹车中断
```

### 验收

- vgamepad 模式 + 物理手柄，踩住刹车连续降挡：刹车灯常亮不闪。
- 未踩刹车时升/降挡：不出现凭空刹车（车速/刹车灯无异常）。

---

## 六、P3-new 调查结论：Race 高转不升挡——实测推翻原假设（不修复）

> **状态：已调查，结论为「按原假设修复会让该车更慢」，故撤销 P3-new 修复。**
> 调查方法：用 `iter_replay_records` 解码 `logs/没有触发升档.gz`，重建逐挡功率曲线，
> 并用真实 `TCULogic`（强制 RACE）回放整段日志观察实际决策。

### 原假设（已被推翻）

最初的现象描述是：Race 全油门卡在 3 挡、rpm 90→91%、功率 158.4→157.0 kW（轻微下降），
推断「早已越过功率峰值，留在 3 挡纯属损失加速度，TCU 该升不升」。计划方案 A 据此提出
「过峰值 + 功率下降即升挡」兜底。

### 实测数据（车 4216 / class 2 / PI 561 / redline 16500）

**1. 跨挡物理：在该车上，保持 3 挡才是正确的。**
定速时轮上驱动力 ∝ `engine_power / speed`（传动比在前后抵消），所以**当前速度下发动机功率更高的挡位加速更快**。
该车 3→4 升挡后 rpm 落到升挡前的 **70.7%**（齿比实测）。对比「现在 3 挡的功率」与「升 4 挡后落点的功率」：

| 升挡时 rpm% | P(3 挡) | 落到 | P(4 挡) | 结论 |
|---|---|---|---|---|
| 90% | 158 kW | 64% | 123 kW | **保持 3 挡（升挡损失 35 kW）** |
| 94% | 154 kW | 67% | 129 kW | 保持 3 挡（损失 25 kW） |
| 100% | 154 kW | 71% | 138 kW | 保持 3 挡（损失 16 kW） |

**任何**升挡点上，升 4 挡都更慢。所谓「功率下降」（158→157，<1%）只是越过 ~85% 功率峰值后正常的平顶缓降，
**不代表升挡能挽回加速度**。原假设把「发动机功率曲线的缓降」误当成了「该升挡的信号」。

**2. 现有代码本就会在限速器附近升挡。** 用当前 `TCULogic` 回放该日志，TCU 在 rpm 98.9% / 98.6%
（按学习到的 redline 折算）发出了 `3→4` 升挡命令——并非「卡住升不了」。日志里的 `3→N→4`
（t≈262ms）正是一次**正常**的接近换挡点后完成的换挡（N 帧 power 变负是换挡离合断开），不是失败。

**3. 该日志来自「上次发行版」（P0/P1 之前）。** 即便如此，原始帧也显示它最终换挡成功了。

### 为什么不实施方案 A/B

- **方案 A（功率下降兜底）**：会让该车在 90% 就升挡，按上表直接损失 ~35 kW 加速度，是**回归**。
  「实测功率下降」对绝大多数 NA 车在功率峰值之后恒成立，用它当升挡信号会让几乎所有车过早升挡掉出动力带。
- **方案 B（fallback 上限）**：`optimal_upshift_rpm` 已 clamp `model` 到 0.97、blend 到 fallback(0.94)；
  该车正确行为本就是「逼近限速器再升」，再压低上限只会让它更早升挡变慢。
- **方案 C（rev-limiter）**：回放确认该车 redline 学习正常（`effective_redline≈16500`，正是 rpm_max），无需修复。

### 若仍要深究的「真问题」（另立，非本计划范围）

唯一可能值得看的残留点：进入某挡后到首次升挡尝试之间，post-shift lock 与 transient lock 叠加可能造成约
0.5s 的迟滞。但这是**调参**问题（锁定时长），不是原计划描述的「算法不升挡」bug，且 P0 已对 Race 的
`downshift_lock_s` / `cascade_lock_s` 做过缩短。需要时再用回放单独评估，不在此计划内。

### 教训

`logs/*.gz` 回放在动手前必须先解码核对。本节原假设仅凭节选帧的「功率微降」下判断，
未做跨挡功率对比，方向完全错误。**先解码、再下结论、再写方案。**

---

## 七、P4-new：vjoy 输出配置面板

### 背景

vjoy 输出后端已落地（`virtual_tcu/input/vjoy_output.py`），`effective_output_mode` 已在 `web/server.py` 上报 `vjoy`，但**前端无法选择 vjoy 模式、也无法配置其按键**。这是 vjoy PR 遗留的前端缺口。

### 涉及配置项（后端已读取，前端缺 UI）

`virtual_tcu/config/constants.py` 中：

```python
"vjoy_direct_shift": True,     # 直选挡位(B1-B10/B11倒挡) vs 顺序换挡(B13/B14)
"vjoy_use_clutch": False,      # 换挡时附带按离合键
"vjoy_shift_key_up": "B13",    # 顺序模式升挡键
"vjoy_shift_key_down": "B14",  # 顺序模式降挡键
"vjoy_clutch_key": "B12",      # 离合键
```

### 改动点

1. **`packages/shared/src/config/settings.ts`**
   - `OUTPUT_MODE_OPTIONS` 增加 `{ value: 'vjoy', i18nKey: 'outputModeVjoy' }`。
   - 新增 `VJOY_BUTTON_OPTIONS`（B1–B14，对应 `_BUTTON_MAP`；可标注 B11=倒挡、B13/B14=升/降挡默认）。
   - 新增 `VJOY_BUTTON_FIELDS`（`vjoy_shift_key_up` / `vjoy_shift_key_down` / `vjoy_clutch_key`）。
   - 直选/离合是布尔，归入开关而非按键下拉。

2. **`apps/dashboard/src/components/SettingsPanel.vue`**
   - 现有 `v-if="output_mode === 'gamepad'"` 块旁，新增 `output_mode === 'vjoy'` 块：
     - `vjoy_direct_shift` 开关（直选 / 顺序）。
     - `vjoy_use_clutch` 开关 + `vjoy_clutch_key` 下拉（仅开离合时显示）。
     - 顺序模式（`direct_shift=false`）时显示 `vjoy_shift_key_up/down` 下拉；直选模式下这两项无效，应隐藏或灰显。
   - 复用现有 `restartBackend` 提示（vjoy 同样需重启后端切换）。

3. **`apps/dashboard/src/config/settings.ts`** — re-export 新增的 `VJOY_*` 常量。

4. **`apps/electron/src/settings-renderer/SettingsApp.ts`** — 该处也引用 `OUTPUT_MODE_OPTIONS`，需同步支持 vjoy 选项（确认 Electron 设置页与 dashboard 一致）。

5. **i18n（en + zh-CN）** — 新增文案：`outputModeVjoy`、`vjoyDirectShift`、`vjoyUseClutch`、`vjoyClutchKey`、`vjoyShiftUp`、`vjoyShiftDown`，以及直选/顺序模式的说明 hint。

### 交互注意

- 直选模式下挡位键由 `target_gear` 直接映射 B1–B11，**不需要**用户配 升/降挡键；顺序模式才需要。UI 应按 `direct_shift` 动态显隐，避免用户误配无效项。
- 离合键误配（非 B1–B14）后端已降级为“无离合换挡”并打日志（见 vjoy 输出修复）；UI 用下拉枚举 B1–B14 可从源头杜绝误配。
- 切换 output_mode 需重启后端才生效（与 gamepad 一致）。

### 验收

- 设置页能选 vjoy；选中后出现 vjoy 专属配置块。
- 切直选/顺序，升降挡键下拉随之显隐。
- 改完重启后端，`effective_output_mode` 上报 `vjoy`，实车换挡生效。

---

## 八、P5 模式优化：合并 Dynamic


### 是否合并

建议合并，但放在 Race/腾空修复之后。

理由：

- 当前用户反馈集中在 Race 与 airtime，删除 Dynamic 不会直接解决。
- 删除模式会影响后端枚举、配置、前端模式列表、HUD、i18n、历史 `current_mode` 迁移。
- 先把 `DriveStyleTracker` 用在 Comfort/Race 中，再删除 UI 模式，用户感知更平滑。

### 合并策略

1. `Mode.DYNAMIC` 从 `MODE_ORDER` 与前端 `DRIVE_MODES` 删除。
2. 配置迁移：
   - 如果旧配置 `current_mode == "DYNAMIC"`，启动时迁移到 `COMFORT`。
   - 保留 `dynamic_up_*` 配置一个版本，读取时映射为 Comfort sport 曲线参数；后续再清理。
3. Comfort 内联 drive style：
   - `CRUISE`：保留 cruise efficiency upshift。
   - `ADAPTIVE`：降低 kickdown/predictive 阈值，启用 transient block。
   - `SPORT`：提高 upshift 曲线、降低动力降挡阈值，但不要完全变成 Race。
4. Race 使用 drive style 做“保守上限”：
   - index 低且油门低时，允许稍早升挡以降低巡航噪音。
   - 一旦 throttle/rpm/brake/lat-g 表现为运动驾驶，立即恢复完整 Race 策略。
5. 前端保留 `drive_style_regime` 展示，让用户看到 Comfort/Race 内部自适应状态。

### 不建议合并 Offroad

Offroad 虽然与 Race 相似，但仍有真实独有价值：

- `TORQUE DOWN` 对低速爬坡有用。
- 轮速差误判过滤 `_is_spinning_not_traction()` 更适合越野。
- anti-stall 更早介入。

如果未来要减少模式数量，先观察 Race 修复后 Offroad 使用率与日志表现，再决定是否合并。

---

## 九、P6 离合辅助：跨输出统一（按新 `shift_to` 接口重写）

### 现状变化（重要）

原计划写于 `shift_up/shift_down/shift_down_double` 接口时代，该接口**已被移除**，统一为 `shift_to(from_gear, target_gear)`。同时 **vjoy 输出已自带一套离合实现**（`vjoy_use_clutch` / `vjoy_clutch_key`，直选模式下离合脉冲、挡位保持）。因此本项不再是“从零加离合”，而是：

1. 把 vjoy 已验证的离合思路，按需推广到 keyboard / gamepad；
2. 统一离合配置命名（避免 vjoy 用 `vjoy_clutch_key`、其它输出又一套）。

### 是否需要

不是 Race/腾空问题的修复前提（那些是决策与状态判断问题，离合不解决）。仅对使用 **Manual with Clutch** 且离合映射正确的玩家可能降低换挡延迟、减少动力中断。普通 Manual/Automatic 玩家开启离合可能导致错挡、空挡感。**默认关闭**。

### 接口设计（适配 `shift_to`）

不再给每个 shift 方法加 `use_clutch` 参数（方法已合并为 `shift_to`）。改为：

- 离合是否启用，由各输出自己读配置（vjoy 已是此模式：`use_clutch` property）。
- `OutputInterface` 不需要新方法；`shift_to` 内部按配置决定是否押离合。
- 时序参数（pre/overlap/release）作为各输出的内部常量或配置读取。

### 各输出的离合实现

- **vjoy**：已完成（直选模式离合脉冲 + 挡位保持；顺序模式离合与挡位同押同松）。可作为参考实现。
- **keyboard**：离合是一个键（如 `shift`）。时序：
  ```text
  press clutch → wait pre_ms → press shift → wait overlap_ms
  → release shift → wait release_ms → release clutch
  ```
- **gamepad**：
  - 离合映射到**按钮**（LB/RB/A 等）→ 直接用 `press_button`，与 keyboard 同时序。
  - 离合映射到 **LT/RT 扳机轴** → 用 `left_trigger`/`right_trigger`（vgamepad 已确认支持），按 analog 处理。**注意**与第五节“LT 刹车中断”的交互：离合用 LT 时会和刹车镜像逻辑冲突，需明确 LT 同时只能服务一个用途，或离合优先用按钮。

### 新增配置（统一命名建议）

```python
"feat_clutch_assist": False,        # keyboard/gamepad 总开关（vjoy 用既有 vjoy_use_clutch）
"clutch_key": "shift",              # keyboard 离合键
"gamepad_clutch": "LB",             # gamepad 离合按钮（或 LT/RT）
"clutch_pre_ms": 20,
"clutch_overlap_ms": 55,
"clutch_release_ms": 25,
"clutch_modes": ["RACE", "OFFROAD"],
```

### 验收指标

- 同车同挡，记录按键触发到 `td.gear` 改变的帧数；对比单键 shift 与 clutch-assisted shift 的中位延迟。
- 若无明显降低延迟或误换挡增加，默认继续关闭。
- gamepad LT 用作离合时，不与刹车镜像（第五节）互相破坏。


---

## 十、建议实施任务清单

### P0-1 Race 动力降挡（已完成）

- [x] 新增 `_target_gear_for_power()`：基于齿比和功率曲线选择目标挡。
- [x] 新增 `_track_power_demand_downshift()`：非爬坡低转大油门主动降挡。
- [x] `_mode_race()` 接入 power down，保留 over-rev 保护。
- [x] `_shift_down()` 支持 `cascade_lock_s`，Race 使用更短串联锁。
- [x] `_shift_up()` 支持 `downshift_lock_s`，Race upshift 不再统一锁 1s。

### P0-2 腾空与落地恢复（已完成）

- [x] `AirtimeDetector.update(td, now)` 返回状态边沿。
- [x] 引入 `vel_y` 与部分 wheel slip 投票，降低漏判。
- [x] 增加 `landing_recovery_until`。
- [x] 落地时清理 downshift/predictive lock，短暂禁止 upshift。
- [x] Race/Offroad 接入 `_landing_recovery_downshift()`。
- [x] snapshot 增加 `landing_recovery` / `airtime_state`。

### P1 测试与日志（已完成）

- [x] 增加 AirtimeDetector 单元测试。
- [x] 增加 Race power down / brake down 测试。
- [x] 增加 replay 对比指标输出。
- [x] 用真实用户日志验证阈值。

### P2-new vgamepad LT 刹车中断（第五节，已完成）

- [x] `GamepadOutput` 在换挡 `update()` 前设置 LT，镜像 `td.brake`（方案 B）。
- [x] 在 `GamepadOutput` 缓存每帧刹车值（`set_brake`，由 `TCULogic.process` 每帧调用；接口提供 no-op 默认，keyboard/vjoy 不受影响）。
- [x] press 与 release 两次 `update()` 都带 LT，避免 release 帧清零。
- [x] 新增 `gamepad_preserve_brake` 配置（默认 True）。
- [x] 实测（需 Windows + 真实手柄）：踩刹车连续降挡刹车灯不闪；未踩刹车换挡不凭空刹车。
- [ ] 评估是否需对 RT（油门）做对称处理（升挡多在全油门，暂不实现，留观察）。

### P3-new Race 高转不升挡（第六节，已撤销）

- [x] 解码 `logs/没有触发升档.gz` + 真实 `TCULogic` 回放，确认原假设错误（跨挡功率对比：保持低挡更快）。
- [x] 结论：**不修复**。方案 A/B 会让该车提前升挡掉出动力带，属回归。
- 残留可选项（非本计划范围，需要时另立）：评估进入某挡后到首次升挡尝试的锁定叠加是否过长（调参，非算法 bug）。

### P4-new vjoy 配置面板（第七节）

- [x] `OUTPUT_MODE_OPTIONS` 增加 `vjoy`；新增 `VJOY_BUTTON_OPTIONS` / `VJOY_BUTTON_FIELDS`。
- [x] `SettingsPanel.vue` 增加 `output_mode === 'vjoy'` 配置块（直选/离合开关 + 按键下拉，按 `direct_shift` 显隐升降挡键）。
- [x] `apps/dashboard/src/config/settings.ts` re-export 新增常量。
- [x] `apps/electron/.../SettingsApp.ts` 同步支持 vjoy。
- [x] i18n（en + zh-CN）新增 vjoy 文案。
- [x] 实测：选 vjoy → 配置块出现 → 重启后端 → `effective_output_mode=vjoy` → 实车换挡生效。

### P5 Dynamic 合并（第八节，已完成）

- [x] Comfort 内联 drive style 自适应参数（CRUISE=经典 Comfort 不变；ADAPTIVE/SPORT=移植原 `_dynamic_cruise` 偏运动：transient hold、更紧的 brake/predictive/engine-brake 锁、`dynamic_up_*` 运动升挡曲线、抑制 CRUISE EFF/COAST DOWN）。受 `feat_drive_style` 开关门控。
- [x] Race 内联 drive style 低负载保守策略（`feat_drive_style` 开 + CRUISE 工况时升挡 offset 0.03→0.0，略早升挡降低巡航转速；状态文案 `cruise`）。
- [x] `MODE_ORDER`/`Mode` 枚举移除 `DYNAMIC`。
- [x] 旧配置 `current_mode == "DYNAMIC"` 启动迁移到 `COMFORT`（`config/store.py` load()，大小写不敏感，写回磁盘）。
- [x] 更新 `packages/shared/src/config/modes.ts`、`types/ws.ts`、`utils/mode-colors.ts`、`apps/electron/.../HudApp.ts` 类型与颜色、i18n（en + zh-CN）。`--color-mode-dynamic` 色值保留（ADAPTIVE 工况药丸 + sport-index 渐变条仍在用）。`dynamic_up_*` 配置/滑块保留（现服务 Comfort 运动曲线），文案改去"动态模式"措辞。
- [x] 删除 `_mode_dynamic/_dynamic_cruise/_dynamic_sport` + 分发分支 + `_compute_shift_advisor` 的 `Mode.DYNAMIC` 分支。
- [x] `MANUAL` 一致性已核对：`MODE_ORDER`/`DRIVE_MODES`/`DriveMode` 联合类型一致。
- [x] 测试：新增 `tests/test_drive_style.py`（regime 升降转换 + Comfort 经典/运动 + Race cruise/in-band）。**注：`tests/conftest.py` 的 `FakeOutput` 在 `shift_to` 重构后一直未更新（实现的是已删除的 `shift_up/shift_down_double`），整个测试套件在 main 上无法实例化——本次一并修复。** 全套 28 passed / 2 skipped；ruff + eslint + vue-tsc 全绿；dashboard 构建通过；DYNAMIC→COMFORT 迁移端到端验证通过。

### P6 离合辅助（第九节，跨输出统一）

- [x] 统一离合配置命名（keyboard/gamepad 用 `feat_clutch_assist` 等；vjoy 沿用 `vjoy_use_clutch`）。
- [x] KeyboardOutput 支持 clutch sequence（pre/overlap/release 时序）。
- [x] GamepadOutput 支持按钮式 clutch；LT/RT 扳机式离合与刹车镜像（P2-new）冲突需处理。
- [x] 离合配置 UI（与 P4-new vjoy 面板协调）。
- [x] 增加换挡延迟 A/B 日志指标。

---

## 十一、最终建议

P0（Race 降挡 + 落地 recovery）、P1（测试/调参）、P2-new（vgamepad LT 刹车中断）已完成；P3-new 经实测撤销。当前未完成项按优先级：

1. ~~**P2-new vgamepad LT 刹车中断**~~ —— **已完成**。方案 B（虚拟 LT 镜像真实刹车）已实现：`GamepadOutput.set_brake` 每帧缓存物理刹车，换挡时在两次 `update()` 前都把 LT 设为 `int(brake*255)`；接口提供 no-op 默认，keyboard/vjoy 不受影响；`gamepad_preserve_brake` 默认 True。待 Windows + 真实手柄实测确认。
2. ~~**P3-new Race 高转不升挡**~~ —— **已撤销**。回放实测推翻原假设：该车在限速器附近保持低挡最快，升挡反而损失 16–35 kW，且现有代码本就会在 ~99% rpm 升挡。不做修复，详见第六节。
3. **P4-new vjoy 配置面板** —— 当前最高优先级未完成项。补齐 vjoy PR 的前端缺口，让 vjoy 模式真正对用户可用。纯前端 + 配置，无算法风险。
4. **P5 Dynamic 合并** —— 产品/交互简化，不是体验 bug 的根因，无紧迫性。注意 `MANUAL` 模式已新增，合并时需一并核对模式列表一致性。
5. **P6 离合辅助** —— opt-in 实验功能，默认关闭。vjoy 已有简版实现，本项是按新 `shift_to` 接口推广到 keyboard/gamepad 并统一配置；其中 gamepad 用 LT/RT 作离合会与 P2-new 的刹车镜像冲突，需先理清 LT 用途归属。

依赖关系提示：P6 的 gamepad LT 离合与 P2-new 的 LT 刹车镜像都争用同一个扳机轴。P2-new 已占用 LT 做刹车镜像，故 P6 的 gamepad 离合通道**应优先用按钮式离合**（LB/RB/A 等）规避冲突；若必须用 LT/RT，需明确同一帧 LT 只能服务一个用途。

