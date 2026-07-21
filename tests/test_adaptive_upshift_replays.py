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
STO_LOGS = [
    REPO_ROOT / "logs" / "tcu_replay_sto_1.bin.gz",
    REPO_ROOT / "logs" / "tcu_replay_sto_2.bin.gz",
]
SHELBY = REPO_ROOT / "logs" / "tcu_replay_Shelby.bin.gz"
HIGH_REDLINE_LOW_END = REPO_ROOT / "logs" / "tcu_replay_高红区低端车.bin.gz"
NISSAN_20260716 = REPO_ROOT / "logs" / "tcu_replay_20260716_121805NissanBe1.bin.gz"
FORD_20260716 = REPO_ROOT / "logs" / "tcu_replay_20260716_122510FordGT2005.bin.gz"
HUAYRA_20260716 = REPO_ROOT / "logs" / "tcu_replay_20260716_123131Huayra.bin.gz"


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
        projected = tcu._calibrator.project_rpm_after_shift(td, target_gear)
        commands.append(
            {
                "ms": round(clock["now"] * 1000),
                "from": from_gear,
                "to": target_gear,
                "state": tcu._tcu_state,
                "rpm_pct": td.rpm_pct,
                "driven_slip": tcu._driven_wheel_slip(td),
                "landing_pct": (
                    projected / td.engine_max_rpm
                    if projected is not None and td.engine_max_rpm > 0
                    else None
                ),
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


@pytest.mark.parametrize("log_path", STO_LOGS, ids=lambda path: path.name)
def test_sto_high_gears_do_not_treat_slow_climb_as_limiter(log_path, monkeypatch, tmp_path):
    if not log_path.is_file():
        pytest.skip(f"{log_path.name} not in logs/")

    commands = _replay_commands(log_path, monkeypatch, tmp_path)
    early_high_gear = [
        c
        for c in commands
        if 4 <= c["from"] <= 7 and c["to"] == c["from"] + 1 and c["rpm_pct"] < 0.89
    ]

    assert not early_high_gear, (
        "normal high-gear RPM growth must not be treated as an unreachable ceiling; "
        f"commands={early_high_gear}"
    )
    assert {c["from"] for c in commands if c["to"] == c["from"] + 1} >= {1, 2, 3}


@pytest.mark.skipif(not SHELBY.is_file(), reason="Shelby replay not in logs/")
def test_shelby_recovers_third_to_fourth_at_real_limiter(monkeypatch, tmp_path):
    commands = _replay_commands(SHELBY, monkeypatch, tmp_path)
    recoveries = [
        c
        for c in commands
        if c["from"] == 3 and c["to"] == 4 and 6_225 <= c["ms"] < 10_507 and c["state"] == "UPSHIFT"
    ]
    assert recoveries, f"expected a limiter-driven 3->4 recovery; commands={commands}"


@pytest.mark.skipif(
    not HIGH_REDLINE_LOW_END.is_file(),
    reason="high-redline low-end replay not in logs/",
)
def test_low_end_car_learns_low_nominal_limiter_and_keeps_upshifting(monkeypatch, tmp_path):
    commands = _replay_commands(HIGH_REDLINE_LOW_END, monkeypatch, tmp_path)
    assert [c for c in commands if c["from"] == 1 and c["to"] == 2 and c["ms"] < 7_612], (
        f"expected 1->2 before the recorded manual shift; commands={commands}"
    )
    assert [c for c in commands if c["from"] == 2 and c["to"] == 3 and c["ms"] < 12_831], (
        f"expected 2->3 before the recorded manual shift; commands={commands}"
    )
    assert not [
        c
        for c in commands
        if c["from"] == 3
        and c["to"] == 2
        and 12_985 <= c["ms"] < 14_195
        and c["state"] == "RACE POWER DOWN"
    ]


@pytest.mark.skipif(not NISSAN_20260716.is_file(), reason="20260716 Nissan replay missing")
def test_20260716_nissan_reaches_each_upshift_before_recorded_ack(monkeypatch, tmp_path):
    commands = _replay_commands(NISSAN_20260716, monkeypatch, tmp_path)

    assert [c for c in commands if c["from"] == 1 and c["to"] == 2 and c["ms"] < 10_779]
    assert [c for c in commands if c["from"] == 2 and c["to"] == 3 and c["ms"] < 34_512]


@pytest.mark.skipif(not FORD_20260716.is_file(), reason="20260716 Ford replay missing")
def test_20260716_ford_requests_fifth_before_top_speed(monkeypatch, tmp_path):
    commands = _replay_commands(FORD_20260716, monkeypatch, tmp_path)

    # 4th-gear RPM creeps 83→86% until ~51 s, so the stricter 13.2.6 plateau
    # evidence (pinned RPM + extended hold for low peaks) confirms at ~58.6 s —
    # still well before the recorded braking at ~88.5 s.
    assert [
        c
        for c in commands
        if c["from"] == 4 and c["to"] == 5 and c["state"] == "UPSHIFT" and c["ms"] < 62_000
    ]


@pytest.mark.skipif(not HUAYRA_20260716.is_file(), reason="20260716 Huayra replay missing")
def test_20260716_huayra_rejects_spin_upshifts_with_bad_landings(monkeypatch, tmp_path):
    commands = _replay_commands(HUAYRA_20260716, monkeypatch, tmp_path)
    unsafe = [
        c
        for c in commands
        if c["to"] == c["from"] + 1
        and c["driven_slip"] > 1.2
        and (c["landing_pct"] is None or c["landing_pct"] < 0.60)
    ]

    assert not unsafe, f"wheelspin upshifts would land below the Race power band: {unsafe}"
