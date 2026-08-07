"""Issue #74: cars upshifted at the fuel cut instead of near peak power.

Three defects combined to pin every shift point to the rev limiter:

- ``PowerCurveDetector`` demanded a sample spread real driving never produces
  and high-RPM coverage measured against Forza's inflated nominal
  ``engine_max_rpm``, so its estimate was discarded on every car;
- ``_effective_upshift_pct`` clamped the curve back to the fallback, so even a
  surviving estimate could not move a shift point;
- a gear that tops out below its target had no way to upshift once the
  1.4 s load plateau rejected it as "still accelerating" (Ford GT stuck in 4th).

A fourth defect went the other way: a low-gear traction sawtooth could be
learned as the fuel cut, dragging the shift point far below peak power.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import virtual_tcu.logic.tcu as tcu_module
from tests.conftest import CAR_KEY, REPO_ROOT, FakeOutput, make_telemetry
from virtual_tcu.config.store import ConfigStore
from virtual_tcu.learning.power_curve import PowerCurveDetector
from virtual_tcu.learning.rev_limiter import RevLimiterDetector
from virtual_tcu.logic.tcu import TCULogic
from virtual_tcu.storage.profiles import ProfileStore
from virtual_tcu.telemetry.logger import TelemetryLogger
from virtual_tcu.telemetry.parser import parse_fh6_packet
from virtual_tcu.telemetry.replay_reader import iter_replay_records

_MAX_RPM = 8000.0
# Torque peaking at 50% puts peak power near 64% — comfortably below the
# fallback, so the curve has somewhere to move the shift point to.
_PEAK_TORQUE_R = 0.50


def _torque(r: float) -> float:
    return 300.0 * (1.0 - ((r - _PEAK_TORQUE_R) / 0.45) ** 2)


def _feed_curve(det: PowerCurveDetector, *, top_r: float, sweeps: int = 40) -> None:
    """Sweep the rev range up to *top_r*, the way a series of WOT pulls does.

    Weighted like real telemetry rather than uniformly: the engine crosses the
    bottom of the band in a moment and then sits near the top, which is exactly
    why the sample standard deviation stays small.
    """
    top_band = [top_r - 0.06, top_r - 0.04, top_r - 0.02, top_r - 0.01, top_r]
    steps = [0.30, 0.45, 0.60, 0.72] + top_band * 6
    for _ in range(sweeps):
        for r in steps:
            det.observe(
                make_telemetry(
                    gear=4,
                    current_rpm=r * _MAX_RPM,
                    engine_max_rpm=_MAX_RPM,
                    torque_nm=_torque(r),
                    accel_raw=255,
                )
            )


def test_realistic_pull_reaches_usable_curve_confidence():
    """The old 0.16 spread floor was unreachable: nine issue replays produced
    0.045-0.099, so confidence never left zero and the curve was dead code."""
    det = PowerCurveDetector()
    _feed_curve(det, top_r=0.92)
    fit = det._fits[CAR_KEY]

    assert fit.x_spread < 0.16, "sanity: real sweeps stay well under the old threshold"
    assert det.confidence(CAR_KEY) > 0.5


def test_curve_applies_to_cars_whose_ceiling_is_below_nominal_coverage():
    """Ford GT cuts fuel at 88.3% of nominal, so it could never satisfy the
    absolute 90% coverage gate. Repeatedly returning to 88% must count."""
    det = PowerCurveDetector()
    _feed_curve(det, top_r=0.88)

    assert det._max_r[CAR_KEY] < PowerCurveDetector.HIGH_RPM_COVERAGE
    assert det.observed_ceiling_pct(CAR_KEY) == pytest.approx(0.88)
    assert det.peak_power_rpm(CAR_KEY) is not None

    td = make_telemetry(gear=4, current_rpm=0.80 * _MAX_RPM, engine_max_rpm=_MAX_RPM)
    assert det.optimal_upshift_rpm(td, fallback=0.94, offset=0.03) < 0.94


def test_a_ceiling_that_keeps_rising_is_not_treated_as_coverage():
    """Evidence collected against a plateau is void once the engine goes past it."""
    det = PowerCurveDetector()
    _feed_curve(det, top_r=0.82)
    assert det.observed_ceiling_pct(CAR_KEY) == pytest.approx(0.82)

    det.observe(
        make_telemetry(
            gear=4,
            current_rpm=0.90 * _MAX_RPM,
            engine_max_rpm=_MAX_RPM,
            torque_nm=_torque(0.90),
            accel_raw=255,
        )
    )
    assert det.observed_ceiling_pct(CAR_KEY) is None


def test_small_max_r_step_does_not_inherit_prior_ceiling_hits():
    """A creep inside CEILING_BAND must not keep the old hit tally.

    Coverage is "repeated revisits at this peak". If max_r edges up by less
    than the band and the previous count is retained, the new peak is granted
    immediately without those revisits.
    """
    det = PowerCurveDetector()
    _feed_curve(det, top_r=0.82)
    assert det.observed_ceiling_pct(CAR_KEY) == pytest.approx(0.82)

    step = 0.82 + PowerCurveDetector.CEILING_BAND * 0.5
    det.observe(
        make_telemetry(
            gear=4,
            current_rpm=step * _MAX_RPM,
            engine_max_rpm=_MAX_RPM,
            torque_nm=_torque(step),
            accel_raw=255,
        )
    )

    assert det._max_r[CAR_KEY] == pytest.approx(step)
    assert det.observed_ceiling_pct(CAR_KEY) is None
    assert det._ceiling_hits[CAR_KEY] == pytest.approx(1.0)


def test_curve_may_lower_the_target_but_not_past_the_reduction_bound(make_logic):
    tcu = make_logic("RACE")
    _feed_curve(tcu._power_curve, top_r=0.92)
    td = make_telemetry(gear=4, current_rpm=0.80 * _MAX_RPM, engine_max_rpm=_MAX_RPM)

    fallback = tcu._wot_upshift_fallback(td)
    target = tcu._effective_upshift_pct(td, 0.03)

    assert target < fallback, "the learned peak-power point must move the shift point"
    assert target >= fallback - TCULogic.MAX_CURVE_REDUCTION - 1e-9
    assert target >= tcu._config.get("race_up_mid", 80) / 100


def _drive_topped_out_gear(tcu, out, clock, *, gear: int, rpm_pct: float, frames: int = 260):
    """WOT in a gear that creeps 0.5 points of RPM while still gaining speed.

    This is the Ford GT's 4th gear: not a plateau (the car is still doing
    +2.2 km/h/s) but ~10 s away from a target it never reaches.
    """
    for i in range(frames):
        pct = rpm_pct + i * 0.00002
        td = make_telemetry(
            gear=gear,
            current_rpm=pct * _MAX_RPM,
            engine_max_rpm=_MAX_RPM,
            speed_ms=(250.0 + i * 0.036) / 3.6,
            torque_nm=_torque(min(pct, 0.98)),
            accel_raw=255,
            brake_raw=0,
        )
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td)


def test_topped_out_high_gear_upshifts_past_peak_power(make_logic, out, clock):
    tcu = make_logic("RACE")
    _feed_curve(tcu._power_curve, top_r=0.88)
    peak_power = tcu._power_curve.peak_power_rpm(CAR_KEY)
    assert peak_power is not None and peak_power < 0.82

    _drive_topped_out_gear(tcu, out, clock, gear=4, rpm_pct=0.82)

    # The synthetic frames never report the new gear, so the pending-upshift
    # retry may repeat the command; one is enough to prove the gear was freed.
    assert [kind for kind, _ in out.shifts if kind == "UP"]


def test_topped_out_gear_below_peak_power_keeps_pulling(make_logic, out, clock):
    """A gear that stalls before peak power is still making progress."""
    tcu = make_logic("RACE")
    _feed_curve(tcu._power_curve, top_r=0.92)
    peak_power = tcu._power_curve.peak_power_rpm(CAR_KEY)
    assert peak_power is not None and peak_power > 0.60

    _drive_topped_out_gear(tcu, out, clock, gear=4, rpm_pct=0.55)

    assert [kind for kind, _ in out.shifts if kind == "UP"] == []


def test_stall_is_not_available_in_low_gears(make_logic, out, clock):
    """1st/2nd already have the short-window ceiling path and pull hard."""
    tcu = make_logic("RACE")
    _feed_curve(tcu._power_curve, top_r=0.88)

    _drive_topped_out_gear(tcu, out, clock, gear=2, rpm_pct=0.82)

    assert tcu._gear_stall_key is None


def _feed_wot(det: RevLimiterDetector, *, rpm: float, nominal: float, now: float, frames: int):
    for i in range(frames):
        det.observe(
            make_telemetry(
                gear=3,
                current_rpm=rpm,
                engine_max_rpm=nominal,
                accel_raw=255,
            ),
            last_downshift_time=0.0,
            now=now + i * 0.016,
        )


def _lift(det: RevLimiterDetector, *, nominal: float, now: float):
    """Close the throttle so the detector's window cannot span two pulls."""
    for i in range(5):
        det.observe(
            make_telemetry(gear=3, current_rpm=nominal * 0.5, engine_max_rpm=nominal),
            last_downshift_time=0.0,
            now=now + i * 0.016,
        )


