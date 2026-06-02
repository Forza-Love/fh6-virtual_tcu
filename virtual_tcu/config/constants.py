class Cfg:
    UDP_IP = "0.0.0.0"
    UDP_PORT = 5555
    WEB_HOST = "127.0.0.1"
    WEB_PORT = 8765
    CONFIG_FILE = "tcu_config.json"
    PROFILES_FILE = "tcu_profiles.json"
    LOG_DIR = "logs"
    KEY_HOLD_S = 0.04
    SHIFT_COOLDOWN_MS = 350
    POST_BRAKE_GRACE_MS = 600
    LOW_GEAR_LOCK_MS = 800
    ANTI_STALL_RPM = 1100
    MIN_SPEED_KMH = 12.0
    OVER_REV_LIMIT = 1.02
    IMPACT_DECEL_KMH = 25.0  # single-frame speed collapse this large = a crash/impact
    REVERSE_HOLD_MS = 700
    REVERSE_EXIT_MS = 500
    BRAKE_SPIKE_DELTA = 0.30
    LOG_MAX_MB = 10
    LOG_FILE_PREFIX = "tcu_replay"


DEFAULTS = {
    "comfort_up_idle": 40,
    "comfort_up_mid": 58,
    "comfort_up_wot": 82,
    "dynamic_up_idle": 42,
    "dynamic_up_mid": 58,
    "dynamic_up_wot": 82,
    "race_up_idle": 70,
    "race_up_mid": 80,
    "race_up_wot": 94,
    "race_power_thr": 68,
    "race_power_floor": 60,
    "race_coast_rpm": 30,
    "drift_up": 92,
    "drift_down": 65,
    "offroad_up_idle": 35,
    "offroad_up_mid": 72,
    "offroad_up_wot": 90,
    "offroad_down_rpm": 55,
    "offroad_coast_rpm": 32,
    "brake_thr": 35,
    "kickdown_pedal": 78,
    "kickdown_rpm": 50,
    "coast_down_rpm": 28,
    "launch_rpm": 4500,
    "cornering_yaw": 22,
    "feat_cornering_lock": True,
    "feat_launch_control": True,
    "feat_brake_curve": True,
    "feat_drivetrain_aware": True,
    "feat_per_car_profiles": True,
    "feat_shift_advisor": True,
    "feat_reverse_hold": True,
    "feat_sound_beep": False,
    "feat_discord_rpc": False,
    "feat_power_curve": True,
    "feat_engine_brake": True,
    "feat_turbo_compensate": True,
    "feat_airtime_lock": True,
    "feat_landing_recovery": True,
    "feat_transient_lock": True,
    "feat_drive_style": True,
    "hotkey_cycle_mode": "f9",
    "hotkey_toggle_log": "f8",
    "vjoy_direct_shift": True,
    "vjoy_use_clutch": False,
    "vjoy_shift_key_up": "B13",
    "vjoy_shift_key_down": "B14",
    "vjoy_clutch_key": "B12",
    "shift_key_up": "e",
    "shift_key_down": "q",
    "output_mode": "keyboard",
    "gamepad_shift_up": "B",
    "gamepad_shift_down": "X",
    "gamepad_preserve_brake": True,
    # Clutch assist (keyboard / gamepad only; vjoy uses vjoy_use_clutch)
    "feat_clutch_assist": False,
    "clutch_key": "shift",          # keyboard clutch key (FH6 = shift)
    "clutch_pre_ms": 20,            # ms between clutch press and shift key press
    "clutch_overlap_ms": 55,        # ms shift key is held while clutch is down
    "clutch_release_ms": 25,        # ms between shift key release and clutch release
    "gamepad_clutch_btn": "",       # gamepad clutch button name (empty = disabled)
    "current_mode": "COMFORT",
    "web_host": "127.0.0.1",
    "web_port": 8765,
    "udp_port": 5555,
}
