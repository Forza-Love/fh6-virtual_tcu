"""Versioned per-signature profile persistence and relearning."""

import json

from tests.conftest import CAR_KEY, CAR_KEY_BASE, make_telemetry
from virtual_tcu.config.store import ConfigStore  # noqa: E402
from virtual_tcu.input.interface import OutputInterface  # noqa: E402
from virtual_tcu.logic.tcu import TCULogic  # noqa: E402
from virtual_tcu.storage.profiles import (  # noqa: E402
    PROFILE_SCHEMA_VERSION,
    ProfileStore,
)
from virtual_tcu.telemetry.car_key import storage_key  # noqa: E402
from virtual_tcu.telemetry.logger import TelemetryLogger  # noqa: E402
from virtual_tcu.telemetry.model import Telemetry  # noqa: E402


class _Out(OutputInterface):
    @property
    def key_up(self) -> str:
        return "e"

    @property
    def key_down(self) -> str:
        return "q"

    def is_self_press(self, key: str) -> bool:
        return False

    def shift_to(self, from_gear: int, target_gear: int):
        pass

    def shutdown(self):
        pass


def test_profile_store_legacy_three_part_key(tmp_path):
    prof = ProfileStore(path=str(tmp_path / "prof.json"))
    prof.data["100_5_800"] = {"gear_ratios": {"1": 100.0}, "gear_counts": {"1": 10}}
    prof.save()

    got = prof.get(CAR_KEY)
    assert got is not None
    assert got["gear_ratios"]["1"] == 100.0


def test_profile_store_four_part_storage_key(tmp_path):
    prof = ProfileStore(path=str(tmp_path / "prof.json"))
    prof.set(CAR_KEY, {"gear_ratios": {"1": 90.0}})

    assert storage_key(CAR_KEY) in prof.data
    assert prof.get(CAR_KEY)["gear_ratios"]["1"] == 90.0

    stored = json.loads((tmp_path / "prof.json").read_text())
    assert stored["version"] == PROFILE_SCHEMA_VERSION
    assert storage_key(CAR_KEY) in stored["profiles"]


def test_profile_schema_mismatch_archives_and_relearns(tmp_path):
    path = tmp_path / "prof.json"
    path.write_text(
        json.dumps(
            {
                "version": PROFILE_SCHEMA_VERSION - 1,
                "profiles": {storage_key(CAR_KEY): {"gear_ratios": {"1": 90.0}}},
            }
        )
    )

    prof = ProfileStore(path=path)

    assert prof.data == {}
    assert prof.get(CAR_KEY) is None
    assert json.loads(path.read_text())["version"] == PROFILE_SCHEMA_VERSION
    assert list(tmp_path.glob("prof.json.schema-*.bak"))


def test_signature_change_must_stabilize_before_profile_switch(tmp_path):
    cfg = ConfigStore(path=str(tmp_path / "cfg.json"))
    prof = ProfileStore(path=str(tmp_path / "prof.json"))
    tcu = TCULogic(_Out(), prof, cfg, TelemetryLogger())
    initial = make_telemetry(idle_rpm=75.0)
    initial.profile_tune_id = 0
    tcu._sync_profile_tune_id(initial)
    initial_id = initial.profile_tune_id

    for _ in range(tcu.TUNE_SIGNATURE_STABLE_FRAMES - 1):
        stable = make_telemetry(idle_rpm=800.0)
        stable.profile_tune_id = 0
        tcu._sync_profile_tune_id(stable)
        assert stable.profile_tune_id == initial_id

    stable = make_telemetry(idle_rpm=800.0)
    stable.profile_tune_id = 0
    tcu._sync_profile_tune_id(stable)

    assert stable.profile_tune_id == stable.tune_signature
    assert stable.profile_tune_id != initial_id


def test_learning_is_saved_immediately_and_remains_learned_offline(tmp_path):
    cfg = ConfigStore(path=str(tmp_path / "cfg.json"))
    prof = ProfileStore(path=str(tmp_path / "prof.json"))
    tcu = TCULogic(_Out(), prof, cfg, TelemetryLogger())
    tcu._current_car_key = CAR_KEY
    tcu._tune_id_by_base[CAR_KEY_BASE] = CAR_KEY[3]

    first = make_telemetry(
        is_race_on=1,
        gear=1,
        speed_ms=10.0,
        current_rpm=4000.0,
        torque_nm=300.0,
        power_w=120_000.0,
    )
    second = make_telemetry(
        is_race_on=1,
        gear=2,
        speed_ms=20.0,
        current_rpm=4000.0,
        torque_nm=300.0,
        power_w=120_000.0,
    )

    tcu.process(first)
    assert prof.get(CAR_KEY) is None
    tcu.process(second)

    saved = prof.get(CAR_KEY)
    assert saved is not None
    assert saved["tune_signature"] == CAR_KEY[3]
    assert prof.is_learned(CAR_KEY)
    assert tcu.snapshot(None)["calibrated"] is True
    assert tcu.snapshot(Telemetry())["calibrated"] is True
    assert not (tmp_path / "prof.json.tmp").exists()

    reloaded_prof = ProfileStore(path=str(tmp_path / "prof.json"))
    reloaded_tcu = TCULogic(_Out(), reloaded_prof, cfg, TelemetryLogger())
    assert reloaded_tcu.snapshot(Telemetry())["calibrated"] is True

    ok, key = tcu.relearn_current_profile()
    assert ok is True
    assert key == storage_key(CAR_KEY)
    assert prof.get(CAR_KEY) is None
    assert tcu.snapshot(None)["calibrated"] is False


def test_ratio_drift_splits_tune_slot(tmp_path, monkeypatch):
    import virtual_tcu.logic.tcu as tcu_mod

    clock = {"now": 1000.0}
    monkeypatch.setattr(tcu_mod.time, "time", lambda: clock["now"])

    cfg = ConfigStore(path=str(tmp_path / "cfg.json"))
    prof = ProfileStore(path=str(tmp_path / "prof.json"))
    tcu = TCULogic(_Out(), prof, cfg, TelemetryLogger())
    tcu._current_car_key = CAR_KEY
    tcu._profile_baseline_gear1[CAR_KEY] = 100.0
    tcu._calibrator.load(
        CAR_KEY,
        {"ratios": {1: 150.0, 2: 80.0}, "counts": {1: 50, 2: 50}},
    )

    td = make_telemetry(gear=1, speed_ms=30.0, current_rpm=4500.0)
    td.profile_tune_id = CAR_KEY[3]
    tcu._tune_id_by_base[CAR_KEY_BASE] = CAR_KEY[3]

    tcu._check_tune_ratio_drift(td)

    new_id = tcu._tune_id_by_base[CAR_KEY_BASE]
    assert new_id == CAR_KEY[3]
    assert tcu._current_car_key is not None
    assert tcu._current_car_key[3] == new_id
    assert tcu._profile_baseline_gear1.get(tcu._current_car_key) is None
    assert tcu._calibrator.get_ratios(CAR_KEY) == {}
