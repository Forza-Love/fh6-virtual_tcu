# Adaptive Upshift Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore reliable Race/Offroad upshifts for unreachable learned targets and sustained high-gear load plateaus while preventing low-power-band wheelspin shifts and preserving the `13.2.6-pre.2` brake and rising-RPM protections.

**Architecture:** Keep all policy in `TCULogic`, but separate three decisions behind small helpers: a shared bounded upshift target, normalized turbo demand, and a timed high-gear load-plateau detector. Add a Race-only ratio-aware wheelspin landing guard, then prove the combined behavior with synthetic tests and the three supplied replays.

**Tech Stack:** Python 3.12+, pytest, Ruff, TypeScript/Vue/Electron workspace validation with Node 24 and pnpm 10.33.0.

## Global Constraints

- Production runtime is Windows-only; use CI-parity checks and `pnpm test:py` on non-Windows hosts.
- Use Node 24 or newer and pnpm 10.33.0 for workspace commands.
- Add no dependencies and no per-car Ford/Pagani exceptions.
- Keep the `13.2.6-pre.2` rising-RPM, brake landing, pending-upshift, and low-gear RPM-ceiling protections.
- Apply the new wheelspin landing guard to Race only; leave Comfort and Offroad wheelspin policy unchanged.
- Treat the configured/verified fallback as an upper bound on learned upshift targets in Race and Offroad.
- Do not touch user-owned `d.json` or `dummy.json`.
- Do not move or recreate `v13.2.6-pre.2`; release this work as `13.2.6-pre.3`.
- Recorded gear values cannot acknowledge newly generated replay commands; replay tests must inspect the first relevant command/window rather than treating later retries as real-game hunting.

## File Map

- Modify `virtual_tcu/logic/tcu.py`: bounded target helper, normalized turbo helper, timed high-gear plateau state, Race wheelspin landing guard, and call-site integration.
- Create `tests/test_adaptive_upshift_recovery.py`: focused synthetic unit tests for the four new policy boundaries.
- Create `tests/test_adaptive_upshift_replays.py`: replay-level regressions for Ford, Pagani, and brake-downshift recovery.
- Modify `CHANGELOG.md`: bilingual `13.2.6-pre.3` release notes.
- Modify `package.json`: set the release version; `scripts/sync-version.mjs` updates the remaining package and Python version files.
- Modify generated version targets: `apps/dashboard/package.json`, `apps/electron/package.json`, `packages/shared/package.json`, `packages/ui/package.json`, `pyproject.toml`, and `virtual_tcu/__init__.py`.

---

### Task 1: Bound every learned upshift target with one shared helper

**Files:**

- Create: `tests/test_adaptive_upshift_recovery.py`
- Modify: `virtual_tcu/logic/tcu.py:1179-1217`

**Interfaces:**

- Consumes: `_wot_upshift_fallback(td: Telemetry, *, mode: Mode | None = None) -> float` and `PowerCurveDetector.optimal_upshift_rpm(td, fallback, offset) -> float`.
- Produces: `_effective_upshift_pct(td: Telemetry, offset: float, *, mode: Mode | None = None) -> float`, used by anti-hunting, in-band upshifts, and the shift advisor.

- [ ] **Step 1: Write failing target-boundary tests**

Create `tests/test_adaptive_upshift_recovery.py` with:

