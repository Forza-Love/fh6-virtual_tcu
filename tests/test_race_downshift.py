"""Race downshift aggressiveness + global airborne-hold tests.

Covers the P0 changes:
- power-demand downshift fires on heavy-throttle / low-rev / flat ground
- over-rev guard still blocks a downshift that would exceed redline
- Race brake-down uses a looser gate than Comfort (moderate sustained
  brake while slowing downshifts in Race, not in Comfort)
- the global airborne hold blocks the pre-dispatch GEAR MISMATCH path that
  the per-mode transient block never reached
"""

from tests.conftest import CAR_KEY, make_telemetry
from virtual_tcu.config.constants import Cfg


def _kinds(out):
    return [k for k, _ in out.shifts]


def test_power_demand_downshift_fires(make_logic, out, clock):
    # gear 5 @ 130 km/h, ratio 35 -> rpm ~4550 (pct 0.57 < 0.60 floor),
    # heavy throttle, no brake, flat road -> should drop a gear.
    tcu = make_logic("RACE")
    td = make_telemetry(speed_ms=130 / 3.6, current_rpm=35 * 130, accel_raw=int(0.90 * 255), gear=5)
    for _ in range(20):
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td)
    assert "DOWN" in _kinds(out) or "DOWN2" in _kinds(out)


def test_power_demand_skips_when_in_band(make_logic, out, clock):
    # Already in the power band (rpm_pct ~0.85) -> no power-demand downshift.
    tcu = make_logic("RACE")
    speed = (0.85 * 8000) / 35  # ratio 35 -> rpm_pct 0.85
    td = make_telemetry(
        speed_ms=speed / 3.6, current_rpm=0.85 * 8000, accel_raw=int(0.90 * 255), gear=5
    )
    for _ in range(20):
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td)
    assert "DOWN" not in _kinds(out) and "DOWN2" not in _kinds(out)


def test_shift_down_blocks_overrev(make_logic, out, clock):
    # gear 3 @ 110 km/h; downshift to gear 2 (ratio 80) -> 8800 rpm > 1.02*8000.
    tcu = make_logic("RACE")
    td = make_telemetry(speed_ms=110 / 3.6, current_rpm=58 * 110, gear=3)
    assert tcu._shift_down(td, 300, "TEST") is False
    assert out.shifts == []
    assert tcu._tcu_state == "OVER-REV BLOCKED"


def _load_short_gearing(tcu):
    ratios = {1: 100.0, 2: 69.0, 3: 47.0, 4: 36.0, 5: 29.0, 6: 24.0}
    tcu._calibrator.load(CAR_KEY, {"ratios": ratios, "counts": {g: 50 for g in ratios}})


def test_skip_down_validates_exact_target_gear(make_logic, out):
    """A 6→2 command must validate 2nd, not the unrelated 4th gear."""
    tcu = make_logic("RACE")
    _load_short_gearing(tcu)
    td = make_telemetry(
        speed_ms=120 / 3.6,
        current_rpm=24 * 120,
        brake_raw=255,
        gear=6,
    )

    # 2nd would land at 8280 RPM, beyond the 8160 hard over-rev limit.
    assert tcu._shift_down_double(td, 250, target=2) is False
    assert out.shifts == []


def test_brake_target_is_safe_at_current_speed(make_logic, out, clock):
    """Future-speed selection must not execute an unsafe target immediately."""
    tcu = make_logic("RACE")
    _load_short_gearing(tcu)
    commands = []
    out.shift_to = lambda from_gear, target_gear: commands.append((from_gear, target_gear))
    td = make_telemetry(
        speed_ms=120 / 3.6,
        current_rpm=24 * 120,
        brake_raw=255,
        gear=6,
    )

    assert tcu._track_brake_down(td, clock.now, brake_thr=0.21) is True
    # At the projected 96 km/h the desired gear is 2nd, but at the current
    # 120 km/h it would land at 103.5% of redline. 3rd lands safely at 70.5%.
    assert commands == [(6, 3)]


def test_brake_target_keeps_safe_direct_downshift(make_logic, out, clock):
    """The safety clamp must not make already-safe brake shifts less responsive."""
    tcu = make_logic("RACE")
    _load_short_gearing(tcu)
    commands = []
    out.shift_to = lambda from_gear, target_gear: commands.append((from_gear, target_gear))
    td = make_telemetry(
        speed_ms=110 / 3.6,
        current_rpm=24 * 110,
        brake_raw=255,
        gear=6,
    )

    assert tcu._track_brake_down(td, clock.now, brake_thr=0.21) is True
    assert commands == [(6, 2)]


def test_panic_brake_cannot_bypass_current_speed_safety(make_logic, out, clock):
    """Low current RPM must not bypass the 98% brake landing limit."""
    tcu = make_logic("RACE", seed_ratios=False)
    ratios = {1: 100.0, 2: 69.0, 3: 30.0}
    tcu._calibrator.load(CAR_KEY, {"ratios": ratios, "counts": {g: 50 for g in ratios}})
    commands = []
    out.shift_to = lambda from_gear, target_gear: commands.append((from_gear, target_gear))
    td = make_telemetry(
        speed_ms=115 / 3.6,
        current_rpm=30 * 115,
        brake_raw=255,
        gear=3,
    )

    # 2nd would land at 7935 RPM (99.2%): below the 102% hard blocker but
    # above the 98% brake-down ceiling. Heavy braking must not bypass it.
    assert tcu._track_brake_down(td, clock.now, brake_thr=0.21) is False
    assert commands == []


