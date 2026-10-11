from __future__ import annotations

import ctypes
from typing import Protocol

from .config import MouseConfig


MOVE_RELATIVE = 1
ERR_SUCCESS = 0
SEND_TYPE_NAMES = {
    0: "AnyDriver",
    1: "SendInput",
    2: "LogitechLegacy",
    3: "Razer",
    4: "DD",
    5: "MouClassInputInjection",
    6: "LogitechGHubNew",
}


class MouseInput(Protocol):
    @property
    def description(self) -> str: ...

    def is_activation_pressed(self) -> bool: ...

    def move_relative(self, dx: int, dy: int) -> bool: ...

    def close(self) -> None: ...


def _load_win32api():
    try:
        import win32api
    except ImportError as exc:
        raise RuntimeError("pywin32 is required for activation-key polling") from exc
    return win32api


class IbMouseInput:
    """IbInputSimulator-backed relative mouse input."""

    def __init__(self, config: MouseConfig):
        if not config.dll_path.is_file():
            raise FileNotFoundError(f"IbInputSimulator DLL not found: {config.dll_path}")

        self.config = config
        self._win32api = _load_win32api()
        self._dll = ctypes.WinDLL(str(config.dll_path))
        self._closed = False
        self._bind_functions()
        self.active_send_type = config.preferred_send_type
        error = int(self._dll.IbSendInit(config.preferred_send_type, 0, None))
        if error != ERR_SUCCESS:
            self.active_send_type = config.fallback_send_type
            error = int(self._dll.IbSendInit(config.fallback_send_type, 0, None))
        if error != ERR_SUCCESS:
            self._closed = True
            raise RuntimeError(f"IbInputSimulator initialization failed: error={error}")

    @property
    def description(self) -> str:
        send_type = SEND_TYPE_NAMES.get(self.active_send_type, str(self.active_send_type))
        return f"IbMouseInput/{send_type}"

    def _bind_functions(self) -> None:
        self._dll.IbSendInit.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        self._dll.IbSendInit.restype = ctypes.c_uint32
        self._dll.IbSendDestroy.argtypes = []
        self._dll.IbSendDestroy.restype = None
        self._dll.IbSendMouseMove.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
        self._dll.IbSendMouseMove.restype = ctypes.c_bool

    def is_activation_pressed(self) -> bool:
        return (self._win32api.GetAsyncKeyState(self.config.activation_key) & 0x8000) != 0

    def move_relative(self, dx: int, dy: int) -> bool:
        if self._closed:
            return False
        return bool(
            self._dll.IbSendMouseMove(dx & 0xFFFFFFFF, dy & 0xFFFFFFFF, MOVE_RELATIVE)
        )

    def close(self) -> None:
        if not self._closed:
            self._dll.IbSendDestroy()
            self._closed = True

    def __enter__(self) -> "IbMouseInput":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


class PyAutoGuiMouseInput:
    """PyAutoGUI-backed relative mouse input with Win32 activation polling."""

    def __init__(self, config: MouseConfig):
        try:
            import pyautogui
        except ImportError as exc:
            raise RuntimeError("pyautogui is required for the pyautogui mouse mode") from exc

        self.config = config
        self._win32api = _load_win32api()
        self._pyautogui = pyautogui
        self._old_pause = pyautogui.PAUSE
        self._old_failsafe = pyautogui.FAILSAFE
        pyautogui.PAUSE = max(0.0, float(config.pyautogui_pause_s))
        pyautogui.FAILSAFE = bool(config.pyautogui_failsafe)
        self._closed = False

    @property
    def description(self) -> str:
        return "PyAutoGuiMouseInput"

    def is_activation_pressed(self) -> bool:
        return (self._win32api.GetAsyncKeyState(self.config.activation_key) & 0x8000) != 0

    def move_relative(self, dx: int, dy: int) -> bool:
        if self._closed:
            return False
        try:
            self._pyautogui.moveRel(int(dx), int(dy), duration=0, _pause=False)
            return True
        except self._pyautogui.FailSafeException:
            return False

    def close(self) -> None:
        if self._closed:
            return
        self._pyautogui.PAUSE = self._old_pause
        self._pyautogui.FAILSAFE = self._old_failsafe
        self._closed = True

    def __enter__(self) -> "PyAutoGuiMouseInput":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


def create_mouse_input(config: MouseConfig) -> MouseInput:
    mode = config.mode.strip().lower()
    if mode == "ib":
        return IbMouseInput(config)
    if mode == "pyautogui":
        return PyAutoGuiMouseInput(config)
    raise ValueError(
        f"Unsupported mouse input mode: {config.mode!r}. Use 'ib' or 'pyautogui'."
    )