def _feed_sawtooth(det: RevLimiterDetector, *, peak_pct: float, nominal: float, now: float):
    for i in range(55):
        pct = peak_pct if i % 2 == 0 else peak_pct - 0.035
        det.observe(
            make_telemetry(
                gear=3,
                current_rpm=nominal * pct,
                engine_max_rpm=nominal,
                accel_raw=255,
            ),
            last_downshift_time=0.0,
            now=now + i * 0.016,
        )


def test_sawtooth_below_an_already_reached_rpm_is_not_the_fuel_cut():
    """Huayra R: a 81% traction sawtooth was learned as fuel cut although the
    engine had already pulled to 96%, dragging every shift point down."""
    det = RevLimiterDetector()
    nominal = 12000.0
    _feed_wot(det, rpm=nominal * 0.96, nominal=nominal, now=1000.0, frames=40)
    _lift(det, nominal=nominal, now=1001.0)
    _feed_sawtooth(det, peak_pct=0.81, nominal=nominal, now=1002.0)

    td = make_telemetry(gear=3, current_rpm=nominal * 0.81, engine_max_rpm=nominal)
    assert det.effective_redline(td) is None
    assert det.candidate_redline(td) is None
    assert not det.is_verified(td.car_key)


def test_a_learned_limiter_the_engine_revs_past_is_discarded():
    det = RevLimiterDetector()
    nominal = 12000.0
    _feed_sawtooth(det, peak_pct=0.81, nominal=nominal, now=1000.0)
    td = make_telemetry(gear=3, current_rpm=nominal * 0.81, engine_max_rpm=nominal)
    assert det.effective_redline(td) == pytest.approx(nominal * 0.81)

    _lift(det, nominal=nominal, now=1001.0)
    _feed_wot(det, rpm=nominal * 0.96, nominal=nominal, now=1002.0, frames=40)

    assert det.effective_redline(td) is None
    assert not det.is_verified(td.car_key)


