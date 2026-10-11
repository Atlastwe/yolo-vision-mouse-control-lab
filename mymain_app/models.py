from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(slots=True)
class Detection:
    x: float
    y: float
    t_capture: float
    confidence: float


@dataclass(slots=True)
class Target:
    found: bool = False
    track_id: int | None = None
    label: str | None = None
    cx: float | None = None
    cy: float | None = None
    confidence: float | None = None
    box: tuple[int, int, int, int] | None = None


class SharedTargetState:
    def __init__(self):
        self._lock = threading.Lock()
        self._latest_detection: Detection | None = None
        self._last_detection_arrival = 0.0
        self._target = Target()

    def update(self, detection: Detection, target: Target) -> None:
        with self._lock:
            self._latest_detection = detection
            self._last_detection_arrival = time.perf_counter()
            self._target = target

    def clear_target(self) -> None:
        with self._lock:
            self._target = Target()

    def snapshot(self) -> tuple[Detection | None, float, Target]:
        with self._lock:
            return self._latest_detection, self._last_detection_arrival, self._target


@dataclass(slots=True)
class CaptureGeometry:
    screen_width: int
    screen_height: int
    source_width: int
    source_height: int
    crop_x: int
    crop_y: int
    crop_width: int
    crop_height: int

    @property
    def screen_center(self) -> tuple[float, float]:
        return self.screen_width * 0.5, self.screen_height * 0.5

    @property
    def local_center(self) -> tuple[int, int]:
        return self.crop_width // 2, self.crop_height // 2

    @property
    def scale_x(self) -> float:
        return self.screen_width / self.source_width if self.source_width else 1.0

    @property
    def scale_y(self) -> float:
        return self.screen_height / self.source_height if self.source_height else 1.0

    def crop_to_screen(self, x: float, y: float) -> tuple[float, float]:
        return (self.crop_x + x) * self.scale_x, (self.crop_y + y) * self.scale_y


def centered_geometry(
    screen_width: int,
    screen_height: int,
    source_width: int,
    source_height: int,
    width_ratio: float,
    height_ratio: float,
) -> CaptureGeometry:
    crop_width = max(2, int(source_width * width_ratio))
    crop_height = max(2, int(source_height * height_ratio))
    return CaptureGeometry(
        screen_width=screen_width,
        screen_height=screen_height,
        source_width=source_width,
        source_height=source_height,
        crop_x=max(0, (source_width - crop_width) // 2),
        crop_y=max(0, (source_height - crop_height) // 2),
        crop_width=crop_width,
        crop_height=crop_height,
    )
