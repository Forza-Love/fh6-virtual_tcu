# Shift Stability Design

## Goal

Restore the predictable shift feel of 13.2.2 while retaining fixes added since
that release. The stabilization targets the reported early 1→2 shift, failure
to continue upshifting, repeated gear hunting, and brake downshifts that land
too deeply in the red zone.

## Constraints

- Keep the post-13.2.2 fixes for rev-limiter learning and shift acknowledgement.
- Do not broadly roll back constants whose effects apply to every vehicle.
- Prefer a less aggressive staged brake downshift over an unsafe direct target.
- Do not add a coast-time forced upshift that could change gear mid-corner.
- Preserve Comfort behavior and vehicles without learned ratios wherever possible.

## Design

### Brake downshift safety

The desired brake gear may continue to be selected using projected braking
speed, because that provides useful engine braking. Before a command is sent,
the target is clamped against the RPM it would produce at the current speed.
Starting at the desired target, move upward through the available gears until
the learned ratio predicts no more than 98% of the effective rev ceiling.

If ratio data for a direct target is missing, fall back to the existing
single-step downshift. A multi-gear command validates the exact target it will
send, not the fixed `current gear - 2` gear. Shift counters reflect the actual
number of crossed gears.

This affects only ratio-aware aggressive braking when the desired target is
unsafe at the current speed. Safe targets, Comfort mode, and ratio-less cars
retain their existing path.

### Low-gear upshift timing

A WOT plateau below the configured Race or Offroad shift point remains a valid
reason to upshift. A rising RPM trace is not a plateau. The detector must use
the recent window's direction as well as its range: a stable or oscillating
ceiling may use the learned fallback, while a meaningful positive climb must
continue toward the configured shift point.

The one-frame/short launch wheelspin path remains disabled in first gear. The
existing shift acknowledgement fixes remain in place so a temporary in-shift
gear encoding cannot clear the pending command.

### Anti-hunting consistency

Power-demand downshift protection must compare the target gear against the same
effective WOT upshift fallback used by the upshift path. This prevents a
downshift into a gear that immediately satisfies the adaptive plateau upshift
threshold.

### Timing constants

The 13.2.2 constants are not restored as a group. A longer acknowledgement
timeout may be restored only if replay and tests show that a correctly handled
slow acknowledgement still expires too early. Normal confirmed shifts should
clear pending state rather than wait for the timeout.

## Verification

Regression tests cover:

- exact-target over-rev validation for a multi-gear brake downshift;
- clamping a projected-speed target that is unsafe at current speed;
- safe targets remaining unchanged;
- a rising second-gear RPM trace not using the mid fallback;
- a true low-gear RPM plateau still upshifting;
- post-brake return to throttle continuing to upshift;
- no near-threshold power-demand downshift/upshift loop.

The recorded issue logs are replayed, followed by the Python suite and the
repository's Linux CI-parity lint, typecheck, dashboard build, and Electron
compile checks. Release versioning is advanced only after these checks pass.
