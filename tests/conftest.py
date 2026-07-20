"""Shared test fixtures and helpers for the Virtual TCU test suite.

These tests run on Linux/CI without the game: telemetry is constructed by
hand (or replayed from a recorded log) and fed straight into TCULogic with
a fake output that records shift calls instead of injecting keys. Wall-clock
time is replaced by a controllable clock so shift cooldowns/locks are
deterministic.
"""

# ruff: noqa: E402 -- keyboard must be mocked before importing TCULogic.

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Importing the real ``keyboard`` package can touch platform input services at
# collection time. Tests only need its listener surface, so install the mock
# before importing TCULogic (which imports ``keyboard`` at module scope).
sys.modules.setdefault("keyboard", MagicMock())

import virtual_tcu.logic.tcu as tcu_module
from virtual_tcu.config.store import ConfigStore
from virtual_tcu.input.interface import OutputInterface
from virtual_tcu.logic.tcu import TCULogic
from virtual_tcu.storage.profiles import ProfileStore
from virtual_tcu.telemetry.logger import TelemetryLogger
from virtual_tcu.telemetry.model import Telemetry

CAR_KEY_BASE = (100, 5, 800)


def _default_car_key() -> tuple[int, int, int, int]:
    probe = Telemetry()
    probe.engine_max_rpm = 8000.0
    probe.car_ordinal = CAR_KEY_BASE[0]
    probe.car_class = CAR_KEY_BASE[1]
    probe.pi = CAR_KEY_BASE[2]
    return probe.car_key


CAR_KEY = _default_car_key()


class FakeOutput(OutputInterface):
    """Records shift commands instead of injecting keys."""

    def __init__(self):
        self.shifts: list[tuple[str, float]] = []
        self.now = 0.0

    @property
    def key_up(self) -> str:
        return "e"

    @property
    def key_down(self) -> str:
        return "q"

    def is_self_press(self, key: str) -> bool:
        return False

    def shift_to(self, from_gear: int, target_gear: int):
        if target_gear > from_gear:
            self.shifts.append(("UP", self.now))
        elif target_gear <= from_gear - 2:
            self.shifts.append(("DOWN2", self.now))
        else:
            self.shifts.append(("DOWN", self.now))

    def shutdown(self):
        pass


class Clock:
    """Controllable replacement for time.time() inside the TCU module."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make_telemetry(**kw) -> Telemetry:
    """A plausible mid-drive telemetry frame; override fields via kwargs."""
    t = Telemetry()
    t.engine_max_rpm = 8000.0
    t.car_ordinal = CAR_KEY_BASE[0]
    t.car_class = CAR_KEY_BASE[1]
    t.pi = CAR_KEY_BASE[2]
    t.accel_y = 0.0  # grounded by default (see fh6-accel-y-airborne-signal)
    for k, v in kw.items():
        setattr(t, k, v)
    if not t.profile_tune_id:
        t.profile_tune_id = t.tune_signature
    return t


@pytest.fixture
def clock(monkeypatch) -> Clock:
    c = Clock()
    monkeypatch.setattr(tcu_module.time, "time", c)
    return c


@pytest.fixture
def out() -> FakeOutput:
    return FakeOutput()


@pytest.fixture
def make_logic(out, clock, tmp_path):
    """Factory: build a TCULogic in a given mode with isolated config/profiles.

    Pins _current_car_key so the new-car wipe in _process_internal doesn't
    drop seeded gear ratios.
    """

    def _make(mode: str = "RACE", seed_ratios: bool = True) -> TCULogic:
        cfg = ConfigStore(path=str(tmp_path / "cfg.json"))
        prof = ProfileStore(path=str(tmp_path / "prof.json"))
        tcu = TCULogic(out, prof, cfg, TelemetryLogger())
        tcu.set_mode(mode)
        tcu._current_car_key = CAR_KEY
        if seed_ratios:
            ratios = {1: 120.0, 2: 80.0, 3: 58.0, 4: 44.0, 5: 35.0, 6: 29.0}
            tcu._calibrator.load(CAR_KEY, {"ratios": ratios, "counts": {g: 50 for g in ratios}})
        return tcu

    return _make


def feed(
    tcu: TCULogic, out: FakeOutput, clock: Clock, td: Telemetry, frames: int, dt: float = 0.016
):
    """Process *td* for *frames* steps, advancing the clock by *dt* each step."""
    for _ in range(frames):
        clock.now += dt
        out.now = clock.now
        tcu.process(td)


REPO_ROOT = Path(__file__).resolve().parent.parent
