import time
import unittest
from unittest.mock import patch

import numpy as np

from mymain_app.config import AppConfig
from mymain_app.app import Application
from mymain_app.detector import YoloDetector
from mymain_app.logging_utils import DebugLogger
from mymain_app.models import Detection, Target, centered_geometry
from mymain_app.motion import CVKalman2D, VisualServoController
from mymain_app.mouse_input import create_mouse_input
from mymain_app.pipeline import Pipeline


class FakeCapture:
    source_size = (320, 240)

    def __init__(self):
        self.stopped = False

    def get_latest_frame(self):
        time.sleep(0.001)
        return np.zeros((240, 320, 3), dtype=np.uint8)

    def stop(self):
        self.stopped = True


class FakeDetector:
    def infer(self, frame):
        return object()

    def select_target(self, result, geometry):
        return Target()


class FakeMouse:
    def __init__(self):
        self.closed = False

    @property
    def description(self):
        return "FakeMouse"

    def is_activation_pressed(self):
        return False

    def move_relative(self, dx, dy):
        raise AssertionError("inactive fake mouse must not move")

    def close(self):
        self.closed = True


class FakeBox:
    def __init__(self, xyxy, confidence=0.9, class_id=0, track_id=None):
        self.xyxy = np.asarray([xyxy], dtype=np.float32)
        self.conf = np.asarray([confidence], dtype=np.float32)
        self.cls = np.asarray([class_id], dtype=np.float32)
        self.id = (
            None
            if track_id is None
            else np.asarray([track_id], dtype=np.float32)
        )


class FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes


def make_detector():
    detector = YoloDetector.__new__(YoloDetector)
    detector.config = AppConfig().detection
    detector.model = type("FakeModel", (), {"names": {0: "Enemy", 1: "Head"}})()
    detector._last_target = None
    detector._locked_track_id = None
    detector._locked_track_misses = 0
    return detector


