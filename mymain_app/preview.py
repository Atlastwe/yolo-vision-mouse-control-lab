from __future__ import annotations

import json
import queue
import threading
import time

from .config import OutputConfig


class Preview:
    def __init__(self, config: OutputConfig):
        import cv2
        import win32api

        self.cv2 = cv2
        self.win32api = win32api
        self.config = config
        self.window_name = "model recognition inspector"
        self.visible = config.preview_visible_at_start
        self._window_created = False
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def _open_window(self, frame) -> None:
        if self._window_created:
            return
        cv2 = self.cv2
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        height, width = frame.shape[:2]
        window_width = max(320, self.config.preview_window_width)
        window_height = max(180, int(window_width * height / max(1, width)))
        cv2.resizeWindow(self.window_name, window_width, window_height)
        self._window_created = True

    def _close_window(self) -> None:
        if self._window_created:
            try:
                self.cv2.destroyWindow(self.window_name)
            except self.cv2.error:
                pass
        self._window_created = False

    def _poll_visibility_toggle(self) -> None:
        if self.win32api.GetAsyncKeyState(self.config.preview_toggle_key) & 1:
            self.visible = not self.visible
            if not self.visible:
                self._close_window()
            state = "shown" if self.visible else "hidden"
            print(f"recognition inspector: {state}")

    @staticmethod
    def _box_track_id(box) -> int | None:
        value = getattr(box, "id", None)
        return None if value is None else int(value[0].item())

    def run(self, pipeline) -> None:
        cv2 = self.cv2
        last_output, last_write_at, last_log_at = None, 0.0, 0.0
        fps_started, fps_frames, fps = time.perf_counter(), 0, 0.0
        print("recognition inspector: press F8 to show or hide")
        try:
            while pipeline.is_running() and not self._stop_event.is_set():
                self._poll_visibility_toggle()
                try:
                    frame, result, target, geometry = pipeline.result_queue.get(timeout=0.05)
                except queue.Empty:
                    if self.visible and cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                    continue
                output = {"found": target.found, "track_id": target.track_id,
                          "label": target.label, "cx": target.cx,
                          "cy": target.cy, "conf": target.confidence}
                now = time.perf_counter()
                if output != last_output or now - last_write_at >= self.config.json_write_interval_s:
                    with self.config.json_path.open("w", encoding="utf-8") as file:
                        json.dump(output, file, separators=(",", ":"))
                    last_output, last_write_at = output.copy(), now
                if now - last_log_at >= self.config.log_interval_s:
                    print(f"target=({target.cx:.0f},{target.cy:.0f}) id={target.track_id} "
                          f"label={target.label} conf={target.confidence:.2f}"
                          if target.found else "no target")
                    last_log_at = now
                boxes = getattr(result, "boxes", None)
                if self.visible and self.config.preview_draw_all_detections and boxes is not None:
                    for box in boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        class_id = int(box.cls[0].item())
                        names = getattr(result, "names", {})
                        label = names.get(class_id, str(class_id))
                        confidence = float(box.conf[0].item())
                        track_id = self._box_track_id(box)
                        text = f"{label} {confidence:.2f} id={track_id}"
                        cv2.putText(frame, text, (x1, max(16, y1 - 5)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)
                if self.visible and target.box is not None:
                    x1, y1, x2, y2 = target.box
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                    cv2.circle(frame, ((x1 + x2) // 2, (y1 + y2) // 2), 4, (0, 0, 255), -1)
                    cv2.putText(frame, f"{target.label} id={target.track_id} "
                                f"({target.cx:.0f}, {target.cy:.0f})",
                                (x1, max(20, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX,
                                0.6, (0, 0, 255), 2)
                fps_frames += 1
                elapsed = now - fps_started
                if elapsed >= 0.5:
                    fps, fps_started, fps_frames = fps_frames / elapsed, now, 0
                if self.visible:
                    self._open_window(frame)
                    cv2.drawMarker(frame, geometry.local_center, (255, 255, 0),
                                   cv2.MARKER_CROSS, 20, 1)
                    cv2.putText(frame, f"FPS {fps:.1f} | F8 hide | Q quit", (10, 25),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
                    cv2.imshow(self.window_name, frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                    try:
                        if cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE) < 1:
                            self.visible = False
                            self._window_created = False
                    except cv2.error:
                        self.visible = False
                        self._window_created = False
        finally:
            self._close_window()
