<script setup lang="ts">
  import type { TabId } from './settings-panel'
  import type { SessionStats, ShiftHistoryItem, TelemetrySnapshot } from '@/types/telemetry'
  import type { ConfigMap } from '@/types/ws'
  import { NButton, NCard, NFlex, NInput, NSlider, NSwitch, NTabPane, NTabs, NText } from 'naive-ui'
  import { computed, toRefs } from 'vue'
  import {
    CLUTCH_ASSIST_FIELDS,
    CLUTCH_TIMING_SLIDERS,
    FEATURE_TOGGLES,
    GAMEPAD_BUTTON_FIELDS,
    GAMEPAD_BUTTON_OPTIONS,
    HOTKEY_FIELDS,
    OUTPUT_MODE_OPTIONS,
    SETTING_GROUPS,
    SHIFT_KEY_FIELDS,
    VJOY_BUTTON_OPTIONS,
    VJOY_SHIFT_BUTTON_FIELDS,
  } from '@/config/settings'
  import { useNetworkSettings } from './network-settings'

  import { sliderUnit, TAB_IDS, useConfirmReset, useSettingsPanel } from './settings-panel'

  const props = withDefaults(
    defineProps<{
      config: ConfigMap
      telemetry?: TelemetrySnapshot | null
      sessionStats?: SessionStats | null
      shiftHistory?: ShiftHistoryItem[]
      watchdogStuck?: boolean
      visibleTabs?: string[]
      initialTab?: string
      hideTabBar?: boolean
    }>(),
    {
      telemetry: null,
      sessionStats: null,
      shiftHistory: () => [],
      watchdogStuck: false,
      visibleTabs: () => [...TAB_IDS],
      initialTab: '',
      hideTabBar: false,
    },
  )
  const emit = defineEmits([
    'setConfig',
    'applyNetwork',
    'resetConfig',
    'exportProfile',
    'openImport',
    'restartBackend',
  ])

  const { config, telemetry, sessionStats, shiftHistory, visibleTabs } = toRefs(props)

  const {
    activeTab,
    slidersFor,
    statsRows,
    historyItems,
    configValue,
    configBool,
    configText,
    sliderDef,
  } = useSettingsPanel(
    () => config.value,
    () => telemetry.value,
    () => sessionStats.value,
    () => shiftHistory.value,
  )

  if (props.initialTab && (props.visibleTabs ?? TAB_IDS).includes(props.initialTab)) {
    activeTab.value = props.initialTab as TabId
  } else if (props.visibleTabs?.length && !props.visibleTabs.includes(activeTab.value)) {
    activeTab.value = props.visibleTabs[0] as TabId
  }

  const extrasSliders = computed(() => slidersFor('extras'))

  const {
    draftHost: networkDraftHost,
    draftWebPort: networkDraftWebPort,
    draftUdpPort: networkDraftUdpPort,
    dirty: networkDirty,
    applyError: networkApplyError,
    validate: validateNetwork,
  } = useNetworkSettings(() => config.value)

  function applyNetworkSettings() {
    const parsed = validateNetwork()
    if (parsed) emit('applyNetwork', parsed.host, parsed.webPort, parsed.udpPort)
  }

  const { confirmReset } = useConfirmReset(() => emit('resetConfig'))
</script>

