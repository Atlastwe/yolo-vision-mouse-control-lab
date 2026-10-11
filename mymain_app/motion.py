from __future__ import annotations

import numpy as np

from .config import ControlConfig
from .models import Detection


class CVKalman2D:
    def __init__(self, q_vel: float = 900.0, r_pos: float = 25.0):
        self.x = np.zeros((4, 1), dtype=np.float64)
        self.p = np.eye(4, dtype=np.float64) * 200.0
        self.last_t: float | None = None
        self.q_vel = q_vel
        self.r_pos = r_pos
        self.h = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float64)

    @staticmethod
    def _transition(dt: float) -> np.ndarray:
        return np.array(
            [[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]],
            dtype=np.float64,
        )

    def _process_noise(self, dt: float) -> np.ndarray:
        dt2, dt3, dt4 = dt * dt, dt**3, dt**4
        q = self.q_vel
        return np.array(
            [
                [dt4 * q / 4, 0, dt3 * q / 2, 0],
                [0, dt4 * q / 4, 0, dt3 * q / 2],
                [dt3 * q / 2, 0, dt2 * q, 0],
                [0, dt3 * q / 2, 0, dt2 * q],
            ],
            dtype=np.float64,
        )

    def predict_to(self, now: float) -> None:
        if self.last_t is None:
            self.last_t = now
            return
        dt = max(1e-4, now - self.last_t)
        transition = self._transition(dt)
        self.x = transition @ self.x
        self.p = transition @ self.p @ transition.T + self._process_noise(dt)
        self.last_t = now

    def reset(self, detection: Detection | None = None) -> None:
        self.x.fill(0.0)
        self.p = np.eye(4, dtype=np.float64) * 200.0
        self.last_t = None
        if detection is not None:
            self.x[0, 0], self.x[1, 0] = detection.x, detection.y
            self.last_t = detection.t_capture

    def update(self, detection: Detection) -> None:
        if self.last_t is None:
            self.x[0, 0], self.x[1, 0] = detection.x, detection.y
            self.last_t = detection.t_capture
            return
        # A control tick may run after this frame was captured. Never move the
        # filter clock backwards when a delayed measurement arrives.
        if detection.t_capture > self.last_t:
            self.predict_to(detection.t_capture)
        measurement = np.array([[detection.x], [detection.y]], dtype=np.float64)
        confidence = min(max(detection.confidence, 1e-3), 1.0)
        measurement_noise = np.eye(2, dtype=np.float64) * (self.r_pos / confidence)
        residual = measurement - self.h @ self.x
        residual_covariance = self.h @ self.p @ self.h.T + measurement_noise
        gain = self.p @ self.h.T @ np.linalg.inv(residual_covariance)
        self.x = self.x + gain @ residual
        self.p = (np.eye(4, dtype=np.float64) - gain @ self.h) @ self.p

    def predict_future(self, seconds: float) -> np.ndarray:
        px, py, vx, vy = self.x[:, 0]
        return np.array([px + vx * seconds, py + vy * seconds, vx, vy], dtype=np.float64)


class JerkLimiter:
    def __init__(self, config: ControlConfig):
        self.config = config
        self.velocity = np.zeros(2, dtype=np.float64)
        self.acceleration = np.zeros(2, dtype=np.float64)

    def step(self, command: np.ndarray, dt: float) -> np.ndarray:
        dt = max(dt, 1e-4)
        target_acceleration = (command - self.velocity) / dt
        acceleration_delta = target_acceleration - self.acceleration
        delta_norm = np.linalg.norm(acceleration_delta)
        delta_limit = self.config.jerk_max * dt
        if delta_norm > delta_limit and delta_norm > 1e-9:
            acceleration_delta *= delta_limit / delta_norm
        self.acceleration += acceleration_delta
        acceleration_norm = np.linalg.norm(self.acceleration)
        if acceleration_norm > self.config.acceleration_max and acceleration_norm > 1e-9:
            self.acceleration *= self.config.acceleration_max / acceleration_norm
        self.velocity += self.acceleration * dt
        velocity_norm = np.linalg.norm(self.velocity)
        if velocity_norm > self.config.velocity_max and velocity_norm > 1e-9:
            self.velocity *= self.config.velocity_max / velocity_norm
        return self.velocity.copy()

    def decay(self) -> np.ndarray:
        self.acceleration *= self.config.stop_decay
        self.velocity *= self.config.stop_decay
        return self.velocity.copy()

    def reset(self) -> None:
        self.acceleration.fill(0.0)
        self.velocity.fill(0.0)


class VisualServoController:
    def __init__(self, config: ControlConfig):
        self.config = config
        self.integral = np.zeros(2, dtype=np.float64)
        self.motion = JerkLimiter(config)

    def speed_scale(self, distance_px: float) -> float:
        """Scale control speed smoothly as the target approaches screen center."""
        if distance_px <= self.config.stop_radius_px:
            return 0.0
        radius = max(self.config.slowdown_radius_px, self.config.stop_radius_px + 1e-6)
        progress = np.clip(
            (distance_px - self.config.stop_radius_px)
            / (radius - self.config.stop_radius_px),
            0.0,
            1.0,
        )
        smooth_progress = progress * progress * (3.0 - 2.0 * progress)
        near_scale = float(np.clip(self.config.near_speed_scale, 0.0, 1.0))
        return float(near_scale + (1.0 - near_scale) * smooth_progress)

    def step(self, offset: np.ndarray, target_velocity: np.ndarray, dt: float) -> np.ndarray:
        position_error = offset.copy()
        distance = float(np.linalg.norm(position_error))
        if distance <= self.config.stop_radius_px:
            self.hard_stop()
            return np.zeros(2, dtype=np.float64)
        if distance < self.config.deadzone_px:
            position_error.fill(0.0)
        if np.linalg.norm(position_error) < self.config.integral_zone_px:
            self.integral += position_error * dt
            integral_norm = np.linalg.norm(self.integral)
            if integral_norm > self.config.integral_limit and integral_norm > 1e-9:
                self.integral *= self.config.integral_limit / integral_norm
        else:
            self.integral *= 0.94
        command = (
            self.config.kp * position_error
            + self.config.kv * target_velocity
            + self.config.ki * self.integral
        )
        command *= self.speed_scale(distance)
        return self.motion.step(command, dt)

    def decay_to_stop(self) -> None:
        self.integral *= 0.9
        self.motion.decay()

    def hard_stop(self) -> None:
        self.integral.fill(0.0)
        self.motion.reset()


class TargetSmoother:
    def __init__(self, alpha: float = 0.35):
        self.alpha = float(alpha)
        self.position: np.ndarray | None = None

    def update(self, target_position: np.ndarray) -> np.ndarray:
        if self.position is None:
            self.position = target_position.copy()
        else:
            self.position += self.alpha * (target_position - self.position)
        return self.position

    def reset(self) -> None:
        self.position = None
