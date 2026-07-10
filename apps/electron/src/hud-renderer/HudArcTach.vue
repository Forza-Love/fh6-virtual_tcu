<script setup lang="ts">
  import { computed } from 'vue'
  import { ARC_TACH_TICKS, arcTachTickX } from './hud-arc-tach'
  import { arcTachColor, arcTachDash } from './hud-rpm-segments'

  const props = withDefaults(defineProps<{ rpmPct: number; showTicks?: boolean }>(), {
    showTicks: false,
  })

  const dash = computed(() => arcTachDash(props.rpmPct, 100))
  const stroke = computed(() => arcTachColor(props.rpmPct))
</script>

<template>
  <div class="arc-tach" :class="{ compact: !showTicks }">
    <svg :viewBox="showTicks ? '0 0 220 118' : '0 0 220 102'" aria-hidden="true">
      <path
        class="arc-bg"
        d="M 24 96 A 86 86 0 0 1 196 96"
        fill="none"
        stroke-width="10"
        stroke-linecap="round"
      />
      <path
        class="arc-fill"
        d="M 24 96 A 86 86 0 0 1 196 96"
        fill="none"
        stroke-width="10"
        stroke-linecap="round"
        pathLength="100"
        :stroke="stroke"
        :stroke-dasharray="dash"
      />
      <text
        v-for="(t, i) in ARC_TACH_TICKS"
        v-show="showTicks"
        :key="i"
        class="tick"
        :x="arcTachTickX(i)"
        y="112"
      >
        {{ t }}
      </text>
    </svg>
    <div v-if="$slots.default" class="arc-slot">
      <slot />
    </div>
  </div>
</template>

<style scoped>
  .arc-tach {
    position: relative;
    width: 100%;
    max-width: 260px;
    margin: 0 auto;
  }

  svg {
    width: 100%;
    height: auto;
    display: block;
  }

  .arc-tach.compact svg {
    margin-bottom: -4px;
  }

  .arc-bg {
    stroke: rgba(255, 255, 255, 0.12);
  }

  .arc-fill {
    filter: drop-shadow(0 0 5px rgba(255, 255, 255, 0.35));
    transition:
      stroke-dasharray 75ms linear,
      stroke 150ms linear;
  }

  .tick {
    fill: rgba(148, 163, 184, 0.85);
    font-size: 9px;
    font-weight: 600;
    text-anchor: middle;
    font-family: inherit;
  }

  .arc-slot {
    position: absolute;
    left: 50%;
    top: 52%;
    transform: translate(-50%, -50%);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    pointer-events: none;
  }

  .arc-slot :deep(.shift-hints) {
    pointer-events: auto;
  }
</style>
