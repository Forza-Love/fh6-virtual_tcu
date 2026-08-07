from virtual_tcu.telemetry.model import Telemetry


class _ParabolaFit:
    """Incremental least-squares fit of torque = a*r^2 + b*r + c, where r
    is rpm fraction (0..1). Accumulators decay slowly so the model adapts
    if the car setup changes. O(1) memory — only sums are kept."""

    DECAY = 0.9997

    def __init__(self):
        self.n = self.sx = self.sx2 = self.sx3 = self.sx4 = 0.0
        self.sy = self.sxy = self.sx2y = 0.0
        self._abc = None

    def add(self, x: float, y: float, weight: float = 1.0):
        d = self.DECAY
        self.n = self.n * d + weight
        self.sx = self.sx * d + weight * x
        self.sx2 = self.sx2 * d + weight * x * x
        self.sx3 = self.sx3 * d + weight * x**3
        self.sx4 = self.sx4 * d + weight * x**4
        self.sy = self.sy * d + weight * y
        self.sxy = self.sxy * d + weight * x * y
        self.sx2y = self.sx2y * d + weight * x * x * y
        self._abc = None

    def solve(self):
        """Return (a, b, c) of the fitted parabola, or None if ill-posed."""
        if self._abc is not None:
            return self._abc
        if self.n < 4:
            return None
        m = [
            [self.sx4, self.sx3, self.sx2],
            [self.sx3, self.sx2, self.sx],
            [self.sx2, self.sx, self.n],
        ]
        rhs = [self.sx2y, self.sxy, self.sy]

        def det3(mat):
            return (
                mat[0][0] * (mat[1][1] * mat[2][2] - mat[1][2] * mat[2][1])
                - mat[0][1] * (mat[1][0] * mat[2][2] - mat[1][2] * mat[2][0])
                + mat[0][2] * (mat[1][0] * mat[2][1] - mat[1][1] * mat[2][0])
            )

        det = det3(m)
        if abs(det) < 1e-9:
            return None

        def swap(mat, col, vec):
            return [[vec[r] if c == col else mat[r][c] for c in range(3)] for r in range(3)]

        a = det3(swap(m, 0, rhs)) / det
        b = det3(swap(m, 1, rhs)) / det
        c = det3(swap(m, 2, rhs)) / det
        self._abc = (a, b, c)
        return self._abc

    def to_dict(self) -> dict:
        """Serialise accumulator state so the fit can be restored later."""
        return {
            "n": self.n,
            "sx": self.sx,
            "sx2": self.sx2,
            "sx3": self.sx3,
            "sx4": self.sx4,
            "sy": self.sy,
            "sxy": self.sxy,
            "sx2y": self.sx2y,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "_ParabolaFit":
        """Restore a fit from a previously-saved to_dict() snapshot."""
        fit = cls()
        for attr in ("n", "sx", "sx2", "sx3", "sx4", "sy", "sxy", "sx2y"):
            if attr in d:
                setattr(fit, attr, float(d[attr]))
        return fit

    @property
    def x_spread(self) -> float:
        if self.n < 2:
            return 0.0
        mean = self.sx / self.n
        var = self.sx2 / self.n - mean * mean
        return var**0.5 if var > 0 else 0.0


class PowerCurveDetector:
    """Per-car engine model. Fits a parabola to (rpm, torque) samples and
    derives peak torque and peak power analytically from the curve.

    Unlike a bucket histogram, this gives a usable estimate from very few
    samples (the curve shape extrapolates the peak) and converges smoothly
    as more data arrives — no binary learning/learned threshold."""

    MIN_SAMPLES = 8
    FULL_CONF_SAMPLES = 80
    # Real driving never produces the 0.16 sample spread the first version of
    # this detector asked for: the TCU holds the engine in the top of the band,
    # so the distribution stays narrow no matter how many full pulls are made.
    # Across the nine issue #74 replays the observed spread was 0.045-0.099,
    # which left every car permanently below the confidence floor.
    MIN_SPREAD = 0.035
    GOOD_SPREAD = 0.085
    # Upshift timing needs samples near the real redline; mid-range-only fits
    # extrapolate a peak too early (common on RWD before a limiter pull).
    HIGH_RPM_COVERAGE = 0.90
    # Forza's nominal engine_max_rpm sits well above the reachable fuel cut on
    # many cars (Ford GT cuts at 88.3% of nominal), so HIGH_RPM_COVERAGE alone
    # would disable the curve for them forever. Repeatedly returning to the same
    # ceiling proves the top of the range was sampled just as well as crossing
    # 90% would — provided that ceiling is high enough to be a plausible
    # limiter rather than a mid-range plateau.
    MIN_CEILING_PCT = 0.78
    CEILING_BAND = 0.02
    CEILING_SAMPLES = 40.0
    STATIONARY_LEARN_SPEED_KMH = 8.0

    def __init__(self):
        self._fits: dict[tuple, _ParabolaFit] = {}
        self._max_r: dict[tuple, float] = {}
        self._ceiling_hits: dict[tuple, float] = {}

    def _gear_ok(self, td: Telemetry) -> bool:
        if td.gear >= 2:
            return True
        # Brake+throttle revving in 1st is the fastest way to learn limiter/curve.
        return td.gear == 1 and td.speed_kmh < self.STATIONARY_LEARN_SPEED_KMH

    def observe(self, td: Telemetry):
        ck = td.car_key
        if ck[0] <= 0 or not self._gear_ok(td):
            return
        if td.throttle < 0.45 or td.torque_nm <= 0 or td.is_shifting:
            return
        r = td.rpm_pct
        if r < 0.20 or r > 1.0:
            return
        prev_max = self._max_r.get(ck, 0.0)
        if r > prev_max:
            self._max_r[ck] = r
            # Any new high voids prior ceiling evidence — including a creep
            # inside CEILING_BAND. Keeping the old hit tally would grant the
            # new peak coverage without the required revisits at that RPM.
            self._ceiling_hits[ck] = 0.0
        # Partial throttle and some slip still carry curve-shape info but
        # weigh less — the least-squares fit absorbs them as soft evidence.
        weight = 1.0
        if td.throttle < 0.70:
            weight *= 0.5
        if td.rear_slip > 0.5:
            weight *= 0.4
        if r >= self.HIGH_RPM_COVERAGE and td.throttle >= 0.85:
            weight *= 1.6
        if td.throttle >= 0.85 and r >= self._max_r[ck] - self.CEILING_BAND:
            self._ceiling_hits[ck] = self._ceiling_hits.get(ck, 0.0) + 1.0
        self._fits.setdefault(ck, _ParabolaFit()).add(r, td.torque_nm, weight)

    def _has_high_rpm_coverage(self, car_key: tuple) -> bool:
        max_r = self._max_r.get(car_key, 0.0)
        if max_r >= self.HIGH_RPM_COVERAGE:
            return True
        return self.observed_ceiling_pct(car_key) is not None

    def observed_ceiling_pct(self, car_key: tuple) -> float | None:
        """Highest WOT RPM fraction the engine has repeatedly returned to.

        This is a lower bound on the real fuel cut, confirmed by revisiting the
        same ceiling rather than by a fuel-cut sawtooth, so it stays available
        on cars the TCU upshifts before the limiter is ever touched.
        """
        max_r = self._max_r.get(car_key, 0.0)
        if max_r < self.MIN_CEILING_PCT:
            return None
        if self._ceiling_hits.get(car_key, 0.0) < self.CEILING_SAMPLES:
            return None
        return max_r

    def _peaks(self, car_key: tuple):
        """Return (peak_torque_rpm, peak_power_rpm, confidence)."""
        fit = self._fits.get(car_key)
        if fit is None or fit.n < self.MIN_SAMPLES:
            return None, None, 0.0
        abc = fit.solve()
        if abc is None:
            return None, None, 0.0
        a, b, c = abc
        if a >= -1e-6:  # not concave-down → no torque peak in range yet
            return None, None, 0.0

        pt = max(0.40, min(0.98, -b / (2 * a)))

        # Peak power: maximize torque*rpm = a r^3 + b r^2 + c r.
        # dP/dr = 3a r^2 + 2b r + c.
        deriv_at_redline = 3 * a + 2 * b + c
        if deriv_at_redline > 0:
            # Power still climbing at the limiter — high-rev NA engines
            # (e.g. BMW S54). The "peak" is effectively the redline:
            # shift as late as possible.
            pp = 0.97
        else:
            disc = 4 * b * b - 12 * a * c
            if disc < 0:
                pp = min(pt + 0.10, 0.95)
            else:
                sq = disc**0.5
                roots = [(-2 * b + sq) / (6 * a), (-2 * b - sq) / (6 * a)]
                cands = [r for r in roots if pt - 0.02 <= r <= 1.0]
                pp = max(cands) if cands else min(pt + 0.10, 0.95)
        pp = max(pt, min(0.97, pp))

        n_conf = max(
            0.0, min(1.0, (fit.n - self.MIN_SAMPLES) / (self.FULL_CONF_SAMPLES - self.MIN_SAMPLES))
        )
        s_conf = max(
            0.0, min(1.0, (fit.x_spread - self.MIN_SPREAD) / (self.GOOD_SPREAD - self.MIN_SPREAD))
        )
        max_r = self._max_r.get(car_key, 0.0)
        span = self.HIGH_RPM_COVERAGE - 0.40
        high_conf = max(0.0, min(1.0, (max_r - 0.40) / span)) if span > 0 else 0.0
        conf = n_conf * s_conf * high_conf
        # Mid-range-only parabolas often place the peak far below the real
        # power band — ignore until we have high-RPM evidence.
        if not self._has_high_rpm_coverage(car_key):
            return None, None, 0.0
        return pt, pp, conf

    def peak_torque_rpm(self, car_key: tuple) -> float | None:
        return self._peaks(car_key)[0]

    def peak_power_rpm(self, car_key: tuple) -> float | None:
        return self._peaks(car_key)[1]

    def confidence(self, car_key: tuple) -> float:
        return self._peaks(car_key)[2]

    def optimal_upshift_rpm(
        self, td: Telemetry, fallback: float = 0.85, offset: float = 0.03
    ) -> float:
        pt, pp, conf = self._peaks(td.car_key)
        if pp is None:
            return fallback
        model = max(0.65, min(0.97, pp + offset))
        # Blend: early low-confidence estimates lean on the fallback, mature
        # ones trust the model fully. The blend weight is the whole point of
        # the confidence score, so there is no additional hard gate on top of
        # it — one used to sit here and, together with the unreachable spread
        # thresholds, meant the model never moved a single shift point.
        return conf * model + (1.0 - conf) * fallback

    def has_data(self, car_key: tuple) -> bool:
        return self._peaks(car_key)[1] is not None

    def dump(self, car_key: tuple) -> dict | None:
        """Serialise the parabola fit for *car_key*, or None if no data."""
        fit = self._fits.get(car_key)
        if fit is None:
            return None
        data = fit.to_dict()
        max_r = self._max_r.get(car_key)
        if max_r is not None:
            data["max_r"] = max_r
        data["ceiling_hits"] = self._ceiling_hits.get(car_key, 0.0)
        return data

    def load(self, car_key: tuple, data: dict):
        """Restore a parabola fit from a previously-saved dump."""
        if not isinstance(data, dict):
            return
        self._fits[car_key] = _ParabolaFit.from_dict(data)
        if "max_r" in data:
            self._max_r[car_key] = float(data["max_r"])
        self._ceiling_hits[car_key] = float(data.get("ceiling_hits", 0.0))
