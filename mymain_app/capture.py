from __future__ import annotations

import ctypes
from typing import Protocol

import numpy as np

from .logging_utils import DebugLogger


class CaptureBackend(Protocol):
    @property
    def source_size(self) -> tuple[int, int]: ...

    def get_latest_frame(self): ...

    def stop(self) -> None: ...


def get_screen_size() -> tuple[int, int]:
    try:
        import win32api

        return int(win32api.GetSystemMetrics(0)), int(win32api.GetSystemMetrics(1))
    except Exception:
        return 1920, 1080


class DxcamCapture:
    def __init__(self, screen_size: tuple[int, int]):
        try:
            import dxcam
        except ImportError as exc:
            raise RuntimeError("dxcam is required for standalone capture") from exc
        self._camera = dxcam.create()
        if self._camera is None:
            raise RuntimeError("dxcam.create() did not return a camera")
        self._camera.start()
        self._source_size = screen_size

    @property
    def source_size(self) -> tuple[int, int]:
        return self._source_size

    def get_latest_frame(self):
        return self._camera.get_latest_frame()

    def stop(self) -> None:
        stop = getattr(self._camera, "stop", None)
        if callable(stop):
            stop()


class ObsSourceCapture:
    """Read a named OBS source into a BGR numpy array."""

    def __init__(self, obs, source_name: str, logger: DebugLogger):
        self.obs = obs
        self.logger = logger
        self.source = None
        self.texrender = None
        self.stagesurf = None
        self.width = 0
        self.height = 0
        self._obs_dll = None
        self._warned_missing_stage = False
        self._start(source_name)

    @property
    def source_size(self) -> tuple[int, int]:
        return self.width, self.height

    def _start(self, source_name: str) -> None:
        if not source_name:
            raise ValueError("OBS source name is empty")
        self.source = self.obs.obs_get_source_by_name(source_name)
        if not self.source:
            raise RuntimeError(f"OBS source not found: {source_name}")
        self._update_size()
        self.obs.obs_enter_graphics()
        try:
            self.texrender = self.obs.gs_texrender_create(self.obs.GS_RGBA, self.obs.GS_ZS_NONE)
        finally:
            self.obs.obs_leave_graphics()
        if self.texrender is None:
            self.stop()
            raise RuntimeError("Failed to create OBS texture renderer")

    def _update_size(self) -> None:
        if self.source is None:
            return
        width = int(self.obs.obs_source_get_width(self.source) or 0)
        height = int(self.obs.obs_source_get_height(self.source) or 0)
        if width <= 0 or height <= 0 or (width == self.width and height == self.height):
            return
        self.width, self.height = width, height
        self.obs.obs_enter_graphics()
        try:
            if self.stagesurf is not None:
                self.obs.gs_stagesurface_destroy(self.stagesurf)
            self.stagesurf = self.obs.gs_stagesurface_create(width, height, self.obs.GS_RGBA)
        finally:
            self.obs.obs_leave_graphics()

    def get_latest_frame(self):
        self._update_size()
        if self.source is None or self.texrender is None or self.stagesurf is None:
            return None
        self.obs.obs_enter_graphics()
        try:
            reset = getattr(self.obs, "gs_texrender_reset", None)
            if callable(reset):
                reset(self.texrender)
            if not self.obs.gs_texrender_begin(self.texrender, self.width, self.height):
                self.logger.every("obs_texrender", "OBS texture renderer is not ready")
                return None
            try:
                self.obs.gs_clear(self.obs.GS_CLEAR_COLOR, self.obs.vec4(), 0.0, 0)
                self.obs.gs_ortho(0.0, float(self.width), 0.0, float(self.height), -100.0, 100.0)
                self.obs.obs_source_video_render(self.source)
            finally:
                self.obs.gs_texrender_end(self.texrender)

            texture = self.obs.gs_texrender_get_texture(self.texrender)
            if texture is None or not self._stage_texture(texture):
                return None
            flush = getattr(self.obs, "gs_flush", None)
            if callable(flush):
                flush()
            mapped = self._map_stage_surface()
            if mapped is None:
                return None
            data, linesize = mapped
            try:
                pixels = np.frombuffer(data, dtype=np.uint8)
                pixels = pixels.reshape((self.height, linesize // 4, 4))[:, : self.width, :]
                return pixels[:, :, :3][:, :, ::-1].copy()
            finally:
                self._unmap_stage_surface()
        finally:
            self.obs.obs_leave_graphics()

    def _stage_texture(self, texture) -> bool:
        for name in ("gs_stage_texture", "gs_stage_surface"):
            stage = getattr(self.obs, name, None)
            if callable(stage):
                stage(self.stagesurf, texture)
                return True
        if not self._warned_missing_stage:
            self._warned_missing_stage = True
            print("Warning: OBS has no texture staging function")
        return False

    def _map_stage_surface(self):
        try:
            mapped = self.obs.gs_stagesurface_map(self.stagesurf)
        except TypeError:
            return self._map_stage_surface_ctypes()
        if not mapped:
            return None
        data, linesize = mapped, 0
        if isinstance(mapped, tuple):
            if len(mapped) == 3:
                ok, data, linesize = mapped
                if not ok:
                    return None
            elif len(mapped) == 2:
                data, linesize = mapped
            elif len(mapped) == 1:
                data = mapped[0]
            else:
                return None
        if not linesize:
            get_linesize = getattr(self.obs, "gs_stagesurface_get_linesize", None)
            linesize = int(get_linesize(self.stagesurf)) if callable(get_linesize) else self.width * 4
        return data, int(linesize)

    def _map_stage_surface_ctypes(self):
        dll = self._get_obs_dll()
        address = self._swig_ptr_address(self.stagesurf)
        if dll is None or not address:
            return None
        data_pointer = ctypes.c_void_p()
        linesize = ctypes.c_uint32()
        ok = dll.gs_stagesurface_map(
            ctypes.c_void_p(address), ctypes.byref(data_pointer), ctypes.byref(linesize)
        )
        if not ok or not data_pointer.value or linesize.value <= 0:
            return None
        buffer_type = ctypes.c_ubyte * (int(linesize.value) * self.height)
        return buffer_type.from_address(data_pointer.value), int(linesize.value)

    def _unmap_stage_surface(self) -> None:
        address = self._swig_ptr_address(self.stagesurf)
        if self._obs_dll is not None and address:
            self._obs_dll.gs_stagesurface_unmap(ctypes.c_void_p(address))
        else:
            self.obs.gs_stagesurface_unmap(self.stagesurf)

    def _get_obs_dll(self):
        if self._obs_dll is not None:
            return self._obs_dll
        try:
            dll = ctypes.CDLL("obs.dll")
            dll.gs_stagesurface_map.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(ctypes.c_uint32),
            ]
            dll.gs_stagesurface_map.restype = ctypes.c_bool
            dll.gs_stagesurface_unmap.argtypes = [ctypes.c_void_p]
            dll.gs_stagesurface_unmap.restype = None
            self._obs_dll = dll
        except OSError:
            self._obs_dll = None
        return self._obs_dll

    @staticmethod
    def _swig_ptr_address(value) -> int:
        if value is None:
            return 0
        pointer = getattr(value, "this", value)
        try:
            return int(pointer)
        except (TypeError, ValueError):
            text = repr(pointer)
            marker = " at 0x"
            index = text.rfind(marker)
            if index < 0:
                return 0
            end = text.find(">", index)
            try:
                return int(text[index + 4 : end if end >= 0 else None], 16)
            except ValueError:
                return 0

    def stop(self) -> None:
        if self.source is None:
            return
        self.obs.obs_enter_graphics()
        try:
            if self.stagesurf is not None:
                self.obs.gs_stagesurface_destroy(self.stagesurf)
                self.stagesurf = None
            if self.texrender is not None:
                self.obs.gs_texrender_destroy(self.texrender)
                self.texrender = None
        finally:
            self.obs.obs_leave_graphics()
        self.obs.obs_source_release(self.source)
        self.source = None