```python
"""Regression coverage for bounded and recoverable automatic upshifts."""

from __future__ import annotations

import copy

import pytest
from tests.conftest import CAR_KEY, feed, make_telemetry
from virtual_tcu.core.mode import Mode


def _force_learned_target(monkeypatch, tcu, target: float) -> None:
    monkeypatch.setattr(
        tcu._power_curve,
        "optimal_upshift_rpm",
        lambda td, fallback, offset: target,
    )


def test_learned_target_cannot_exceed_configured_race_wot(
    make_logic, out, clock, monkeypatch
):
    tcu = make_logic("RACE")
    _force_learned_target(monkeypatch, tcu, 0.97)
    td = make_telemetry(
        gear=4,
        current_rpm=0.94 * 8000,
        engine_max_rpm=8000,
        speed_ms=170 / 3.6,
        accel_raw=255,
        brake_raw=0,
    )

    assert tcu._effective_upshift_pct(td, 0.03) == pytest.approx(0.94)
    assert tcu._track_upshift_in_band(td, clock.now, offset=0.03) is True
    assert [kind for kind, _ in out.shifts] == ["UP"]


def test_advisor_and_anti_hunt_use_the_same_bounded_target(
    make_logic, monkeypatch
):
    tcu = make_logic("RACE")
    tcu._last_auto_mode = Mode.RACE
    _force_learned_target(monkeypatch, tcu, 0.97)
    td = make_telemetry(
        gear=4,
        current_rpm=0.945 * 8000,
        engine_max_rpm=8000,
        speed_ms=170 / 3.6,
        accel_raw=255,
    )

    assert tcu._anti_hunt_upshift_pct(td) == pytest.approx(0.94)
    tcu._compute_shift_advisor(td)
    assert tcu._shift_advice == "up"
```

- [ ] **Step 2: Run the new tests and verify the missing helper fails**

Run:

```bash
pytest tests/test_adaptive_upshift_recovery.py::test_learned_target_cannot_exceed_configured_race_wot tests/test_adaptive_upshift_recovery.py::test_advisor_and_anti_hunt_use_the_same_bounded_target -v
```

Expected: FAIL because `TCULogic` has no `_effective_upshift_pct` and the existing call sites accept the learned 97% target.

- [ ] **Step 3: Add the shared bounded-target helper and replace all three call sites**

In `virtual_tcu/logic/tcu.py`, add beside `_wot_upshift_fallback`:

```python
def _effective_upshift_pct(
    self,
    td: Telemetry,
    offset: float,
    *,
    mode: Mode | None = None,
) -> float:
    """Bound the learned shift point by the configured/reachable fallback."""
    fallback = self._wot_upshift_fallback(td, mode=mode)
    learned = self._power_curve.optimal_upshift_rpm(
        td,
        fallback=fallback,
        offset=offset,
    )
    return min(learned, fallback)
```

Replace `_anti_hunt_upshift_pct` with:

```python
def _anti_hunt_upshift_pct(self, td: Telemetry) -> float:
    """Return the effective upshift point used to guard a downshift."""
    offset = 0.07 if self.mode == Mode.OFFROAD else 0.03
    return self._effective_upshift_pct(td, offset)
```

In `_track_upshift_in_band`, replace the fallback/model calculation with:

```python
target_pct = self._effective_upshift_pct(td, offset)
```

In `_compute_shift_advisor`, replace both Race and Offroad branches with:

```python
if base_mode == Mode.RACE:
    up_pct = self._effective_upshift_pct(td, 0.03, mode=base_mode)
elif base_mode == Mode.OFFROAD:
    up_pct = self._effective_upshift_pct(td, 0.07, mode=base_mode)
```

- [ ] **Step 4: Run focused and neighboring target tests**

Run:

```bash
pytest tests/test_adaptive_upshift_recovery.py tests/test_power_curve_cold_start.py tests/test_hunting.py -v
```

Expected: PASS; learned power-curve calculations remain intact, while callers apply the fallback ceiling consistently.

- [ ] **Step 5: Commit the bounded-target change**

```bash
git add tests/test_adaptive_upshift_recovery.py virtual_tcu/logic/tcu.py
git commit -m "fix: bound learned upshift targets"
```

---

### Task 2: Normalize turbo demand before spool blocking

**Files:**

- Modify: `tests/test_adaptive_upshift_recovery.py`
- Modify: `virtual_tcu/logic/tcu.py:1253-1274`

**Interfaces:**

- Consumes: telemetry `boost_raw`, `throttle`, and `rpm_pct`.
- Produces: `_turbo_target(td: Telemetry) -> float` in the normalized `[0.0, 1.8]` range, shared by `_update_turbo` and `_turbo_lag_block_upshift`.

