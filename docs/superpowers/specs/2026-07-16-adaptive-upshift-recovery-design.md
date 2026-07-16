# Adaptive Upshift Recovery and Load-Plateau Design

## Goal

Fix the remaining issues reproduced from the Ford GT 2005, Pagani Huayra R
2021, and brake-downshift replays without rolling back the shift-timing and
brake-downshift safety work in `13.2.6-pre.2`:

1. a Race wheelspin upshift lands below the power band and is immediately
   reversed by a power-demand downshift;
2. a high-confidence power-curve model raises the normal upshift target above
   both the configured WOT point and the reachable engine speed, leaving the
   car stuck at the limiter;
3. a high-gear car reaches a sustained load plateau below the normal WOT target
   and never qualifies for the existing low-gear RPM-ceiling recovery;
4. telemetry boost values outside the normalized range are compared directly
   with the normalized turbo accumulator, permanently blocking some upshifts.

## Evidence

### Brake-downshift replay

On the current `pre/13.2.6` working tree, replaying
`logs/刹车降档卡到2档.bin.gz` in Race mode produces this command sequence:

- 29.253 s: wheelspin `2→3` at 72.5% RPM; predicted third-gear landing is 42.5%;
- 29.764 s: power-demand `3→2` after the car falls below the power band;
- 30.291–32.394 s: second gear remains at WOT, peaks at 96.6%, and never shifts;
- the learned upshift target rises from 96.4% to 97.0%, while Race is configured
  for 94%.

The existing brake safety remains effective. The later brake `2→1` command is
predicted to land at 94.5% of the effective rev ceiling, below the 98% limit.

### Ford GT 2005

In `logs/tcu_replay_FordGT2005.bin.gz`, fourth gear remains at wide-open
throttle for about 33.8 seconds. RPM rises from 72.4%, spends most of the final
section around 82–84%, briefly peaks at 87.0%, and never reaches the configured
94% target. Road speed and RPM both flatten under sustained load, but the
existing broad speed-wall recovery is intentionally limited to gears 1–2, so
no `4→5` command is issued.

The same replay exposes a separate unit mismatch. Raw boost is approximately
12, while `_update_turbo` rejects values above 5 and synthesizes a normalized
target capped at 1.8. `_turbo_lag_block_upshift` then compares that normalized
accumulator against `raw_boost * 0.7`, a threshold it can never reach. Below
85% RPM, this can block an otherwise valid upshift indefinitely.

### Pagani Huayra R 2021

In `logs/tcu_replay_PaganiHuayraR2021.bin.gz`, the learned power-curve target
eventually rises from about 95.5% to 96.8%, while the engine peaks around 95.9%.
The configured Race WOT target remains 94%, but the learned target currently
replaces rather than bounds the fallback. After roughly one minute, the car can
therefore remain on the limiter in any gear without an in-band upshift.

The replay was recorded with `13.2.6-pre.1`. Its initial launch `2→3` occurs
while second-gear RPM is still rising rapidly. The local `13.2.6-pre.2` rising-
RPM guard already prevents that first command. A later wheelspin `2→3` remains
reproducible, however: it is issued at 91.8% RPM and is projected to land at
34.2%, after which the power-demand path shifts back to second.

## Design

### Effective upshift ceiling

In the shared Race/Offroad in-band upshift path, calculate the learned optimal
target as today, then use the lower of:

- the learned optimal target; and
- the effective fallback returned by `_wot_upshift_fallback`.

The effective fallback is either the configured mode WOT point or a lower RPM
ceiling confirmed by a continuous WOT plateau. This makes the configured value
an upper bound rather than allowing the model to demand an unreachable 97%.

This makes the learned model advisory within a safe envelope: it may retain an
earlier optimal shift, but it cannot raise the required RPM above the configured
or verified reachable limit. It preserves the successful `13.2.6-pre.1` timing
on the tested D- and C-class cars instead of globally restoring older values.

The same effective ceiling must be used by the shift advisor and anti-hunting
guard so the dashboard, upshift decision, and downshift protection do not
disagree about the active shift point.

### Normalized turbo target

Extract one helper that converts telemetry boost to the same normalized target
used by the turbo accumulator:

- use the valid telemetry value when it is between 0.01 and 5, capped at 1.8;
- otherwise use the existing throttle/RPM estimate, also capped at 1.8.

Both `_update_turbo` and `_turbo_lag_block_upshift` use this helper. The blocker
continues to protect genuine turbo spool below 85% RPM, but it no longer compares
normalized state with an unrelated raw telemetry scale.

