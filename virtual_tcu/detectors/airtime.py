from dataclasses import dataclass

from virtual_tcu.telemetry.model import Telemetry


@dataclass(frozen=True)
class AirState:
    """Per-frame airtime result. ``airborne`` is the steady state; the two
    edge flags fire exactly once so the caller can run takeoff / landing
    hooks without tracking previous state itself."""

    airborne: bool
    airborne_started: bool
    just_landed: bool


class AirtimeDetector:
    """Detects the car leaving the ground and the moment it lands again,
    from vertical proper-acceleration (``accel_y``).

    Empirically verified against FH6 replay telemetry: grounded driving sits
    at ``accel_y ≈ 0``, sustained free-fall reads ``≈ -12.5`` for the whole
    jump arc (gravity, sign-negative), and a landing impact spikes sharply
    positive (seen up to +195) before settling back to zero.

    Wheel slip is **not** used: in real logs it frequently reads 0 even mid-
    air, so the previous "all four wheels spinning" gate never engaged and
    the car kept shifting in flight. ``vel_y`` is a poor primary signal too —
    it flips sign across the arc (up then down) while ``accel_y`` stays
    negative throughout — so the vertical acceleration is the clean
    discriminator and the only one we key on."""

    FREEFALL_G = -6.0  # accel_y below this = free-fall (enter airborne)
    GROUND_G = -4.0  # accel_y above this = back on the ground (exit)
    # A crest can unload the suspension without producing three full
    # free-fall frames. Wheel-speed/RPM based shift decisions are already
    # unreliable there, so expose a short pre-air hold as well.
    UNWEIGHTED_G = -3.0
    MIN_SPEED_FOR_AIRBORNE = 15.0
    FRAMES_TO_ENGAGE = 3
    FRAMES_TO_DISENGAGE = 2
    LANDING_WINDOW_S = 0.75
    UNWEIGHTED_HOLD_S = 0.25
    # A crest hold is meant for a brief suspension unload. A sustained
    # downhill grade can keep accel_y below UNWEIGHTED_G for many seconds —
    # renewing the hold there would freeze every automatic shift exactly when
    # descent recovery is needed, so bound the continuous hold.
    UNWEIGHTED_MAX_CONTINUOUS_S = 1.0

    def __init__(self):
        self._air_streak = 0
        self._ground_streak = 0
        self._is_airborne = False
        self._landing_until = 0.0
        self._unweighted_until = 0.0
        self._unweighted_since = 0.0
        self._is_unweighted = False

    def update(self, td: Telemetry, now: float) -> AirState:
        falling = td.accel_y < self.FREEFALL_G and td.speed_kmh > self.MIN_SPEED_FOR_AIRBORNE
        unweighted = td.accel_y < self.UNWEIGHTED_G and td.speed_kmh > self.MIN_SPEED_FOR_AIRBORNE
        if unweighted:
            self._unweighted_until = now + self.UNWEIGHTED_HOLD_S
        held = unweighted or now < self._unweighted_until
        if held:
            if self._unweighted_since == 0.0:
                self._unweighted_since = now
            elif (now - self._unweighted_since) > self.UNWEIGHTED_MAX_CONTINUOUS_S:
                # Edge-bounded: a hold that keeps renewing is a grade, not a
                # crest. Stay released until the raw signal actually clears.
                held = False
        else:
            self._unweighted_since = 0.0
        self._is_unweighted = held
        # Hysteresis band (-6 .. -4): neither vote advances, so a value hovering
        # near the threshold can't flap the state.
        grounded = td.accel_y > self.GROUND_G

        airborne_started = False
        just_landed = False

        if not self._is_airborne:
            self._air_streak = self._air_streak + 1 if falling else 0
            if self._air_streak >= self.FRAMES_TO_ENGAGE:
                self._is_airborne = True
                self._ground_streak = 0
                airborne_started = True
        else:
            # The positive landing-impact spike is well above GROUND_G, so it
            # counts as a ground vote and triggers the landing edge promptly.
            self._ground_streak = self._ground_streak + 1 if grounded else 0
            if self._ground_streak >= self.FRAMES_TO_DISENGAGE:
                self._is_airborne = False
                self._air_streak = 0
                self._landing_until = now + self.LANDING_WINDOW_S
                just_landed = True

        return AirState(
            airborne=self._is_airborne,
            airborne_started=airborne_started,
            just_landed=just_landed,
        )

    @property
    def is_airborne(self) -> bool:
        return self._is_airborne

    @property
    def is_unweighted(self) -> bool:
        """Whether suspension load is too low for a reliable shift decision."""
        return self._is_unweighted

    @property
    def landing_until(self) -> float:
        return self._landing_until
