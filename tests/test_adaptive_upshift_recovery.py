"""Regression coverage for bounded and recoverable automatic upshifts."""

from __future__ import annotations

import copy

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
