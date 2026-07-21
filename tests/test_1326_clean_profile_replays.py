"""Regression gates from the 13.2.6 shift-logic root-cause analysis.

The four clean-profile logs under ``logs/13.2.6问题日志/`` reproduced the
reported failures with cold profiles (see
docs/superpowers/specs/2026-07-21-shift-logic-root-cause-analysis.md):

- late fuel-cut-driven upshifts because limiter trust never matured;
- early 8→9 / 9→10 at 81-84% from the micro-window load plateau;
- inconsistent shift points across repeated pulls of the same gear.

These tests replay every available log with Race mode and a cold profile and
assert the acceptance criteria from the analysis document.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest
import virtual_tcu.logic.tcu as tcu_module
from tests.conftest import REPO_ROOT, FakeOutput
from virtual_tcu.config.store import ConfigStore
from virtual_tcu.logic.tcu import TCULogic
from virtual_tcu.storage.profiles import ProfileStore
from virtual_tcu.telemetry.logger import TelemetryLogger
from virtual_tcu.telemetry.parser import parse_fh6_packet
from virtual_tcu.telemetry.replay_reader import iter_replay_records

LOG_DIR = REPO_ROOT / "logs" / "13.2.6问题日志"
LOGS = sorted(LOG_DIR.glob("*.bin.gz")) if LOG_DIR.is_dir() else []


def _replay_upshifts(log_path: Path, monkeypatch, tmp_path) -> list[dict]:
    clock = {"now": 0.0}
    monkeypatch.setattr(tcu_module.time, "time", lambda: clock["now"])
    out = FakeOutput()
    cfg = ConfigStore(path=str(tmp_path / "cfg.json"))
    prof = ProfileStore(path=str(tmp_path / "prof.json"))
    tcu = TCULogic(out, prof, cfg, TelemetryLogger())
    tcu.set_mode("RACE")
    current = {"td": None}
    ups: list[dict] = []
    record = out.shift_to

    def capture(from_gear: int, target_gear: int) -> None:
        td = current["td"]
        if target_gear > from_gear:
            ups.append(
                {
                    "ms": round(clock["now"] * 1000),
                    "from": from_gear,
                    "rpm_pct": td.rpm_pct,
                    "state": tcu._tcu_state,
                    "limiter_verified": tcu._rev_limiter.is_verified(td.car_key),
                }
            )
        record(from_gear, target_gear)

    out.shift_to = capture
    for rel_ms, raw in iter_replay_records(log_path):
        td = parse_fh6_packet(raw)
        if td is None:
            continue
        clock["now"] = rel_ms / 1000.0
        out.now = clock["now"]
        current["td"] = td
        tcu.process(td)
    return ups


@pytest.mark.parametrize("log_path", LOGS, ids=lambda p: p.name)
@pytest.mark.skipif(not LOGS, reason="13.2.6 clean-profile logs not in logs/")
def test_no_low_plateau_upshift_in_high_gears(log_path, monkeypatch, tmp_path):
    """8→9 at 82.7% / 81.1% must not recur: no WOT upshift below 86%
    in 4th gear or higher without verified limiter evidence."""
    ups = _replay_upshifts(log_path, monkeypatch, tmp_path)
    early = [u for u in ups if u["from"] >= 4 and u["rpm_pct"] < 0.86 and u["state"] == "UPSHIFT"]
    assert not early, f"early high-gear upshifts: {early}"


@pytest.mark.parametrize("log_path", LOGS, ids=lambda p: p.name)
@pytest.mark.skipif(not LOGS, reason="13.2.6 clean-profile logs not in logs/")
def test_limiter_trust_matures_during_the_pull(log_path, monkeypatch, tmp_path):
    """Replaying the logs must not leave every command with an untrusted
    limiter throughout the entire pull (cross-gear evidence accumulation)."""
    ups = _replay_upshifts(log_path, monkeypatch, tmp_path)
    assert ups, "expected automatic upshifts in the replay"
    assert any(u["limiter_verified"] for u in ups), (
        f"limiter never verified across {len(ups)} upshifts"
    )


@pytest.mark.parametrize("log_path", LOGS, ids=lambda p: p.name)
@pytest.mark.skipif(not LOGS, reason="13.2.6 clean-profile logs not in logs/")
def test_same_gear_shift_points_are_consistent(log_path, monkeypatch, tmp_path):
    """Comparable pulls of the same car/gear must stay within ~2 percentage
    points once the limiter is verified."""
    ups = _replay_upshifts(log_path, monkeypatch, tmp_path)
    by_gear: dict[int, list[float]] = defaultdict(list)
    for u in ups:
        if u["limiter_verified"] and u["state"] == "UPSHIFT":
            by_gear[u["from"]].append(u["rpm_pct"])
    for gear, pcts in by_gear.items():
        if len(pcts) < 2:
            continue
        spread = max(pcts) - min(pcts)
        assert spread <= 0.02 + 1e-9, (
            f"gear {gear} verified shift points spread {spread:.3f}: {pcts}"
        )