class ModularWorkflowTests(unittest.TestCase):
    def test_unknown_mouse_mode_is_rejected(self):
        config = AppConfig().mouse
        config.mode = "unknown"
        with self.assertRaisesRegex(ValueError, "Unsupported mouse input mode"):
            create_mouse_input(config)

    def test_obs_preview_runs_in_its_own_worker(self):
        calls = []

        class FakePreview:
            def __init__(self, config):
                calls.append(("init", config.preview_visible_at_start))

            def run(self, pipeline):
                calls.append(("run", pipeline))

        config = AppConfig()
        config.output.debug = False
        application = Application(config, obs=object())
        fake_pipeline = object()
        application.pipeline = fake_pipeline
        with patch("mymain_app.app.Preview", FakePreview):
            application._start_preview_thread()
            application._preview_thread.join(timeout=1.0)

        self.assertEqual(calls, [("init", True), ("run", fake_pipeline)])

    def test_centered_geometry_maps_source_to_screen(self):
        geometry = centered_geometry(1920, 1080, 1280, 720, 0.5, 0.5)
        self.assertEqual((geometry.crop_x, geometry.crop_y), (320, 180))
        self.assertEqual(geometry.crop_to_screen(320, 180), (960.0, 540.0))

    def test_controller_respects_velocity_limit(self):
        config = AppConfig().control
        controller = VisualServoController(config)
        velocity = controller.step(
            np.array([10000.0, 10000.0]), np.zeros(2), config.interval_s
        )
        self.assertLessEqual(np.linalg.norm(velocity), config.velocity_max)

    def test_speed_scale_increases_with_target_distance(self):
        config = AppConfig().control
        controller = VisualServoController(config)
        near = controller.speed_scale(config.stop_radius_px + 1.0)
        middle = controller.speed_scale(config.slowdown_radius_px * 0.5)
        far = controller.speed_scale(config.slowdown_radius_px + 100.0)
        self.assertLess(near, middle)
        self.assertLess(middle, far)
        self.assertEqual(far, 1.0)

    def test_controller_hard_stops_inside_stop_radius(self):
        config = AppConfig().control
        controller = VisualServoController(config)
        for _ in range(20):
            controller.step(np.array([500.0, 0.0]), np.zeros(2), config.interval_s)
        stopped = controller.step(
            np.array([config.stop_radius_px, 0.0]), np.zeros(2), config.interval_s
        )
        np.testing.assert_array_equal(stopped, np.zeros(2))
        np.testing.assert_array_equal(controller.motion.velocity, np.zeros(2))

    def test_kalman_does_not_move_its_clock_backwards(self):
        estimator = CVKalman2D()
        estimator.reset(Detection(100.0, 200.0, 10.0, 1.0))
        estimator.update(Detection(110.0, 210.0, 9.0, 1.0))
        self.assertEqual(estimator.last_t, 10.0)

    def test_kalman_reset_immediately_uses_new_target(self):
        estimator = CVKalman2D()
        estimator.reset(Detection(100.0, 200.0, 1.0, 1.0))
        estimator.reset(Detection(900.0, 500.0, 2.0, 1.0))
        prediction = estimator.predict_future(0.05)
        np.testing.assert_allclose(prediction[:2], [900.0, 500.0])

    def test_target_lock_keeps_same_track_for_small_score_improvement(self):
        detector = make_detector()
        geometry = centered_geometry(1000, 1000, 1000, 1000, 1.0, 1.0)
        first = detector.select_target(
            FakeResult([FakeBox((530, 480, 570, 520), track_id=10)]), geometry
        )
        self.assertEqual(first.track_id, 10)

        second = detector.select_target(
            FakeResult(
                [
                    FakeBox((530, 480, 570, 520), track_id=10),
                    FakeBox((510, 480, 550, 520), track_id=20),
                ]
            ),
            geometry,
        )
        self.assertEqual(second.track_id, 10)

    def test_target_lock_switches_when_alternative_is_clearly_better(self):
        detector = make_detector()
        geometry = centered_geometry(1000, 1000, 1000, 1000, 1.0, 1.0)
        detector.select_target(
            FakeResult([FakeBox((680, 480, 720, 520), track_id=10)]), geometry
        )
        switched = detector.select_target(
            FakeResult(
                [
                    FakeBox((680, 480, 720, 520), track_id=10),
                    FakeBox((480, 480, 520, 520), track_id=20),
                ]
            ),
            geometry,
        )
        self.assertEqual(switched.track_id, 20)

    def test_target_lock_tolerates_short_tracking_gap(self):
        detector = make_detector()
        geometry = centered_geometry(1000, 1000, 1000, 1000, 1.0, 1.0)
        detector.select_target(
            FakeResult([FakeBox((530, 480, 570, 520), track_id=10)]), geometry
        )
        replacement = FakeResult([FakeBox((480, 480, 520, 520), track_id=20)])
        for _ in range(detector.config.target_lock_miss_frames):
            self.assertFalse(detector.select_target(replacement, geometry).found)
        self.assertEqual(detector.select_target(replacement, geometry).track_id, 20)

    def test_locked_target_keeps_updating_during_small_low_confidence_motion(self):
        detector = make_detector()
        geometry = centered_geometry(1000, 1000, 1000, 1000, 1.0, 1.0)
        first = detector.select_target(
            FakeResult([FakeBox((480, 480, 520, 520), confidence=0.9, track_id=10)]),
            geometry,
        )
        moved = detector.select_target(
            FakeResult([FakeBox((483, 478, 523, 518), confidence=0.3, track_id=10)]),
            geometry,
        )
        self.assertEqual(first.track_id, moved.track_id)
        self.assertEqual((moved.cx, moved.cy), (503.0, 498.0))

    def test_pipeline_workflow_starts_produces_and_stops(self):
        config = AppConfig()
        config.output.debug = False
        capture = FakeCapture()
        mouse = FakeMouse()
        pipeline = Pipeline(
            config,
            capture,
            FakeDetector(),
            mouse,
            (1920, 1080),
            DebugLogger(enabled=False),
        )
        pipeline.start()
        frame, result, target, geometry = pipeline.result_queue.get(timeout=2.0)
        self.assertEqual(frame.shape[0], geometry.crop_height)
        self.assertEqual(frame.shape[1], geometry.crop_width)
        self.assertFalse(target.found)
        pipeline.stop()
        self.assertTrue(capture.stopped)
        self.assertTrue(mouse.closed)
        self.assertFalse(pipeline.is_running())


if __name__ == "__main__":
    unittest.main()
