"""Per-tune vehicle keys for profile storage and learning."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from virtual_tcu.telemetry.model import Telemetry

# (car_ordinal, car_class, pi, tune_id)
CarKey = tuple[int, int, int, int]
CarKeyBase = tuple[int, int, int]

# Relative change in learned vs saved gear-1 ratio → invalidate and relearn the
# current signature slot. Gearing is not part of the engine fingerprint.
RATIO_DRIFT_THRESHOLD = 0.22
MIN_GEAR1_SAMPLES_FOR_DRIFT = 30


def car_key_base(td: Telemetry) -> CarKeyBase:
    return (td.car_ordinal, td.car_class, td.pi)


def compute_tune_signature(td: Telemetry) -> int:
    """Stable fingerprint from engine/drivetrain fields (not gearing)."""
    max_rpm = int(td.engine_max_rpm) if td.engine_max_rpm > 0 else 0
    idle = int(td.idle_rpm) if td.idle_rpm > 0 else 0
    return (max_rpm << 16) | (idle << 6) | ((td.drivetrain & 0x3) << 3) | (td.num_cylinders & 0x7)


def make_car_key(base: CarKeyBase, tune_id: int) -> CarKey:
    return (base[0], base[1], base[2], tune_id)


def storage_key(car_key: tuple[int, ...]) -> str:
    if len(car_key) == 3:
        return f"{car_key[0]}_{car_key[1]}_{car_key[2]}"
    if len(car_key) == 4:
        return f"{car_key[0]}_{car_key[1]}_{car_key[2]}_{car_key[3]}"
    raise ValueError(f"invalid car_key length: {len(car_key)}")
