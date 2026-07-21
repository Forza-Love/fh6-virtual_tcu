import type { DriveMode } from '@virtual-tcu/shared/types/ws'
import type { ConfigMap } from '@/types/ws'
import { useTcuStore } from '@virtual-tcu/shared/composables/useTcuStore'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

export function useDashboardApp() {
  const { t } = useI18n()
  const store = useTcuStore()

  const isFullUi = computed(() => store.uiMode.value === 'full')

  const mainGridClass = computed(() =>
    isFullUi.value
      ? 'bg-tcu-border grid min-h-0 grid-cols-[260px_1fr_380px] gap-px max-[1200px]:grid-cols-1'
      : 'bg-tcu-border grid min-h-0 grid-cols-[260px_1fr_300px] gap-px max-[1100px]:grid-cols-1',
  )

  function onSetConfig(key: string, value: string | number | boolean) {
    store.setConfig(key, value)
  }

  function onSaveNetworkAndRestart(
    host: string,
    webPort: number,
    udpPort: number,
    udpHubEnabled: boolean,
    udpHubTargets: string,
  ) {
    store.saveNetworkAndRestart(host, webPort, udpPort, udpHubEnabled, udpHubTargets)
  }

  function onExportProfile() {
    store.exportProfile()
  }

  function onOpenImport() {
    store.openImportProfile(t('modal.importTitle'))
  }

  function onRelearnProfile() {
    store.relearnProfile()
  }

  return {
    store,
    isFullUi,
    mainGridClass,
    mode: store.mode,
    connected: store.connected,
    live: store.live,
    shiftCount: store.shiftCount,
    packetsTotal: store.packetsTotal,
    telemetry: store.telemetry,
    logStatus: store.logStatus,
    shiftHistory: store.shiftHistory,
    sessionStats: store.sessionStats,
    watchdogStuck: store.watchdogStuck,
    systemLogs: store.systemLogs,
    telemetryLogs: store.telemetryLogs,
    config: store.config as ConfigMap,
    modal: store.modal,
    onSetMode: (mode: string) => store.setMode(mode as DriveMode),
    onRelearnProfile,
    onLogStart: (mode: string) =>
      store.logStart(mode as 'events' | 'all', String(store.config.log_output_format ?? 'bin.gz')),
    onSetConfig,
    onSaveNetworkAndRestart,
    onResetConfig: store.resetConfig,
    onRestartBackend: store.restartBackend,
    onLogStop: (saveAs?: 'file' | 'fusion_snapshot') => store.logStop(saveAs),
    onTriggerFusionSnapshot: () => store.triggerFusionSnapshot('manual_dump'),
    onExportProfile,
    onOpenImport,
    onCloseModal: store.closeModal,
    onConfirmModal: store.confirmModal,
    onModalText: (text: string) => {
      store.modal.text = text
    },
  }
}
