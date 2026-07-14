"""Regression for issue #62: rev-limiter must not poison upshift timing.

When RevLimiterDetector learned the TCU's own upshift plateau as the engine
redline and overwrote ``engine_max_rpm``, every gear after 1st shifted ~15–20%
below the real redline (e.g. ~5600 on a 7000 RPM car in Race).
"""

import virtual_tcu.logic.tcu as tcu_module
from tests.conftest import Clock, FakeOutput, make_telemetry
from virtual_tcu.config.store import ConfigStore
from virtual_tcu.learning.rev_limiter import RevLimiterDetector
from virtual_tcu.logic.tcu import TCULogic
from virtual_tcu.storage.profiles import ProfileStore
from virtual_tcu.telemetry.logger import TelemetryLogger


def _simulate_wot_pull(mode: str, *, max_rpm: float = 7000.0) -> list[tuple[int, int, int]]:
    """Return [(from_gear, shift_rpm, pct_of_true_redline), ...] for each upshift."""
    out = FakeOutput()
    clock = Clock()
    tcu_module.time.time = clock
    cfg = ConfigStore(path=f"/tmp/tcu_early_up_{mode}.json")
    prof = ProfileStore(path=f"/tmp/tcu_early_up_prof_{mode}.json")
    tcu = TCULogic(out, prof, cfg, TelemetryLogger())
    tcu.set_mode(mode)

    ratios = {1: 130.0, 2: 85.0, 3: 62.0, 4: 48.0, 5: 38.0, 6: 31.0}
    tcu._calibrator.load(
        make_telemetry(engine_max_rpm=max_rpm).car_key,
        {"ratios": ratios, "counts": {g: 50 for g in ratios}},
    )

    gear = 1
    speed = 0.0
    results: list[tuple[int, int, int]] = []

    for _ in range(3000):
        clock.now += 0.016
        out.now = clock.now
        ratio = ratios.get(gear, 40)
        speed = min(speed + 0.35, 280)
        rpm = min(ratio * speed, max_rpm * 0.995)
        r = rpm / max_rpm
        trq = max(180.0, 250.0 * (1 - ((r - 0.55) / 0.5) ** 2))
        td = make_telemetry(
            gear=gear,
            current_rpm=rpm,
            engine_max_rpm=max_rpm,
            speed_ms=speed / 3.6,
            torque_nm=trq,
            accel_raw=255,
        )
        tcu._current_car_key = td.car_key
        before = len(out.shifts)
        tcu.process(td)
        for s in out.shifts[before:]:
            if s[0] == "UP":
                results.append((gear, round(rpm), round(r * 100)))
                gear += 1
                speed *= 0.72
    return results


def test_race_mode_keeps_upshift_near_configured_redline_pct():
    """Rev-limiter fix: 3rd+ must not collapse to ~80%; 1st/2nd may use race_up_mid."""
    shifts = _simulate_wot_pull("RACE")
    assert len(shifts) >= 3
    low = [pct for from_gear, _rpm, pct in shifts if from_gear <= 2]
    high = [pct for from_gear, _rpm, pct in shifts if from_gear >= 3]
    assert low, "expected 1st/2nd upshifts"
    assert high, "expected upshifts past 2nd"
    for pct in low:
        assert pct >= 80, f"low-gear upshift at {pct}% (expected >=80% race_up_mid)"
    assert max(high) >= 90, f"high-gear upshifts never near redline: {high}"
    assert sum(high) / len(high) >= 88, f"high-gear upshifts averaged too low: {high}"


def test_nominal_engine_max_rpm_is_not_overwritten():
    out = FakeOutput()
    clock = Clock()
    tcu_module.time.time = clock
    cfg = ConfigStore(path="/tmp/tcu_nominal_max.json")
    prof = ProfileStore(path="/tmp/tcu_nominal_max_prof.json")
    tcu = TCULogic(out, prof, cfg, TelemetryLogger())
    tcu.set_mode("RACE")

    max_rpm = 7000.0
    td = make_telemetry(
        gear=4,
        current_rpm=6500.0,
        engine_max_rpm=max_rpm,
        accel_raw=255,
    )
    tcu._rev_limiter._redline[td.car_key] = 6597.5
    tcu.process(td)
    assert td.engine_max_rpm == max_rpm


def test_rev_limiter_rejects_tcu_upshift_plateau():
    """A ~94% plateau (typical Race upshift) must not be stored as fuel-cut."""
    import sys
    from unittest.mock import MagicMock

    sys.modules.setdefault("keyboard", MagicMock())

    det = RevLimiterDetector()
    nominal = 7000.0
    plateau = nominal * 0.943
    now = 1000.0

    for i in range(40):
        # Sawtooth around the TCU upshift ceiling, not the real limiter.
        rpm = plateau + (80.0 if i % 2 == 0 else -80.0)
        td = make_telemetry(
            gear=2,
            current_rpm=rpm,
            engine_max_rpm=nominal,
            accel_raw=255,
        )
        det.observe(td, last_downshift_time=0.0, now=now + i * 0.016)

    assert det.effective_redline(td) is None