### Sustained high-gear load plateau

Extend RPM-ceiling recovery with a separate high-gear load-plateau condition.
It applies only when all of the following remain true continuously:

- gear is 3 or higher;
- throttle is at least 85%, brake is at most 5%, and maximum driven-wheel slip
  is at most 0.8;
- RPM is at or above the mode's mid upshift threshold;
- across the latest 10 RPM samples, the final-three average exceeds the first-
  three average by no more than 0.5 percentage points;
- across the latest 15 speed samples, road speed grows by no more than 0.8 km/h;
- the condition persists for at least one second.

When confirmed, use the observed plateau as the verified fallback, bounded by
the configured WOT and mode mid thresholds. Reset the candidate on a gear
change, throttle lift, braking, excessive slip, or renewed RPM/speed growth.
This lets the Ford recover after a genuine sustained fourth-gear load wall,
while avoiding a shift during a short hill, corner, launch, or traction event.

### Race wheelspin landing guard

Keep the existing wheelspin detector and its traction intent. Before Race sends
a wheelspin upshift, use the learned ratio for the next gear to project landing
RPM at the current speed.

- If the projected next gear is at or above `race_power_floor`, allow the shift.
- If it is below `race_power_floor`, hold the current gear so the power-demand
  path will not immediately reverse the action.
- If the next-gear ratio is not learned, preserve current behavior rather than
  disabling traction protection globally.

The guard is applied to Race only. Comfort and Offroad wheelspin behavior is not
changed without a reproducing log for those modes.

The `13.2.6-pre.2` rising-RPM check remains in place. It is the regression guard
for the Pagani's initial launch event and is independent of the landing guard
for the later wheelspin event.

## Alternatives Rejected

### Disable wheelspin upshifts

This would remove a useful traction-protection path from vehicles that land in
a healthy next gear. The landing guard is narrower and evidence-based.

### Restore old timers or extend the downshift lock

A longer lock only delays the `3→2` reversal and does not fix the low landing
RPM or unreachable 97% target. It would also slow unrelated vehicles.

### Cap only second gear

Earlier reports include a car stuck on `3→4`, and the same learned-target
inconsistency applies in every gear. The effective ceiling belongs in the shared
in-band upshift path.

### Add per-car exceptions

Ford- or Pagani-specific RPM values would handle only the supplied tunes and
would fail again when gearing, power upgrades, or drivetrain swaps change. The
selected signals describe the actual failure state and remain vehicle-agnostic.

### Treat every high-gear RPM pause as a ceiling

A brief RPM pause can be caused by a corner, slope, wheelspin, or throttle
transition. Requiring continuous high load, low slip, flat RPM and speed, plus a
minimum duration, prevents that transient state from becoming a premature
upshift trigger.

## Testing

Add regressions that fail before production changes:

- a 94% Race frame must upshift even when the learned model asks for 97%;
- a verified lower plateau must override a high learned model target;
- the shift advisor and anti-hunting threshold must use the same bounded target;
- raw boost above the normalized telemetry range must not permanently block an
  otherwise valid upshift;
- a sustained high-gear load plateau must recover an upshift, while rising RPM,
  wheelspin, throttle lift, and braking must reset or reject the plateau;
- a ratio-aware Race wheelspin upshift is blocked when the next gear would land
  below `race_power_floor`;
- a healthy or ratio-less wheelspin upshift remains allowed;
- replaying `tcu_replay_FordGT2005.bin.gz` must issue `4→5` before the next
  braking section;
- replaying `tcu_replay_PaganiHuayraR2021.bin.gz` must not perform the initial
  rising-RPM launch skip, must reject the low-landing wheelspin shift, and must
  resume normal upshifts after the learned model matures;
- replaying `刹车降档卡到2档.bin.gz` must issue `2→3` after the final power
  downshift and before the next brake application.

Replay assertions account for the fact that a recorded gear cannot acknowledge
a newly generated shift command; repeated commands after an expected recovery
are not interpreted as real-game hunting.

Run the existing low-gear, hunting, brake-downshift, pending-acknowledgement and
rev-limiter regression groups, every available replay (including the D- and
C-class logs), the full Python suite, lint, typecheck, Dashboard build, and
Electron build.

## Release

Do not move or publish the existing local `v13.2.6-pre.2` tag. After the fix and
verification, advance the package version to `13.2.6-pre.3`, commit it, create
`v13.2.6-pre.3`, and publish the branch and tag once GitHub authentication is
available.