- [ ] **Step 1: Add failing normalized-turbo tests**

Append to `tests/test_adaptive_upshift_recovery.py`:

```python
def test_out_of_range_raw_boost_uses_normalized_estimate(make_logic):
    tcu = make_logic("RACE")
    td = make_telemetry(
        current_rpm=0.80 * 8000,
        engine_max_rpm=8000,
        accel_raw=255,
        boost_raw=12.0,
    )

    assert tcu._turbo_target(td) == pytest.approx(1.44)
    for _ in range(100):
        tcu._update_turbo(td, 0.016)
    assert tcu._turbo_lag_block_upshift(td) is False


def test_valid_raw_boost_remains_the_turbo_target(make_logic):
    tcu = make_logic("RACE")
    td = make_telemetry(boost_raw=1.2, accel_raw=255, current_rpm=6400)
    assert tcu._turbo_target(td) == pytest.approx(1.2)
```

- [ ] **Step 2: Run the turbo tests and verify they fail**

Run:

```bash
pytest tests/test_adaptive_upshift_recovery.py -k turbo -v
```

Expected: FAIL because `_turbo_target` does not exist and the blocker compares the normalized accumulator to `12.0 * 0.7`.

- [ ] **Step 3: Implement one normalized target and use it on both sides**

Replace the turbo methods in `virtual_tcu/logic/tcu.py` with:

```python
@staticmethod
def _turbo_target(td: Telemetry) -> float:
    """Return boost demand on the normalized scale used by `_turbo_bar`."""
    if 0.01 < td.boost_raw < 5.0:
        return min(td.boost_raw, 1.8)
    estimate = td.throttle * td.rpm_pct * 1.8
    return max(0.0, min(estimate, 1.8))

def _turbo_lag_block_upshift(self, td: Telemetry) -> bool:
    if not self._config.get("feat_turbo_compensate"):
        return False
    target = self._turbo_target(td)
    if target < 0.3 or td.throttle < 0.50:
        return False
    if td.rpm_pct > 0.85:
        return False
    return self._turbo_bar < target * 0.7

def _update_turbo(self, td: Telemetry, dt: float):
    target = self._turbo_target(td)
    if target > self._turbo_bar:
        self._turbo_bar += 3.5 * dt * (target - self._turbo_bar)
    else:
        self._turbo_bar -= 4.2 * dt * (self._turbo_bar - target)
    self._turbo_bar = max(0.0, min(self._turbo_bar, 1.8))
```

- [ ] **Step 4: Run turbo, target, and low-gear tests**

Run:

```bash
pytest tests/test_adaptive_upshift_recovery.py tests/test_low_gear_rpm_ceiling.py -v
```

Expected: PASS, including the existing launch rising-RPM protection.

- [ ] **Step 5: Commit normalized turbo handling**

```bash
git add tests/test_adaptive_upshift_recovery.py virtual_tcu/logic/tcu.py
git commit -m "fix: normalize turbo upshift demand"
```

---

### Task 3: Detect sustained high-gear load plateaus

**Files:**

- Modify: `tests/test_adaptive_upshift_recovery.py`
- Modify: `virtual_tcu/logic/tcu.py:70-80, 510-535, 1131-1178`

**Interfaces:**

- Consumes: `_rpm_pct_history`, `_speed_history`, `Telemetry.car_key`, gear, throttle, brake, drivetrain-specific slip, mode mid/WOT configuration, and `time.time()`.
- Produces: `_driven_wheel_slip(td: Telemetry) -> float`, `_reset_load_plateau() -> None`, and `_high_gear_load_plateau_reached(td: Telemetry, mid: float, mode: Mode, now: float) -> bool`.

- [ ] **Step 1: Add plateau test helpers and failing recovery/control tests**

Append to `tests/test_adaptive_upshift_recovery.py`:

