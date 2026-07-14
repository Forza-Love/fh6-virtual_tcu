"""Regression for issue #67: low-gear hunting / stuck upshifts on fast cars.

Symptoms reported on v13.2.3 (Race, defaults):
- High-power cars thrash low gears (skip 2nd, drop back, jump again)
- Low gears often only move after a manual intervention
- Stays \"learning\" until a manual shift lets a second gear calibrate

Root causes interacting with #61's shorter settle windows
(``UPSHIFT_PENDING_TIMEOUT_S`` 1.2→0.7, ``LOW_GEAR_LOCK_MS`` 800→400):

1. Forza mid-shift encoding (``gear > 10``) was treated as a *successful*
   pending upshift, clearing the pending gate while the car was still in the
   old gear — a second E could fire and skip a gear.
2. ``_we_shifted`` was cleared in the same frame as the keypress, so the later
   gear-change frame always looked like a manual intervention.
"""

from __future__ import annotations

from tests.conftest import CAR_KEY, make_telemetry

_FAST_RATIOS = {1: 160.0, 2: 105.0, 3: 72.0, 4: 52.0, 5: 40.0, 6: 32.0}
_MAX_RPM = 9000.0


def test_midshift_gear_encoding_does_not_clear_pending_upshift(make_logic, out, clock):
    """gear=11 (is_shifting) must not count as \"upshift confirmed\".

    Otherwise the pending gate drops while still in 1st and a second UP fires
    — the game applies both and skips 2nd (issue #67 fast-car path).
    """
    tcu = make_logic("RACE", seed_ratios=False)
    tcu._calibrator.load(CAR_KEY, {"ratios": _FAST_RATIOS, "counts": {g: 80 for g in _FAST_RATIOS}})

    td1 = make_telemetry(
        gear=1,
        current_rpm=0.96 * _MAX_RPM,
        engine_max_rpm=_MAX_RPM,
        speed_ms=50.0 / 3.6,
        vel_z=14.0,
        accel_raw=255,
        brake_raw=0,
        torque_nm=400.0,
        power_w=200_000.0,
    )
    for _ in range(40):
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td1)

    assert sum(1 for k, _ in out.shifts if k == "UP") == 1
    assert tcu._pending_upshift_from == 1

    # Forza mid-shift packets: gear byte > 10.
    td_shift = make_telemetry(
        gear=11,
        current_rpm=0.90 * _MAX_RPM,
        engine_max_rpm=_MAX_RPM,
        speed_ms=55.0 / 3.6,
        vel_z=15.0,
        accel_raw=255,
        brake_raw=0,
        torque_nm=200.0,
        power_w=100_000.0,
        is_shifting=True,
    )
    for _ in range(15):
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td_shift)

    assert tcu._pending_upshift_from == 1, (
        "mid-shift gear>10 must not clear pending "
        f"(pending={tcu._pending_upshift_from}, cap={tcu._upshift_cap_by_key.get(CAR_KEY)})"
    )

    # Still physically in 1st right after the animation blip. Within the
    # (possibly extended) pending window a second UP must not fire — that is
    # the skip-gear path. Soft-cap retry after a *true* timeout is intentional.
    deadline = tcu._pending_upshift_until
    while clock.now < deadline - 0.05:
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td1)

    ups = sum(1 for k, _ in out.shifts if k == "UP")
    assert ups == 1, f"second UP while still in gear 1 (skip risk): shifts={out.shifts}"


def test_auto_upshift_confirm_not_treated_as_manual(make_logic, out, clock):
    """Gear rising after a TCU upshift must not apply the manual-intervention hold."""
    tcu = make_logic("RACE", seed_ratios=False)
    tcu._calibrator.load(CAR_KEY, {"ratios": _FAST_RATIOS, "counts": {g: 80 for g in _FAST_RATIOS}})

    td1 = make_telemetry(
        gear=1,
        current_rpm=0.96 * _MAX_RPM,
        engine_max_rpm=_MAX_RPM,
        speed_ms=35.0 / 3.6,
        vel_z=10.0,
        accel_raw=255,
        brake_raw=0,
        torque_nm=400.0,
        power_w=200_000.0,
    )
    for _ in range(30):
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td1)

    assert any(k == "UP" for k, _ in out.shifts)
    no_up_before = tcu._no_upshift_until
    no_down_before = tcu._no_downshift_until

    td2 = make_telemetry(
        gear=2,
        current_rpm=0.70 * _MAX_RPM,
        engine_max_rpm=_MAX_RPM,
        speed_ms=55.0 / 3.6,
        vel_z=15.0,
        accel_raw=255,
        brake_raw=0,
        torque_nm=350.0,
        power_w=180_000.0,
    )
    clock.now += 0.05
    out.now = clock.now
    tcu.process(td2)

    assert tcu._no_upshift_until <= max(no_up_before, clock.now + 0.05), (
        f"auto confirm treated as manual up-lock: "
        f"{tcu._no_upshift_until=} {no_up_before=} {clock.now=}"
    )
    assert tcu._no_downshift_until <= max(no_down_before, clock.now + 0.05), (
        f"auto confirm treated as manual down-lock: "
        f"{tcu._no_downshift_until=} {no_down_before=} {clock.now=}"
    )


def test_slow_ack_then_confirmed_upshift_can_continue(make_logic, out, clock):
    """A slow game ack past the pending window must not permanently brick low gears."""
    tcu = make_logic("RACE", seed_ratios=False)
    tcu._calibrator.load(CAR_KEY, {"ratios": _FAST_RATIOS, "counts": {g: 80 for g in _FAST_RATIOS}})

    td1 = make_telemetry(
        gear=1,
        current_rpm=0.96 * _MAX_RPM,
        engine_max_rpm=_MAX_RPM,
        speed_ms=40.0 / 3.6,
        vel_z=12.0,
        accel_raw=255,
        brake_raw=0,
        torque_nm=400.0,
        power_w=200_000.0,
    )
    for _ in range(100):
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td1)

    assert any(k == "UP" for k, _ in out.shifts)

    td2 = make_telemetry(
        gear=2,
        current_rpm=0.96 * _MAX_RPM,
        engine_max_rpm=_MAX_RPM,
        speed_ms=70.0 / 3.6,
        vel_z=20.0,
        accel_raw=255,
        brake_raw=0,
        torque_nm=400.0,
        power_w=200_000.0,
    )
    ups_before = sum(1 for k, _ in out.shifts if k == "UP")
    for _ in range(120):
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td2)
    ups_after = sum(1 for k, _ in out.shifts if k == "UP")
    assert ups_after > ups_before, (
        f"stuck after slow ack: cap={tcu._upshift_cap_by_key.get(CAR_KEY)} shifts={out.shifts}"
    )
