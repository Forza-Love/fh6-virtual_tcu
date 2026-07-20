"""AirtimeDetector unit tests.

These lock in the accel_y-based detection: free-fall reads sustained
NEGATIVE accel_y (~-12.5), grounded ~0, landing spikes strongly positive.
A regression to the old "all four wheels slip > 1.2" gate — which never
engaged on real logs — must fail here. See memory fh6-accel-y-airborne-signal.
"""

from tests.conftest import make_telemetry
from virtual_tcu.detectors.airtime import AirState, AirtimeDetector


def _run(det: AirtimeDetector, td, frames, now_start=0.0, dt=0.016):
    states = []
    now = now_start
    for _ in range(frames):
        now += dt
        states.append(det.update(td, now))
    return states, now


def test_freefall_engages_airborne():
    det = AirtimeDetector()
    air = make_telemetry(speed_ms=140 / 3.6, accel_y=-12.5, vel_y=-5.0)
    states, _ = _run(det, air, 5)
    assert det.is_airborne
    # exactly one rising edge
    assert sum(s.airborne_started for s in states) == 1


def test_grounded_stays_grounded():
    det = AirtimeDetector()
    ground = make_telemetry(speed_ms=140 / 3.6, accel_y=0.0)
    _run(det, ground, 10)
    assert not det.is_airborne


def test_slip_is_ignored():
    """High wheel slip with grounded accel_y must NOT read as airborne —
    this is the exact false assumption that broke the old detector."""
    det = AirtimeDetector()
    spinning = make_telemetry(
        speed_ms=80 / 3.6, accel_y=0.5, slip_fl=3, slip_fr=3, slip_rl=3, slip_rr=3
    )
    _run(det, spinning, 10)
    assert not det.is_airborne


def test_landing_edge_and_window():
    det = AirtimeDetector()
    air = make_telemetry(speed_ms=140 / 3.6, accel_y=-12.5)
    _, now = _run(det, air, 5)
    assert det.is_airborne

    # landing impact: strongly positive accel_y
    impact = make_telemetry(speed_ms=140 / 3.6, accel_y=120.0)
    states, now = _run(det, impact, 3, now_start=now)
    assert not det.is_airborne
    assert sum(s.just_landed for s in states) == 1
    assert det.landing_until > now  # recovery window still open


def test_settled_ground_after_landing():
    det = AirtimeDetector()
    air = make_telemetry(speed_ms=140 / 3.6, accel_y=-12.5)
    _, now = _run(det, air, 5)
    ground = make_telemetry(speed_ms=140 / 3.6, accel_y=0.0)
    states, _ = _run(det, ground, 3, now_start=now)
    assert not det.is_airborne
    assert sum(s.just_landed for s in states) == 1


def test_single_freefall_frame_does_not_engage():
    """One stray free-fall frame (sensor blip / crest) must not trip it."""
    det = AirtimeDetector()
    ground = make_telemetry(speed_ms=140 / 3.6, accel_y=0.0)
    blip = make_telemetry(speed_ms=140 / 3.6, accel_y=-12.0)
    det.update(ground, 0.016)
    det.update(blip, 0.032)  # single airborne-looking frame
    det.update(ground, 0.048)
    assert not det.is_airborne


def test_short_crest_exposes_unweighted_hold_without_airborne_state():
    det = AirtimeDetector()
    crest = make_telemetry(speed_ms=180 / 3.6, accel_y=-3.5)
    det.update(crest, 0.016)

    assert det.is_unweighted
    assert not det.is_airborne

    settled = make_telemetry(speed_ms=180 / 3.6, accel_y=0.0)
    det.update(settled, 0.20)
    assert det.is_unweighted
    det.update(settled, 0.30)
    assert not det.is_unweighted


def test_hysteresis_band_does_not_flap():
    """accel_y sitting in the -6..-4 band (neither falling nor grounded)
    must not toggle the state once airborne."""
    det = AirtimeDetector()
    air = make_telemetry(speed_ms=140 / 3.6, accel_y=-12.5)
    _, now = _run(det, air, 5)
    assert det.is_airborne
    band = make_telemetry(speed_ms=140 / 3.6, accel_y=-5.0)  # in hysteresis band
    _run(det, band, 10, now_start=now)
    assert det.is_airborne  # still aloft — band neither grounds nor re-arms


def test_low_speed_never_airborne():
    det = AirtimeDetector()
    slow = make_telemetry(speed_ms=5 / 3.6, accel_y=-12.5)
    _run(det, slow, 6)
    assert not det.is_airborne


def test_airstate_is_frozen_dataclass():
    st = AirState(airborne=True, airborne_started=False, just_landed=False)
    assert st.airborne and not st.just_landed
