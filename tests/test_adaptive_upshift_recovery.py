"""Regression coverage for bounded and recoverable automatic upshifts."""

from __future__ import annotations

import copy

import pytest
from tests.conftest import feed, make_telemetry
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


def _high_gear_plateau_telemetry():
    return make_telemetry(
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


def _upshifts(out) -> list[tuple[str, float]]:
    return [shift for shift in out.shifts if shift[0] == "UP"]


def _feed_plateau(tcu, out, clock, td, frames: int, *, dt: float = 0.016) -> None:
    for _ in range(frames):
        td.accel_raw = 255
        td.brake_raw = 0
        feed(tcu, out, clock, td, 1, dt=dt)


def test_sustained_high_gear_load_plateau_triggers_upshift(make_logic, out, clock):
    tcu = make_logic("RACE")
    td = _high_gear_plateau_telemetry()

    _feed_plateau(tcu, out, clock, td, 85)

    assert len(_upshifts(out)) == 1


def test_rising_high_gear_rpm_never_confirms_load_plateau(make_logic, out, clock):
    tcu = make_logic("RACE")
    td = _high_gear_plateau_telemetry()
    td.current_rpm = 0.80 * td.engine_max_rpm
    td.speed_ms = 295 / 3.6

    for _ in range(60):
        td.current_rpm += 0.0015 * td.engine_max_rpm
        td.speed_ms += 0.25 / 3.6
        _feed_plateau(tcu, out, clock, td, 1)

    assert _upshifts(out) == []


def test_load_plateau_mode_change_requires_fresh_continuity(make_logic, out, clock):
    tcu = make_logic("RACE")
    td = _high_gear_plateau_telemetry()
    _feed_plateau(tcu, out, clock, td, 60)
    assert _upshifts(out) == []

    tcu.set_mode("MANUAL")
    _feed_plateau(tcu, out, clock, td, 1, dt=0.5)
    tcu.set_mode("RACE")
    _feed_plateau(tcu, out, clock, td, 1)
    assert _upshifts(out) == []

    _feed_plateau(tcu, out, clock, td, 70)
    assert len(_upshifts(out)) == 1


def test_load_plateau_shifting_frame_requires_fresh_continuity(make_logic, out, clock):
    tcu = make_logic("RACE")
    td = _high_gear_plateau_telemetry()
    _feed_plateau(tcu, out, clock, td, 60)
    assert _upshifts(out) == []

    shifting = copy.copy(td)
    shifting.is_shifting = 1
    feed(tcu, out, clock, shifting, 1, dt=0.5)
    _feed_plateau(tcu, out, clock, td, 1)
    assert _upshifts(out) == []

    _feed_plateau(tcu, out, clock, td, 70)
    assert len(_upshifts(out)) == 1


@pytest.mark.parametrize(
    "breaker",
    ["throttle", "brake", "slip", "gear", "rpm_growth", "speed_growth"],
)
def test_load_plateau_continuity_resets_on_transient(make_logic, out, clock, breaker):
    tcu = make_logic("RACE")
    td = _high_gear_plateau_telemetry()
    _feed_plateau(tcu, out, clock, td, 50)
    assert _upshifts(out) == []

    bad = copy.copy(td)
    if breaker == "throttle":
        bad.accel_raw = 0
    elif breaker == "brake":
        bad.brake_raw = 255
    elif breaker == "slip":
        bad.slip_rl = 1.0
    elif breaker == "gear":
        bad.gear = 3
    elif breaker == "rpm_growth":
        for i in range(10):
            bad.current_rpm = (0.80 + i * 0.002) * bad.engine_max_rpm
            feed(tcu, out, clock, bad, 1)
    else:
        for i in range(15):
            bad.speed_ms = (295 + i * 0.5) / 3.6
            feed(tcu, out, clock, bad, 1)
    if breaker not in ("rpm_growth", "speed_growth"):
        feed(tcu, out, clock, bad, 1)

    _feed_plateau(tcu, out, clock, td, 50)
    assert _upshifts(out) == []

    _feed_plateau(tcu, out, clock, td, 35)
    assert len(_upshifts(out)) == 1
