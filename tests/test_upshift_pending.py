"""Upshift must not spam until the game confirms the gear change."""

from pathlib import Path

import virtual_tcu.logic.tcu as tcu_module
from tests.conftest import CAR_KEY, FakeOutput, make_telemetry
from virtual_tcu.config.store import ConfigStore
from virtual_tcu.logic.tcu import TCULogic
from virtual_tcu.storage.profiles import ProfileStore
from virtual_tcu.telemetry.logger import TelemetryLogger
from virtual_tcu.telemetry.parser import parse_fh6_packet
from virtual_tcu.telemetry.replay_reader import iter_replay_records


def test_upshift_pending_blocks_repeat(make_logic, out, clock):
    tcu = make_logic("COMFORT")
    td = make_telemetry(
        gear=2,
        current_rpm=6800,
        engine_max_rpm=8000.0,
        speed_ms=80.0 / 3.6,
        accel_raw=255,
        brake_raw=0,
    )
    # Stay inside the pending window (0.7 s) — soft-cap retry after timeout is
    # covered by test_failed_low_gear_upshift_retries_at_redline.
    for _ in range(40):
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td)
    ups = [s for s in out.shifts if s[0] == "UP"]
    assert len(ups) == 1


def test_failed_high_gear_upshift_backs_off_without_permanent_cap(make_logic, out, clock):
    """One missed ack at 6th is not proof of a 6-speed box: retries continue
    with exponential backoff (no per-frame spam, no permanent lockout)."""
    tcu = make_logic("COMFORT")
    td = make_telemetry(
        gear=6,
        current_rpm=7600,
        engine_max_rpm=8000.0,
        speed_ms=200.0 / 3.6,
        accel_raw=255,
        brake_raw=0,
    )
    for _ in range(300):  # 4.8 s
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td)
    ups = [s for s in out.shifts if s[0] == "UP"]
    # timeout 0.7s + backoff 0.8/1.6/3.2... → a handful of probes, not spam.
    assert 2 <= len(ups) <= 4
    # The cap is soft: still recorded, but with retry state, not permanent.
    assert tcu._upshift_cap_by_key.get(CAR_KEY, 10) <= 6
    assert tcu._upshift_fail_count[CAR_KEY] >= 2


def test_true_top_gear_settles_into_bounded_probing(make_logic, out, clock):
    """A genuine top gear must not receive unbounded repeated commands."""
    tcu = make_logic("COMFORT")
    td = make_telemetry(
        gear=6,
        current_rpm=7600,
        engine_max_rpm=8000.0,
        speed_ms=200.0 / 3.6,
        accel_raw=255,
        brake_raw=0,
    )
    for _ in range(2000):  # 32 s at fuel cut in the true top gear
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td)
    ups = [s for s in out.shifts if s[0] == "UP"]
    # After backoff saturates at UPSHIFT_CAP_MAX_BACKOFF_S (8 s), the steady
    # state is at most ~one probe per 8.7 s.
    assert len(ups) <= 7


def test_ten_speed_recovers_from_one_lost_high_gear_command(make_logic, out, clock):
    """A lost 8→9 command on a 10-speed must not permanently cap 8th."""
    tcu = make_logic("COMFORT")
    td8 = make_telemetry(
        gear=8,
        current_rpm=7600,
        engine_max_rpm=8000.0,
        speed_ms=280.0 / 3.6,
        accel_raw=255,
        brake_raw=0,
    )
    # First command is lost: no ack for well past the pending timeout.
    for _ in range(60):  # ~1 s → timeout fires, soft cap at 8
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td8)
    assert tcu._upshift_cap_by_key[CAR_KEY] == 8

    # Keep demanding power: the retry must fire after backoff.
    for _ in range(120):  # ~1.9 s more
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td8)
    ups = [s for s in out.shifts if s[0] == "UP"]
    assert len(ups) >= 2, "retry after backoff never fired"

    # This time the game acknowledges 9th: all failure state must clear.
    td9 = make_telemetry(
        gear=9,
        current_rpm=7500,
        engine_max_rpm=8000.0,
        speed_ms=300.0 / 3.6,
        accel_raw=255,
        brake_raw=0,
    )
    # Short window: long enough for the 9→10 command, before its own pending
    # timeout would re-cap (the fed telemetry never acknowledges).
    for _ in range(45):
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td9)
    assert tcu._upshift_cap_by_key[CAR_KEY] == 10
    assert CAR_KEY not in tcu._upshift_fail_count
    # And 9→10 must still be commandable.
    ups = [s for s in out.shifts if s[0] == "UP"]
    assert len(ups) >= 3, "9→10 was blocked by stale cap state"


