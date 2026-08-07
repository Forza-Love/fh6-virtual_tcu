# Changelog

## [13.2.8] - 2026-08-07

### Fixed

- **Upshifts pinned to the rev limiter (#74)** — the learned power curve is now actually applied. Its confidence score required a sample spread real driving never produces (nine reported replays measured 0.045–0.099 against a 0.16 threshold), and a second hard gate on top of the confidence blend discarded whatever survived, so across roughly 500 upshifts in those logs the curve moved the shift point five times. Every car ended up shifting at its fuel cut instead of near peak power.
- **Cars whose fuel cut sits below 90% of nominal RPM** — high-RPM coverage was measured against Forza's inflated nominal `engine_max_rpm`, which the Ford GT (fuel cut at 88.3% of nominal) can never reach, permanently disabling its power curve. Repeatedly returning to the same ceiling now counts as coverage.
- **Gears that top out below their upshift target** — a car can be aero-limited without pinning RPM the way the load-plateau detector demands (the reported Ford GT crawled up 4th at 0.6%/s while still gaining 2.2 km/h/s, and needed 320 km/h to reach a target it met at 299). A longer stall window, armed only past peak power, now frees the gear; the car reaches 5th instead of staying in 4th.
- **Traction sawtooth learned as fuel cut** — a low-gear oscillation could be verified as the rev limiter and then drag every shift point down for good (a Pagani Huayra R was pinned to 9,765 rpm after having already revved to 11,524, collapsing its Race target to the 80% mid threshold). A learned or candidate limiter must now clear the highest WOT RPM the engine has demonstrably reached, and a stored value the engine later revs past is discarded. Profiles written before this check are reconciled on load against the power curve's persisted coverage.
- **Road-speed walls below peak power** — plateau and stall evidence may no longer place the shift point under the learned peak-power RPM; only a measured rev ceiling can.

### Changed

- **RWD traction upshifts** — the cold-curve guard now requires a calibrated landing gear rather than using power-curve confidence as a proxy for "this car has been driven a while", which stopped holding once the curve matures at a realistic rate.
- **Profile contents** — `power_curve.ceiling_hits` and `rev_limiter.max_wot_rpm` are added as optional keys. Both default to zero when absent, existing fields keep their units and meaning, and older files load unchanged, so `PROFILE_SCHEMA_VERSION` stays at 1 and no car has to relearn.

## [13.2.7] - 2026-07-21

### Fixed

- **High-gear permanent lockout** — remove the sixth-gear hard upshift cap; a missed acknowledgement now soft-caps with exponential backoff (capped) so 7–10 speed transmissions can recover, and a downshift clears stale cap state.
- **Cross-gear limiter trust** — bank independent fuel-cut candidate episodes and verify the limiter across gears, so later gears reuse the first clean discovery instead of re-paying the fuel-cut cost after each live-candidate shift.
- **False high-gear load plateaus** — require time-normalized RPM/speed evidence and stronger near-limiter proof before lowering a WOT target; ordinary 81–84% high-speed acceleration no longer triggers early 8→9 / 9→10 shifts.
- **Race/Offroad descent recovery** — add sustained low-demand speed-gain engine-brake downshifts that work above the old 30% coast floor, with crest/unweighted holds bounded so a long downhill grade cannot freeze shifting indefinitely.
- **Profile persistence lifecycle** — wrap `tcu_profiles.json` in a versioned envelope (`PROFILE_SCHEMA_VERSION = 1`, independent of the app version), archive incompatible/legacy files, stabilize engine-signature switches, and persist learning milestones atomically.
- **Calibration UX** — add a confirmed **Relearn** action for the current car profile, keep Settings reset behind a confirmation dialog, and broadcast config/profile updates to all clients.
- **Replay regressions** — cover clean-profile 13.2.6 logs, soft-cap retry/backoff, cross-gear limiter confirmation, sustained unweighted grades, and descent downshifts.

### Changed

- **Legacy profile files** — unversioned flat `tcu_profiles.json` from earlier builds is archived and replaced with the new envelope; cars relearn once after upgrading to 13.2.7. Ordinary future app releases keep the same schema and retain learning.

## [13.2.6] - 2026-07-20

### Fixed

- **Race launch and wheelspin stability** — hold low-gear upshifts whose learned landing RPM would fall below the power band, require meaningful RPM before a third-gear traction upshift, and suppress power-demand downshifts until driven-wheel grip returns. This prevents high-power cars such as the Pagani Huayra from entering `2→3→2` launch loops.
- **Faster real-limiter recovery** — use a stable live fuel-cut candidate for shift timing before the stricter persisted safety limit is fully confirmed, reducing time spent beyond the usable redline without weakening over-rev protection.
- **Low and unreachable redlines** — recognize verified fuel-cut patterns down to 78% of Forza's nominal maximum RPM, keep learned shift targets within configured or reachable ceilings, and recover low-gear/high-load plateaus that cannot reach the normal WOT target.
- **High-gear load plateaus** — recover upshifts at sustained speed/load walls while rejecting ordinary slow RPM growth, braking, wheelspin, throttle lifts, and transient chassis events.
- **Hill-crest shift hold** — detect brief suspension unloading before full airborne detection and freeze automatic shifts through the crest, preventing floaty high-speed moments from causing an unsafe high-RPM downshift.
- **Shift safety and acknowledgement** — preserve pending upshifts through Forza's mid-shift gear encoding, retry rejected low-gear commands safely, normalize turbo demand, and keep brake/power downshifts within learned over-rev limits.
- **Replay regression coverage** — add recorded and synthetic coverage for Nissan Be-1, Ford GT 2005, Pagani Huayra, Shelby Daytona, Lamborghini Huracán STO, low-redline vehicles, hill crests, braking, and low-gear hunting.

## [13.2.6-pre.4] - 2026-07-16

> **Pre-release**
>
> Corrects RPM-ceiling detection across the Lamborghini Huracán STO, Shelby Daytona, and cars whose reachable fuel cut is far below Forza's nominal maximum RPM.

### Fixed

- **STO high-gear early upshifts** — restrict the short-window RPM-ceiling fallback to gears 1–2 so normal slow RPM growth in gears 4–7 is no longer mistaken for an unreachable redline.
- **Low nominal fuel-cut learning** — accept verified repeated limiter sawtooth patterns from 78% of nominal RPM upward, while rejecting one-off RPM drops, gear-transition carryover, wheelspin, and gradually moving peaks.
- **Shelby third-gear recovery** — recognize the Daytona's approximately 89% real limiter and restore automatic `3→4` upshifts.
- **Low-end long-red-zone vehicles** — learn approximately 84% reachable limiters, restore continuous `1→2→3` upshifts, and use the verified ceiling for over-rev protection so a valid upshift is not reversed immediately.
- **Profile compatibility** — persist newly verified limiter values with a version marker; older low limiter values remain untrusted until confirmed live, preventing stale false learning from returning.
- **Replay regressions** — add coverage for both STO logs, Shelby, and the high-red-zone low-end vehicle alongside the existing Ford, Pagani, brake, and low-gear suites.

## [13.2.6-pre.3] - 2026-07-16

> **Pre-release**
>
> Stabilizes the remaining Ford GT 2005, Pagani Huayra R 2021, and post-brake upshift edge cases without reverting the improved D/C-class timing.

### Fixed

- **Reachable upshift ceiling** — bound learned Race/Offroad targets by the configured or verified reachable fallback so a mature power-curve model cannot demand unreachable RPM.
- **High-gear load plateau** — recover an upshift after at least one second of stable high-load, low-slip RPM and speed plateau; rising RPM, braking, throttle lift, slip, and gear changes reset the detector.
- **Turbo compensation units** — normalize raw boost before comparing it with the internal turbo accumulator, preventing permanent sub-85% upshift blocking.
- **Race wheelspin landing** — suppress traction-save upshifts that would land below `race_power_floor`, preventing `2→3→2` loops while preserving healthy and ratio-less traction shifts.
- **Replay regressions** — cover Ford, Pagani, brake-stuck-in-second, launch, D/C-class, brake safety, and pending acknowledgement paths.

## [13.2.6-pre.1] - 2026-07-14

> **Pre-release / 预发布测试版**
>
> Refines v13.2.5 upshift logic after user replay `跳一档.gz`: no more fixed 80% threshold on gears 1–2; uses RPM-ceiling detection instead.
>
> 在 v13.2.5 基础上细化升档逻辑（用户 replay `跳一档.gz` 反馈）：取消 1–2 档固定 80% 阈值，改为转速触顶检测。

### Fixed

- **v13.2.5 regressions (user replay `跳一档.gz`)** — replace blanket `race_up_mid` fallback on gears 1–2 with `_rpm_ceiling_reached()` (tight plateau + low-gear speed wall); shift at measured ceiling (`peak - 1%`) instead of a flat 80%. Fixes launch wheelspin upshift at ~66% RPM (1st gear wheelspin disabled; 2nd/3rd only, RPM ≥ 72%) and restores post-brake upshifts when RPM plateaus below `race_up_wot`.
- **pytest** — extend `test_low_gear_rpm_ceiling.py` with `跳一档.gz` replay regressions.

## [13.2.5] - 2026-07-14


### Fixed

- **Race 1st-gear RPM ceiling (#67 follow-up)** — gears 1–2 in Race/Offroad now cap the in-band upshift fallback to `race_up_mid` / `offroad_up_mid` when the WOT point is speed-limited below `race_up_wot`; fixes logs where AWD S1 cars held 1st at ~89% RPM with zero upshift commands issued.
- **AWD/FWD wheelspin upshift during cold start** — power-curve cold-start block on wheelspin upshifts now applies to RWD only; AWD launch wheelspin can upshift again. Initialise `_slip_streak` in `TCULogic.__init__`.
- **pytest** — `test_low_gear_rpm_ceiling.py` (synthetic + user `tcu_replay_20260714_*.bin.gz` replays).

## [13.2.4] - 2026-07-14

### Fixed

- **Low-gear hunting / stuck upshifts (#67)** — Forza mid-shift telemetry (`gear > 10`) no longer clears the pending upshift gate while the car is still in the previous gear; the pending deadline extends during in-progress shifts instead of timing out into a second UP that skips gears. `_we_shifted` is no longer cleared on the keypress frame so slow game acknowledgements do not permanently brick low-gear auto upshifts.
- **pytest** — `test_issue67_low_gear_hunting.py` covers mid-shift encoding, slow-ack timeout recovery, and fast-car gear-skip regression paths.

## [13.2.3] - 2026-07-10

### Added

- **GitHub issue templates** — bilingual Bug Report and Feature Request forms (`bug_report.yml`, `feature_request.yml`) with version, install method, component, reproduction steps, and environment checks; blank issues disabled via `config.yml`.
- **Telemetry model** — parse `TireSlipAngle` (offset 164) and `TireCombinedSlip` (offset 180) from FH6 UDP into the `Telemetry` model (additive; no TCU logic consumes them yet).
- **pytest** — `test_early_upshift_rev_limiter.py` for Race-mode upshift timing and false rev-limiter learning from TCU upshift plateaus (#62).

### Changed

- **Shift timing constants** — `LOW_GEAR_LOCK_MS` 800→400 ms; `UPSHIFT_PENDING_TIMEOUT_S` 1.2→0.7 s for faster upshift response (#61).
- **Power curve confidence** — `HIGH_RPM_COVERAGE` 0.78→0.90; upshift point stays at or above the configured `race_up_wot` fallback while high-RPM coverage is missing or confidence is below 70%; mid-range-only parabola peaks are always rejected until high-RPM evidence exists.
- **Cloud dev docs** — `AGENTS.md` clarifies Node 24 selection and dashboard smoke-test gotchas for cloud agents.

### Fixed

- **Tire slip offset (#56)** — read `TireSlipRatio` from byte offset **84** instead of 136 (`WheelInPuddleDepth`), fixing AWD dry-race `front_slip` stuck at 0.00 and restoring RWD wheelspin upshift and related slip-driven logic.
- **Early upshift (#62)** — `RevLimiterDetector` no longer overwrites `td.engine_max_rpm`; ignore rev-limiter samples for 0.8 s after upshifts; commit learned fuel-cut only when bounce ≥97% of nominal redline; learned redline applies only in `_rev_ceiling()` over-rev guards while shift timing and power-curve learning use the game's nominal `engine_max_rpm`.
- **HUD tach scale duplication (#66)** — deduplicate rounded RPM scale ticks and key Vue scale nodes by index so long sessions no longer accumulate repeated tach numbers when redline rounding collides (e.g. 6k → repeated 2/5).

## [13.2.2] - 2026-06-07

### Added

- **Feature toggle tooltips** — shared `FeatureToggleList` component shows an info icon beside each switch; hover reveals a short EN / zh-CN explanation on Electron Settings and the Web dashboard.
- **pytest** — `test_power_curve_cold_start.py` (mid-range-only samples must not cause early upshifts); `test_upshift_pending.py` extended for low-gear cap retry and reverse-exit launch upshifts.

### Changed

- **Power curve cold start** — track per-car high-RPM coverage; count 1st-gear stationary brake+throttle revving toward learning; up-weight WOT samples near the limiter; reject mid-range-only parabola peaks until ≥78% RPM has been seen; keep Race upshift at the configured `race_up_wot` fallback until then; persist `max_r` in saved power-curve profiles.
- **RWD wheelspin upshift** — skip traction-save upshifts while per-car power-curve confidence is still low (<25%).
- **Settings feature panel** — UI lists 11 core toggles only; Discord RPC, shift beep, and hold-Q reverse are hidden from the panel but remain available via `tcu_config.json`.

### Fixed

- **Rejected low-gear upshift** — soft top-gear cap (below 6th) clears after `UPSHIFT_CAP_RETRY_S` when still at WOT near redline, so the TCU retries instead of staying capped; 6th+ keeps a hard cap for impossible ratios.
- **Launch after reverse** — exiting reverse no longer blocks a forward 1st-gear redline upshift during the reverse-exit lock window.

## [13.2.1] — 2026-06-06

### Added

- **UDP Telemetry Hub** — forward raw FH6 UDP packets to one or more `host:port` targets from the network settings panel; duplicate-target and feedback-loop validation, with server-side target parsing before save.
- **Logs tab** — Electron Settings and the Web dashboard share a unified recording console: xterm live system output, optional parsed telemetry stream, replay logger start/stop, fusion snapshot actions, and an output-format picker (`bin.gz`, `csv`, `json`, `jsonl`, `summary`, `chart.html`).
- **Fusion Snapshot Logger** — ring-buffer flight recorder (~3 s) fuses telemetry and TCU state; dumps CSV (optional self-contained `chart.html`) on auto/manual shifts, redline anomalies, F8, or from the Logs tab; broadcasts `fusion_snapshot` over WebSocket.
- **Replay export pipeline** — recording stop converts to the selected format inline; CSV auto-splits into roaming vs `raceN` files by `is_race_on`; `format_paths` merges multiple replay inputs; `scripts/plot_snapshot.py` for offline chart rendering.
- **Electron update modal** — `UpdateAvailableModal` shows release notes, in-app download progress, GitHub fallback, and restart-to-install; tray menu labels follow system locale (EN / zh-CN).
- **pytest coverage** — upshift pending, per-tune profile keys, gear-ratio engine-brake rejection, UDP hub forwarding/validation, and backend restart argv.

### Changed

- **Per-car profile key** — profiles keyed by `(car_ordinal, car_class, pi, tune_id)` where `tune_id` comes from engine/drivetrain signature and ratio-drift slot splitting; legacy three-part keys still load.
- **Gear ratio learning** — reject engine-braking, overrun, and gear-order-invalid samples for cleaner ratio calibration.
- **Network settings** — unified Apply flow saves web host/port, UDP port, and UDP Hub targets together via the `set_network` WebSocket message.

### Fixed

- **Upshift spam / stuck top gear** — pending upshift window blocks repeat E presses until the game confirms the shift; failed upshift caps the learned top gear for that tune (#48, #50).
- **Tune swap profile reuse** — switching to a different tune with the same PI no longer reuses stale gear ratios that blocked upshifts (#49).
- **Backend restart from dev** — `exec_restart()` now re-invokes `python -m virtual_tcu` instead of `virtual_tcu/__main__.py`, fixing broken imports after network-settings restart.

## [13.2.0] — 2026-06-02

### Added

- **vJoy output mode** — virtual DirectInput shift injection for racing wheels (preserves force feedback); configurable upshift/downshift/clutch buttons and direct-shift vs clutch-assisted paths in Settings.
- **Shift clutch assist (keyboard)** — optional clutch key press before E/Q shifts with configurable pre/overlap/release timing; Electron Settings and backend-only Web UI expose the controls.
- **HUD templates** — Classic (arc tach), Racing (segmented RPM bar), and Minimal (LED dot tach); shift advisor arrows, shift banner, pedal gauge, click-through pin/unpin, and per-template minimum window bounds.
- **HUD dynamic sizing** — `hud:set-size` IPC and content-driven overlay height; legacy `glass` template configs map to Classic.
- **Backend-only Web UI settings** — standalone zip / `python -m virtual_tcu` dashboard regains the full settings column (vJoy, clutch assist, network, profiles) via shared `packages/ui` components.
- **pytest suite** — airtime detection and aggressive Race downshift behavior covered by unit tests.

### Changed

- **Drive modes** — removed standalone **DYNAMIC** from the F9 cycle; former Dynamic behavior is folded into **COMFORT** / **RACE** through the drive-style tracker (CRUISE / ADAPTIVE / SPORT regimes, toggle `feat_drive_style`).
- **Race TCU** — more aggressive downshifts; gear recovery after airtime landings and sporty coast; airtime now detected from vertical acceleration instead of wheel slip, with a global airborne hold.
- **Monorepo UI** — dashboard settings/HUD strings live in `packages/shared` + `packages/ui`; Electron settings and browser dashboard share the same components.
- **Locale picker** — improved language selection in settings (Electron + Web).

### Removed

- **Virtual XInput gamepad output mode** — removed entirely (`GamepadOutput`, `vgamepad`/ViGEmBus dependency, the bundled `driver/ViGEmBusSetup_x64.msi`, the `installViGEmBus`/`check_gamepad` IPC + WebSocket paths, and all gamepad button settings/locales). As a second XInput device it sent a full controller-state packet on every shift, zeroing the player's steering/throttle and making cornering feel laggy/unresponsive. Output is now **keyboard** (default) or **vJoy**. Saved configs with `output_mode: "gamepad"` automatically fall back to keyboard.
- **`OutputInterface.set_brake`** — only the virtual gamepad needed the brake mirror; removed from the interface and the TCU loop.
- **Deprecated vJoy DLL** from the repo; driver must be installed separately.

### Fixed

- **vJoy** — guard misconfigured clutch key; restore button hold timing; backend no longer force-exits when vJoy is configured but unused.
- **Manual + clutch** — transmission no longer stuck in neutral when using clutch assist with manual TCU mode.
- **Sporty coast / impacts** — recover target gear after hard landings and coast-down in sport regimes.
- **HUD** — restore full redesign lost during a lint-staged stash.

## [13.1.2] — 2026-05-29

### Added

- **HTTP health polling for Electron backend ready** — the main process treats aiohttp as ready when localhost responds, in addition to the `[backend-ready]` stdout marker.
- **ViGEmBus MSI integrity check** — Electron verifies the SHA-256 of the bundled installer before launching it.

### Changed

- **Electron backend lifecycle module** — spawn/stop/restart moved to `BackendLifecycle` with serialized restart, async process-tree kill, and `readline` stdout parsing.
- **IPC action results** — `openExternal` and `installViGEmBus` return `{ ok, error }` for clearer error handling in the settings UI.

### Fixed

- **Backend crash on Japanese Windows (cp932)** — force UTF-8 on stdout/stderr and use ASCII-safe console log text so PyInstaller builds no longer exit before the web server starts.
- **Concurrent backend restart race** — tray and IPC restart no longer spawn overlapping Python processes when triggered in quick succession.

### Security

- **`open-external` URL policy** — block localhost, private IPs, and link-local hosts from renderer-initiated `shell.openExternal` (manual LAN dashboard access in an external browser is unchanged).

---

## [13.1.1] — 2026-05-27

### Added

- **ViGEmBus driver installer bundled** — `driver/ViGEmBusSetup_x64.msi` is included in the Electron installer (`resources/driver/`) and published in the repo for direct download. Settings UI shows an **Install Driver** button that launches the bundled MSI.
- **Gamepad driver pre-check** — switching to gamepad mode in settings runs a WebSocket `check_gamepad` probe before saving config, with localized error prompts and an install shortcut when the driver is missing.
- **`effective_output_mode` in WebSocket init** — the dashboard now knows whether the backend is actually running keyboard or gamepad output (config alone may differ until restart).

### Changed

- **Lightweight gamepad availability check** — the probe now opens a transient ViGEmBus connection instead of spawning a temporary virtual XInput device, avoiding ghost controllers and false "driver not installed" errors while a gamepad is already active.
- **PyInstaller vgamepad bundling** — `virtual_tcu.spec` collects `ViGEmClient.dll` and vgamepad hidden imports without importing the package at build time (CI/build hosts do not need ViGEmBus installed).
- **Lazy vgamepad import** — removed the startup `import vgamepad` from `deps.py` so keyboard mode still launches if the gamepad client DLL is unavailable.
- **`installViGEmBus` refactored** into the settings store for cleaner encapsulation across Electron and Web UI contexts.

### Fixed

- **Packaged backend crash on startup** — PyInstaller now bundles `ViGEmClient.dll` under `vgamepad/win/vigem/client/{x64,x86}/`, fixing `FileNotFoundError` in release builds.
- **False gamepad driver detection** — skip the probe when the backend is already in gamepad mode; increased check timeout to 8 s for cold PyInstaller imports.
- **Electron backend lifecycle** — kill hung/orphaned backend processes on restart; validate HTTP/HTTPS URLs before `openExternal`; ensure backend shuts down cleanly on app quit.

---

## [13.1.0] — 2026-05-27

### Added

- **Gamepad output mode** — choose between keyboard (E/Q) and virtual Xbox 360 controller (XInput) for shift injection. Gamepad mode uses `vgamepad` + ViGEmBus driver and supports 10 configurable button options (A/B/X/Y/LB/RB/DPAD…). Default mapping: **B** = upshift, **X** = downshift.
- **Per-car profile persistence** — learned gear ratios, power-curve data, and rev-limiter detection are now saved to `tcu_profiles.json` keyed by `(car_ordinal, car_class, PI)`. Data survives restarts and is restored automatically when you switch back to a previously-driven car+tune combination.
- **"Save & Restart Backend" button** in network and output-mode settings, so configuration changes that require a restart (IP/port/UDP port, output mode) can be applied in one click.
- **Gamepad button selector** — a dropdown (not free-text input) in both the Electron Settings and the Web UI for choosing gamepad shift buttons, showing descriptive labels like "A (bottom)", "LB (左肩键)".
- **Line-buffered stdout parsing** — prevents a rare 30 s startup timeout when the `[backend-ready]` marker is split across two OS pipe chunks.
- **Renderer sandbox enabled** on both the Settings and HUD `BrowserWindow` instances, blocking direct Node.js access from renderer processes (Electron security hardening).

### Changed

- **Output interface abstraction** — `VirtualKeyboard` is now `KeyboardOutput`, implementing the shared `OutputInterface` ABC. `TCULogic` and `ReverseHoldDetector` interact with the interface, making keyboard/gamepad backends fully interchangeable.
- **Vehicle identity** — the internal identifier for a car is now the composite `car_key = (car_ordinal, car_class, PI)` instead of bare `car_ordinal`. This fixes a long-standing bug where swapping to a differently-tuned copy of the same car model did not trigger a fresh learning cycle.
- **`vgamepad`** is now a regular (non-optional) Python dependency. If the ViGEmBus driver is not installed, switching to gamepad mode prints a clear error and automatically falls back to keyboard output.

### Fixed

- Same car model with different tune setups no longer silently reuses stale gear-ratio and power-curve data from the previous tune.
- `ProfileStore` was instantiated but never called at runtime — `tcu_profiles.json` was never created. Now works as documented.

---

# 更新日志

## [13.2.8] - 2026-08-07

### 修复

- **升挡点被钉死在断油线上（#74）** — 学习到的动力曲线现在真正生效。此前它的置信度要求真实驾驶产生不出的采样离散度（issue 提供的九份回放实测 0.045–0.099，阈值却是 0.16），并且在置信度混合之上还压了一道硬门，把侥幸活下来的结果也抹平；结果是这些日志里约 500 次升挡中，动力曲线只影响过 5 次。所有车最终都在断油点换挡，而不是在功率峰值附近。
- **断油转速低于名义转速 90% 的车辆** — 高转覆盖度原本以 Forza 虚高的 `engine_max_rpm` 为分母，Ford GT（断油在名义值的 88.3%）永远无法达标，动力曲线被永久禁用。现在反复回到同一转速天花板也计为已覆盖转速带顶部。
- **无法达到升挡目标的挡位** — 车辆可能受风阻限制却不符合负载平台检测要求的「转速钉死」（问题中的 Ford GT 在 4 挡以每秒 0.6% 缓慢爬升，同时车速仍在每秒增加 2.2 km/h；目标需要 320 km/h，实际只能到 299）。新增更长窗口的停滞判据，且仅在越过功率峰值后才武装，使该挡位得以解放——该车现在能升上 5 挡而不是卡在 4 挡。
- **牵引锯齿被误学成断油** — 低挡牵引振荡可能被确认为断油红线，并从此把所有换挡点拖低（一台 Pagani Huayra R 在已经拉到 11,524 rpm 之后仍被钉在 9,765 rpm，Race 目标塌陷到 80% 的中段地板）。现在已学习值与候选值都必须高于发动机实际达到过的最高 WOT 转速；已存储但后来被转速超越的值会被丢弃。此检查之前写入的配置文件，会在加载时用动力曲线已持久化的覆盖度进行校正。
- **低于功率峰值的车速墙** — 负载平台与挡位停滞证据不再允许把换挡点压到学习到的功率峰值转速以下；只有实测到的转速天花板才可以。

### 变更

- **后驱牵引升挡** — 冷车守卫改为要求目标挡位已标定落点转速，不再用动力曲线置信度充当「这辆车已经开了一段时间」的代理——在曲线以正常速度成熟之后，该代理不再成立。
- **配置文件内容** — 新增可选键 `power_curve.ceiling_hits` 与 `rev_limiter.max_wot_rpm`。两者缺失时按 0 处理，既有字段的单位与含义不变，旧文件照常加载，因此 `PROFILE_SCHEMA_VERSION` 保持为 1，任何车辆都无需重新学习。

## [13.2.7] - 2026-07-21

### 修复

- **高挡永久锁死** — 取消「六挡起硬封顶」假设；漏确认改为带上限的指数退避软封顶，使 7–10 速变速箱可恢复升挡，降挡会清除过期封顶状态。
- **跨挡断油红线信任** — 将各次独立断油候选记入证据库并跨挡确认，后续挡位复用首次可靠发现，不再因每次实时候选升挡后重置而反复撞断油。
- **高挡误判负载平台** — 要求按时间归一化的转速/车速证据，并在接近红线时才允许下调 WOT 目标；普通 81–84% 高速加速不再触发过早的 8→9 / 9→10。
- **Race/Offroad 下坡恢复** — 在低油门/轻刹车且车速持续增加时进行发动机制动降挡（可高于旧的 30% 滑行门槛）；坡顶卸载保持有连续时长上限，长下坡不会无限冻结换挡。
- **配置学习生命周期** — `tcu_profiles.json` 使用与应用版本无关的信封版本（`PROFILE_SCHEMA_VERSION = 1`），不兼容/旧格式归档备份，稳定发动机指纹切换，并在学习里程碑到达时原子写入。
- **标定交互** — 为当前车辆增加需确认的「重新学习」；设置重置改为确认对话框；配置/配置文件变更向所有客户端广播。
- **回放回归** — 覆盖 13.2.6 洁净 profile 日志、软封顶重试/退避、跨挡红线确认、持续卸载坡道与下坡降挡路径。

### 变更

- **旧版配置文件** — 早期无版本扁平 `tcu_profiles.json` 会归档并替换为新信封；升级到 13.2.7 后车辆需重新学习一次。之后普通应用发版在 schema 不变时保留已学习数据。

## [13.2.6] - 2026-07-20

### 修复

- **Race 起步与轮滑稳定性** — 当已学习的下一挡落点低于动力区间时保持当前低挡，三挡牵引力升挡前要求足够转速，并在驱动轮恢复抓地前禁止动力降挡，避免 Pagani Huayra 等高性能车辆陷入 `2→3→2` 起步循环。
- **更快识别实际断油点** — 稳定的实时断油候选可在严格的持久化安全红线完全确认前用于升挡时机，减少发动机停留在有效红线之外的时间，同时不降低防超转保护。
- **低红线与不可达红线** — 支持确认低至 Forza 名义最高转速 78% 的真实断油特征，将学习目标限制在配置值或已验证可达上限内，并恢复无法达到常规 WOT 目标的低挡及高负载平台升挡。
- **高挡持续负载平台** — 在持续极速/负载墙下恢复升挡，同时排除正常缓慢爬升、刹车、轮滑、松油和车身瞬态造成的误判。
- **坡顶换挡保持** — 在完全离地检测触发前识别短暂悬挂卸载并冻结自动换挡，避免高速发飘时错误降入高转低挡。
- **换挡安全与确认** — 在 Forza 换挡中间挡位编码期间保留待确认升挡，安全重试被拒绝的低挡指令，统一涡轮需求量纲，并保证刹车/动力降挡不超过学习到的安全转速。
- **回放回归覆盖** — 新增 Nissan Be-1、Ford GT 2005、Pagani Huayra、Shelby Daytona、Lamborghini Huracán STO、低红线车辆、坡顶、刹车和低挡 hunting 的录制与合成测试。

## [13.2.6-pre.4] - 2026-07-16

> **预发布测试版**
>
> 修正 Lamborghini Huracán STO、Shelby Daytona，以及实际断油转速明显低于 Forza 名义最高转速车辆的红线识别。

### 修复

- **STO 高挡过早升挡** — 将短窗口转速触顶回退限制在 1–2 挡，4–7 挡正常但较慢的转速上升不再被误判为无法达到的红线。
- **低于名义转速的断油识别** — 支持识别名义转速 78% 以上、重复出现的断油锯齿；同时排除单次转速跌落、跨挡残留、轮胎打滑与持续移动的峰值。
- **Shelby 三挡恢复** — 识别 Daytona 约 89% 的实际断油红线，恢复自动 `3→4` 升挡。
- **长红区低端车辆** — 学习约 84% 的可达红线，恢复连续 `1→2→3` 升挡，并将已验证红线用于降挡防超转，避免正确升挡后立即被软件降回。
- **配置兼容** — 新确认的实际红线使用带版本标记的格式持久化；旧版较低红线在实时重新确认前不会被信任，防止历史误学习重新生效。
- **回放回归** — 新增两份 STO、Shelby 与高红区低端车回放测试，并保留 Ford、Pagani、刹车与低挡测试覆盖。

## [13.2.6-pre.3] - 2026-07-16

> **预发布测试版**
>
> 修复 Ford GT 2005、Pagani Huayra R 2021 与刹车后恢复升挡的剩余边缘问题，同时保留已经改善的 D/C 级车辆升挡表现。

### 修复

- **可达升挡上限** — 将 Race/Offroad 自学习目标限制在配置值或已验证的可达回退值以内，防止成熟动力曲线要求车辆无法达到的转速。
- **高挡持续负载平台** — 高负载、低打滑且转速和车速稳定至少一秒后允许恢复升挡；转速上升、刹车、松油、打滑或换挡都会重置检测。
- **涡轮补偿量纲** — 比较内部涡轮状态前先归一化原始增压值，避免 85% 转速以下被永久禁止升挡。
- **Race 轮滑落挡保护** — 阻止落点低于 `race_power_floor` 的牵引力升挡，避免 `2→3→2` 循环，同时保留健康落点和未学习齿比时的保护。
- **回放回归** — 覆盖 Ford、Pagani、刹车卡二挡、起步、D/C 级车辆、刹车安全与升挡确认路径。

## [13.2.6-pre.1] - 2026-07-14

> **预发布测试版**
>
> 在 v13.2.5 基础上细化升档逻辑（用户 replay `跳一档.gz` 反馈）：取消 1–2 档固定 80% 阈值，改为转速触顶检测。

### 修复

- **v13.2.5 回归（用户 replay `跳一档.gz`）** — 用 `_rpm_ceiling_reached()`（紧 plateau + 低档速度墙）替代 1–2 档固定 `race_up_mid` 回退；在实测天花板（`peak - 1%`）升档，不再一律 80%。禁用 1 档打滑升档（仅 2–3 档、RPM ≥ 72%），修复起步 ~66% 过早升档；刹车后再加速时 RPM 触顶可恢复升档。
- **pytest** — `test_low_gear_rpm_ceiling.py` 增加 `跳一档.gz` 回放回归。

## [13.2.5] - 2026-07-14

### 修复

- **Race 一档转速触顶 (#67 后续)** — Race/Offroad 的 1–2 档在-band 升档回退值降至 `race_up_mid` / `offroad_up_mid`，避免长齿比车辆全油门卡在 ~89% 却永远不发升档指令。
- **冷启动 AWD/FWD 打滑升档** — 动力曲线未校准时，打滑升档禁用仅保留 RWD；AWD 起步大滑移可再次升档。`TCULogic.__init__` 初始化 `_slip_streak`。
- **pytest** — `test_low_gear_rpm_ceiling.py`（合成场景 + 用户 `tcu_replay_20260714_*.bin.gz` 回放）。

## [13.2.4] - 2026-07-14

### 修复

- **低档乱档 / 升档卡死 (#67)** — Forza 换挡中遥测（`gear > 10`）不再在车辆仍处原档时清除 pending 升档门闩；换挡进行中延长等待截止时间，避免超时后再发第二次 UP 导致跳档。`_we_shifted` 不再在按键当帧清除，慢速游戏确认不会永久锁死低档自动升档。
- **pytest** — `test_issue67_low_gear_hunting.py` 覆盖换挡中编码、慢确认超时恢复与高马力跳档回归路径。

## [13.2.3] - 2026-07-10

### 新增

- **GitHub Issue 模板** — 双语缺陷报告与功能请求表单（`bug_report.yml`、`feature_request.yml`），含版本、安装方式、组件、复现步骤与环境检查；`config.yml` 禁用空白 Issue。
- **遥测模型** — 从 FH6 UDP 解析 `TireSlipAngle`（offset 164）与 `TireCombinedSlip`（offset 180）写入 `Telemetry` 模型（纯增量，TCU 逻辑暂未使用）。
- **pytest** — `test_early_upshift_rev_limiter.py` 覆盖 Race 模式升档时机与 TCU 升档平台误学断油红线（#62）。

### 变更

- **换挡时序常量** — `LOW_GEAR_LOCK_MS` 800→400 ms；`UPSHIFT_PENDING_TIMEOUT_S` 1.2→0.7 s，升档响应更快（#61）。
- **动力曲线置信度** — `HIGH_RPM_COVERAGE` 0.78→0.90；高转覆盖不足或置信度 <70% 时升档点不低于配置的 `race_up_wot` 回退值；无高转证据前一律拒绝中段抛物线峰值。
- **Cloud 开发文档** — `AGENTS.md` 补充 Node 24 选择与 dashboard smoke 测试注意事项。

### 修复

- **轮胎滑移偏移 (#56)** — `TireSlipRatio` 改从字节 offset **84** 读取（原先误读 offset 136 的 `WheelInPuddleDepth`），修复 AWD 干地比赛 `front_slip` 恒为 0.00，恢复后驱打滑升档等依赖滑移的逻辑。
- **过早升档 (#62)** — `RevLimiterDetector` 不再覆写 `td.engine_max_rpm`；升档后 0.8 s 内忽略断油样本；仅当 bounce ≥ 名义红线 97% 时才提交学习值； learned 红线仅用于 `_rev_ceiling()` 过转保护，换挡与动力曲线仍用游戏名义 `engine_max_rpm`。
- **HUD 码表刻度重复 (#66)** — 去重舍入碰撞的 RPM 刻度标签，Vue 节点按索引绑定 key，长时间驾驶不再累积重复刻度数字（如 6k 红线出现重复 2/5）。

## [13.2.2] - 2026-06-07

### 新增

- **功能切换工具提示** — 共享的 `FeatureToggleList` 组件在每个开关旁边显示一个信息图标；鼠标悬停在图标上会显示 Electron 设置和 Web 控制面板上的简短英文/中文说明。

- **pytest** — `test_power_curve_cold_start.py`（仅中段转速的采样不得导致提前升档）；`test_upshift_pending.py` 已扩展，用于低档位上限重试和反向起步升档。

### 更改

- **动力曲线冷启动** — 跟踪每辆车的高转速覆盖率；统计 1 档静止状态下踩刹车加油门的转速变化以进行学习；提高接近转速限制器时全油门采样的权重；在转速达到 ≥78% 之前，拒绝仅中段转速的抛物线峰值；在此之前，将赛道升档保持在配置的 `race_up_wot` 回退值；将 `max_r` 保留在已保存的动力曲线配置文件中。

- **后驱车轮打滑升档** — 当每辆车的动力曲线置信度仍然较低（<25%）时，跳过牵引力保护升档。

- **设置功能面板** — 用户界面仅列出 11 个核心开关；Discord RPC、换挡提示音和按住 Q 键倒车功能已从面板中隐藏，但仍可通过 `tcu_config.json` 访问。

### 已修复

- **低档升档失败** — 当车辆仍处于全油门接近红线转速时，在执行 `UPSHIFT_CAP_RETRY_S` 后，软性最高档位（6 档以下）的升档限制会被清除，因此 TCU 会重试而不是保持限制；6 档及以上档位对不可能的齿比保持硬性限制。

- **倒车后起步** — 倒车退出锁定窗口期间，退出倒车挡不再阻止前进挡 1 档红线升档。

## [13.2.1] — 2026-06-06

### 新增

- **UDP 遥测转发（UDP Hub）** — 将原始 FH6 UDP 数据包转发到一个或多个 `host:port` 目标；网络设置中可配置，保存前校验重复目标与回环端口，服务端解析目标列表。
- **日志（Logs）标签页** — Electron 设置与 Web 仪表盘共用统一录制控制台：xterm 实时系统输出、可选解析遥测流、回放录制启停、融合快照操作，以及输出格式选择（`bin.gz`、`csv`、`json`、`jsonl`、`summary`、`chart.html`）。
- **融合快照记录器（Fusion Snapshot Logger）** — 环形缓冲（约 3 秒）融合遥测与 TCU 状态；自动/手动换挡、红线异常、F8 或日志页触发时导出 CSV（可选自包含 `chart.html`）；经 WebSocket 广播 `fusion_snapshot`。
- **回放导出管线** — 停止录制时按所选格式内联转换；CSV 按 `is_race_on` 自动拆分为 roaming / `raceN` 文件；`format_paths` 支持合并多个回放输入；新增 `scripts/plot_snapshot.py` 离线绘图脚本。
- **Electron 更新弹窗** — `UpdateAvailableModal` 展示发行说明、应用内下载进度、GitHub 备用下载与重启安装；托盘菜单文案随系统语言切换（中/英）。
- **pytest 测试** — 升挡 pending、分调教档案键、齿轮比发动机制动样本过滤、UDP Hub 转发/校验、后端重启 argv。

### 变更

- **车辆档案键** — 档案按 `(car_ordinal, car_class, pi, tune_id)` 存储；`tune_id` 由发动机/传动系统签名与齿轮比漂移分槽决定；仍兼容旧版三段键。
- **齿轮比学习** — 忽略发动机制动、滑行拖转及档位顺序无效样本，校准更稳定。
- **网络设置** — 统一「应用」流程，经 `set_network` 一次性保存 Web 主机/端口、UDP 端口与 UDP Hub 目标。

### 修复

- **升挡连发 / 顶档卡住** — pending 升挡窗口内禁止重复按 E，直至游戏确认换挡；升挡失败时对该调教封顶最高可用档位（#48、#50）。
- **换调教档案复用** — 同 PI 换不同调教时不再误用过期齿轮比导致升不了档（#49）。
- **开发环境后端重启** — `exec_restart()` 改为 `python -m virtual_tcu` 重新拉起，避免网络设置重启后因 `__main__.py` 路径导致 import 失败。

## [13.2.0] — 2026-06-02

### 新增

- **vJoy 输出模式** — 通过虚拟 DirectInput 设备注入换挡（适合力反馈方向盘）；设置中可配置升/降挡/离合按键及直按换挡 vs 离合辅助路径。
- **键盘离合辅助** — 可选在 E/Q 换挡前按下离合键，预压/重叠/释放时间可调；Electron 设置与 backend-only Web UI 均提供相关选项。
- **HUD 模板** — 经典（弧形转速表）、竞技（分段 RPM 条）、极简（LED 点阵转速）；换档提示箭头、换档横幅、踏板条、点击穿透固定/解除，各模板有最小窗口尺寸。
- **HUD 动态尺寸** — `hud:set-size` IPC，高度随内容伸缩；旧版 `glass` 模板配置自动映射为经典模板。
- **backend-only Web 完整设置** — 便携 zip / `python -m virtual_tcu` 仪表盘恢复右侧完整设置栏（vJoy、离合辅助、网络、档案等），与 Electron 共用 `packages/ui` 组件。
- **pytest 测试** — 腾空检测与 Race 模式积极降挡行为有单元测试覆盖。

### 变更

- **驾驶模式** — F9 循环中移除独立 **DYNAMIC**；原动态模式逻辑并入 **COMFORT** / **RACE**，由驾驶风格追踪器在 CRUISE / ADAPTIVE / SPORT 子状态间切换（`feat_drive_style`）。
- **Race TCU** — 更积极的降挡；腾空落地与运动型滑行后恢复档位；腾空改由垂直加速度检测（不再依赖轮胎滑移），并全局保持腾空锁定。
- **Monorepo UI** — 设置/HUD 文案与组件迁至 `packages/shared`、`packages/ui`；Electron 设置与浏览器仪表盘共用同一套 UI。
- **语言选择** — 设置中改进 locale 切换体验。

### 移除

- **虚拟 XInput 手柄输出** — 完全移除（`GamepadOutput`、`vgamepad`/ViGEmBus、内置 `driver/ViGEmBusSetup_x64.msi`、`installViGEmBus`/`check_gamepad` IPC 与 WebSocket 路径及全部手柄相关设置/文案）。作为第二台 XInput 设备会在每次换挡时发送完整手柄状态包，导致转向/油门被清零、弯道手感迟滞。输出现为 **键盘**（默认）或 **vJoy**；已保存的 `output_mode: "gamepad"` 自动回退为键盘。
- **`OutputInterface.set_brake`** — 仅虚拟手柄需要刹车镜像，已从接口与 TCU 主循环移除。
- 仓库内**过时的 vJoy DLL**；运行时需自行安装 vJoy 驱动。

### 修复

- **vJoy** — 误配离合键保护；恢复按键保持时序；未使用 vJoy 时后端不再强制退出。
- **手动 + 离合** — 离合辅助 + 手动 TCU 模式下不再卡在空挡。
- **运动滑行 / 撞击** — 硬着陆与运动型滑行后恢复目标档位。
- **HUD** — 修复 lint-staged stash 导致的部分重设计丢失。

---

## [13.1.2] — 2026-05-29

### 新增

- **Electron 后端 HTTP 健康探测** — 除 stdout `[backend-ready]` 外，主进程通过本机 HTTP 响应判断 aiohttp 是否已就绪。
- **ViGEmBus MSI 完整性校验** — 启动安装包前校验内置 MSI 的 SHA-256，防止被篡改后静默执行。

### 变更

- **Electron 后端生命周期模块** — 抽离 `BackendLifecycle`，重启互斥、异步进程树杀灭、`readline` 按行解析 stdout。
- **IPC 结构化返回** — `openExternal` 与 `installViGEmBus` 返回 `{ ok, error }`，设置页可展示明确错误。

### 修复

- **日文 Windows (cp932) 启动崩溃** — 强制 stdout/stderr 使用 UTF-8，控制台日志改为 ASCII 安全字符，避免打包版在 banner 处 `UnicodeEncodeError` 导致一直 disconnected。
- **并发重启竞态** — 托盘/IPC 快速连点「重启后端」不再重叠拉起多个 Python 进程。

### 安全

- **`open-external` URL 策略** — 拦截渲染进程发起的 localhost、内网与 link-local 链接（用户在其它设备浏览器手动访问局域网仪表板不受影响）。

---

## [13.1.1] — 2026-05-27

### 新增

- **内置 ViGEmBus 驱动安装包** — `driver/ViGEmBusSetup_x64.msi` 随 Electron 安装包分发（`resources/driver/`），并上传至仓库供直接下载。设置页提供 **安装驱动** 按钮，一键启动内置 MSI。
- **手柄驱动预检** — 在设置中切换到手柄模式时，保存配置前通过 WebSocket `check_gamepad` 检测驱动是否可用；失败时显示本地化提示，并可直接跳转安装。
- **WebSocket init 新增 `effective_output_mode`** — 前端可获知后端当前实际运行的输出模式（键盘/手柄），而不只看 config 里的配置值（切换后需重启后端才生效）。

### 变更

- **轻量级手柄可用性检测** — 预检改为临时连接 ViGEmBus 总线，不再创建临时虚拟 XInput 手柄，避免产生 ghost 手柄，以及在后端已运行手柄模式时误报「驱动未安装」。
- **PyInstaller vgamepad 打包** — `virtual_tcu.spec` 在不 import vgamepad 的前提下收集 `ViGEmClient.dll` 及 hidden imports，CI/构建机无需安装 ViGEmBus 驱动。
- **vgamepad 延迟加载** — 移除 `deps.py` 启动时的 `import vgamepad`，手柄客户端 DLL 不可用时键盘模式仍可正常启动。
- **`installViGEmBus` 重构** — 移入 settings store，Electron 设置窗口与 Web UI 共用更清晰的封装。

### 修复

- **打包版后端启动崩溃** — PyInstaller 现会将 `ViGEmClient.dll` 打入 `vgamepad/win/vigem/client/{x64,x86}/`，修复发版后 `FileNotFoundError`。
- **手柄驱动误报** — 后端已在手柄模式运行时跳过预检；检测超时延长至 8 秒，适配 PyInstaller 冷启动较慢的 import。
- **Electron 后端生命周期** — 重启时清理挂死/孤儿后端进程；`openExternal` 前校验 HTTP/HTTPS URL；退出应用前确保后端正常关闭。

---

## [13.1.0] — 2026-05-27

### 新增

- **手柄输出模式** — 可选择键盘（E/Q）或虚拟 Xbox 360 手柄（XInput）来注入换挡指令。手柄模式使用 `vgamepad` + ViGEmBus 驱动，支持 10 种可配置按钮（A/B/X/Y/LB/RB/十字键…）。默认映射：**B** = 升挡，**X** = 降挡。
- **每车档案持久化** — 学习到的齿轮比、动力曲线和断油转速数据现在会按 `(car_ordinal, car_class, PI)` 三维度保存至 `tcu_profiles.json`。数据在重启后保留，切换回之前驾驶过的车辆+调校组合时自动恢复。
- **「保存并重启后端」按钮** — 在网络设置和输出模式卡片中，一键保存并重启后端，适用于需要重启才能生效的配置变更（IP/端口/UDP 端口、输出模式切换）。
- **手柄按钮选择器** — Electron 设置窗口和 Web UI 中均使用下拉框（而非文本输入）选择手柄换挡按键，带描述性标签如「A (底部)」「LB (左肩键)」。
- **行缓冲 stdout 解析** — 防止 `[backend-ready]` 标记在 OS 管道中被切分为两个 chunk 时导致的 30 秒超时启动失败。
- **启用渲染器沙箱** — Settings 和 HUD 两个 `BrowserWindow` 均启用 `sandbox: true`，阻止渲染进程直接访问 Node.js API（Electron 安全加固）。

### 变更

- **输出接口抽象** — `VirtualKeyboard` 现为 `KeyboardOutput`，实现统一的 `OutputInterface` 抽象基类。`TCULogic` 和 `ReverseHoldDetector` 通过接口交互，键盘/手柄后端可完全互换。
- **车辆标识** — 内部车辆标识符现为复合的 `car_key = (car_ordinal, car_class, PI)`，而非单独的 `car_ordinal`。修复了一个长期存在的 bug：切换到同一车型的不同调校时，学习系统不会触发新的学习周期。
- **`vgamepad`** 现为常规（非可选）Python 依赖。若 ViGEmBus 驱动未安装，切换到手柄模式时会打印清晰的错误提示并自动回退到键盘模式。

### 修复

- 同一车型的不同调校不再静默复用上一个调校的过期齿轮比和动力曲线数据。
- `ProfileStore` 之前被实例化但从未在运行时调用——`tcu_profiles.json` 从未被创建。现在按文档说明正常工作。
