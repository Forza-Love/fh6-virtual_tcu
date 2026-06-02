import time
from concurrent.futures import ThreadPoolExecutor

import keyboard

from virtual_tcu.config.constants import Cfg
from virtual_tcu.config.store import ConfigStore
from virtual_tcu.input.interface import OutputInterface


class KeyboardOutput(OutputInterface):
    """Inject shift commands as keyboard key-presses (E / Q by default).

    When ``feat_clutch_assist`` is enabled the output sends a full clutch
    sequence around each shift press:

    1. Press clutch key (default: ``shift`` — the FH6 "Manual with Clutch"
       binding for Shift+E / Shift+Q).
    2. Wait ``clutch_pre_ms`` ms.
    3. Press the shift key (E or Q).
    4. Wait ``clutch_overlap_ms`` ms (key hold, same role as KEY_HOLD_S).
    5. Release the shift key.
    6. Wait ``clutch_release_ms`` ms.
    7. Release the clutch key.

    With the default ``clutch_key = "shift"`` this produces the exact key
    chord that FH6 expects for clutch-assisted sequential shifts.
    """

    def __init__(self, config: ConfigStore):
        self._config = config
        self._self_press_until: dict[str, float] = {}
        self.SELF_PRESS_WINDOW_S = 0.15
        # Single worker ensures keystrokes are executed sequentially without thread leaks
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="KB_Worker")

    # -- config properties -----------------------------------------------------

    @property
    def key_up(self) -> str:
        return str(self._config.get("shift_key_up", "e")).lower()

    @property
    def key_down(self) -> str:
        return str(self._config.get("shift_key_down", "q")).lower()

    @property
    def clutch_key(self) -> str:
        return str(self._config.get("clutch_key", "shift")).lower()

    @property
    def use_clutch(self) -> bool:
        return bool(self._config.get("feat_clutch_assist", False))

    @property
    def clutch_pre_ms(self) -> int:
        return int(self._config.get("clutch_pre_ms", 20))

    @property
    def clutch_overlap_ms(self) -> int:
        return int(self._config.get("clutch_overlap_ms", 55))

    @property
    def clutch_release_ms(self) -> int:
        return int(self._config.get("clutch_release_ms", 25))

    # -- OutputInterface -------------------------------------------------------

    def is_self_press(self, key: str) -> bool:
        return time.time() < self._self_press_until.get(key.lower(), 0.0)

    def shift_to(self, from_gear: int, target_gear: int):
        # from_gear and target_gear must be 0-10
        if not (0 <= from_gear <= 10) or not (0 <= target_gear <= 10):
            print(f"[Keyboard] invalid gear numbers: from {from_gear} to {target_gear}")
            return
        if from_gear == target_gear:
            return

        shifts_needed = abs(target_gear - from_gear)
        shift_key = self.key_up if target_gear > from_gear else self.key_down

        if self.use_clutch:
            def _multi_shift_clutch():
                for i in range(shifts_needed):
                    self._press_release_with_clutch(shift_key)
                    if i < shifts_needed - 1:
                        time.sleep(0.06)

            self._executor.submit(_multi_shift_clutch)
        else:
            def _multi_shift():
                for i in range(shifts_needed):
                    self._press_release(shift_key)
                    if i < shifts_needed - 1:
                        time.sleep(0.06)

            self._executor.submit(_multi_shift)

    def shutdown(self):
        self._executor.shutdown(wait=False)

    # -- internals -------------------------------------------------------------

    def _press_release(self, key: str):
        """Simple press-hold-release without clutch."""
        try:
            key = key.lower()
            self._self_press_until[key] = time.time() + self.SELF_PRESS_WINDOW_S
            keyboard.press(key)
            time.sleep(Cfg.KEY_HOLD_S)
            keyboard.release(key)
        except Exception as e:
            print(f"[KB] Input simulation failed: {e}")

    def _press_release_with_clutch(self, key: str):
        """Press clutch → hold → press shift key → hold → release → hold → release clutch.

        The self-press window covers the entire sequence so the paddle
        listener does not mis-read the injected key as a manual input.
        """
        ck = self.clutch_key
        k = key.lower()
        pressed_ck = False
        pressed_k = False
        try:
            pre_s = self.clutch_pre_ms / 1000.0
            overlap_s = self.clutch_overlap_ms / 1000.0
            release_s = self.clutch_release_ms / 1000.0
            # Extend self-press window for the full sequence duration.
            total_s = pre_s + overlap_s + release_s + 0.05
            deadline = time.time() + total_s + self.SELF_PRESS_WINDOW_S
            self._self_press_until[k] = deadline
            self._self_press_until[ck] = deadline

            keyboard.press(ck)
            pressed_ck = True
            time.sleep(pre_s)

            keyboard.press(k)
            pressed_k = True
            time.sleep(overlap_s)

            keyboard.release(k)
            pressed_k = False
            time.sleep(release_s)

            keyboard.release(ck)
            pressed_ck = False
        except Exception as e:
            print(f"[KB] Clutch-assisted shift failed: {e}")
        finally:
            try:
                if pressed_k:
                    keyboard.release(k)
                if pressed_ck:
                    keyboard.release(ck)
            except Exception:
                pass