def test_max_wot_rpm_survives_a_profile_round_trip():
    det = RevLimiterDetector()
    nominal = 8000.0
    _feed_sawtooth(det, peak_pct=0.844, nominal=nominal, now=1000.0)
    td = make_telemetry(gear=3, current_rpm=nominal * 0.844, engine_max_rpm=nominal)

    restored = RevLimiterDetector()
    restored.load(td.car_key, det.dump(td.car_key))

    assert restored.effective_redline(td) == pytest.approx(nominal * 0.844)
    assert restored._max_wot_rpm[td.car_key] == pytest.approx(nominal * 0.844)


def test_legacy_profile_without_max_wot_rpm_still_loads():
    det = RevLimiterDetector()
    td = make_telemetry(gear=3, current_rpm=6000.0, engine_max_rpm=8000.0)
    det.load(td.car_key, {"rpm": 6752.0, "version": RevLimiterDetector.SERIAL_VERSION})

    assert det.effective_redline(td) == pytest.approx(6752.0)
    assert det.is_verified(td.car_key)


def test_upgrading_a_poisoned_profile_drops_the_bad_limiter(make_logic):
    """Profiles saved before the plausibility floor must not stay poisoned:
    the power curve's persisted max_r proves the engine revved higher."""
    tcu = make_logic("RACE", seed_ratios=False)
    td = make_telemetry(gear=3, current_rpm=0.81 * 12000.0, engine_max_rpm=12000.0)
    ck = td.car_key
    tcu._profiles.set(
        ck,
        {
            "tune_signature": ck[3],
            "power_curve": {"n": 200.0, "max_r": 0.96},
            "rev_limiter": {"rpm": 9765.0, "version": RevLimiterDetector.SERIAL_VERSION},
        },
    )

    tcu._load_profiles(ck, td)

    assert tcu._rev_limiter.effective_redline(td) is None
    assert not tcu._rev_limiter.is_verified(ck)


