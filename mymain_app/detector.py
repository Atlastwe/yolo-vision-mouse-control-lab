from __future__ import annotations

import numpy as np

from .config import DetectionConfig
from .models import CaptureGeometry, Target


class YoloDetector:
    def __init__(self, config: DetectionConfig):
        from ultralytics import YOLO

        if not config.model_path.is_file():
            raise FileNotFoundError(f"YOLO model not found: {config.model_path}")
        self.config = config
        self.model = YOLO(str(config.model_path))
        self._last_target: Target | None = None
        self._locked_track_id: int | None = None
        self._locked_track_misses = 0

    @property
    def description(self) -> str:
        if self.config.tracking_enabled:
            return f"YOLO + ByteTrack ({self.config.tracker_config})"
        return "YOLO detection"

    def infer(self, frame):
        if self.config.tracking_enabled:
            return self.model.track(
                frame,
                persist=True,
                tracker=self.config.tracker_config,
                imgsz=self.config.image_size,
                conf=min(self.config.confidence, self.config.tracker_input_confidence),
                verbose=False,
            )[0]
        return self.model(
            frame,
            imgsz=self.config.image_size,
            conf=self.config.confidence,
            verbose=False,
        )[0]

    def select_target(self, result, geometry: CaptureGeometry) -> Target:
        boxes = getattr(result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            self._note_locked_target_missing()
            return Target()

        center = np.array(geometry.screen_center, dtype=np.float64)
        candidates: list[tuple[float, Target]] = []
        for box in boxes:
            class_id = int(box.cls[0].item())
            label = self.model.names.get(class_id, str(class_id))
            if label not in self.config.class_priority:
                continue
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            local_x = (x1 + x2) * 0.5
            local_y = (y1 + y2) * 0.5
            screen_x, screen_y = geometry.crop_to_screen(local_x, local_y)
            confidence = float(box.conf[0].item())
            track_id = None
            box_track_id = getattr(box, "id", None)
            if box_track_id is not None:
                track_id = int(box_track_id[0].item())
            minimum_confidence = self.config.confidence
            if track_id is not None and track_id == self._locked_track_id:
                minimum_confidence = self.config.locked_target_confidence
            if confidence < minimum_confidence:
                continue
            distance_from_center = np.linalg.norm(np.array([screen_x, screen_y]) - center)
            distance_from_last = 0.0
            if self._last_target and self._last_target.cx is not None and self._last_target.cy is not None:
                distance_from_last = float(
                    np.linalg.norm(
                        np.array([screen_x - self._last_target.cx, screen_y - self._last_target.cy])
                    )
                )
            class_rank = self.config.class_priority[label]
            box_area = max(1.0, (x2 - x1) * (y2 - y1))
            score = float(distance_from_center)
            score += class_rank * self.config.class_rank_penalty
            score -= confidence * 30.0
            score -= np.sqrt(box_area) * self.config.box_size_bonus
            if track_id is None:
                score += distance_from_last * 0.35
            candidates.append(
                (
                    score,
                    Target(
                        found=True,
                        track_id=track_id,
                        label=label,
                        cx=screen_x,
                        cy=screen_y,
                        confidence=confidence,
                        box=(int(x1), int(y1), int(x2), int(y2)),
                    ),
                )
            )

        if not candidates:
            self._note_locked_target_missing()
            return Target()

        candidates.sort(key=lambda item: item[0])
        best_score, target = candidates[0]
        if self.config.target_lock_enabled and self._locked_track_id is not None:
            locked = next(
                (item for item in candidates if item[1].track_id == self._locked_track_id),
                None,
            )
            if locked is not None:
                locked_score, locked_target = locked
                if best_score + self.config.target_switch_score_margin >= locked_score:
                    target = locked_target
                self._locked_track_misses = 0
            elif self._locked_track_misses < self.config.target_lock_miss_frames:
                self._locked_track_misses += 1
                return Target()

        self._locked_track_id = target.track_id
        self._locked_track_misses = 0
        self._last_target = target
        return target

    def _note_locked_target_missing(self) -> None:
        if self._locked_track_id is None:
            return
        self._locked_track_misses += 1
        if self._locked_track_misses > self.config.target_lock_miss_frames:
            self._locked_track_id = None
            self._locked_track_misses = 0