```python
def _set_plateau_histories(tcu, *, rpm: float = 0.82, speed: float = 300.0) -> None:
    tcu._rpm_pct_history.clear()
    tcu._rpm_pct_history.extend([rpm] * 10)
    tcu._speed_history.clear()
    tcu._speed_history.extend([speed] * 15)


def _sample_fallback(tcu, clock, td, frames: int) -> float:
    fallback = 1.0
    for _ in range(frames):
        _set_plateau_histories(tcu, rpm=td.rpm_pct, speed=td.speed_kmh)
        fallback = tcu._wot_upshift_fallback(td)
        clock.now += 0.016
    return fallback


def test_sustained_high_gear_load_plateau_lowers_fallback(make_logic, clock):
    tcu = make_logic("RACE")
    td = make_telemetry(
        gear=4,
        current_rpm=0.82 * 8000,
        engine_max_rpm=8000,
        speed_ms=300 / 3.6,
        accel_raw=255,
        brake_raw=0,
        drivetrain=1,
        slip_rl=0.1,
        slip_rr=0.1,
    )

    fallback = _sample_fallback(tcu, clock, td, 70)
    assert fallback == pytest.approx(0.81)


def test_rising_high_gear_rpm_never_confirms_load_plateau(make_logic, clock):
    tcu = make_logic("RACE")
    td = make_telemetry(
        gear=4,
        current_rpm=0.84 * 8000,
        engine_max_rpm=8000,
        speed_ms=300 / 3.6,
        accel_raw=255,
        drivetrain=1,
    )

    for _ in range(90):
        tcu._rpm_pct_history.clear()
        tcu._rpm_pct_history.extend([0.80 + i * 0.002 for i in range(10)])
        tcu._speed_history.clear()
        tcu._speed_history.extend([295 + i * 0.5 for i in range(15)])
        fallback = tcu._wot_upshift_fallback(td)
        clock.now += 0.016

    assert fallback == pytest.approx(0.94)


@pytest.mark.parametrize(
    "breaker",
    ["throttle", "brake", "slip", "gear", "rpm_growth", "speed_growth"],
)
def test_load_plateau_continuity_resets_on_transient(make_logic, clock, breaker):
    tcu = make_logic("RACE")
    td = make_telemetry(
        gear=4,
        current_rpm=0.82 * 8000,
        engine_max_rpm=8000,
        speed_ms=300 / 3.6,
        accel_raw=255,
        drivetrain=1,
        slip_rl=0.1,
        slip_rr=0.1,
    )
    assert _sample_fallback(tcu, clock, td, 45) == pytest.approx(0.94)

    bad = copy.copy(td)
    _set_plateau_histories(tcu)
    if breaker == "throttle":
        bad.accel_raw = 0
    elif breaker == "brake":
        bad.brake_raw = 255
    elif breaker == "slip":
        bad.slip_rl = 1.0
    elif breaker == "gear":
        bad.gear = 3
    elif breaker == "rpm_growth":
        tcu._rpm_pct_history.clear()
        tcu._rpm_pct_history.extend([0.80 + i * 0.002 for i in range(10)])
    else:
        tcu._speed_history.clear()
        tcu._speed_history.extend([295 + i * 0.5 for i in range(15)])
    tcu._wot_upshift_fallback(bad)
    clock.now += 0.016

    assert _sample_fallback(tcu, clock, td, 45) == pytest.approx(0.94)
```

- [ ] **Step 2: Run plateau tests and verify they fail at the old 94% fallback**

Run:

```bash
pytest tests/test_adaptive_upshift_recovery.py -k plateau -v
```

Expected: the sustained Ford-shaped plateau test FAILS with fallback `0.94`; continuity controls may also fail because no timed plateau state exists.

- [ ] **Step 3: Add plateau state and drivetrain-aware slip calculation**

In `TCULogic.__init__`, after `_rpm_pct_history`, add:

```python
self._load_plateau_key: tuple[tuple, int, str] | None = None
self._load_plateau_since = 0.0
```

