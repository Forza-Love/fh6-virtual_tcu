"""Replay regression: feed recorded FH6 telemetry through TCULogic and assert
the core airtime invariant — the TCU issues ZERO shifts while airborne.

This is the regression guard for the bug where the car kept upshifting
mid-jump. It runs against any logs/*.bin.gz present (the user records these
on Windows); when none exist (clean CI checkout) it skips. Logs are
gitignored, so this is an opt-in local/integration check.
"""

import pytest
from tests.conftest import REPO_ROOT, FakeOutput
from virtual_tcu.config.store import ConfigStore
from virtual_tcu.logic.tcu import TCULogic
from virtual_tcu.storage.profiles import ProfileStore
from virtual_tcu.telemetry.logger import TelemetryLogger
from virtual_tcu.telemetry.parser import parse_fh6_packet
from virtual_tcu.telemetry.replay_reader import iter_replay_records

LOG_FILES = sorted((REPO_ROOT / "logs").glob("*.bin.gz")) if (REPO_ROOT / "logs").exists() else []

pytestmark = pytest.mark.skipif(
    not LOG_FILES, reason="no replay logs in logs/ (recorded on Windows)"
)


def _replay(log_path, mode, monkeypatch, tmp_path):
    out = FakeOutput()
    cfg = ConfigStore(path=str(tmp_path / "cfg.json"))
    prof = ProfileStore(path=str(tmp_path / "prof.json"))
    tcu = TCULogic(out, prof, cfg, TelemetryLogger())
    tcu.set_mode(mode)

    import virtual_tcu.logic.tcu as tcu_module

    clock = {"now": 0.0}
    monkeypatch.setattr(tcu_module.time, "time", lambda: clock["now"])

    airborne_frames = 0
    shifts_airborne = []
    landings = 0
    prev_landing = False
    for rel_ms, raw in iter_replay_records(log_path):
        td = parse_fh6_packet(raw)
        if td is None:
            continue
        clock["now"] = rel_ms / 1000.0
        out.now = clock["now"]
        before = len(out.shifts)
        tcu.process(td)
        if tcu._airtime.is_airborne:
            airborne_frames += 1
            for s in out.shifts[before:]:
                shifts_airborne.append((s[0], round(rel_ms / 1000.0, 2), td.gear))
        if tcu._airtime_state == "LANDING" and not prev_landing:
            landings += 1
        prev_landing = tcu._airtime_state == "LANDING"
    return out, airborne_frames, shifts_airborne, landings


@pytest.mark.parametrize("log_path", LOG_FILES, ids=lambda p: p.name)
@pytest.mark.parametrize("mode", ["RACE", "OFFROAD"])
def test_no_shifts_while_airborne(log_path, mode, monkeypatch, tmp_path):
    out, airborne_frames, shifts_airborne, landings = _replay(log_path, mode, monkeypatch, tmp_path)
    if airborne_frames == 0:
        pytest.skip(f"{log_path.name}: no airborne frames — skipping vacuous check")
    assert shifts_airborne == [], (
        f"{log_path.name} [{mode}]: TCU shifted {len(shifts_airborne)} times while airborne: "
        f"{shifts_airborne[:10]}"
    )