def test_power_down_missing_skip_ratio_falls_back_to_single(make_logic, out, clock):
    """A missing exact skip target ratio must degrade to one safe downshift."""
    tcu = make_logic("RACE", seed_ratios=False)
    ratios = {1: 120.0, 2: 80.0, 3: 58.0, 5: 35.0, 6: 29.0}
    tcu._calibrator.load(CAR_KEY, {"ratios": ratios, "counts": {g: 50 for g in ratios}})
    commands = []
    out.shift_to = lambda from_gear, target_gear: commands.append((from_gear, target_gear))
    td = make_telemetry(
        speed_ms=100 / 3.6,
        current_rpm=29 * 100,
        accel_raw=255,
        brake_raw=0,
        gear=6,
    )

    assert tcu._track_power_demand_downshift(td, clock.now) is True
    assert commands == [(6, 5)]


def _feed_decel(tcu, out, clock, *, gear, brake, throttle, start_kmh, ratio, frames=16, step=1.2):
    for i in range(frames):
        spd = start_kmh - i * step
        clock.now += 0.016
        out.now = clock.now
        td = make_telemetry(
            speed_ms=spd / 3.6,
            current_rpm=ratio * spd,
            accel_raw=int(throttle * 255),
            brake_raw=int(brake * 255),
            gear=gear,
        )
        tcu.process(td)


def test_race_brake_down_on_moderate_sustained_brake(make_logic, out, clock):
    # Moderate brake (0.40) while clearly slowing -> Race downshifts.
    tcu = make_logic("RACE")
    _feed_decel(tcu, out, clock, gear=4, brake=0.40, throttle=0.0, start_kmh=135, ratio=44.0)
    assert "DOWN" in _kinds(out)


def test_comfort_holds_on_moderate_sustained_brake(make_logic, out, clock):
    # Same moderate brake in Comfort -> strict gate, no downshift.
    tcu = make_logic("COMFORT")
    _feed_decel(tcu, out, clock, gear=4, brake=0.40, throttle=0.0, start_kmh=135, ratio=44.0)
    assert "DOWN" not in _kinds(out)


def test_airborne_hold_blocks_mismatch(make_logic, out, clock):
    # Establish airborne at speed (no mismatch), then drop into a
    # mismatch-shaped frame (tall gear, low speed, low rpm) while still
    # airborne. The global hold must suppress the MISMATCH downshift.
    tcu = make_logic("RACE")
    high = make_telemetry(speed_ms=140 / 3.6, accel_y=-12.5, current_rpm=35 * 140, gear=5)
    for _ in range(5):
        clock.now += 0.016
        out.now = clock.now
        tcu.process(high)
    assert tcu._airtime.is_airborne
    # mismatch-shaped, still airborne (speed 30 > 15 keeps detector aloft)
    mismatch = make_telemetry(speed_ms=30 / 3.6, accel_y=-12.5, current_rpm=35 * 30, gear=5)
    for _ in range(5):
        clock.now += 0.016
        out.now = clock.now
        tcu.process(mismatch)
    assert out.shifts == []
    assert tcu._tcu_state == "AIRBORNE"


def test_grounded_mismatch_downshifts(make_logic, out, clock):
    # Same mismatch shape on the ground -> MISMATCH downshift fires,
    # proving it's the airborne hold (not some other guard) doing the work.
    tcu = make_logic("RACE")
    md = make_telemetry(speed_ms=30 / 3.6, accel_y=0.0, current_rpm=35 * 30, gear=5)
    clock.now += 0.016
    out.now = clock.now
    tcu.process(md)
    assert "DOWN" in _kinds(out)
    assert Cfg.MIN_SPEED_KMH < 30  # sanity: not the standstill path


def test_race_descent_downshift_recovers_above_coast_floor(make_logic, out, clock):
    """13.2.6 gap: gravity holds downhill RPM above the 30% coast floor and
    light maintenance throttle disables the coast path — Race must still
    select an engine-braking gear on a sustained descent."""
    tcu = make_logic("RACE")
    # gear 5, ratio 35: 100 km/h -> 3500 rpm (43% — above race_coast_rpm 30%).
    speed = 100.0
    for _ in range(90):  # ~1.44 s of accelerating descent, light throttle
        speed += 0.06  # ~3.75 km/h/s gain with no meaningful pedal input
        td = make_telemetry(
            gear=5,
            speed_ms=speed / 3.6,
            current_rpm=35 * speed,
            accel_raw=int(0.10 * 255),
            brake_raw=0,
        )
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td)
    assert "DOWN" in _kinds(out)
    assert tcu._tcu_state in ("ENGINE BRAKE", "POST-SHIFT")


def test_race_descent_downshift_never_selects_unsafe_gear(make_logic, out, clock):
    """A descent downshift is blocked by the hunt/over-rev guards when the
    lower gear would land at or beyond the usable ceiling."""
    tcu = make_logic("RACE")
    # gear 3 at 140 km/h: gear 2 (ratio 80) would land at 11200 rpm >> ceiling.
    speed = 140.0
    for _ in range(90):
        speed += 0.06
        td = make_telemetry(
            gear=3,
            speed_ms=speed / 3.6,
            current_rpm=58 * speed * 0.5,  # keep displayed rpm low
            accel_raw=0,
            brake_raw=0,
        )
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td)
    assert "DOWN" not in _kinds(out) and "DOWN2" not in _kinds(out)


def test_unweighted_crest_holds_power_downshift(make_logic, out, clock):
    tcu = make_logic("RACE")
    crest = make_telemetry(
        speed_ms=180 / 3.6,
        accel_y=-3.5,
        current_rpm=0.50 * 8000,
        accel_raw=255,
        gear=7,
    )

    clock.now += 0.016
    out.now = clock.now
    tcu.process(crest)

    assert out.shifts == []
    assert tcu._tcu_state == "UNWEIGHTED"
