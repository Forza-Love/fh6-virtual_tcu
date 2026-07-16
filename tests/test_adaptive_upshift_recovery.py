"""Regression coverage for bounded and recoverable automatic upshifts."""

from __future__ import annotations

import pytest
from tests.conftest import make_telemetry
from virtual_tcu.core.mode import Mode


def _force_learned_target(monkeypatch, tcu, target: float) -> None:
    monkeypatch.setattr(
        tcu._power_curve,
        "optimal_upshift_rpm",
        lambda td, fallback, offset: target,
    )


def test_learned_target_cannot_exceed_configured_race_wot(make_logic, out, clock, monkeypatch):
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


def test_advisor_and_anti_hunt_use_the_same_bounded_target(make_logic, monkeypatch):
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
