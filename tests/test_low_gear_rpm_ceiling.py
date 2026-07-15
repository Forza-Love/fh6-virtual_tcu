"""Regression: Race upshift when WOT RPM plateaus below race_up_wot.

- tcu_replay_20260714_*.bin.gz: ordinal 1155 tops ~89% in 1st — must upshift.
- 跳一档.gz: launch wheelspin must not upshift at ~66% RPM; post-brake must recover.
"""

from __future__ import annotations

import pytest
import virtual_tcu.logic.tcu as tcu_module
from tests.conftest import REPO_ROOT, make_telemetry
from virtual_tcu.config.store import ConfigStore
from virtual_tcu.logic.tcu import TCULogic
from virtual_tcu.storage.profiles import ProfileStore
from virtual_tcu.telemetry.logger import TelemetryLogger
from virtual_tcu.telemetry.parser import parse_fh6_packet
from virtual_tcu.telemetry.replay_reader import iter_replay_records

_ISSUE_LOGS = sorted((REPO_ROOT / "logs").glob("tcu_replay_20260714_*.bin.gz"))
_SKIP_LOG = REPO_ROOT / "logs" / "跳一档.gz"


def _feed_plateau(tcu, out, clock, td, *, frames: int = 50):
    for _ in range(frames):
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td)


def test_race_rpm_ceiling_plateau_triggers_upshift(make_logic, out, clock):
    """Stable ~88% WOT in 1st must upshift once RPM stops climbing below 94%."""
    tcu = make_logic("RACE", seed_ratios=False)
    td = make_telemetry(
        gear=1,
        current_rpm=7088,
        engine_max_rpm=8000.0,
        speed_ms=68.0 / 3.6,
        vel_z=18.0,
        accel_raw=255,
        brake_raw=0,
        drivetrain=2,
    )
    _feed_plateau(tcu, out, clock, td)

    ups = [s for s in out.shifts if s[0] == "UP"]
    assert len(ups) >= 1


def test_race_climbing_rpm_does_not_use_mid_fallback(make_logic, out, clock):
    """Still-climbing 80% in 2nd must not upshift at the mid fallback (80%)."""
    tcu = make_logic("RACE", seed_ratios=False)
    for rpm in range(6000, 7100, 100):
        td = make_telemetry(
            gear=2,
            current_rpm=float(rpm),
            engine_max_rpm=8000.0,
            speed_ms=90.0 / 3.6,
            vel_z=25.0,
            accel_raw=255,
            brake_raw=0,
        )
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td)

    ups = [s for s in out.shifts if s[0] == "UP"]
    assert ups == []


def test_race_stale_plateau_does_not_shift_on_next_pull(make_logic, out, clock):
    """A throttle lift must break plateau history before the next WOT pull."""
    tcu = make_logic("RACE", seed_ratios=False)
    tcu._rpm_pct_history.extend([0.88] * 10)

    lifted = make_telemetry(
        gear=2,
        current_rpm=6000.0,
        engine_max_rpm=8000.0,
        speed_ms=90.0 / 3.6,
        accel_raw=0,
        brake_raw=0,
    )
    clock.now += 0.016
    out.now = clock.now
    tcu.process(lifted)
    assert list(tcu._rpm_pct_history) == []

    rising = make_telemetry(
        gear=2,
        current_rpm=7000.0,
        engine_max_rpm=8000.0,
        speed_ms=90.0 / 3.6,
        accel_raw=255,
        brake_raw=0,
    )
    clock.now += 0.016
    out.now = clock.now
    tcu.process(rising)

    assert [s for s in out.shifts if s[0] == "UP"] == []


def test_awd_wheelspin_upshift_requires_launch_pull(make_logic, out, clock):
    """AWD wheelspin upshift waits for meaningful RPM/speed, not spin at 62%."""
    tcu = make_logic("RACE", seed_ratios=False)
    td = make_telemetry(
        gear=1,
        current_rpm=5000,
        engine_max_rpm=8000.0,
        speed_ms=20.0 / 3.6,
        vel_z=5.5,
        accel_raw=255,
        brake_raw=0,
        drivetrain=2,
        slip_rl=2.0,
        slip_rr=2.5,
    )
    for _ in range(6):
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td)

    assert [s for s in out.shifts if s[0] == "UP"] == []


def test_awd_wheelspin_upshift_gear2_only(make_logic, out, clock):
    """Wheelspin upshift applies from 2nd/3rd — not from 1st launch."""
    tcu = make_logic("RACE", seed_ratios=False)
    td1 = make_telemetry(
        gear=1,
        current_rpm=5800,
        engine_max_rpm=8000.0,
        speed_ms=25.0 / 3.6,
        vel_z=7.0,
        accel_raw=255,
        brake_raw=0,
        drivetrain=2,
        slip_rl=2.0,
        slip_rr=2.5,
    )
    for _ in range(6):
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td1)
    assert [s for s in out.shifts if s[0] == "UP"] == []

    td2 = make_telemetry(
        gear=2,
        current_rpm=5800,
        engine_max_rpm=8000.0,
        speed_ms=45.0 / 3.6,
        vel_z=12.0,
        accel_raw=255,
        brake_raw=0,
        drivetrain=2,
        slip_rl=2.0,
        slip_rr=2.5,
    )
    for _ in range(6):
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td2)

    ups = [s for s in out.shifts if s[0] == "UP"]
    assert len(ups) >= 1