Add these helpers before `_rpm_ceiling_reached`:

```python
@staticmethod
def _driven_wheel_slip(td: Telemetry) -> float:
    if td.drivetrain == 0:
        return max(td.slip_fl, td.slip_fr)
    if td.drivetrain == 1:
        return max(td.slip_rl, td.slip_rr)
    return max(td.slip_fl, td.slip_fr, td.slip_rl, td.slip_rr)

def _reset_load_plateau(self) -> None:
    self._load_plateau_key = None
    self._load_plateau_since = 0.0

def _high_gear_load_plateau_reached(
    self,
    td: Telemetry,
    mid: float,
    mode: Mode,
    now: float,
) -> bool:
    key = (td.car_key, td.gear, mode.value)
    valid_load = (
        td.gear >= 3
        and td.throttle >= 0.85
        and td.brake <= 0.05
        and td.rpm_pct >= mid
        and self._driven_wheel_slip(td) <= 0.8
        and len(self._rpm_pct_history) >= 10
        and len(self._speed_history) >= 15
    )
    if not valid_load:
        self._reset_load_plateau()
        return False

    rpm = list(self._rpm_pct_history)[-10:]
    speed = list(self._speed_history)[-15:]
    rpm_growth = sum(rpm[-3:]) / 3 - sum(rpm[:3]) / 3
    speed_growth = speed[-1] - speed[0]
    if rpm_growth > 0.005 or speed_growth > 0.8:
        self._reset_load_plateau()
        return False

    if self._load_plateau_key != key:
        self._load_plateau_key = key
        self._load_plateau_since = now
        return False
    return now - self._load_plateau_since >= 1.0
```

In the long-pause reset block, add:

```python
self._reset_load_plateau()
```

- [ ] **Step 4: Integrate the timed plateau into the WOT fallback**

In `_wot_upshift_fallback`, replace the final ceiling check with:

```python
if td.gear >= 3:
    high_gear_plateau = self._high_gear_load_plateau_reached(
        td,
        mid,
        m,
        time.time(),
    )
else:
    self._reset_load_plateau()
    high_gear_plateau = False
if self._rpm_ceiling_reached(td, wot) or high_gear_plateau:
    peak = max(list(self._rpm_pct_history)[-10:])
    return min(wot, max(mid, peak - 0.01))
return wot
```

In `_wheelspin_upshift_now`, replace the drivetrain `if/elif/else` slip block with:

```python
slip = self._driven_wheel_slip(td)
```

- [ ] **Step 5: Run plateau and low-gear regressions**

Run:

```bash
pytest tests/test_adaptive_upshift_recovery.py tests/test_low_gear_rpm_ceiling.py -v
```

Expected: PASS. The stable high-gear fallback becomes `0.81`; rising and interrupted histories remain `0.94`; existing low-gear behavior is unchanged.

- [ ] **Step 6: Commit high-gear plateau recovery**

```bash
git add tests/test_adaptive_upshift_recovery.py virtual_tcu/logic/tcu.py
git commit -m "fix: recover sustained high gear load plateaus"
```

---

### Task 4: Reject Race wheelspin shifts that land below the power band

**Files:**

- Modify: `tests/test_adaptive_upshift_recovery.py`
- Modify: `virtual_tcu/logic/tcu.py:1688-1712`

**Interfaces:**

- Consumes: `GearRatioCalibrator.project_rpm_after_shift(td, target_gear) -> float | None`, nominal `engine_max_rpm`, and configured `race_power_floor`.
- Produces: `_race_wheelspin_landing_allowed(td: Telemetry, power_floor: float) -> bool`.

- [ ] **Step 1: Add failing landing-guard tests**

Append to `tests/test_adaptive_upshift_recovery.py`:

