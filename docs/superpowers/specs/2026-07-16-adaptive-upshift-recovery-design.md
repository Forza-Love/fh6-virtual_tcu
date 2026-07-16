# Adaptive Upshift Recovery Design

## Goal

Fix the two issues reproduced from `logs/刹车降档卡到2档.bin.gz` without
rolling back the brake-downshift safety work in `13.2.6-pre.2`:

1. a Race wheelspin upshift lands below the power band and is immediately
   reversed by a power-demand downshift;
2. a high-confidence power-curve model raises the normal upshift target above
   both the configured WOT point and the detected RPM-plateau fallback, leaving
   the car stuck in second gear.

## Evidence

On the current `pre/13.2.6` working tree, replaying the new log in Race mode
produces this command sequence:

- 29.253 s: wheelspin `2→3` at 72.5% RPM; predicted third-gear landing is 42.5%;
- 29.764 s: power-demand `3→2` after the car falls below the power band;
- 30.291–32.394 s: second gear remains at WOT, peaks at 96.6%, and never shifts;
- the learned upshift target rises from 96.4% to 97.0%, while Race is configured
  for 94%.

The existing brake safety remains effective. The later brake `2→1` command is
predicted to land at 94.5% of the effective rev ceiling, below the 98% limit.

## Design

### Effective upshift ceiling

In the shared Race/Offroad in-band upshift path, calculate the learned optimal
target as today, then use the lower of:

- the learned optimal target; and
- the effective fallback returned by `_wot_upshift_fallback`.

The effective fallback is either the configured mode WOT point or a lower RPM
ceiling confirmed by a continuous WOT plateau. This makes the configured value
an upper bound rather than allowing the model to demand an unreachable 97%.

This does not force every vehicle to shift at the configured point. A learned
optimal target below the configured value remains valid, and a verified lower
plateau can still recover a car that cannot reach the configured value.

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

## Testing

Add regressions that fail before production changes:

- a 94% Race frame must upshift even when the learned model asks for 97%;
- a verified lower plateau must override a high learned model target;
- a ratio-aware Race wheelspin upshift is blocked when the next gear would land
  below `race_power_floor`;
- a healthy or ratio-less wheelspin upshift remains allowed;
- replaying `刹车降档卡到2档.bin.gz` must issue `2→3` after the final power
  downshift and before the next brake application.

Run the existing low-gear, hunting, brake-downshift, pending-acknowledgement and
rev-limiter regression groups, all available replays, the full Python suite,
lint, typecheck, Dashboard build, and Electron build.

## Release

Do not move or publish the existing local `v13.2.6-pre.2` tag. After the fix and
verification, advance the package version to `13.2.6-pre.3`, commit it, create
`v13.2.6-pre.3`, and publish the branch and tag once GitHub authentication is
available.
