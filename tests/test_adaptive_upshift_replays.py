"""Regression replay coverage for 13.2.6-pre.3 shift recovery."""

from __future__ import annotations

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

FORD = REPO_ROOT / "logs" / "tcu_replay_FordGT2005.bin.gz"
PAGANI = REPO_ROOT / "logs" / "tcu_replay_PaganiHuayraR2021.bin.gz"
BRAKE = REPO_ROOT / "logs" / "刹车降档卡到2档.bin.gz"


def _replay_commands(log_path: Path, monkeypatch, tmp_path) -> list[dict]:
    clock = {"now": 0.0}
    monkeypatch.setattr(tcu_module.time, "time", lambda: clock["now"])
    out = FakeOutput()
    cfg = ConfigStore(path=str(tmp_path / f"{log_path.stem}-cfg.json"))
    prof = ProfileStore(path=str(tmp_path / f"{log_path.stem}-prof.json"))
    tcu = TCULogic(out, prof, cfg, TelemetryLogger())
    tcu.set_mode("RACE")
    current = {"td": None}
    commands: list[dict] = []

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
        c
        for c in commands
        if c["from"] == 4
        and c["to"] == 5
        and 38_328 <= c["ms"] < 75_080
        and c["state"] == "UPSHIFT"
    ]
    assert recoveries, (
        "expected a normal 4->5 UPSHIFT after Ford re-entered 4th at 38,328 ms "
        f"and before braking at 75,080 ms; commands={commands}"
    )


@pytest.mark.skipif(not PAGANI.is_file(), reason="Pagani replay not in logs/")
def test_pagani_rejects_bad_skips_and_recovers_after_learning(monkeypatch, tmp_path):
    commands = _replay_commands(PAGANI, monkeypatch, tmp_path)
    early_skips = [c for c in commands if c["from"] == 2 and c["to"] == 3 and c["ms"] < 7_000]
    unsafe_window = [
        c for c in commands if c["from"] == 2 and c["to"] == 3 and 70_000 <= c["ms"] <= 72_000
    ]
    recoveries = [
        c
        for c in commands
        if c["from"] == 2
        and c["to"] == 3
        and 85_785 <= c["ms"] < 126_601
        and c["state"] == "UPSHIFT"
    ]
    assert not early_skips, f"unexpected launch 2->3 before 7,000 ms: {early_skips}"
    assert not unsafe_window, (
        f"unexpected 2->3 in the 70,000-72,000 ms unsafe window: {unsafe_window}; "
        f"commands={commands}"
    )
    assert recoveries, (
        "expected a normal 2->3 UPSHIFT after Pagani re-entered 2nd at 85,785 ms "
        f"and before its downshift to 1st at 126,601 ms; commands={commands}"
    )


@pytest.mark.skipif(not BRAKE.is_file(), reason="brake replay not in logs/")
def test_brake_replay_recovers_second_before_next_brake(monkeypatch, tmp_path):
    commands = _replay_commands(BRAKE, monkeypatch, tmp_path)
    assert [c for c in commands if c["from"] == 2 and c["to"] == 3 and 30_200 <= c["ms"] < 32_400]
