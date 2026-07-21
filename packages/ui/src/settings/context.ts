import type { FeatureToggle, SliderDef } from '@virtual-tcu/shared/config/settings'
import type { InjectionKey, Ref } from 'vue'

export interface StatsRows {
  duration: string
  total: number
  upshifts: number
  downshifts: number
  kickdowns: number
  brakeDowns: number
  predictives: number
  launches: number
  peakRpm: number
  peakSpeed: number
  peakGLat: string
  peakGLon: string
  peakPower: number
  avgThr: number
  cars: number
  calib: boolean | undefined
  powerLearned: boolean | undefined
}

export interface ShiftHistoryItem {
  action: string
  gear: number
  reason: string
  rule: string
  ts: number
  rpm_pct: number
  throttle: number
  brake: number
}

export interface SettingsContext {
  t: (key: string, params?: Record<string, unknown>) => string
  locale: Ref<string>
  store: {
    connected: Ref<boolean>
    live: Ref<boolean>
    mode: Ref<string>
    config: Record<string, unknown>
    telemetry: Ref<Record<string, unknown> | null>
    sessionStats: Ref<Record<string, unknown> | null>
    shiftHistory: Ref<Array<Record<string, unknown>>>
    logStatus: Ref<{
      recording: boolean
      mode: string
      packets: number
      size_kb: number
      file?: string | null
      format?: string
    } | null>
    packetsTotal: Ref<number>
    systemLogs: Ref<Array<{ time: number; level: string; msg: string }>>
    telemetryLogs: Ref<Array<{ time: number; reason: string; filename: string }>>
    webUrls: Ref<{ local?: string; lan?: string; udp_port?: number } | null>
    effectiveOutputMode: Ref<'keyboard' | 'vjoy' | null>
    modal: { open: boolean; title: string; text: string; readOnly: boolean; mode: string }
    setMode: (id: string) => void
    setConfig: (key: string, value: unknown) => void
    saveNetworkAndRestart: (
      host: string,
      webPort: number,
      udpPort: number,
      udpHubEnabled: boolean,
      udpHubTargets: string,
    ) => void
    resetConfig: () => void
    relearnProfile: () => void
    send: (msg: Record<string, unknown>) => void
    closeModal: () => void
    confirmModal: () => void
    openModal: (mode: string, title: string, text: string) => void
  }
  driveModes: Array<{ id: string; i18nKey: string }>
  featureToggles: FeatureToggle[]
  hotkeyFields: Array<{ key: string; i18nKey: string; placeholder: string }>
  shiftKeyFields: Array<{ key: string; i18nKey: string; placeholder: string }>
  outputModeOptions: ReadonlyArray<{ value: string; i18nKey: string }>
  logOutputFormatOptions: ReadonlyArray<{ value: string; i18nKey: string }>
  settingsSliders: Ref<SliderDef[]>
  advancedSliders: Ref<SliderDef[]>
  statusLabel: Ref<{ text: string; kind: 'success' | 'warning' | 'error' }>
  statsRows: Ref<StatsRows | null>
  historyItems: Ref<ShiftHistoryItem[]>
  dashboardUrl: Ref<string>
  lanUrl: Ref<string | null>
  udpPort: Ref<number>
  configNumber: (key: string) => number
  configBool: (key: string) => boolean
  configText: (key: string) => string
  sliderUnit: (s: SliderDef) => string
  networkDraftHost: Ref<string>
  networkDraftWebPort: Ref<string>
  networkDraftUdpPort: Ref<string>
  networkDraftUdpHubEnabled: Ref<boolean>
  networkDraftUdpHubTargetTags: Ref<string[]>
  networkUdpHubTagError: Ref<string>
  networkDirty: Ref<boolean>
  networkApplyError: Ref<string>
  networkApplyOk: Ref<boolean>
  networkApplying: Ref<boolean>
  allowsNetworkBindHostInput: (value: string) => boolean
  allowsNetworkPortInput: (value: string) => boolean
  allowsNetworkUdpHubTargetInput: (value: string) => boolean
  setNetworkUdpHubEnabled: (value: boolean) => void
  setNetworkUdpHubTargetTags: (value: unknown) => void
  onNetworkUdpHubTagCreate: (label: string) => string | false
  applyNetworkSettings: () => void
  onLogStart: (mode: 'events' | 'all') => void
  onLogStop: (saveAs?: 'file' | 'fusion_snapshot') => void
  onTriggerFusionSnapshot: () => void
  onExportProfile: () => void
  onOpenImport: () => void
  openDashboard: () => void
  restartBackend: () => void
  toggleHud: () => void
  openGithub: () => void
  updater: {
    state: Ref<{ kind: string; version?: string; percent?: number; message?: string }>
    currentVersion: Ref<string>
    showUpdateModal: Ref<boolean>
    check: () => void
    download: () => void
    dismissModal: () => void
    openReleasePage: () => void
    install: () => void
  }
}

export const settingsContextKey: InjectionKey<SettingsContext> = Symbol('settings-context')
