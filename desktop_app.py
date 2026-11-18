from __future__ import annotations

import queue
import sys
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from mymain_app.config import AppConfig


ACTIVATION_KEYS = {
    "鼠标左键": 0x01,
    "鼠标右键": 0x02,
    "鼠标中键": 0x04,
    "鼠标侧键 1": 0x05,
    "鼠标侧键 2": 0x06,
    "Shift": 0x10,
    "Ctrl": 0x11,
    "Alt": 0x12,
}
IB_SEND_TYPES = {
    "LogitechGHubNew": 6,
    "LogitechLegacy": 2,
    "SendInput": 1,
}


class QueueStream:
    def __init__(self, output_queue: queue.Queue[str]):
        self.output_queue = output_queue

    def write(self, text: str) -> int:
        if text:
            self.output_queue.put(text)
        return len(text)

    def flush(self) -> None:
        return None


class ControlPanel:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.config = AppConfig()
        self.app: Any | None = None
        self.preview: Any | None = None
        self.preview_thread: threading.Thread | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.busy = False

        self.model_path = tk.StringVar(value=str(self.config.detection.model_path))
        self.mouse_mode = tk.StringVar(value=self.config.mouse.mode)
        self.ib_send_type = tk.StringVar(
            value=next(
                (name for name, value in IB_SEND_TYPES.items() if value == self.config.mouse.preferred_send_type),
                "LogitechGHubNew",
            )
        )
        self.activation_key = tk.StringVar(value="鼠标右键")
        self.show_preview = tk.BooleanVar(value=True)
        self.status_text = tk.StringVar(value="已停止")
        self.backend_text = tk.StringVar(value="尚未初始化")

        self._configure_window()
        self._build_ui()
        self._install_log_streams()
        self.root.report_callback_exception = self._report_callback_exception
        self._schedule_updates()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _configure_window(self) -> None:
        self.root.title("YOLO Vision Control")
        self.root.geometry("940x680")
        self.root.minsize(780, 560)
        self.root.configure(bg="#f4f6f8")

        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Subtitle.TLabel", font=("Microsoft YaHei UI", 9), foreground="#52606d")
        style.configure("Status.TLabel", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TButton", font=("Microsoft YaHei UI", 9), padding=(12, 7))
        style.configure("TLabel", font=("Microsoft YaHei UI", 9))
        style.configure("TCheckbutton", font=("Microsoft YaHei UI", 9))
        style.configure("TLabelframe.Label", font=("Microsoft YaHei UI", 9, "bold"))

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=18)
        container.grid(row=0, column=0, sticky="nsew")
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)

        header = ttk.Frame(container)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="YOLO Vision Control", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="独立运行控制面板 · DXCam / YOLO / ByteTrack",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        status_frame = ttk.Frame(header)
        status_frame.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Label(status_frame, text="状态").grid(row=0, column=0, sticky="e", padx=(0, 8))
        ttk.Label(status_frame, textvariable=self.status_text, style="Status.TLabel").grid(
            row=0, column=1, sticky="e"
        )
        ttk.Label(status_frame, textvariable=self.backend_text, style="Subtitle.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="e", pady=(4, 0)
        )

        settings = ttk.LabelFrame(container, text="运行配置", padding=12)
        settings.grid(row=1, column=0, sticky="ew")
        settings.columnconfigure(1, weight=1)

        ttk.Label(settings, text="识别模型").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.model_entry = ttk.Entry(settings, textvariable=self.model_path)
        self.model_entry.grid(row=0, column=1, sticky="ew")
        ttk.Button(settings, text="浏览...", command=self.browse_model).grid(row=0, column=2, padx=(8, 0))

        ttk.Label(settings, text="输出方式").grid(row=1, column=0, sticky="w", pady=(12, 0), padx=(0, 10))
        options = ttk.Frame(settings)
        options.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(12, 0))
        options.columnconfigure(4, weight=1)
        self.mode_box = ttk.Combobox(
            options, textvariable=self.mouse_mode, values=("ib", "pyautogui"), state="readonly", width=18
        )
        self.mode_box.grid(row=0, column=0, sticky="w")
        self.mode_box.bind("<<ComboboxSelected>>", lambda _event: self._sync_backend_controls())

        ttk.Label(options, text="激活按键").grid(row=0, column=1, padx=(22, 8))
        self.key_box = ttk.Combobox(
            options,
            textvariable=self.activation_key,
            values=tuple(ACTIVATION_KEYS),
            state="readonly",
            width=16,
        )
        self.key_box.grid(row=0, column=2)
        ttk.Checkbutton(options, text="显示识别预览", variable=self.show_preview).grid(
            row=0, column=3, sticky="e", padx=(22, 0)
        )

        ttk.Label(settings, text="IbInput 发送类型").grid(
            row=2, column=0, sticky="w", pady=(12, 0), padx=(0, 10)
        )
        self.ib_send_type_box = ttk.Combobox(
            settings,
            textvariable=self.ib_send_type,
            values=tuple(IB_SEND_TYPES),
            state="readonly",
            width=22,
        )
        self.ib_send_type_box.grid(row=2, column=1, sticky="w", pady=(12, 0))
        ttk.Label(
            settings,
            text="初始化成功但无移动时，请依次尝试 Legacy 和 SendInput",
            style="Subtitle.TLabel",
        ).grid(row=2, column=2, sticky="e", pady=(12, 0))
        self._sync_backend_controls()

        actions = ttk.Frame(container)
        actions.grid(row=2, column=0, sticky="ew", pady=14)
        actions.columnconfigure(3, weight=1)
        self.check_button = ttk.Button(actions, text="检查环境", command=self.check_environment)
        self.check_button.grid(row=0, column=0, padx=(0, 8))
        self.start_button = ttk.Button(actions, text="启动", command=self.start)
        self.start_button.grid(row=0, column=1, padx=(0, 8))
        self.stop_button = ttk.Button(actions, text="停止", command=self.stop, state="disabled")
        self.stop_button.grid(row=0, column=2)
        ttk.Label(actions, text="运行时按住所选激活键才会输出移动", style="Subtitle.TLabel").grid(
            row=0, column=3, sticky="e"
        )

        log_frame = ttk.LabelFrame(container, text="运行日志", padding=8)
        log_frame.grid(row=3, column=0, sticky="nsew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log_text = tk.Text(
            log_frame,
            wrap="word",
            state="disabled",
            bg="#111827",
            fg="#d1fae5",
            insertbackground="#ffffff",
            font=("Cascadia Mono", 9),
            relief="flat",
            padx=10,
            pady=10,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _install_log_streams(self) -> None:
        stream = QueueStream(self.log_queue)
        sys.stdout = stream
        sys.stderr = stream
        print("控制面板已就绪。请先检查环境，再启动。", flush=True)

    def _report_callback_exception(self, exc_type, exc_value, exc_traceback) -> None:
        print("".join(traceback.format_exception(exc_type, exc_value, exc_traceback)), flush=True)
        self.status_text.set("界面错误")
        messagebox.showerror("界面错误", "操作执行失败，详细信息已写入运行日志。")

    def _schedule_updates(self) -> None:
        self._drain_logs()
        self._refresh_runtime_status()
        self.root.after(150, self._schedule_updates)

    def _drain_logs(self) -> None:
        chunks: list[str] = []
        while True:
            try:
                chunks.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        if chunks:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", "".join(chunks))
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

    def _refresh_runtime_status(self) -> None:
        running = bool(self.app and self.app.pipeline and self.app.pipeline.is_running())
        if running:
            self.status_text.set("运行中")
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
        elif not self.busy:
            if self.status_text.get() == "运行中":
                self.status_text.set("已停止")
                self.backend_text.set("运行已结束，请查看日志")
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")

    def browse_model(self) -> None:
        selected = filedialog.askopenfilename(
            title="选择 YOLO 模型",
            filetypes=(("YOLO 模型", "*.engine *.pt *.onnx"), ("所有文件", "*.*")),
        )
        if selected:
            self.model_path.set(selected)

    def _apply_settings(self) -> None:
        self.config.detection.model_path = Path(self.model_path.get()).expanduser().resolve()
        self.config.mouse.mode = self.mouse_mode.get()
        self.config.mouse.preferred_send_type = IB_SEND_TYPES[self.ib_send_type.get()]
        self.config.mouse.activation_key = ACTIVATION_KEYS[self.activation_key.get()]
        self.config.output.show_preview = self.show_preview.get()

    def _sync_backend_controls(self) -> None:
        state = "readonly" if self.mouse_mode.get() == "ib" and not self.busy else "disabled"
        self.ib_send_type_box.configure(state=state)

    @staticmethod
    def _load_runtime():
        # Import NumPy first to keep Intel OpenMP initialization deterministic in
        # mixed Conda/PyPI environments, then load the heavier YOLO runtime.
        import numpy  # noqa: F401

        from mymain_app.app import Application, check_dependencies
        from mymain_app.preview import Preview

        return Application, check_dependencies, Preview

    def _set_busy(self, value: bool, status: str) -> None:
        self.busy = value
        self.status_text.set(status)
        state = "disabled" if value else "normal"
        self.check_button.configure(state=state)
        self.start_button.configure(state=state)
        self.mode_box.configure(state="disabled" if value else "readonly")
        self.key_box.configure(state="disabled" if value else "readonly")
        self._sync_backend_controls()
        self.model_entry.configure(state=state)

    def check_environment(self) -> None:
        if self.busy:
            return
        self._apply_settings()
        self._set_busy(True, "检查中")
        print("\n[check] 正在检查依赖和模型...", flush=True)

        def worker() -> None:
            try:
                _, check_dependencies, _ = self._load_runtime()
                errors = check_dependencies(self.config, load_model=True)
                if errors:
                    for error in errors:
                        print(f"[check] {error}", flush=True)
                    self.root.after(0, lambda: self._finish_check(False))
                else:
                    print("[check] 依赖和模型加载正常。", flush=True)
                    self.root.after(0, lambda: self._finish_check(True))
            except Exception:
                print(traceback.format_exc(), flush=True)
                self.root.after(0, lambda: self._finish_check(False))

        threading.Thread(target=worker, name="dependency-check", daemon=True).start()

    def _finish_check(self, passed: bool) -> None:
        self._set_busy(False, "检查通过" if passed else "检查失败")

    def start(self) -> None:
        if self.busy or (self.app and self.app.pipeline and self.app.pipeline.is_running()):
            return
        self._apply_settings()
        self._set_busy(True, "启动中")
        print("\n[start] 正在初始化采集、模型和输出后端...", flush=True)

        def worker() -> None:
            try:
                Application, _, Preview = self._load_runtime()
                self.app = Application(self.config)
                self.app.start()
                if self.config.output.show_preview and self.app.pipeline is not None:
                    self.preview = Preview(self.config.output)
                    self.preview_thread = threading.Thread(
                        target=self.preview.run,
                        args=(self.app.pipeline,),
                        name="desktop-preview",
                        daemon=True,
                    )
                    self.preview_thread.start()
                backend = self.app.pipeline.mouse.description if self.app.pipeline else "未知后端"
                self.root.after(0, lambda: self._finish_start(backend))
            except Exception:
                print(traceback.format_exc(), flush=True)
                if self.app is not None:
                    self.app.stop()
                self.root.after(0, self._fail_start)

        threading.Thread(target=worker, name="application-start", daemon=True).start()

    def _finish_start(self, backend: str) -> None:
        self.backend_text.set(backend)
        self._set_busy(False, "运行中")
        self.stop_button.configure(state="normal")

    def _fail_start(self) -> None:
        self.backend_text.set("初始化失败，请查看日志")
        self._set_busy(False, "启动失败")
        messagebox.showerror("启动失败", "程序未能启动，请查看窗口中的运行日志。")

    def stop(self) -> None:
        if self.busy:
            return
        self._set_busy(True, "停止中")

        def worker() -> None:
            try:
                if self.preview is not None:
                    self.preview.stop()
                if self.app is not None:
                    self.app.stop()
                print("[stop] 程序已停止。", flush=True)
            finally:
                self.app = None
                self.preview = None
                self.preview_thread = None
                self.root.after(0, self._finish_stop)

        threading.Thread(target=worker, name="application-stop", daemon=True).start()

    def _finish_stop(self) -> None:
        self.backend_text.set("尚未初始化")
        self._set_busy(False, "已停止")

    def close(self) -> None:
        if self.preview is not None:
            self.preview.stop()
        if self.app is not None:
            self.app.stop()
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    ControlPanel(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
