import type { LogStatus, SessionStats, ShiftHistoryItem, TelemetrySnapshot } from './telemetry'

export type DriveMode = 'COMFORT' | 'RACE' | 'DRIFT' | 'OFFROAD' | 'MANUAL'

export type ConfigMap = Record<string, string | number | boolean>

export interface WebUrls {
  bind_host: string
  port: number
  local: string
  lan?: string
  udp_port?: number
}

export type TcuUiMode = 'full' | 'view_only'

export interface InitPayload {
  mode: DriveMode
  live: boolean
  shift_count: number
  packets_total: number
  config: ConfigMap
  defaults: ConfigMap
  log_status: LogStatus
  system_logs?: Omit<SystemLog, 'time'>[]
  web_urls?: WebUrls
  effective_output_mode?: 'keyboard' | 'vjoy'
  /** `view_only` when spawned with --backend-only (Electron); `full` for standalone backend. */
  ui_mode?: TcuUiMode
}

export interface StatePayload {
  mode?: DriveMode
  live?: boolean
  shift_count?: number
  packets_total?: number
}

export type WsOutbound =
  | { type: 'set_mode'; mode: string }
  | { type: 'set_config'; key: string; value: string | number | boolean }
  | { type: 'set_web_bind'; host: string; port: number }
  | { type: 'set_network'; web_host: string; web_port: number; udp_port: number }
  | {
      type: 'save_network_and_restart'
      web_host: string
      web_port: number
      udp_port: number
      udp_hub_enabled: boolean
      udp_hub_targets: string
    }
  | { type: 'reset_config' }
  | { type: 'relearn_profile' }
  | { type: 'log_start'; mode: string; format?: string }
  | { type: 'log_stop'; save_as?: 'file' | 'fusion_snapshot'; reason?: string }
  | { type: 'trigger_fusion_snapshot'; reason?: string }
  | { type: 'request_graph' }
  | { type: 'export_profile' }
  | { type: 'import_profile'; data: unknown }
  | { type: 'restart_backend' }

export type WsInbound =
  | { type: 'init'; data: InitPayload }
  | { type: 'telemetry'; data: TelemetrySnapshot }
  | { type: 'state'; data: StatePayload }
  | { type: 'config_reset'; data: ConfigMap }
  | { type: 'log_status'; data: LogStatus; last_file?: string }
  | { type: 'log_conversion'; ok: boolean; format: string; files?: string[]; error?: string }
  | { type: 'profile_export'; data: unknown }
  | { type: 'profile_imported'; ok: boolean; data?: ConfigMap; error?: string }
  | { type: 'profile_relearned'; ok: boolean; profile_key?: string | null }
  | { type: 'graph_data'; data: unknown }
  | { type: 'network_changed'; ok?: boolean; error?: string; data: WebUrls }
  | { type: 'web_bind_changed'; ok?: boolean; error?: string; data: WebUrls }
  | { type: 'config_update'; data: Partial<ConfigMap> }
  | { type: 'system_log'; level: string; msg: string }
  | { type: 'fusion_snapshot'; reason: string; filename: string; chart_filename?: string }

export interface SystemLog {
  time: number
  level: string
  msg: string
}

export interface TelemetryLog {
  time: number
  reason: string
  filename: string
}

export interface TcuUiState {
  connected: boolean
  live: boolean
  mode: DriveMode
  shiftCount: number
  packetsTotal: number
  config: ConfigMap
  defaults: ConfigMap
  telemetry: TelemetrySnapshot | null
  logStatus: LogStatus | null
  shiftHistory: ShiftHistoryItem[]
  sessionStats: SessionStats | null
  watchdogStuck: boolean
  systemLogs: SystemLog[]
  telemetryLogs: TelemetryLog[]
}
