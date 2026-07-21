<script setup lang="ts">
  import { EyeOutline, OpenOutline, RefreshOutline } from '@vicons/ionicons5'
  import {
    NButton,
    NCard,
    NDivider,
    NFlex,
    NGrid,
    NGridItem,
    NIcon,
    NTag,
    NText,
    useDialog,
  } from 'naive-ui'
  import { inject } from 'vue'
  import { settingsContextKey } from './context'
  import SettingsHud from './SettingsHud.vue'

  const ctx = inject(settingsContextKey)!
  const { t, store, driveModes, dashboardUrl, lanUrl, udpPort, openDashboard, toggleHud } = ctx
  const dialog = useDialog()

  function modeColor(id: string) {
    return (
      (
        {
          COMFORT: '#2563eb',
          RACE: '#16a34a',
          DRIFT: '#dc2626',
          OFFROAD: '#ea580c',
          MANUAL: '#64748b',
        } as Record<string, string>
      )[id] ?? '#64748b'
    )
  }

  function modeTagText(id: string, i18nKey: string) {
    return `${t(`modes.${i18nKey}.name`)} · ${t(`modes.${i18nKey}.tag`).toUpperCase()}`
  }

  function relearnProfile() {
    dialog.warning({
      title: t('calibration.relearn'),
      content: t('calibration.relearnConfirm'),
      positiveText: t('modal.confirm'),
      negativeText: t('modal.cancel'),
      onPositiveClick: () => store.relearnProfile(),
    })
  }
</script>

<template>
  <NGrid :cols="12" :x-gap="16" :y-gap="16" responsive="screen" item-responsive>
    <NGridItem :span="6">
      <NCard :title="t('modes.title')" size="small" :bordered="false" style="height: 100%">
        <template #header-extra>
          <NText depth="3" style="font-size: 11px">
            {{ t('modes.hotkeyHintBefore') }}<kbd>F9</kbd>
          </NText>
        </template>
        <NGrid :cols="2" :x-gap="8" :y-gap="8">
          <NGridItem v-for="m in driveModes" :key="m.id">
            <NButton
              block
              :type="store.mode.value === m.id ? 'primary' : 'default'"
              :secondary="store.mode.value !== m.id"
              :color="store.mode.value === m.id ? modeColor(m.id) : undefined"
              @click="store.setMode(m.id)"
            >
              {{ modeTagText(m.id, m.i18nKey) }}
            </NButton>
          </NGridItem>
        </NGrid>
      </NCard>
    </NGridItem>

    <NGridItem :span="6">
      <NCard :title="t('electronApp.quickActionsTitle')" size="small" :bordered="false">
        <NText depth="3" style="font-size: 12px">
          {{ t('electronApp.quickActionsHint') }}
        </NText>
        <NFlex :size="8" style="margin-top: 12px">
          <NButton type="primary" block size="large" @click="openDashboard">
            <template #icon>
              <NIcon :component="OpenOutline" />
            </template>
            {{ t('electronApp.openDashboard') }}
          </NButton>
          <NButton block size="large" @click="toggleHud">
            <template #icon>
              <NIcon :component="EyeOutline" />
            </template>
            {{ t('electronApp.toggleHud') }}
          </NButton>
        </NFlex>

        <NDivider style="margin: 16px 0" />

        <div
          style="
            font-size: 11px;
            color: #64748b;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 8px;
          "
        >
          {{ t('electronApp.connectionTitle') }}
        </div>
        <NGrid :cols="2" :x-gap="12" :y-gap="6">
          <NGridItem>
            <NText depth="3">
              {{ t('electronApp.dashboardUrl') }}
            </NText>
          </NGridItem>
          <NGridItem>
            <NText code style="font-family: ui-monospace, monospace; font-size: 12px">
              {{ dashboardUrl }}
            </NText>
          </NGridItem>
          <NGridItem v-if="lanUrl">
            <NText depth="3">
              {{ t('electronApp.lanUrl') }}
            </NText>
          </NGridItem>
          <NGridItem v-if="lanUrl">
            <NText code style="font-family: ui-monospace, monospace; font-size: 12px">
              {{ lanUrl }}
            </NText>
          </NGridItem>
          <NGridItem>
            <NText depth="3">
              {{ t('electronApp.udpPort') }}
            </NText>
          </NGridItem>
          <NGridItem>
            <NText code style="font-family: ui-monospace, monospace; font-size: 12px">
              {{ udpPort }}
            </NText>
          </NGridItem>
          <NGridItem>
            <NText depth="3">
              {{ t('electronApp.telemetryPackets') }}
            </NText>
          </NGridItem>
          <NGridItem>
            <NText code style="font-family: ui-monospace, monospace; font-size: 12px">
              {{ store.packetsTotal.value }}
            </NText>
          </NGridItem>
        </NGrid>
      </NCard>
    </NGridItem>

    <NGridItem :span="12">
      <SettingsHud />
    </NGridItem>

    <NGridItem :span="12">
      <NCard :title="t('calibration.title')" size="small" :bordered="false">
        <NFlex align="center" :size="12">
          <NTag
            :type="store.telemetry.value?.calibrated ? 'success' : 'warning'"
            :bordered="false"
            round
          >
            {{
              store.telemetry.value?.calibrated
                ? t('calibration.calibrated')
                : t('calibration.learning')
            }}
          </NTag>
          <NButton
            size="small"
            type="error"
            ghost
            :disabled="!store.telemetry.value?.calibrated"
            @click="relearnProfile"
          >
            <template #icon>
              <NIcon :component="RefreshOutline" />
            </template>
            {{ t('calibration.relearn') }}
          </NButton>
          <NText depth="3" style="font-size: 12px">
            {{ t('calibration.hint') }}
          </NText>
        </NFlex>
      </NCard>
    </NGridItem>
  </NGrid>
</template>

<style scoped>
  kbd {
    display: inline-block;
    background: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    padding: 1px 6px;
    font-family: ui-monospace, monospace;
    font-size: 11px;
    color: #0f172a;
  }
</style>