FORD_GT_74 = REPO_ROOT / "logs" / "issue logs profile" / "Ford_GT.bin.gz"


@pytest.mark.skipif(not FORD_GT_74.is_file(), reason="issue #74 Ford GT replay not in logs/")
def test_issue74_ford_gt_requests_fifth_gear(monkeypatch, tmp_path):
    """The reported car never left 4th: its 87.2% target needs 320 km/h in 4th
    and the gear is aero-limited at 299."""
    clock = {"now": 0.0}
    monkeypatch.setattr(tcu_module.time, "time", lambda: clock["now"])
    out = FakeOutput()
    tcu = TCULogic(
        out,
        ProfileStore(path=str(tmp_path / "prof.json")),
        ConfigStore(path=str(tmp_path / "cfg.json")),
        TelemetryLogger(),
    )
    tcu.set_mode("RACE")
    commands: list[tuple[int, int]] = []
    out.shift_to = lambda from_gear, target: commands.append((from_gear, target))

    for rel_ms, raw in iter_replay_records(FORD_GT_74):
        td = parse_fh6_packet(raw)
        if td is None:
            continue
        clock["now"] = rel_ms / 1000.0
        out.now = clock["now"]
        tcu.process(td)

    assert (4, 5) in commands, f"still capped at 4th; commands={sorted(set(commands))}"


def _issue74_logs() -> list[Path]:
    directory = REPO_ROOT / "logs" / "issue logs profile"
    return sorted(directory.glob("*.bin.gz")) if directory.is_dir() else []


@pytest.mark.parametrize("log_path", _issue74_logs(), ids=lambda p: p.name)
@pytest.mark.skipif(not _issue74_logs(), reason="issue #74 replays not in logs/")
def test_issue74_shift_target_leaves_the_fuel_cut(log_path, monkeypatch, tmp_path):
    """Every reported car waited for its fuel cut. The learned target must end
    up below the highest WOT RPM the engine actually reached."""
    clock = {"now": 0.0}
    monkeypatch.setattr(tcu_module.time, "time", lambda: clock["now"])
    out = FakeOutput()
    tcu = TCULogic(
        out,
        ProfileStore(path=str(tmp_path / "prof.json")),
        ConfigStore(path=str(tmp_path / "cfg.json")),
        TelemetryLogger(),
    )
    tcu.set_mode("RACE")
    targets: list[tuple[float, float]] = []
    record = out.shift_to
    current = {"td": None}

    def capture(from_gear: int, target_gear: int) -> None:
        if target_gear > from_gear:
            td = current["td"]
            targets.append((tcu._effective_upshift_pct(td, 0.03), td.rpm_pct))
        record(from_gear, target_gear)

    out.shift_to = capture
    fuel_cut = 0.0
    for rel_ms, raw in iter_replay_records(log_path):
        td = parse_fh6_packet(raw)
        if td is None:
            continue
        clock["now"] = rel_ms / 1000.0
        out.now = clock["now"]
        current["td"] = td
        if td.is_race_on and td.throttle >= 0.9 and not td.is_shifting:
            fuel_cut = max(fuel_cut, td.rpm_pct)
        tcu.process(td)

    assert targets, "expected automatic upshifts in the replay"
    assert targets[-1][0] < fuel_cut - 0.005, (
        f"final upshift target {targets[-1][0]:.3f} still sits at the {fuel_cut:.3f} fuel cut"
    )