```python
def _wheelspin_frame(*, speed_kmh: float = 80.0):
    return make_telemetry(
        gear=2,
        current_rpm=0.80 * 8000,
        engine_max_rpm=8000,
        speed_ms=speed_kmh / 3.6,
        accel_raw=255,
        brake_raw=0,
        drivetrain=2,
        slip_rl=2.0,
        slip_rr=2.2,
        profile_tune_id=CAR_KEY[3],
    )


def test_race_wheelspin_shift_is_blocked_below_power_floor(make_logic, out, clock):
    tcu = make_logic("RACE")
    feed(tcu, out, clock, _wheelspin_frame(speed_kmh=80.0), 6)
    assert [kind for kind, _ in out.shifts if kind == "UP"] == []


def test_race_wheelspin_shift_is_allowed_with_healthy_landing(make_logic, out, clock):
    tcu = make_logic("RACE")
    feed(tcu, out, clock, _wheelspin_frame(speed_kmh=90.0), 6)
    assert [kind for kind, _ in out.shifts if kind == "UP"] == ["UP"]


def test_race_wheelspin_preserves_ratio_less_fallback(make_logic, out, clock):
    tcu = make_logic("RACE", seed_ratios=False)
    feed(tcu, out, clock, _wheelspin_frame(speed_kmh=80.0), 6)
    assert [kind for kind, _ in out.shifts if kind == "UP"] == ["UP"]
```

- [ ] **Step 2: Run landing tests and verify the low-landing case fails**

Run:

```bash
pytest tests/test_adaptive_upshift_recovery.py -k wheelspin -v
```

Expected: the 80 km/h case FAILS because gear 3 is projected at 58% RPM, below the 60% Race floor, but current code still issues `2→3`. Healthy and ratio-less controls pass.

- [ ] **Step 3: Implement the Race-only landing guard**

Add beside `_wheelspin_upshift_now`:

```python
def _race_wheelspin_landing_allowed(
    self,
    td: Telemetry,
    power_floor: float,
) -> bool:
    projected = self._calibrator.project_rpm_after_shift(td, td.gear + 1)
    if projected is None or td.engine_max_rpm <= 0:
        return True
    return projected / td.engine_max_rpm >= power_floor
```

Change the Race wheelspin branch to:

```python
if (
    self._wheelspin_upshift_now(td)
    and td.speed_kmh > 15.0
    and self._race_wheelspin_landing_allowed(td, power_floor)
):
    self._shift_up(td, 400, "WHEELSPIN", "traction save", downshift_lock_s=0.5)
    return
```

Do not change the Comfort or Offroad branches.

- [ ] **Step 4: Run wheelspin, hunting, and Race downshift tests**

Run:

```bash
pytest tests/test_adaptive_upshift_recovery.py tests/test_low_gear_rpm_ceiling.py tests/test_hunting.py tests/test_race_downshift.py -v
```

Expected: PASS. Low landings continue into the normal Race decision path without issuing traction-save upshifts; healthy and ratio-less traction shifts remain available.

- [ ] **Step 5: Commit the Race landing guard**

```bash
git add tests/test_adaptive_upshift_recovery.py virtual_tcu/logic/tcu.py
git commit -m "fix: guard race wheelspin shift landings"
```

---

### Task 5: Lock the supplied replays into end-to-end regressions

**Files:**

- Create: `tests/test_adaptive_upshift_replays.py`
- Read only: `logs/tcu_replay_FordGT2005.bin.gz`
- Read only: `logs/tcu_replay_PaganiHuayraR2021.bin.gz`
- Read only: `logs/刹车降档卡到2档.bin.gz`

**Interfaces:**

- Consumes: `iter_replay_records`, `parse_fh6_packet`, `TCULogic.process`, and `OutputInterface.shift_to`.
- Produces: `_replay_commands(...) -> list[dict]`, recording replay time, source/target gears, TCU reason, and RPM fraction for deterministic assertions.

- [ ] **Step 1: Create the replay harness and three acceptance regressions**

Create `tests/test_adaptive_upshift_replays.py`:

