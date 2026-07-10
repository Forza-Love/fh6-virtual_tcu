<script setup lang="ts">
  import { computed } from 'vue'
  import { buildRpmScaleTicks, buildRpmSegments } from './hud-rpm-segments'

  const props = withDefaults(
    defineProps<{
      rpmPct: number
      rpmMax?: number
      segments?: number
      showScale?: boolean
      variant?: 'bar' | 'bar8'
    }>(),
    {
      rpmMax: 8000,
      segments: 16,
      showScale: true,
      variant: 'bar',
    },
  )

  const items = computed(() => buildRpmSegments(props.rpmPct, props.segments))
  const ticks8 = computed(() => buildRpmScaleTicks(8, props.rpmMax))
</script>

<template>
  <div class="rpm-segments" :class="`variant-${variant}`">
    <div v-if="variant === 'bar8' && showScale" class="scale-8">
      <span v-for="(t, i) in ticks8" :key="i">{{ t }}</span>
    </div>
    <div
      class="seg-row"
      role="meter"
      :aria-valuenow="Math.round(rpmPct * 100)"
      aria-valuemin="0"
      aria-valuemax="100"
    >
      <div v-for="(seg, i) in items" :key="i" class="seg" :class="[seg.tone, { lit: seg.lit }]" />
    </div>
  </div>
</template>

<style scoped>
  .rpm-segments {
    display: flex;
    flex-direction: column;
    gap: 3px;
    width: 100%;
  }

  .scale-8 {
    display: flex;
    justify-content: space-between;
    font-size: 9px;
    font-weight: 600;
    color: rgba(248, 250, 252, 0.75);
    padding: 0 2px;
  }

  .seg-row {
    display: flex;
    gap: 2px;
    height: 12px;
  }

  .variant-bar8 .seg-row {
    height: 14px;
    gap: 3px;
  }

  .seg {
    flex: 1;
    border-radius: 1px;
    background: rgba(255, 255, 255, 0.1);
    transition:
      background 80ms linear,
      box-shadow 80ms linear;
  }

  .seg.lit.live {
    background: #f8fafc;
    box-shadow: 0 0 4px rgba(255, 255, 255, 0.35);
  }

  .seg.lit.warn {
    background: #eab308;
    box-shadow: 0 0 5px rgba(234, 179, 8, 0.5);
  }

  .seg.red:not(.lit) {
    background: rgba(239, 68, 68, 0.3);
  }

  .seg.lit.red {
    background: #ef4444;
    box-shadow: 0 0 6px rgba(239, 68, 68, 0.55);
  }

  .seg.warn:not(.lit) {
    background: rgba(234, 179, 8, 0.22);
  }
</style>
