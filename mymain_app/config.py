from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(slots=True)
class MouseConfig:
    # Input backend: "ib" (IbInputSimulator) or "pyautogui".
    mode: str = "pyautogui"
    dll_path: Path = PROJECT_ROOT / "IbInputSimulator-0.4.1" / "Binding.AHK2" / "IbInputSimulator.dll"
    activation_key: int = 0x02
    # IbInputSimulator: 6 = LogitechGHubNew, 1 = Windows SendInput.
    preferred_send_type: int = 6
    fallback_send_type: int = 1
    pyautogui_pause_s: float = 0.0
    pyautogui_failsafe: bool = True


@dataclass(slots=True)
class DetectionConfig:
    model_path: Path = PROJECT_ROOT / "models" / "best.engine"
    class_priority: dict[str, int] = field(default_factory=lambda: {"Head": 0, "Enemy": 1})
    image_size: int = 640
    # A new target must pass confidence; an already locked ByteTrack identity
    # may be retained at a lower score through small motion or brief occlusion.
    confidence: float = 0.5
    locked_target_confidence: float = 0.25
    # Keep stable identities between frames. ByteTrack receives lower-confidence
    # detections for association, while confidence remains the selection cutoff.
    tracking_enabled: bool = True
    tracker_config: str = "bytetrack.yaml"
    tracker_input_confidence: float = 0.1
    target_lock_enabled: bool = True
    target_lock_miss_frames: int = 3
    target_switch_score_margin: float = 45.0
    class_rank_penalty: float = 35.0
    box_size_bonus: float = 0.15
    crop_width_ratio: float = 0.28
    crop_height_ratio: float = 0.28


@dataclass(slots=True)
class ControlConfig:
    frequency_hz: float = 300.0
    total_latency_s: float = 0.050
    prediction_max_s: float = 0.12
    detection_max_age_s: float = 0.18
    hold_last_target_s: float = 0.12
    target_smoothing_alpha: float = 0.75
    target_switch_distance_px: float = 120.0
    stop_decay: float = 0.90
    kp: float = 20.0
    kv: float = 2.2
    ki: float = 0.04
    integral_zone_px: float = 90.0
    integral_limit: float = 220.0
    deadzone_px: float = 0.8
    stop_radius_px: float = 3.0
    slowdown_radius_px: float = 180.0
    near_speed_scale: float = 0.15
    velocity_max: float = 10000.0
    acceleration_max: float = 50000.0
    jerk_max: float = 400000.0

    @property
    def interval_s(self) -> float:
        return 1.0 / self.frequency_hz


@dataclass(slots=True)
class OutputConfig:
    json_path: Path = PROJECT_ROOT / "detect.json"
    json_write_interval_s: float = 0.05
    log_interval_s: float = 0.5
    # Run the recognition inspector. F8 toggles its window without stopping inference.
    show_preview: bool = True
    preview_visible_at_start: bool = True
    preview_toggle_key: int = 0x77  # F8
    preview_window_width: int = 900
    preview_draw_all_detections: bool = True
    debug: bool = True
    debug_interval_s: float = 1.0


@dataclass(slots=True)
class AppConfig:
    mouse: MouseConfig = field(default_factory=MouseConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    control: ControlConfig = field(default_factory=ControlConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    obs_source_name: str = ""