```python
"""Regression replay coverage for 13.2.6-pre.3 shift recovery."""

from __future__ import annotations

from pathlib import Path

import pytest
import virtual_tcu.logic.tcu as tcu_module
from tests.conftest import FakeOutput, REPO_ROOT
from virtual_tcu.config.store import ConfigStore
from virtual_tcu.logic.tcu import TCULogic
from virtual_tcu.storage.profiles import ProfileStore
from virtual_tcu.telemetry.logger import TelemetryLogger
from virtual_tcu.telemetry.parser import parse_fh6_packet
from virtual_tcu.telemetry.replay_reader import iter_replay_records

FORD = REPO_ROOT / "logs" / "tcu_replay_FordGT2005.bin.gz"
PAGANI = REPO_ROOT / "logs" / "tcu_replay_PaganiHuayraR2021.bin.gz"
BRAKE = REPO_ROOT / "logs" / "刹车降档卡到2档.bin.gz"


def _replay_commands(log_path: Path, monkeypatch, tmp_path) -> list[dict]:
    out = FakeOutput()
    cfg = ConfigStore(path=str(tmp_path / f"{log_path.stem}-cfg.json"))
    prof = ProfileStore(path=str(tmp_path / f"{log_path.stem}-prof.json"))
    tcu = TCULogic(out, prof, cfg, TelemetryLogger())
    tcu.set_mode("RACE")
    clock = {"now": 0.0}
    current = {"td": None}
    commands: list[dict] = []
    monkeypatch.setattr(tcu_module.time, "time", lambda: clock["now"])

    def capture(from_gear: int, target_gear: int) -> None:
        td = current["td"]
        commands.append(
            {
                "ms": round(clock["now"] * 1000),
                "from": from_gear,
                "to": target_gear,
                "state": tcu._tcu_state,
                "rpm_pct": td.rpm_pct,
            }
        )

    out.shift_to = capture
    for rel_ms, raw in iter_replay_records(log_path):
        td = parse_fh6_packet(raw)
        if td is None:
            continue
        clock["now"] = rel_ms / 1000.0
        out.now = clock["now"]
        current["td"] = td
        tcu.process(td)
    return commands


@pytest.mark.skipif(not FORD.is_file(), reason="Ford replay not in logs/")
def test_ford_recovers_fourth_to_fifth_before_braking(monkeypatch, tmp_path):
    commands = _replay_commands(FORD, monkeypatch, tmp_path)
    recoveries = [
        c for c in commands if c["from"] == 4 and c["to"] == 5 and c["ms"] < 75_000
    ]
    assert recoveries, commands


@pytest.mark.skipif(not PAGANI.is_file(), reason="Pagani replay not in logs/")
def test_pagani_rejects_bad_skips_and_recovers_after_learning(monkeypatch, tmp_path):
    commands = _replay_commands(PAGANI, monkeypatch, tmp_path)
    assert not [c for c in commands if c["from"] == 2 and c["to"] == 3 and c["ms"] < 7_000]
    assert not [
        c
        for c in commands
        if c["from"] == 2
        and c["to"] == 3
        and 70_000 <= c["ms"] <= 72_000
        and c["state"] == "WHEELSPIN"
    ]
    assert [c for c in commands if c["to"] > c["from"] and c["ms"] >= 85_000]


@pytest.mark.skipif(not BRAKE.is_file(), reason="brake replay not in logs/")
def test_brake_replay_recovers_second_before_next_brake(monkeypatch, tmp_path):
    commands = _replay_commands(BRAKE, monkeypatch, tmp_path)
    assert [
        c
        for c in commands
        if c["from"] == 2 and c["to"] == 3 and 30_200 <= c["ms"] < 32_400
    ]
```

- [ ] **Step 2: Run replay acceptance tests against the unit-tested fixes**

Run:

```bash
pytest tests/test_adaptive_upshift_replays.py -v
```

Expected: PASS for all present replays; missing logs are explicitly skipped. The red/green proof for each production decision is already captured by the synthetic tests in Tasks 1–4; these tests validate their combined behavior on the original telemetry.

