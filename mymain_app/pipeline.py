from __future__ import annotations

import queue
import threading
import time
import traceback

import numpy as np

from .capture import CaptureBackend
from .config import AppConfig
from .detector import YoloDetector
from .logging_utils import DebugLogger
from .models import Detection, SharedTargetState, centered_geometry
from .motion import CVKalman2D, TargetSmoother, VisualServoController
from .mouse_input import MouseInput


def push_latest(target_queue: queue.Queue, item) -> None:
    if target_queue.full():
        try:
            target_queue.get_nowait()
        except queue.Empty:
            pass
    target_queue.put_nowait(item)


class Pipeline:
    """Own the capture, inference, and input-control workflow."""

    def __init__(self, config: AppConfig, capture: CaptureBackend, detector: YoloDetector,
                 mouse: MouseInput, screen_size: tuple[int, int], logger: DebugLogger):
        self.config = config
        self.capture = capture
        self.detector = detector
        self.mouse = mouse
        self.screen_size = screen_size
        self.logger = logger
        self.frame_queue: queue.Queue = queue.Queue(maxsize=1)
        self.result_queue: queue.Queue = queue.Queue(maxsize=1)
        self.state = SharedTargetState()
        self.stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._geometry_lock = threading.Lock()
        source_width, source_height = capture.source_size
        self._geometry = centered_geometry(
            *screen_size, source_width, source_height,
            config.detection.crop_width_ratio, config.detection.crop_height_ratio,
        )

    @property
    def geometry(self):
        with self._geometry_lock:
            return self._geometry

    def start(self) -> None:
        if any(thread.is_alive() for thread in self._threads):
            return
        self.stop_event.clear()
        self._threads = []
        for name, worker in (("capture", self._capture_loop),
                             ("inference", self._inference_loop),
                             ("control", self._control_loop)):
            thread = threading.Thread(target=self._guard(worker), name=name, daemon=True)
            thread.start()
            self._threads.append(thread)
        self.logger.log("pipeline started: capture, inference, control")

    def _guard(self, worker):
        def guarded() -> None:
            try:
                worker()
            except Exception:
                self.logger.log(f"{worker.__name__} crashed:\n{traceback.format_exc()}")
                self.stop_event.set()
        return guarded

    def _refresh_geometry(self, frame) -> None:
        source_height, source_width = frame.shape[:2]
        with self._geometry_lock:
            current = self._geometry
            if current.source_width == source_width and current.source_height == source_height:
                return
            self._geometry = centered_geometry(
                *self.screen_size, source_width, source_height,
                self.config.detection.crop_width_ratio,
                self.config.detection.crop_height_ratio,
            )
            self.logger.log(f"capture geometry updated: source={source_width}x{source_height}")

    def _capture_loop(self) -> None:
        frames = 0
        last_stats = time.perf_counter()
        while not self.stop_event.is_set():
            frame = self.capture.get_latest_frame()
            if frame is None:
                self.logger.every("capture_wait", "capture: waiting for a frame")
                time.sleep(0.001)
                continue
            self._refresh_geometry(frame)
            geometry = self.geometry
            cropped = frame[geometry.crop_y:geometry.crop_y + geometry.crop_height,
                            geometry.crop_x:geometry.crop_x + geometry.crop_width]
            if cropped.size == 0:
                self.logger.every("capture_empty", "capture: centered crop is empty")
                time.sleep(0.01)
                continue
            push_latest(self.frame_queue, (cropped, time.perf_counter(), geometry))
            frames += 1
            now = time.perf_counter()
            if now - last_stats >= 1.0:
                self.logger.log(f"capture: fps={frames / (now - last_stats):.1f}")
                frames, last_stats = 0, now

    def _inference_loop(self) -> None:
        frames = 0
        last_stats = time.perf_counter()
        while not self.stop_event.is_set():
            try:
                frame, captured_at, geometry = self.frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            result = self.detector.infer(frame)
            target = self.detector.select_target(result, geometry)
            if target.found and target.cx is not None and target.cy is not None:
                self.state.update(
                    Detection(target.cx, target.cy, captured_at, target.confidence or 0.0), target
                )
            else:
                self.state.clear_target()
            push_latest(self.result_queue, (frame, result, target, geometry))
            frames += 1
            now = time.perf_counter()
            if now - last_stats >= 1.0:
                self.logger.log(f"inference: fps={frames / (now - last_stats):.1f}")
                frames, last_stats = 0, now

    def _control_loop(self) -> None:
        control = self.config.control
        estimator = CVKalman2D()
        controller = VisualServoController(control)
        smoother = TargetSmoother(alpha=control.target_smoothing_alpha)
        last_capture_time: float | None = None
        last_target_position: np.ndarray | None = None
        last_target_label: str | None = None
        last_track_id: int | None = None
        movement_remainder = np.zeros(2, dtype=np.float64)
        was_pressed = False
        while not self.stop_event.is_set():
            started_at = time.perf_counter()
            pressed = self.mouse.is_activation_pressed()
            detection, arrival_time, target = self.state.snapshot()
            if detection is not None and detection.t_capture != last_capture_time:
                measured_position = np.array([detection.x, detection.y], dtype=np.float64)
                target_changed = (
                    last_target_position is None
                    or target.label != last_target_label
                    or (
                        target.track_id is not None
                        and last_track_id is not None
                        and target.track_id != last_track_id
                    )
                    or (
                        (target.track_id is None or last_track_id is None)
                        and np.linalg.norm(measured_position - last_target_position)
                        > control.target_switch_distance_px
                    )
                )
                if target_changed:
                    estimator.reset(detection)
                    smoother.reset()
                    controller.hard_stop()
                    movement_remainder.fill(0.0)
                else:
                    estimator.update(detection)
                last_target_position = measured_position
                last_target_label = target.label
                last_track_id = target.track_id
                last_capture_time = detection.t_capture
            if was_pressed and not pressed:
                controller.hard_stop()
                smoother.reset()
                movement_remainder.fill(0.0)
            was_pressed = pressed
            age = started_at - arrival_time if arrival_time else float("inf")
            max_age = control.detection_max_age_s if target.found else control.hold_last_target_s
            if pressed and detection is not None and age <= max_age:
                measurement_age = max(0.0, started_at - detection.t_capture)
                prediction_time = min(
                    measurement_age + control.total_latency_s,
                    control.prediction_max_s,
                )
                prediction = estimator.predict_future(prediction_time)
                target_position = smoother.update(prediction[:2])
                offset = target_position - np.array(self.geometry.screen_center, dtype=np.float64)
                if np.linalg.norm(offset) <= control.stop_radius_px:
                    controller.hard_stop()
                    movement_remainder.fill(0.0)
                else:
                    velocity = controller.step(offset, prediction[2:], control.interval_s)
                    movement = velocity * control.interval_s + movement_remainder
                    dx = int(np.rint(movement[0]))
                    dy = int(np.rint(movement[1]))
                    movement_remainder = movement - np.array([dx, dy], dtype=np.float64)
                    if (dx or dy) and not self.mouse.move_relative(dx, dy):
                        self.logger.every("mouse_move", f"mouse move failed: dx={dx} dy={dy}")
            else:
                controller.decay_to_stop()
                movement_remainder.fill(0.0)
                if age > max_age and last_target_position is not None:
                    estimator.reset()
                    smoother.reset()
                    controller.hard_stop()
                    last_target_position = None
                    last_target_label = None
                    last_track_id = None
            elapsed = time.perf_counter() - started_at
            time.sleep(max(0.0, control.interval_s - elapsed))

    def stop(self) -> None:
        self.stop_event.set()
        for thread in self._threads:
            if thread is not threading.current_thread():
                thread.join(timeout=1.0)
        self._threads.clear()
        self.capture.stop()
        self.mouse.close()
        self.logger.log("pipeline stopped")

    def is_running(self) -> bool:
        return bool(self._threads) and not self.stop_event.is_set()
