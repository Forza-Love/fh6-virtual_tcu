import threading
import time
from collections import deque

from virtual_tcu.telemetry.model import Telemetry


class ShiftHistory:
    def __init__(self, max_size: int = 20):
        self._history: deque[dict] = deque(maxlen=max_size)
        self._lock = threading.Lock()

    def record(
        self,
        action: str,
        td: Telemetry,
        reason: str = "",
        rule: str = "",
        blocked_by: str | None = None,
        sent_at: float | None = None,
    ):
        with self._lock:
            entry: dict = {
                "ts": time.time(),
                "action": action,
                "gear": td.gear,
                "rpm_pct": round(td.rpm_pct * 100, 1),
                "throttle": round(td.throttle * 100, 1),
                "brake": round(td.brake * 100, 1),
                "speed": round(td.speed_kmh, 1),
                "reason": reason,
                "rule": rule,
                "blocked_by": blocked_by,
            }
            # sent_at records when the shift command was issued (seconds since epoch/clock).
            # This can be used later to analyze command-to-gear-change latency.
            if sent_at is not None:
                entry["shift_sent_at"] = sent_at
            self._history.append(entry)

    def snapshot(self) -> list:
        with self._lock:
            return list(self._history)
