from __future__ import annotations

import ctypes
import importlib
import sys
import threading
import traceback
from pathlib import Path

from .capture import DxcamCapture, ObsSourceCapture, get_screen_size
from .config import AppConfig
from .detector import YoloDetector
from .logging_utils import DebugLogger
from .mouse_input import create_mouse_input
from .pipeline import Pipeline
from .preview import Preview


class Application:
    def __init__(self, config: AppConfig | None = None, obs=None):
        self.config = config or AppConfig()
        self.obs = obs
        self.logger = DebugLogger(self.config.output.debug, self.config.output.debug_interval_s)
        self.pipeline: Pipeline | None = None
        self.preview: Preview | None = None
        self._preview_thread: threading.Thread | None = None

    @property
    def running_in_obs(self) -> bool:
        return self.obs is not None

    def start(self) -> None:
        if self.pipeline is not None and self.pipeline.is_running():
            self.sync_preview()
            return
        screen_size = get_screen_size()
        capture = (ObsSourceCapture(self.obs, self.config.obs_source_name, self.logger)
                   if self.running_in_obs else DxcamCapture(screen_size))
        try:
            detector = YoloDetector(self.config.detection)
            self.logger.log(f"detector initialized: {detector.description}")
            mouse = create_mouse_input(self.config.mouse)
            self.logger.log(
                f"mouse input initialized: {mouse.description} "
                f"(mode={self.config.mouse.mode.strip().lower()})"
            )
        except Exception:
            capture.stop()
            raise
        self.pipeline = Pipeline(self.config, capture, detector, mouse, screen_size, self.logger)
        self.pipeline.start()
        if self.running_in_obs and self.config.output.show_preview:
            self._start_preview_thread()

    def sync_preview(self) -> None:
        if not self.running_in_obs or self.pipeline is None or not self.pipeline.is_running():
            return
        if self.config.output.show_preview:
            self._start_preview_thread()
        else:
            self._stop_preview_thread()

    def _start_preview_thread(self) -> None:
        if self.pipeline is None:
            return
        if self._preview_thread is not None and self._preview_thread.is_alive():
            return
        self.preview = Preview(self.config.output)

        def run_preview() -> None:
            try:
                self.logger.log("OBS recognition inspector thread started; press F8 to toggle")
                self.preview.run(self.pipeline)
            except Exception:
                self.logger.log(f"recognition inspector crashed:\n{traceback.format_exc()}")

        self._preview_thread = threading.Thread(
            target=run_preview,
            name="recognition-preview",
            daemon=True,
        )
        self._preview_thread.start()

    def _stop_preview_thread(self) -> None:
        if self.preview is not None:
            self.preview.stop()
        if self._preview_thread is not None and self._preview_thread is not threading.current_thread():
            self._preview_thread.join(timeout=2.0)
        self._preview_thread = None
        self.preview = None

    def run_foreground(self) -> None:
        self.start()
        if self.config.output.show_preview:
            Preview(self.config.output).run(self.pipeline)
        else:
            try:
                while self.pipeline and self.pipeline.is_running():
                    self.pipeline.stop_event.wait(0.5)
            except KeyboardInterrupt:
                pass

    def stop(self) -> None:
        if self.pipeline is not None:
            self.pipeline.stop()
            self.pipeline = None
        self._stop_preview_thread()


def check_dependencies(config: AppConfig, load_model: bool = True) -> list[str]:
    errors: list[str] = []
    modules = {"numpy": "numpy", "OpenCV": "cv2", "DXcam": "dxcam",
               "PyWin32": "win32api", "Ultralytics": "ultralytics"}
    if config.detection.tracking_enabled:
        modules["ByteTrack assignment"] = "lap"
    if config.mouse.mode.strip().lower() == "pyautogui":
        modules["PyAutoGUI"] = "pyautogui"
    for label, module_name in modules.items():
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{label}: {exc}")
    paths = [("model", config.detection.model_path)]
    if config.mouse.mode.strip().lower() == "ib":
        paths.append(("IbInputSimulator DLL", config.mouse.dll_path))
    elif config.mouse.mode.strip().lower() != "pyautogui":
        errors.append(
            f"mouse mode must be 'ib' or 'pyautogui', got {config.mouse.mode!r}"
        )
    for label, path in paths:
        if not Path(path).is_file():
            errors.append(f"{label} not found: {path}")
    if load_model and not errors:
        try:
            YoloDetector(config.detection)
        except Exception as exc:
            errors.append(f"model load: {exc}")
    return errors


def relaunch_as_admin() -> bool:
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return False
        arguments = " ".join(f'"{argument}"' for argument in sys.argv)
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable,
                                                     arguments, None, 1)
        return result > 32
    except Exception:
        return False