def test_downshift_restarts_cap_retry_backoff(make_logic, out, clock):
    """A downshift invalidates the evidence behind a suspected cap."""
    tcu = make_logic("COMFORT")
    td6 = make_telemetry(
        gear=6,
        current_rpm=7600,
        engine_max_rpm=8000.0,
        speed_ms=200.0 / 3.6,
        accel_raw=255,
        brake_raw=0,
    )
    for _ in range(300):
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td6)
    assert tcu._upshift_fail_count[CAR_KEY] >= 2

    td5 = make_telemetry(
        gear=5,
        current_rpm=6000,
        engine_max_rpm=8000.0,
        speed_ms=180.0 / 3.6,
        accel_raw=128,
        brake_raw=0,
    )
    clock.now += 0.016
    out.now = clock.now
    tcu.process(td5)
    assert CAR_KEY not in tcu._upshift_fail_count


def test_failed_low_gear_upshift_retries_at_redline(make_logic, out, clock):
    tcu = make_logic("COMFORT")
    td = make_telemetry(
        gear=1,
        current_rpm=7600,
        engine_max_rpm=8000.0,
        speed_ms=45.0 / 3.6,
        vel_z=12.0,
        accel_raw=255,
        brake_raw=0,
    )
    for _ in range(250):
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td)
    ups = [s for s in out.shifts if s[0] == "UP"]
    assert len(ups) >= 2
    assert len(ups) <= 6


def test_reverse_exit_does_not_block_launch_upshift(make_logic, out, clock):
    tcu = make_logic("COMFORT")
    td_r = make_telemetry(gear=0, speed_ms=0, accel_raw=0, vel_z=0)
    tcu.process(td_r)

    td = make_telemetry(
        gear=1,
        current_rpm=7500,
        engine_max_rpm=8000.0,
        speed_ms=25.0 / 3.6,
        vel_z=7.0,
        accel_raw=255,
        brake_raw=0,
    )
    for _ in range(80):
        clock.now += 0.016
        out.now = clock.now
        tcu.process(td)
    ups = [s for s in out.shifts if s[0] == "UP"]
    assert len(ups) >= 1


def test_ski_log_no_6_to_7_spam(clock, tmp_path):
    log_path = Path(__file__).resolve().parent.parent / "logs" / "滑雪越野赛事不换挡.gz"
    if not log_path.is_file():
        return

    cfg = ConfigStore(path=str(tmp_path / "cfg.json"))
    prof_path = Path(__file__).resolve().parent.parent / "tcu_profiles.json"
    prof = ProfileStore(path=str(prof_path if prof_path.is_file() else tmp_path / "prof.json"))

    class CountOut(FakeOutput):
        def __init__(self):
            super().__init__()
            self.pairs: list[tuple[int, int]] = []

        def shift_to(self, from_gear: int, target_gear: int):
            self.pairs.append((from_gear, target_gear))
            super().shift_to(from_gear, target_gear)

    out = CountOut()
    tcu = TCULogic(out, prof, cfg, TelemetryLogger())
    tcu.set_mode("COMFORT")
    tcu_module.time.time = clock

    for ms, raw in iter_replay_records(log_path):
        td = parse_fh6_packet(raw)
        if td is None:
            continue
        clock.now = ms / 1000.0
        tcu.process(td, raw)

    six_to_seven = sum(1 for fg, tg in out.pairs if fg == 6 and tg == 7)
    assert six_to_seven <= 2
