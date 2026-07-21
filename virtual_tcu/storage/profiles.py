import json
from pathlib import Path

from virtual_tcu import paths
from virtual_tcu.telemetry.car_key import storage_key

# This is the persisted learning-data contract, not the application version.
# Increment it only when stored estimator data is no longer safe to reuse.
# Ordinary Virtual TCU releases must keep this value unchanged.
PROFILE_SCHEMA_VERSION = 1


class ProfileStore:
    """Per-car JSON-backed profile storage.

    Profiles are keyed by ``(car_ordinal, car_class, pi, tune_id)`` so different
    tunes of the same car model get separate saved state. Legacy three-part keys
    (no tune_id) are still read for backward compatibility.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else paths.profiles_file()
        self.data: dict[str, dict] = {}
        self._active_key: str | None = None
        self.load()

    def load(self):
        if not self.path.exists():
            self.save()
            return
        try:
            stored = json.loads(self.path.read_text())
        except Exception as exc:
            print(f"[Profiles] load failed, starting fresh: {exc}")
            self._archive_incompatible("corrupt")
            self.data = {}
            self._active_key = None
            self.save()
            return

        version = stored.get("version") if isinstance(stored, dict) else None
        profiles = stored.get("profiles") if isinstance(stored, dict) else None
        if version != PROFILE_SCHEMA_VERSION or not isinstance(profiles, dict):
            print(
                f"[Profiles] schema {version!r} is incompatible with "
                f"{PROFILE_SCHEMA_VERSION}; relearning"
            )
            self._archive_incompatible(f"schema-{version if version is not None else 'legacy'}")
            self.data = {}
            self._active_key = None
            self.save()
            return

        self.data = {str(k): v for k, v in profiles.items() if isinstance(v, dict)}
        active = stored.get("active_profile")
        self._active_key = str(active) if isinstance(active, str) and active in self.data else None

    def _archive_incompatible(self, reason: str) -> None:
        """Keep invalidated learning data recoverable instead of overwriting it."""
        if not self.path.exists():
            return
        backup = self.path.with_name(f"{self.path.name}.{reason}.bak")
        suffix = 1
        while backup.exists():
            backup = self.path.with_name(f"{self.path.name}.{reason}.{suffix}.bak")
            suffix += 1
        try:
            self.path.replace(backup)
        except Exception as exc:
            print(f"[Profiles] could not archive incompatible data: {exc}")

    def save(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": PROFILE_SCHEMA_VERSION,
                "active_profile": self._active_key,
                "profiles": self.data,
            }
            temp_path = self.path.with_name(f"{self.path.name}.tmp")
            temp_path.write_text(json.dumps(payload, indent=2))
            temp_path.replace(self.path)
            return True
        except Exception as e:
            print(f"[Profiles] save failed: {e}")
            return False

    def _legacy_key(self, car_key: tuple[int, ...]) -> str | None:
        if len(car_key) >= 3:
            return f"{car_key[0]}_{car_key[1]}_{car_key[2]}"
        return None

    def get(self, car_key: tuple[int, ...]) -> dict | None:
        k = storage_key(car_key)
        if k in self.data:
            return self.data[k]
        legacy = self._legacy_key(car_key)
        if legacy and legacy in self.data:
            return self.data[legacy]
        return None

    def is_learned(self, car_key: tuple[int, ...] | None) -> bool:
        """Return whether an exact persisted, calibrated profile exists."""
        if car_key is None:
            return False
        key = storage_key(car_key)
        profile = self.data.get(key)
        if not isinstance(profile, dict):
            return False
        stored_sig = profile.get("tune_signature")
        if len(car_key) >= 4 and stored_sig is not None and stored_sig != car_key[3]:
            return False
        ratios = profile.get("gear_ratios")
        return isinstance(ratios, dict) and len(ratios) >= 2

    def has_profile(self, car_key: tuple[int, ...]) -> bool:
        return storage_key(car_key) in self.data

    @property
    def active_car_key(self) -> tuple[int, ...] | None:
        if self._active_key is None:
            return None
        try:
            values = tuple(int(part) for part in self._active_key.split("_"))
        except ValueError:
            return None
        return values if len(values) in (3, 4) else None

    def mark_active(self, car_key: tuple[int, ...]) -> None:
        key = storage_key(car_key)
        if key in self.data and self._active_key != key:
            previous = self._active_key
            self._active_key = key
            if not self.save():
                self._active_key = previous

    def set(self, car_key: tuple[int, ...], profile: dict) -> bool:
        key = storage_key(car_key)
        previous = self.data.get(key)
        previous_active = self._active_key
        self.data[key] = profile
        self._active_key = key
        if self.save():
            return True
        if previous is None:
            self.data.pop(key, None)
        else:
            self.data[key] = previous
        self._active_key = previous_active
        return False

    def delete(self, car_key: tuple[int, ...]) -> bool:
        key = storage_key(car_key)
        previous = self.data.pop(key, None)
        removed = previous is not None
        previous_active = self._active_key
        if self._active_key == key:
            self._active_key = None
        if removed and not self.save():
            self.data[key] = previous
            self._active_key = previous_active
            return False
        return removed
