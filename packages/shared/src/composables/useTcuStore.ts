import type { LogStatus, ShiftHistoryItem, TelemetrySnapshot } from '../types/telemetry'
import type {
  ConfigMap,
  DriveMode,
  SystemLog,
  TcuUiMode,
  TelemetryLog,
  WebUrls,
  WsInbound,
} from '../types/ws'
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { TcuWsClient } from '../api/ws-client'

const client = new TcuWsClient()

interface BackendInfo {
  wsUrl?: string
}

async function resolveElectronWsUrl(): Promise<string | null> {
  const w = window as {
    isElectron?: boolean
    tcu?: { getBackendInfo: () => Promise<BackendInfo> }
  }
  if (!w.isElectron || !w.tcu?.getBackendInfo) return null
  try {
    const info = await w.tcu.getBackendInfo()
    return info.wsUrl ?? null
  } catch {
    return null
  }
}

function wsUrlFromWebUrls(info: WebUrls): string {
  const host = info.bind_host === '0.0.0.0' ? '127.0.0.1' : info.bind_host
  return `ws://${host}:${info.port}/ws`
}

export function useTcuStore() {
  const connected = ref(false)
  const live = ref(false)
  const mode = ref<DriveMode>('COMFORT')
  const shiftCount = ref(0)
  const packetsTotal = ref(0)
  const config = reactive<ConfigMap>({})
  const telemetry = ref<TelemetrySnapshot | null>(null)
  const logStatus = ref<LogStatus | null>(null)
  const shiftHistory = ref<ShiftHistoryItem[]>([])
  const watchdogStuck = ref(false)
  const webUrls = ref<WebUrls | null>(null)
  const webBindStatus = ref<{ ok: boolean; error?: string } | null>(null)
  const effectiveOutputMode = ref<'keyboard' | 'vjoy' | null>(null)
  const uiMode = ref<TcuUiMode>('view_only')
  const systemLogs = ref<SystemLog[]>([])
  const telemetryLogs = ref<TelemetryLog[]>([])

  const modal = reactive({
    open: false,
    mode: 'export' as 'export' | 'import',
    title: '',
    text: '',
    readOnly: false,
  })

  function handle(msg: WsInbound) {
    switch (msg.type) {
      case 'init':
        Object.assign(config, msg.data.config)
        mode.value = msg.data.mode
        live.value = msg.data.live
        shiftCount.value = msg.data.shift_count
        packetsTotal.value = msg.data.packets_total
        logStatus.value = msg.data.log_status
        if (msg.data.system_logs) {
          systemLogs.value = msg.data.system_logs.map((log) => ({
            time: Date.now(),
            level: log.level,
            msg: log.msg,
          }))
        }
        webUrls.value = msg.data.web_urls ?? null
        effectiveOutputMode.value = msg.data.effective_output_mode ?? null
        uiMode.value = msg.data.ui_mode === 'full' ? 'full' : 'view_only'
        connected.value = true
        break
      case 'telemetry':
        telemetry.value = msg.data
        if (msg.data.shift_history) shiftHistory.value = msg.data.shift_history
        if (msg.data.log_status) logStatus.value = msg.data.log_status
        watchdogStuck.value = !!msg.data.watchdog_stuck
        break
      case 'state':
        if (msg.data.mode) mode.value = msg.data.mode
        if (msg.data.live !== undefined) live.value = msg.data.live
        if (msg.data.shift_count !== undefined) shiftCount.value = msg.data.shift_count
        if (msg.data.packets_total !== undefined) packetsTotal.value = msg.data.packets_total
        break
      case 'config_reset':
        Object.keys(config).forEach((k) => delete config[k])
        Object.assign(config, msg.data)
        break
      case 'config_update':
        Object.assign(config, msg.data)
        break
      case 'log_status':
        logStatus.value = msg.data
        break
      case 'log_conversion':
        if (msg.ok) {
          systemLogs.value.push({
            time: Date.now(),
            level: 'INFO',
            msg: `Log converted to ${msg.format}: ${msg.files?.join(', ')}`,
          })
        } else {
          systemLogs.value.push({
            time: Date.now(),
            level: 'ERROR',
            msg: `Log conversion to ${msg.format} failed: ${msg.error}`,
          })
        }
        if (systemLogs.value.length > 300) systemLogs.value.shift()
        break
      case 'profile_export':
        openModal('export', '', JSON.stringify(msg.data, null, 2))
        break
      case 'profile_imported':
        if (msg.ok && msg.data) {
          Object.keys(config).forEach((k) => delete config[k])
          Object.assign(config, msg.data)
        }
        break
      case 'profile_relearned':
        if (msg.ok && telemetry.value) {
          telemetry.value.calibrated = false
          telemetry.value.power_curve_learned = false
        }
        break
      case 'web_bind_changed':
      case 'network_changed':
        webBindStatus.value = { ok: msg.ok !== false, error: msg.error }
        webUrls.value = msg.data
        if (msg.ok !== false) {
          config.web_host = msg.data.bind_host
          config.web_port = msg.data.port
          if (msg.data.udp_port !== undefined) config.udp_port = msg.data.udp_port
          client.setUrl(wsUrlFromWebUrls(msg.data))
        }
        break
      case 'system_log':
        systemLogs.value.push({ time: Date.now(), level: msg.level, msg: msg.msg })
        if (systemLogs.value.length > 300) systemLogs.value.shift()
        break
      case 'fusion_snapshot':
        telemetryLogs.value.unshift({
          time: Date.now(),
          reason: msg.reason,
          filename: msg.filename,
        })
        if (telemetryLogs.value.length > 50) telemetryLogs.value.pop()
        break
    }
  }

  function send(msg: Parameters<TcuWsClient['send']>[0]) {
    client.send(msg)
  }

  function setMode(m: DriveMode) {
    send({ type: 'set_mode', mode: m })
  }

  function setConfig(key: string, value: string | number | boolean) {
    if (key === 'web_host' || key === 'web_port' || key === 'udp_port') return
    send({ type: 'set_config', key, value })
    config[key] = value
  }

  function applyNetwork(host: string, webPort: number, udpPort: number) {
    send({ type: 'set_network', web_host: host, web_port: webPort, udp_port: udpPort })
  }

  function saveNetworkAndRestart(
    host: string,
    webPort: number,
    udpPort: number,
    udpHubEnabled: boolean,
    udpHubTargets: string,
  ) {
    send({
      type: 'save_network_and_restart',
      web_host: host,
      web_port: webPort,
      udp_port: udpPort,
      udp_hub_enabled: udpHubEnabled,
      udp_hub_targets: udpHubTargets,
    })
  }

  function applyWebBind(host: string, port: number) {
    applyNetwork(host, port, Number(config.udp_port ?? 5555))
  }

  function resetConfig() {
    send({ type: 'reset_config' })
  }

  function relearnProfile() {
    send({ type: 'relearn_profile' })
  }

  function restartBackend() {
    send({ type: 'restart_backend' })
  }

  function logStart(mode: 'events' | 'all', format?: string) {
    send({ type: 'log_start', mode, format })
  }

  function logStop(saveAs: 'file' | 'fusion_snapshot' = 'file') {
    send({ type: 'log_stop', save_as: saveAs, reason: 'manual_dump' })
  }

  function triggerFusionSnapshot(reason = 'manual_dump') {
    send({ type: 'trigger_fusion_snapshot', reason })
  }

  function exportProfile() {
    send({ type: 'export_profile' })
  }

  function openImportProfile(title: string) {
    openModal('import', title, '')
  }

  function openModal(m: 'export' | 'import', title: string, content: string) {
    modal.mode = m
    modal.title = title
    modal.text = content
    modal.readOnly = m === 'export'
    modal.open = true
  }

  function closeModal() {
    modal.open = false
  }

  async function confirmModal() {
    if (modal.mode === 'export') {
      try {
        await navigator.clipboard.writeText(modal.text)
        modal.title = 'copied'
        setTimeout(closeModal, 800)
      } catch {
        /* user can copy manually */
      }
    } else {
      try {
        const parsed = JSON.parse(modal.text)
        send({ type: 'import_profile', data: parsed })
        closeModal()
      } catch (e) {
        console.warn(`Invalid JSON: ${(e as Error).message}`)
      }
    }
  }

  const sessionStats = computed(() => telemetry.value?.session_stats ?? null)

  const connectionLabel = computed(() => {
    if (!connected.value) return 'disconnected'
    return live.value ? 'live' : 'standby'
  })

  let cleanupBackendReady: (() => void) | null = null
  let cleanupBackendExit: (() => void) | null = null

  async function connectToBackend(wsUrl?: string) {
    const url = wsUrl ?? (await resolveElectronWsUrl()) ?? TcuWsClient.defaultUrl()
    client.setUrl(url)
    client.connect()
  }

  onMounted(async () => {
    client.onMessage(handle)
    client.onConnectionChange((open) => {
      if (!open) {
        connected.value = false
        live.value = false
      }
    })
    await connectToBackend()

    const tcu = (
      window as {
        tcu?: {
          onBackendReady?: (cb: (info: BackendInfo) => void) => () => void
          onBackendExit?: (cb: (info: unknown) => void) => () => void
        }
      }
    ).tcu

    if (tcu?.onBackendReady) {
      cleanupBackendReady = tcu.onBackendReady((info) => {
        if (info.wsUrl) void connectToBackend(info.wsUrl)
      })
    }
    if (tcu?.onBackendExit) {
      cleanupBackendExit = tcu.onBackendExit(() => {
        connected.value = false
        live.value = false
      })
    }
  })

  onUnmounted(() => {
    cleanupBackendReady?.()
    cleanupBackendExit?.()
    client.disconnect()
  })

  return {
    connected,
    live,
    mode,
    shiftCount,
    packetsTotal,
    config,
    telemetry,
    logStatus,
    shiftHistory,
    watchdogStuck,
    webUrls,
    webBindStatus,
    effectiveOutputMode,
    uiMode,
    sessionStats,
    connectionLabel,
    systemLogs,
    telemetryLogs,
    modal,
    send,
    setMode,
    setConfig,
    applyWebBind,
    applyNetwork,
    saveNetworkAndRestart,
    resetConfig,
    relearnProfile,
    restartBackend,
    logStart,
    logStop,
    triggerFusionSnapshot,
    exportProfile,
    openImportProfile,
    openModal,
    closeModal,
    confirmModal,
  }
}
