<script setup lang="ts">
  import TcuConfigProvider from '@virtual-tcu/ui/components/TcuConfigProvider.vue'
  import AppFooter from './components/AppFooter.vue'
  import AppHeader from './components/AppHeader.vue'
  import DashboardPanel from './components/DashboardPanel.vue'
  import ModeSidebar from './components/ModeSidebar.vue'
  import ProfileModal from './components/ProfileModal.vue'
  import SettingsPanel from './components/SettingsPanel.vue'
  import StatsHistoryPanel from './components/StatsHistoryPanel.vue'
  import { useDashboardApp } from './composables/use-dashboard-app'

  const {
    isFullUi,
    mainGridClass,
    mode,
    connected,
    live,
    shiftCount,
    packetsTotal,
    telemetry,
    logStatus,
    shiftHistory,
    sessionStats,
    watchdogStuck,
    systemLogs,
    telemetryLogs,
    config,
    modal,
    onSetMode,
    onRelearnProfile,
    onSetConfig,
    onSaveNetworkAndRestart,
    onResetConfig,
    onRestartBackend,
    onLogStart,
    onLogStop,
    onTriggerFusionSnapshot,
    onExportProfile,
    onOpenImport,
    onCloseModal,
    onConfirmModal,
    onModalText,
  } = useDashboardApp()
</script>

<template>
  <TcuConfigProvider dark>
    <AppHeader :mode="mode" :connected="connected" :live="live" />
    <main :class="mainGridClass">
      <ModeSidebar
        :mode="mode"
        :shift-count="shiftCount"
        :packets-total="packetsTotal"
        :telemetry="telemetry"
        :interactive="isFullUi"
        @set-mode="onSetMode"
        @relearn="onRelearnProfile"
      />
      <DashboardPanel :live="live" :telemetry="telemetry" />
      <SettingsPanel
        v-if="isFullUi"
        :config="config"
        :telemetry="telemetry"
        :session-stats="sessionStats"
        :shift-history="shiftHistory"
        :watchdog-stuck="watchdogStuck"
        :log-status="logStatus"
        :system-logs="systemLogs"
        :telemetry-logs="telemetryLogs"
        @set-config="onSetConfig"
        @save-network-and-restart="onSaveNetworkAndRestart"
        @reset-config="onResetConfig"
        @restart-backend="onRestartBackend"
        @log-start="onLogStart"
        @log-stop="onLogStop"
        @trigger-fusion-snapshot="onTriggerFusionSnapshot"
        @export-profile="onExportProfile"
        @open-import="onOpenImport"
      />
      <StatsHistoryPanel
        v-else
        :telemetry="telemetry"
        :session-stats="sessionStats"
        :shift-history="shiftHistory"
      />
    </main>
    <AppFooter :view-only="!isFullUi" />
    <ProfileModal
      v-if="isFullUi"
      :open="modal.open"
      :mode="modal.mode"
      :title="modal.title ? $t(`modal.${modal.title}`) : undefined"
      :text="modal.text"
      :read-only="modal.readOnly"
      @close="onCloseModal"
      @confirm="onConfirmModal"
      @update:text="onModalText"
    />
  </TcuConfigProvider>
</template>
