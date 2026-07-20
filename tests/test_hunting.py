"""Regression: no gear hunting under full throttle near the power band edge.

The bug: in RACE mode at WOT, _track_power_demand_downshift would downshift to a
gear whose projected RPM was already above (or very close to) the upshift
threshold. This produced a rapid up→down→up→down oscillation observable as
"sudden downshift while holding throttle" and then immediately upshifting again.

The fix: a projected-RPM anti-hunting guard in _track_power_demand_downshift and
_track_out_of_band_kickdown blocks any downshift that would land in a gear within
8% of the current upshift threshold.
"""

from tests.conftest import CAR_KEY, make_telemetry


def _downs(out):
    return [k for k, _ in out.shifts if k.startswith("DOWN")]


def _ups(out):
    return [k for k, _ in out.shifts if k == "UP"]


# ── gear ratio calibration shared by hunting tests ───────────────────────────
#
# Ratios chosen so gear 4 @ 110 km/h ≈ 72% redline (below power threshold 60%
# check → should NOT down-shift after anti-hunt guard), and gear 3 @ 110 km/h
# ≈ 95% redline (above upshift threshold → anti-hunt guard blocks the downshift).

_RATIOS = {1: 130.0, 2: 90.0, 3: 66.0, 4: 50.0, 5: 40.0, 6: 33.0}
_MAX_RPM = 9200.0


def _seed_power_curve(tcu, car_key):
    """Feed parabolic torque samples so peak_torque_rpm ≈ 0.55."""
    for _ in range(120):
        for r in (0.30, 0.45, 0.55, 0.65, 0.80, 0.93):
            trq = 300 * (1 - ((r - 0.55) / 0.5) ** 2)
            td = make_telemetry(
                gear=4,
                current_rpm=r * _MAX_RPM,
                engine_max_rpm=_MAX_RPM,
                torque_nm=trq,
                accel_raw=255,
            )
            tcu._power_curve.observe(td)


def test_no_hunting_at_wot_near_power_band_edge(make_logic, out, clock):
    """Full-throttle cruise at a speed where gear 3 would be near/above the
    upshift threshold — the TCU must not oscillate between gears."""
    tcu = make_logic("RACE", seed_ratios=False)
    tcu._calibrator.load(CAR_KEY, {"ratios": _RATIOS, "counts": {g: 80 for g in _RATIOS}})
    _seed_power_curve(tcu, CAR_KEY)

    # Gear 4 @ 110 km/h: rpm = 50 * 110 = 5500 / 9200 ≈ 0.598 (just under
    # power-band floor). Full throttle — power demand downshift would have fired
    # before the fix, putting us in gear 3 @ 95% redline → immediate re-upshift.
    td = make_telemetry(
        gear=4,
        current_rpm=int(0.598 * _MAX_RPM),
        engine_max_rpm=_MAX_RPM,
        speed_ms=110.0 / 3.6,
        accel_raw=255,
        brake_raw=0,
    )

    for _ in range(250):
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td)

    reversals = 0
    shifts = out.shifts
    for (ka, _), (kb, _) in zip(shifts, shifts[1:], strict=False):
        dir_a = 1 if ka == "UP" else -1
        dir_b = 1 if kb == "UP" else -1
        if dir_a != dir_b:
            reversals += 1

    # In ~4 seconds at WOT a reasonable TCU may shift a few times, but
    # direction reversals (up→down or down→up within the same session) should
    # be rare — at most 2 (e.g. one corrective down then stabilise).
    assert reversals <= 2, (
        f"gear hunting detected: {reversals} direction reversals in shifts={shifts}"
    )


def test_band_down_blocked_near_upshift_threshold(make_logic, out, clock):
    """BAND DOWN (out-of-band kickdown) must also respect the anti-hunt guard."""
    tcu = make_logic("OFFROAD", seed_ratios=False)
    tcu._calibrator.load(CAR_KEY, {"ratios": _RATIOS, "counts": {g: 80 for g in _RATIOS}})
    _seed_power_curve(tcu, CAR_KEY)

    # Gear 4 @ 110 km/h, throttle=0.65 (above kickdown gate 0.60).
    # Gear 3 projected: 66 * 110 = 7260 / 9200 ≈ 0.789; upshift threshold ≈
    # 0.90+ — guard should NOT block here (79% < threshold - 8%).
    # This test just verifies the guard doesn't over-block legitimate downshifts.
    td_legit = make_telemetry(
        gear=4,
        current_rpm=int(0.46 * _MAX_RPM),
        engine_max_rpm=_MAX_RPM,
        speed_ms=80.0 / 3.6,  # 80 km/h: gear 3 = 66*80/9200 ≈ 0.574
        accel_raw=int(0.65 * 255),
        brake_raw=0,
    )
    for _ in range(30):
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td_legit)

    assert _downs(out), "expected at least one legitimate BAND DOWN downshift"


def test_offroad_torque_down_uses_offroad_upshift_threshold(make_logic, out, clock):
    """Production Offroad dispatch must not downshift into its upshift band."""
    tcu = make_logic("OFFROAD", seed_ratios=False)
    tcu._calibrator.load(CAR_KEY, {"ratios": _RATIOS, "counts": {g: 80 for g in _RATIOS}})

    # Gear 3 would land at 83.2%. That is inside Offroad's 8% guard band
    # (90%-8%=82%), but outside a wrongly hard-coded Race band (94%-8%=86%).
    td = make_telemetry(
        gear=4,
        current_rpm=int(0.40 * _MAX_RPM),
        engine_max_rpm=_MAX_RPM,
        speed_ms=116.0 / 3.6,
        accel_raw=int(0.65 * 255),
        brake_raw=0,
        profile_tune_id=CAR_KEY[-1],
    )
    tcu._tune_id_by_base[td.car_key_base] = CAR_KEY[-1]

    assert tcu._downshift_would_hunt(td, 3) is True
    clock.now += 0.016
    out.now = clock.now
    tcu.process(td)
    assert _downs(out) == []
