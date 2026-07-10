export type RpmSegmentTone = 'off' | 'live' | 'warn' | 'red'

export interface RpmSegment {
  lit: boolean
  tone: RpmSegmentTone
}

export function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value))
}

/** Build discrete RPM bar segments (racing-style LED tach). */
export function buildRpmSegments(rpmPct: number, count = 18): RpmSegment[] {
  const pct = clamp01(rpmPct)
  const litCount = Math.round(pct * count)

  return Array.from({ length: count }, (_, i) => {
    const zone = (i + 1) / count
    const lit = i < litCount

    if (zone > 0.92) return { lit, tone: 'red' as const }
    if (zone > 0.78) return { lit, tone: lit ? 'warn' : 'off' }
    if (lit) return { lit: true, tone: 'live' as const }
    return { lit: false, tone: 'off' as const }
  })
}

/** Build LED dot segments (minimal style). */
export function buildLedDots(rpmPct: number, count = 16): RpmSegment[] {
  return buildRpmSegments(rpmPct, count)
}

/** Fixed top label for racing bar tach (×1000 RPM). */
export const RPM_SCALE_MAX_K = 10

/** Scale tick labels 1 – 8 for horizontal bar tach. @deprecated use buildRpmScaleTicks */
export function rpmScaleOneToEight(): string[] {
  return buildRpmScaleTicks(8, 8000)
}

/** Redline in ×1000 RPM, floored to nearest 0.5, capped at {@link RPM_SCALE_MAX_K}. */
export function rpmMaxToScaleK(rpmMax: number): number {
  if (!Number.isFinite(rpmMax) || rpmMax <= 0) return RPM_SCALE_MAX_K
  return Math.min(RPM_SCALE_MAX_K, Math.floor(rpmMax / 500) * 0.5)
}

export function roundToHalf(value: number): number {
  return Math.round(value * 2) / 2
}

export function formatScaleK(value: number): string {
  const rounded = roundToHalf(value)
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1)
}

/**
 * Racing bar scale: interior ticks are integers; last tick is car redline (×1000, 0.5 step, max 10).
 *
 * Rounded interior values can collide (e.g. 6k → "2"/"5" twice). Duplicates are dropped so
 * Vue list keys stay unique — duplicate `:key` values previously caused scale DOM nodes to
 * accumulate across long telemetry sessions.
 */
export function buildRpmScaleTicks(count: number, rpmMax: number): string[] {
  if (count <= 0) return []
  const maxK = rpmMaxToScaleK(rpmMax)
  const last = formatScaleK(maxK)
  if (count === 1) return [last]

  const ticks: string[] = []
  const seen = new Set<string>()
  for (let i = 0; i < count - 1; i++) {
    const raw = ((i + 1) / count) * maxK
    const label = String(Math.round(raw))
    if (seen.has(label) || label === last) continue
    seen.add(label)
    ticks.push(label)
  }
  ticks.push(last)
  return ticks
}

export function pedalPct(value: number): number {
  return clamp01(value)
}

export function pedalPercentLabel(value: number): string {
  return `${Math.round(pedalPct(value) * 100)}%`
}

/** Arc tachometer value 0 – 8 based on rpm fraction. */
export function arcTachValue(rpmPct: number): number {
  return clamp01(rpmPct) * 8
}

export function arcTachDash(rpmPct: number, pathLength = 100): string {
  const filled = (clamp01(rpmPct) * pathLength).toFixed(2)
  return `${filled} ${pathLength}`
}

export function arcTachColor(rpmPct: number): string {
  const pct = clamp01(rpmPct)
  if (pct > 0.875) return '#ef4444'
  if (pct > 0.75) return '#eab308'
  return '#f8fafc'
}