@pytest.mark.parametrize("log_path", _ISSUE_LOGS, ids=lambda p: p.name)
@pytest.mark.skipif(not _ISSUE_LOGS, reason="issue replay logs not in logs/")
def test_issue_replay_race_issues_upshift(log_path, monkeypatch, tmp_path):
    """User-recorded replays must no longer stay at zero upshifts in Race."""
    from tests.conftest import FakeOutput

    out = FakeOutput()
    cfg = ConfigStore(path=str(tmp_path / "cfg.json"))
    prof = ProfileStore(path=str(tmp_path / "prof.json"))
    tcu = TCULogic(out, prof, cfg, TelemetryLogger())
    tcu.set_mode("RACE")

    clock = {"now": 0.0}
    monkeypatch.setattr(tcu_module.time, "time", lambda: clock["now"])

    for rel_ms, raw in iter_replay_records(log_path):
        td = parse_fh6_packet(raw)
        if td is None:
            continue
        clock["now"] = rel_ms / 1000.0
        out.now = clock["now"]
        tcu.process(td)

    ups = [s for s in out.shifts if s[0] == "UP"]
    assert len(ups) >= 1, f"{log_path.name}: expected Race upshift from RPM ceiling"


@pytest.mark.skipif(not _SKIP_LOG.is_file(), reason="跳一档.gz not in logs/")
def test_skip_first_gear_launch_not_at_low_rpm(monkeypatch, tmp_path):
    """跳一档.gz: first upshift must not fire during low-RPM launch wheelspin."""
    from tests.conftest import FakeOutput

    out = FakeOutput()
    cfg = ConfigStore(path=str(tmp_path / "cfg.json"))
    prof = ProfileStore(path=str(tmp_path / "prof.json"))
    tcu = TCULogic(out, prof, cfg, TelemetryLogger())
    tcu.set_mode("RACE")

    clock = {"now": 0.0}
    monkeypatch.setattr(tcu_module.time, "time", lambda: clock["now"])

    first_up = None
    for rel_ms, raw in iter_replay_records(_SKIP_LOG):
        td = parse_fh6_packet(raw)
        if td is None:
            continue
        clock["now"] = rel_ms / 1000.0
        out.now = clock["now"]
        before = len(out.shifts)
        tcu.process(td)
        for s in out.shifts[before:]:
            if s[0] == "UP" and first_up is None:
                first_up = (rel_ms, td.gear, td.rpm_pct)

    assert first_up is not None
    ms, gear, rpm_pct = first_up
    assert not (gear == 1 and rpm_pct < 0.72), (
        f"first UP too early in 1st: ms={ms} gear={gear} rpm%={rpm_pct:.3f}"
    )


@pytest.mark.skipif(not _SKIP_LOG.is_file(), reason="跳一档.gz not in logs/")
def test_skip_post_brake_recovers_upshifts(monkeypatch, tmp_path):
    """跳一档.gz: after brake-down, WOT must issue upshifts again in 2nd/3rd."""
    from tests.conftest import FakeOutput

    out = FakeOutput()
    cfg = ConfigStore(path=str(tmp_path / "cfg.json"))
    prof = ProfileStore(path=str(tmp_path / "prof.json"))
    tcu = TCULogic(out, prof, cfg, TelemetryLogger())
    tcu.set_mode("RACE")

    clock = {"now": 0.0}
    monkeypatch.setattr(tcu_module.time, "time", lambda: clock["now"])

    ups_after_brake = 0
    for rel_ms, raw in iter_replay_records(_SKIP_LOG):
        td = parse_fh6_packet(raw)
        if td is None:
            continue
        clock["now"] = rel_ms / 1000.0
        out.now = clock["now"]
        before = len(out.shifts)
        tcu.process(td)
        if rel_ms >= 27400:
            ups_after_brake += sum(1 for s in out.shifts[before:] if s[0] == "UP")

    assert ups_after_brake >= 2, "expected upshifts after brake sequence when back on power"


@pytest.mark.skipif(not _SKIP_LOG.is_file(), reason="跳一档.gz not in logs/")
def test_skip_brake_downshifts_land_below_safety_ceiling(monkeypatch, tmp_path):
    """跳一档.gz: brake commands with learned ratios must land at or below 98%."""
    from tests.conftest import FakeOutput

    out = FakeOutput()
    cfg = ConfigStore(path=str(tmp_path / "cfg.json"))
    prof = ProfileStore(path=str(tmp_path / "prof.json"))
    tcu = TCULogic(out, prof, cfg, TelemetryLogger())
    tcu.set_mode("RACE")

    clock = {"now": 0.0}
    monkeypatch.setattr(tcu_module.time, "time", lambda: clock["now"])
    current_td = {"value": None}
    landing_pcts = []
    record_shift = out.shift_to

    def capture_shift(from_gear, target_gear):
        td = current_td["value"]
        if td is not None and target_gear < from_gear and tcu._tcu_state == "BRAKE DOWN":
            projected = tcu._calibrator.project_rpm_after_shift(td, target_gear)
            if projected is not None:
                landing_pcts.append(projected / tcu._rev_ceiling(td))
        record_shift(from_gear, target_gear)

    out.shift_to = capture_shift

    for rel_ms, raw in iter_replay_records(_SKIP_LOG):
        td = parse_fh6_packet(raw)
        if td is None:
            continue
        clock["now"] = rel_ms / 1000.0
        out.now = clock["now"]
        current_td["value"] = td
        tcu.process(td)

    assert landing_pcts, "expected ratio-aware brake downshifts in issue replay"
    assert max(landing_pcts) <= 0.98 + 1e-6, landing_pcts
