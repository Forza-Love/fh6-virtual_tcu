import assert from 'node:assert/strict'
import { buildRpmScaleTicks, formatScaleK, rpmMaxToScaleK } from './hud-rpm-segments.ts'

for (const rpmMax of [4000, 4500, 5000, 5500, 6000, 6500, 7000, 7500, 8000, 8500, 9000, 10000]) {
  const ticks = buildRpmScaleTicks(8, rpmMax)
  assert.equal(
    new Set(ticks).size,
    ticks.length,
    `duplicates for rpmMax=${rpmMax}: ${ticks.join(' ')}`,
  )
  assert.ok(ticks.length >= 2, `expected at least 2 ticks for rpmMax=${rpmMax}`)
  assert.equal(ticks.at(-1), formatScaleK(rpmMaxToScaleK(rpmMax)))
}

assert.deepEqual(buildRpmScaleTicks(8, 7500), ['1', '2', '3', '4', '5', '6', '7', '7.5'])
assert.deepEqual(buildRpmScaleTicks(8, 6000), ['1', '2', '3', '4', '5', '6'])

console.info('hud-rpm-segments scale ticks: ok')
