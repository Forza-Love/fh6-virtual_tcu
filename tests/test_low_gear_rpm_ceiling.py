"""Regression: Race 1st gear speed-limited below race_up_wot must still upshift.

Recorded logs (car ordinal 1155, AWD S1) plateau at ~89% RPM in 1st while WOT
because the gear is too long to reach the default 94% WOT upshift point.
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


def test_race_first_gear_rpm_ceiling_triggers_upshift(make_logic, out, clock):
    """88% RPM in 1st at WOT must upshift in Race (threshold capped to race_up_mid)."""
    tcu = make_logic("RACE", seed_ratios=False)
    td = make_telemetry(
        gear=1,
        current_rpm=7100,
        engine_max_rpm=8000.0,
        speed_ms=68.0 / 3.6,
        vel_z=18.0,
        accel_raw=255,
        brake_raw=0,
        drivetrain=2,
    )
    for _ in range(50):
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td)

    ups = [s for s in out.shifts if s[0] == "UP"]
    assert len(ups) >= 1


def test_awd_wheelspin_upshift_allowed_during_cold_start(make_logic, out, clock):
    """AWD launch wheelspin must upshift even with zero power-curve confidence."""
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
    assert len(ups) >= 1, f"{log_path.name}: expected Race upshift from 1st RPM ceiling"
