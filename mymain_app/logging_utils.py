from __future__ import annotations

import threading
import time


class DebugLogger:
    def __init__(self, enabled: bool = True, default_interval: float = 1.0):
        self.enabled = enabled
        self.default_interval = default_interval
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def log(self, message: str) -> None:
        if self.enabled:
            print(f"[debug] {message}", flush=True)

    def every(self, key: str, message: str, interval: float | None = None) -> None:
        if not self.enabled:
            return
        now = time.perf_counter()
        delay = self.default_interval if interval is None else interval
        with self._lock:
            if now - self._last.get(key, 0.0) < delay:
                return
            self._last[key] = now
        print(f"[debug] {message}", flush=True)