- [ ] **Step 3: Run every replay and neighboring pending/over-rev suites**

Run:

```bash
pytest tests/test_adaptive_upshift_replays.py tests/test_replay_regression.py tests/test_low_gear_rpm_ceiling.py tests/test_upshift_pending.py tests/test_race_downshift.py -v
```

Expected: PASS, with no unsafe brake landing, early launch shift, pending-command spam, or regression in the existing D/C-class logs.

- [ ] **Step 4: Commit replay coverage**

```bash
git add tests/test_adaptive_upshift_replays.py
git commit -m "test: cover adaptive upshift recovery replays"
```

---

### Task 6: Prepare and verify `13.2.6-pre.3`

**Files:**

- Modify: `CHANGELOG.md`
- Modify: `package.json`
- Modify via `pnpm version:sync`: `apps/dashboard/package.json`, `apps/electron/package.json`, `packages/shared/package.json`, `packages/ui/package.json`, `pyproject.toml`, `virtual_tcu/__init__.py`

**Interfaces:**

- Consumes: root `package.json` as the version source of truth and `scripts/sync-version.mjs`.
- Produces: synchronized version `13.2.6-pre.3`, bilingual release notes, annotated tag `v13.2.6-pre.3`, and pushed `pre/13.2.6` branch/tag.

- [ ] **Step 1: Add English and Chinese pre.3 release notes**

Insert this above the English `13.2.6-pre.1` section in `CHANGELOG.md`:

```markdown
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
```

Insert this above the Chinese `13.2.6-pre.1` section below `# 更新日志`:

```markdown
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
```

- [ ] **Step 2: Set and synchronize the pre.3 version**

Change the root `package.json` version to:

```json
"version": "13.2.6-pre.3"
```

Run:

```bash
pnpm version:sync
rg -n '13\.2\.6-pre\.3' package.json pyproject.toml virtual_tcu/__init__.py apps/*/package.json packages/*/package.json
```

Expected: all seven version targets report `13.2.6-pre.3`, with no remaining `13.2.6-pre.2` in those files.

- [ ] **Step 3: Run focused Python verification**

Run:

```bash
pytest tests/test_adaptive_upshift_recovery.py tests/test_adaptive_upshift_replays.py tests/test_low_gear_rpm_ceiling.py tests/test_hunting.py tests/test_race_downshift.py tests/test_upshift_pending.py tests/test_power_curve_cold_start.py -v
```

Expected: PASS; replay tests may only skip when their corresponding local log is absent.

- [ ] **Step 4: Run the full CI-parity validation**

Run each command separately:

```bash
pnpm test:py
pnpm typecheck
pnpm exec eslint .
ruff check virtual_tcu virtual_tcu.py
pnpm build:dashboard
pnpm build:electron
```

Expected: every command exits 0. Do not claim completion or create the release tag if any new failure remains; investigate failures with `superpowers:systematic-debugging`.

- [ ] **Step 5: Review the final diff and commit release metadata**

Run:

```bash
git diff --check
git status --short
git diff --stat
```

Confirm only the planned logic, tests, changelog, and version files changed, then:

```bash
git add CHANGELOG.md package.json apps/dashboard/package.json apps/electron/package.json packages/shared/package.json packages/ui/package.json pyproject.toml virtual_tcu/__init__.py
git commit -m "chore(pre): release v13.2.6-pre.3"
```

- [ ] **Step 6: Apply verification-before-completion and publish the pre branch**

Invoke `superpowers:verification-before-completion`, rerun the required fresh checks it identifies, then create and publish only after they pass:

```bash
git tag -a v13.2.6-pre.3 -m "v13.2.6-pre.3"
git push origin pre/13.2.6
git push origin v13.2.6-pre.3
```

Expected: branch and tag pushes succeed. If GitHub authentication still cannot sign or authorize the push, keep the verified local commit/tag intact, report the exact authentication blocker, and do not move either pre-release tag.
