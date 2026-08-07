from collections import deque

from virtual_tcu.telemetry.model import Telemetry


class RevLimiterDetector:
    """Learns the real rev limiter per car. Forza's reported engine_max_rpm
    is a nominal ceiling, often well above the actual fuel-cut RPM.

    Detection: the limiter has an unmistakable signature at full throttle
    — RPM stops progressing and oscillates in a sawtooth against a fixed
    ceiling. We watch a sliding RPM window; when its maximum stays flat
    (engine not progressing) AND the window oscillates (the sawtooth),
    that ceiling is the cutoff. A steady climb fails the 'flat max' test;
    a WOT hill-crawl fails the 'oscillation' test; noise dips fail both.
    Converges in ~0.7s of sustained limiter bounce."""

    MIN_THROTTLE = 0.92
    POST_DOWNSHIFT_IGNORE_S = 0.6
    POST_UPSHIFT_IGNORE_S = 0.8
    WINDOW = 24
    STABLE_FRAMES = 18
    # A live sawtooth candidate may guide an upshift before it has accumulated
    # enough evidence to become a persisted/over-rev safety limit.
    CANDIDATE_STABLE_FRAMES = 4
    # Some Forza cars report a nominal max RPM far above the reachable fuel
    # cut. The supplied logs include real limiters at 84–93% of nominal.
    MIN_PEAK_PCT = 0.78
    MIN_COMMIT_NOMINAL_FRAC = 0.78
    # Legacy persisted values were learned by an older detector that could
    # mistake a TCU-created plateau for fuel cut. Keep the old trust floor
    # unless a value is confirmed by this detector version.
    LEGACY_MIN_COMMIT_NOMINAL_FRAC = 0.97
    SERIAL_VERSION = 2
    PEAK_EPS = 40.0
    MIN_OSCILLATION = 150.0
    MIN_EDGE_RPM = 40.0
    MIN_RISES = 2
    MIN_DROPS = 2
    # Once a shift consumes a live candidate, the per-gear window resets and
    # the in-gear STABLE_FRAMES trust can never mature under automatic
    # operation. Independent candidate episodes (different gears / pulls) that
    # agree within this tolerance are therefore combined into a verified
    # limiter, so later gears reuse the discovery instead of re-paying the
    # fuel-cut cost.
    CROSS_GEAR_CONFIRMS = 2
    CROSS_GEAR_EPS_FRAC = 0.015
    MAX_BANKED_OBSERVATIONS = 8
    # Downward peak drift while bouncing on the limiter (heat, small grade
    # changes) must not restart the stability count — only a *rising* peak
    # means the engine is still climbing.
    PEAK_DRIFT_DOWN_EPS = 120.0
    # Fuel cut cannot sit below an RPM the engine has demonstrably run at.
    # Traction and turbo oscillation in a low gear can imitate the sawtooth
    # (issue #74: a Huayra R was pinned to 9,765 rpm after having already
    # revved to 11,524), and once such a value is verified it drags the shift
    # point down for good. The highest WOT RPM ever seen is the hard floor
    # every candidate has to clear.
    MAX_SEEN_TOLERANCE = 0.99

    def __init__(self):
        self._redline: dict[tuple, float] = {}
        self._rpm_window: dict[tuple, deque[float]] = {}
        self._peak_hold: dict[tuple, tuple] = {}
        self._active_gear: dict[tuple, int] = {}
        self._verified: set[tuple] = set()
        self._candidate: dict[tuple, float] = {}
        self._episode_peak: dict[tuple, float] = {}
        self._observations: dict[tuple, list[float]] = {}
        self._max_wot_rpm: dict[tuple, float] = {}

    def _reset(self, car: tuple):
        self._bank_episode(car)
        self._rpm_window.pop(car, None)
        self._peak_hold.pop(car, None)
        self._candidate.pop(car, None)

    def _bank_episode(self, car: tuple):
        """Store a finished candidate episode as cross-gear limiter evidence."""
        peak = self._episode_peak.pop(car, None)
        if peak is None:
            return
        obs = self._observations.setdefault(car, [])
        obs.append(peak)
        if len(obs) > self.MAX_BANKED_OBSERVATIONS:
            del obs[: len(obs) - self.MAX_BANKED_OBSERVATIONS]
        self._try_cross_gear_confirm(car)

    def _is_plausible(self, car: tuple, rpm: float) -> bool:
        """Whether *rpm* can be the fuel cut given how high the engine has run."""
        return rpm >= self._max_wot_rpm.get(car, 0.0) * self.MAX_SEEN_TOLERANCE

    def _drop_implausible_redline(self, car: tuple):
        """Forget a stored limiter the engine has since revved past."""
        stored = self._redline.get(car)
        if stored is None or self._is_plausible(car, stored):
            return
        self._redline.pop(car, None)
        self._verified.discard(car)
        self._observations.pop(car, None)
        self._episode_peak.pop(car, None)
        self._candidate.pop(car, None)

    def _try_cross_gear_confirm(self, car: tuple):
        if car in self._verified:
            return
        obs = self._observations.get(car, [])
        if len(obs) < self.CROSS_GEAR_CONFIRMS:
            return
        best = max(obs)
        if not self._is_plausible(car, best):
            return
        eps = best * self.CROSS_GEAR_EPS_FRAC
        agreeing = [p for p in obs if best - p <= eps]
        if len(agreeing) >= self.CROSS_GEAR_CONFIRMS:
            self._redline[car] = best
            self._verified.add(car)

    def observe(
        self,
        td: Telemetry,
        last_downshift_time: float,
        now: float,
        *,
        last_upshift_time: float = 0.0,
    ):
        car = td.car_key
        if self._active_gear.get(car) != td.gear:
            # A window spanning two gears can retain the previous gear's peak
            # and falsely confirm it after the RPM drop.
            self._reset(car)
            self._active_gear[car] = td.gear
        if (
            car[0] <= 0
            or td.is_shifting
            or td.gear < 1
            or td.gear > 10
            or td.engine_max_rpm <= 0
            or td.throttle < self.MIN_THROTTLE
            or now - last_downshift_time < self.POST_DOWNSHIFT_IGNORE_S
            or now - last_upshift_time < self.POST_UPSHIFT_IGNORE_S
            or td.rear_slip > 0.8
            or td.front_slip > 0.8
        ):
            # Wheelspin makes RPM oscillate at WOT without being the
            # limiter — exclude it, same as the gear-ratio calibrator.
            self._reset(car)
            return

        self._max_wot_rpm[car] = max(self._max_wot_rpm.get(car, 0.0), td.current_rpm)
        self._drop_implausible_redline(car)

        win = self._rpm_window.setdefault(car, deque(maxlen=self.WINDOW))
        win.append(td.current_rpm)
        if len(win) < self.WINDOW:
            return

        wmax, wmin = max(win), min(win)
        # Must be high enough to be a plausible limiter, and oscillating
        # (the sawtooth) — a flat WOT hill-crawl is rejected here.
        if wmax < td.engine_max_rpm * self.MIN_PEAK_PCT or (wmax - wmin) < self.MIN_OSCILLATION:
            self._bank_episode(car)
            self._peak_hold.pop(car, None)
            self._candidate.pop(car, None)
            return
        recent = list(win)
        deltas = [new - old for old, new in zip(recent, recent[1:], strict=False)]
        rises = sum(delta >= self.MIN_EDGE_RPM for delta in deltas)
        drops = sum(delta <= -self.MIN_EDGE_RPM for delta in deltas)
        if rises < self.MIN_RISES or drops < self.MIN_DROPS:
            # One impact, shift transient, or telemetry dip is not the
            # repeated sawtooth signature of fuel cut.
            self._bank_episode(car)
            self._peak_hold.pop(car, None)
            self._candidate.pop(car, None)
            return

        anchor_peak, held_frames = self._peak_hold.get(car, (wmax, 0))
        if wmax > anchor_peak + self.PEAK_EPS:
            # Rising peak → the engine is still climbing; any earlier
            # candidate was premature and must not count as evidence.
            anchor_peak, held_frames = wmax, 0
            self._candidate.pop(car, None)
            self._episode_peak.pop(car, None)
        elif wmax < anchor_peak - self.PEAK_DRIFT_DOWN_EPS:
            anchor_peak, held_frames = wmax, 0
            self._candidate.pop(car, None)
        else:
            held_frames += 1
        self._peak_hold[car] = (anchor_peak, held_frames)

        if held_frames >= self.CANDIDATE_STABLE_FRAMES:
            peak = max(anchor_peak, wmax)
            if self._is_plausible(car, peak):
                self._candidate[car] = peak
                self._episode_peak[car] = max(self._episode_peak.get(car, 0.0), peak)

        if held_frames >= self.STABLE_FRAMES:
            confirmed_peak = max(anchor_peak, wmax)
            if confirmed_peak < td.engine_max_rpm * self.MIN_COMMIT_NOMINAL_FRAC:
                return
            if not self._is_plausible(car, confirmed_peak):
                return
            if car not in self._verified:
                # A live confirmation supersedes an untrusted legacy value,
                # even when the legacy value happened to be higher.
                self._redline[car] = confirmed_peak
                self._verified.add(car)
            elif confirmed_peak > self._redline.get(car, 0.0):
                # Once verified, the highest confirmed bounce is the cutoff;
                # a stray low reading can never drag the estimate down.
                self._redline[car] = confirmed_peak

    def reconcile_with_observed(self, car: tuple, observed_rpm: float):
        """Fold an externally measured reachable RPM into the plausibility floor.

        Profiles written before ``max_wot_rpm`` existed restore a limiter with
        no evidence of how high the engine has actually run, so a value learned
        from a traction sawtooth would survive the upgrade. The power curve
        persists that evidence, so it is replayed here on load.
        """
        if observed_rpm <= 0:
            return
        self._max_wot_rpm[car] = max(self._max_wot_rpm.get(car, 0.0), observed_rpm)
        self._drop_implausible_redline(car)

    def effective_redline(self, td: Telemetry) -> float | None:
        return self._redline.get(td.car_key)

    def candidate_redline(self, td: Telemetry) -> float | None:
        """Return a current-gear limiter candidate that is not yet persisted."""
        candidate = self._candidate.get(td.car_key)
        if candidate is None or not self._is_plausible(td.car_key, candidate):
            return None
        return candidate

    def is_verified(self, car: tuple) -> bool:
        return car in self._verified

    def dump(self, car: tuple) -> float | dict | None:
        """Return the learned redline for *car*, or None."""
        redline = self._redline.get(car)
        if redline is None:
            return None
        if car in self._verified:
            # max_wot_rpm is an additive key: older readers ignore it and older
            # files simply restore without the plausibility floor.
            return {
                "rpm": redline,
                "version": self.SERIAL_VERSION,
                "max_wot_rpm": self._max_wot_rpm.get(car, 0.0),
            }
        return redline

    def load(self, car: tuple, redline: float | dict):
        """Restore a previously-learned redline for *car*."""
        if isinstance(redline, dict):
            value = redline.get("rpm")
            version = redline.get("version")
            if (
                isinstance(value, (int, float))
                and value > 0
                and isinstance(version, int)
                and version >= self.SERIAL_VERSION
            ):
                self._redline[car] = float(value)
                self._verified.add(car)
                seen = redline.get("max_wot_rpm")
                if isinstance(seen, (int, float)) and seen > 0:
                    self._max_wot_rpm[car] = float(seen)
            return
        if isinstance(redline, (int, float)) and redline > 0:
            self._redline[car] = float(redline)