<template>
  <div class="flex flex-col gap-4 p-4">
    <NTabs v-if="!hideTabBar" v-model:value="activeTab" type="line" size="small">
      <NTabPane v-for="tab in visibleTabs" :key="tab" :name="tab" :tab="$t(`tabs.${tab}`)">
        <!-- settings tab -->
        <template v-if="tab === 'settings'">
          <NFlex vertical :size="16">
            <div
              v-if="watchdogStuck"
              class="border-warn bg-warn/15 text-warn rounded-lg border px-3.5 py-2.5 text-sm before:font-bold before:content-['⚠_']"
            >
              {{ $t('settings.watchdog') }}
            </div>

            <NCard :title="$t('settings.features')" size="small" :bordered="false">
              <NFlex vertical :size="10">
                <NFlex
                  v-for="f in FEATURE_TOGGLES"
                  :key="f.key"
                  justify="space-between"
                  align="center"
                >
                  <NText>{{ $t(`settings.${f.i18nKey}`) }}</NText>
                  <NSwitch
                    :value="configBool(f.key)"
                    @update:value="emit('setConfig', f.key, $event)"
                  />
                </NFlex>
              </NFlex>
            </NCard>

            <NCard
              v-for="group in SETTING_GROUPS"
              :key="group.i18nKey"
              :title="$t(`settings.${group.i18nKey}`)"
              size="small"
              :bordered="false"
            >
              <template v-if="group.hintKey">
                <NText depth="3" style="font-size: 11px; display: block; margin-bottom: 8px">
                  {{ $t(`settings.${group.hintKey}`) }}
                </NText>
              </template>
              <NFlex vertical :size="14">
                <div v-for="key in group.keys" :key="key">
                  <NFlex justify="space-between" align="center" style="margin-bottom: 4px">
                    <NText>{{ $t(`settings.${sliderDef(key)?.i18nKey ?? key}`) }}</NText>
                    <NText code style="font-family: ui-monospace, monospace">
                      {{ configValue(key) }}{{ sliderUnit(sliderDef(key) ?? {}) }}
                    </NText>
                  </NFlex>
                  <NSlider
                    :value="configValue(key)"
                    :min="sliderDef(key)?.min ?? 0"
                    :max="sliderDef(key)?.max ?? 100"
                    :step="sliderDef(key)?.step ?? 1"
                    @update:value="emit('setConfig', key, $event)"
                  />
                </div>
              </NFlex>
            </NCard>

            <NCard size="small" :bordered="false">
              <NFlex justify="space-between" align="center">
                <NText depth="3" style="font-size: 12px">
                  {{ $t('settings.autosave') }}
                </NText>
                <NButton type="error" ghost size="small" @click="confirmReset">
                  {{ $t('settings.reset') }}
                </NButton>
              </NFlex>
            </NCard>
          </NFlex>
        </template>

        <!-- stats tab -->
        <template v-if="tab === 'stats'">
          <NFlex vertical :size="16">
            <NCard :title="$t('stats.title')" size="small" :bordered="false">
              <template v-if="statsRows">
                <NFlex vertical :size="6">
                  <NFlex justify="space-between" align="center">
                    <NText depth="3">{{ $t('stats.duration') }}</NText>
                    <NText code>{{ statsRows.duration }}</NText>
                  </NFlex>
                  <NFlex justify="space-between" align="center">
                    <NText depth="3">{{ $t('stats.totalShifts') }}</NText>
                    <NText code>{{ statsRows.total }}</NText>
                  </NFlex>
                  <NFlex justify="space-between" align="center">
                    <NText depth="3">{{ $t('stats.upshifts') }}</NText>
                    <NText code>{{ statsRows.upshifts }}</NText>
                  </NFlex>
                  <NFlex justify="space-between" align="center">
                    <NText depth="3">{{ $t('stats.downshifts') }}</NText>
                    <NText code>{{ statsRows.downshifts }}</NText>
                  </NFlex>
                  <NFlex justify="space-between" align="center">
                    <NText depth="3">{{ $t('stats.kickdowns') }}</NText>
                    <NText code>{{ statsRows.kickdowns }}</NText>
                  </NFlex>
                  <NFlex justify="space-between" align="center">
                    <NText depth="3">{{ $t('stats.brakeDowns') }}</NText>
                    <NText code>{{ statsRows.brakeDowns }}</NText>
                  </NFlex>
                  <NFlex justify="space-between" align="center">
                    <NText depth="3">{{ $t('stats.predictives') }}</NText>
                    <NText code>{{ statsRows.predictives }}</NText>
                  </NFlex>
                  <NFlex justify="space-between" align="center">
                    <NText depth="3">{{ $t('stats.launches') }}</NText>
                    <NText code>{{ statsRows.launches }}</NText>
                  </NFlex>
                </NFlex>
              </template>
            </NCard>

            <NCard v-if="statsRows" :title="$t('stats.performance')" size="small" :bordered="false">
              <NFlex vertical :size="6">
                <NFlex justify="space-between" align="center">
                  <NText depth="3">{{ $t('stats.peakRpm') }}</NText>
                  <NText code>{{ statsRows.peakRpm }}</NText>
                </NFlex>
                <NFlex justify="space-between" align="center">
                  <NText depth="3">{{ $t('stats.peakSpeed') }}</NText>
                  <NText code>{{ statsRows.peakSpeed }} km/h</NText>
                </NFlex>
                <NFlex justify="space-between" align="center">
                  <NText depth="3">{{ $t('stats.peakGLat') }}</NText>
                  <NText code>{{ statsRows.peakGLat }}</NText>
                </NFlex>
                <NFlex justify="space-between" align="center">
                  <NText depth="3">{{ $t('stats.peakGLon') }}</NText>
                  <NText code>{{ statsRows.peakGLon }}</NText>
                </NFlex>
                <NFlex justify="space-between" align="center">
                  <NText depth="3">{{ $t('stats.peakPower') }}</NText>
                  <NText code>{{ statsRows.peakPower }} kW</NText>
                </NFlex>
                <NFlex justify="space-between" align="center">
                  <NText depth="3">{{ $t('stats.avgThrottle') }}</NText>
                  <NText code>{{ statsRows.avgThr }}%</NText>
                </NFlex>
                <NFlex justify="space-between" align="center">
                  <NText depth="3">{{ $t('stats.carsDriven') }}</NText>
                  <NText code>{{ statsRows.cars }}</NText>
                </NFlex>
              </NFlex>
            </NCard>

            <NCard v-if="statsRows" :title="$t('stats.learning')" size="small" :bordered="false">
              <NFlex vertical :size="6">
                <NFlex justify="space-between" align="center">
                  <NText depth="3">{{ $t('stats.gearRatios') }}</NText>
                  <NText code>{{
                    statsRows.calib ? $t('stats.learned') : $t('stats.learningStatus')
                  }}</NText>
                </NFlex>
                <NFlex justify="space-between" align="center">
                  <NText depth="3">{{ $t('stats.powerCurve') }}</NText>
                  <NText code>{{
                    statsRows.powerLearned ? $t('stats.learned') : $t('stats.learningStatus')
                  }}</NText>
                </NFlex>
              </NFlex>
            </NCard>
          </NFlex>
        </template>

        <!-- history tab -->
        <template v-if="tab === 'history'">
          <NCard :title="$t('history.title')" size="small" :bordered="false">
            <div class="flex max-h-60 flex-col gap-1 overflow-y-auto">
              <div
                v-if="historyItems.length === 0"
                class="text-tcu-txt-dim py-5 text-center text-xs"
              >
                {{ $t('history.empty') }}
              </div>
              <div
                v-for="(h, i) in historyItems"
                :key="i"
                class="border-tcu-border bg-tcu-bg-1 grid grid-cols-[auto_auto_1fr_auto] items-center gap-2.5 rounded-md border px-2.5 py-1.5 font-mono text-[11px]"
              >
                <span
                  class="text-sm font-bold"
                  :class="h.action === 'UP' ? 'text-accent' : 'text-warn'"
                >
                  {{ h.action === 'UP' ? '↑' : '↓' }}
                </span>
                <span class="text-tcu-txt-muted">gear {{ h.gear }}</span>
                <span class="text-tcu-txt-dim text-[10px] tracking-wide uppercase">{{
                  h.reason || h.rule
                }}</span>
                <span class="text-tcu-txt-dim text-right text-[10px]">
                  {{ new Date(h.ts * 1000).toTimeString().slice(0, 8) }} · {{ h.rpm_pct }}% ·
                  {{ h.throttle }}%T {{ h.brake }}%B
                </span>
              </div>
            </div>
          </NCard>
        </template>

        <!-- extras tab -->
        <template v-if="tab === 'extras'">
          <NFlex vertical :size="16">
            <NCard :title="$t('extras.networkTitle')" size="small" :bordered="false">
              <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
                {{ $t('extras.networkHint') }}
              </NText>
              <NFlex vertical :size="10">
                <NFlex justify="space-between" align="center" :size="8">
                  <NText>{{ $t('extras.webHost') }}</NText>
                  <NInput
                    v-model:value="networkDraftHost"
                    placeholder="0.0.0.0"
                    maxlength="15"
                    size="small"
                    style="width: 120px; font-family: ui-monospace, monospace"
                  />
                </NFlex>
                <NFlex justify="space-between" align="center" :size="8">
                  <NText>{{ $t('extras.webPort') }}</NText>
                  <NInput
                    v-model:value="networkDraftWebPort"
                    placeholder="8765"
                    maxlength="5"
                    size="small"
                    style="width: 120px; font-family: ui-monospace, monospace"
                  />
                </NFlex>
                <NFlex justify="space-between" align="center" :size="8">
                  <NText>{{ $t('extras.udpPort') }}</NText>
                  <NInput
                    v-model:value="networkDraftUdpPort"
                    placeholder="5555"
                    maxlength="5"
                    size="small"
                    style="width: 120px; font-family: ui-monospace, monospace"
                  />
                </NFlex>
              </NFlex>
              <NText depth="3" style="font-size: 11px; display: block; margin-top: 8px">
                {{ $t('extras.udpPortHint') }}
              </NText>
              <NFlex :size="8" align="center" style="margin-top: 12px">
                <NButton
                  type="primary"
                  size="small"
                  :disabled="!networkDirty"
                  @click="applyNetworkSettings"
                >
                  {{ $t('extras.networkApply') }}
                </NButton>
                <NText v-if="networkApplyError" depth="3" style="font-size: 12px; color: #dc2626">
                  {{ $t(`extras.networkErrors.${networkApplyError}`) }}
                </NText>
              </NFlex>
            </NCard>

            <NCard :title="$t('extras.profileTitle')" size="small" :bordered="false">
              <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 12px">
                {{ $t('extras.profileHint') }}
              </NText>
              <NFlex :size="8">
                <NButton @click="emit('exportProfile')">
                  {{ $t('extras.export') }}
                </NButton>
                <NButton @click="emit('openImport')">
                  {{ $t('extras.import') }}
                </NButton>
              </NFlex>
            </NCard>

            <NCard :title="$t('extras.outputMode')" size="small" :bordered="false">
              <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
                {{ $t('extras.outputModeHint') }}
              </NText>
              <NSelect
                :value="($props.config as any).output_mode || 'keyboard'"
                :options="
                  OUTPUT_MODE_OPTIONS.map((o) => ({
                    label: $t(`extras.${o.i18nKey}`),
                    value: o.value,
                  }))
                "
                size="small"
                style="width: 200px"
                @update:value="emit('setConfig', 'output_mode', $event)"
              />
              <template v-if="(($props.config as any).output_mode || 'keyboard') === 'gamepad'">
                <NText depth="3" style="font-size: 12px; display: block; margin: 12px 0 8px">
                  {{ $t('extras.gamepadButtonHint') }}
                </NText>
                <NFlex vertical :size="10">
                  <NFlex
                    v-for="g in GAMEPAD_BUTTON_FIELDS"
                    :key="g.key"
                    justify="space-between"
                    align="center"
                    :size="8"
                  >
                    <NText>{{ $t(`extras.${g.i18nKey}`) }}</NText>
                    <NSelect
                      :value="configText(g.key) || g.placeholder"
                      :options="
                        GAMEPAD_BUTTON_OPTIONS.map((o) => ({ label: o.label, value: o.value }))
                      "
                      size="small"
                      style="width: 140px"
                      @update:value="emit('setConfig', g.key, $event)"
                    />
                  </NFlex>
                </NFlex>

                <NFlex justify="space-between" align="center" style="margin-top: 16px">
                  <NText>{{ $t('extras.clutchAssist') }}</NText>
                  <NSwitch
                    :value="configBool('feat_clutch_assist')"
                    @update:value="emit('setConfig', 'feat_clutch_assist', $event)"
                  />
                </NFlex>
                <template v-if="configBool('feat_clutch_assist')">
                  <NText depth="3" style="font-size: 11px; display: block; margin: 4px 0 12px">
                    {{ $t('extras.gamepadClutchBtnHint') }}
                  </NText>
                  <NFlex justify="space-between" align="center" :size="8">
                    <NText>{{ $t('extras.gamepadClutchBtn') }}</NText>
                    <NSelect
                      :value="configText('gamepad_clutch_btn') || ''"
                      :options="
                        [{label: 'None', value: ''}, ...GAMEPAD_BUTTON_OPTIONS.map((o) => ({ label: o.label, value: o.value }))]
                      "
                      size="small"
                      style="width: 140px"
                      @update:value="emit('setConfig', 'gamepad_clutch_btn', $event)"
                    />
                  </NFlex>
                </template>
              </template>
              <template v-if="(($props.config as any).output_mode || 'keyboard') === 'vjoy'">
                <NText depth="3" style="font-size: 12px; display: block; margin: 12px 0 8px">
                  {{ $t('extras.vjoyHint') }}
                </NText>
                <NFlex vertical :size="12">
                  <NFlex justify="space-between" align="center" :size="8">
                    <NText>{{ $t('extras.vjoyDirectShift') }}</NText>
                    <NSwitch
                      :value="configBool('vjoy_direct_shift')"
                      @update:value="emit('setConfig', 'vjoy_direct_shift', $event)"
                    />
                  </NFlex>
                  <NText depth="3" style="font-size: 11px">
                    {{
                      configBool('vjoy_direct_shift')
                        ? $t('extras.vjoyDirectShiftOn')
                        : $t('extras.vjoyDirectShiftOff')
                    }}
                  </NText>
                  <template v-if="!configBool('vjoy_direct_shift')">
                    <NFlex
                      v-for="g in VJOY_SHIFT_BUTTON_FIELDS"
                      :key="g.key"
                      justify="space-between"
                      align="center"
                      :size="8"
                    >
                      <NText>{{ $t(`extras.${g.i18nKey}`) }}</NText>
                      <NSelect
                        :value="configText(g.key) || g.placeholder"
                        :options="
                          VJOY_BUTTON_OPTIONS.map((o) => ({ label: o.label, value: o.value }))
                        "
                        size="small"
                        style="width: 140px"
                        @update:value="emit('setConfig', g.key, $event)"
                      />
                    </NFlex>
                  </template>
                  <NFlex justify="space-between" align="center" :size="8">
                    <NText>{{ $t('extras.vjoyUseClutch') }}</NText>
                    <NSwitch
                      :value="configBool('vjoy_use_clutch')"
                      @update:value="emit('setConfig', 'vjoy_use_clutch', $event)"
                    />
                  </NFlex>
                  <NFlex
                    v-if="configBool('vjoy_use_clutch')"
                    justify="space-between"
                    align="center"
                    :size="8"
                  >
                    <NText>{{ $t('extras.vjoyClutchKey') }}</NText>
                    <NSelect
                      :value="configText('vjoy_clutch_key') || 'B12'"
                      :options="
                        VJOY_BUTTON_OPTIONS.map((o) => ({ label: o.label, value: o.value }))
                      "
                      size="small"
                      style="width: 140px"
                      @update:value="emit('setConfig', 'vjoy_clutch_key', $event)"
                    />
                  </NFlex>
                </NFlex>
              </template>
              <NFlex :size="8" align="center" style="margin-top: 10px">
                <NButton type="warning" size="small" @click="emit('restartBackend')">
                  {{ $t('extras.saveAndRestart') }}
                </NButton>
                <NText depth="3" style="font-size: 11px; color: #d97706">
                  {{ $t('extras.outputModeRestart') }}
                </NText>
              </NFlex>
            </NCard>

            <NCard
              v-if="(($props.config as any).output_mode || 'keyboard') === 'keyboard'"
              :title="$t('extras.shiftKeys')"
              size="small"
              :bordered="false"
            >
              <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
                {{ $t('extras.shiftKeyHint') }}
              </NText>
              <NFlex vertical :size="10">
                <NFlex
                  v-for="h in SHIFT_KEY_FIELDS"
                  :key="h.key"
                  justify="space-between"
                  align="center"
                  :size="8"
                >
                  <NText>{{ $t(`extras.${h.i18nKey}`) }}</NText>
                  <NInput
                    :value="configText(h.key)"
                    :placeholder="h.placeholder"
                    size="small"
                    style="width: 100px; font-family: ui-monospace, monospace"
                    @update:value="(v) => emit('setConfig', h.key, v.trim().toLowerCase())"
                  />
                </NFlex>

                <NFlex justify="space-between" align="center" style="margin-top: 16px">
                  <NText>{{ $t('extras.clutchAssist') }}</NText>
                  <NSwitch
                    :value="configBool('feat_clutch_assist')"
                    @update:value="emit('setConfig', 'feat_clutch_assist', $event)"
                  />
                </NFlex>
                <template v-if="configBool('feat_clutch_assist')">
                  <NText depth="3" style="font-size: 11px; display: block; margin: 4px 0 12px">
                    {{ $t('extras.clutchAssistHint') }}
                  </NText>
                  <NFlex
                    v-for="h in CLUTCH_ASSIST_FIELDS"
                    :key="h.key"
                    justify="space-between"
                    align="center"
                    :size="8"
                  >
                    <NText>{{ $t(`extras.${h.i18nKey}`) }}</NText>
                    <NInput
                      :value="configText(h.key)"
                      :placeholder="h.placeholder"
                      size="small"
                      style="width: 100px; font-family: ui-monospace, monospace"
                      @update:value="(v) => emit('setConfig', h.key, v.trim().toLowerCase())"
                    />
                  </NFlex>
                  <NFlex vertical :size="14" style="margin-top: 12px">
                    <div v-for="s in CLUTCH_TIMING_SLIDERS" :key="s.key">
                      <NFlex justify="space-between" align="center" style="margin-bottom: 4px">
                        <NText>{{ $t(`extras.${s.i18nKey}`) }}</NText>
                        <NText code style="font-family: ui-monospace, monospace">
                          {{ configValue(s.key) }}ms
                        </NText>
                      </NFlex>
                      <NSlider
                        :value="configValue(s.key)"
                        :min="s.min"
                        :max="s.max"
                        :step="s.step ?? 1"
                        @update:value="(v) => emit('setConfig', s.key, v)"
                      />
                    </div>
                  </NFlex>
                </template>
              </NFlex>
            </NCard>

            <NCard :title="$t('extras.hotkeys')" size="small" :bordered="false">
              <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 8px">
                {{ $t('extras.hotkeyHint') }}
              </NText>
              <NFlex vertical :size="10">
                <NFlex
                  v-for="h in HOTKEY_FIELDS"
                  :key="h.key"
                  justify="space-between"
                  align="center"
                  :size="8"
                >
                  <NText>{{ $t(`extras.${h.i18nKey}`) }}</NText>
                  <NInput
                    :value="configText(h.key)"
                    :placeholder="h.placeholder"
                    size="small"
                    style="width: 100px; font-family: ui-monospace, monospace"
                    @update:value="(v) => emit('setConfig', h.key, v.trim().toLowerCase())"
                  />
                </NFlex>
              </NFlex>
            </NCard>

            <NCard :title="$t('extras.fullTuning')" size="small" :bordered="false">
              <NFlex vertical :size="14">
                <div v-for="s in extrasSliders" :key="s.key">
                  <NFlex justify="space-between" align="center" style="margin-bottom: 4px">
                    <NText>{{ $t(`settings.${s.i18nKey}`) }}</NText>
                    <NText code style="font-family: ui-monospace, monospace">
                      {{ configValue(s.key) }}{{ sliderUnit(s) }}
                    </NText>
                  </NFlex>
                  <NSlider
                    :value="configValue(s.key)"
                    :min="s.min"
                    :max="s.max"
                    :step="s.step ?? 1"
                    @update:value="(v) => emit('setConfig', s.key, v)"
                  />
                </div>
              </NFlex>
            </NCard>
          </NFlex>
        </template>
      </NTabPane>
    </NTabs>
  </div>
</template>
