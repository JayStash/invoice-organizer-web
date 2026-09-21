"""Windows desktop entry point backed by FastAPI and pywebview."""

from __future__ import annotations

import ctypes
import socket
import threading
import time
from ctypes import wintypes
from typing import Any

import uvicorn

from app.runtime import configure_core_runtime, is_frozen


HOST = "127.0.0.1"
PORT = 8000
APP_URL = f"http://{HOST}:{PORT}"
MUTEX_NAME = r"Local\InvoiceOrganizer.Desktop.6A32F2E4-CC14-4A36-BA74-EB5D276991E8"
ERROR_ALREADY_EXISTS = 183
MB_OK = 0x00000000
MB_ICONERROR = 0x00000010
MB_ICONINFORMATION = 0x00000040
MB_SETFOREGROUND = 0x00010000


def show_message(message: str, *, error: bool = False) -> None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.MessageBoxW.argtypes = (
        wintypes.HWND,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.UINT,
    )
    user32.MessageBoxW.restype = ctypes.c_int
    icon = MB_ICONERROR if error else MB_ICONINFORMATION
    user32.MessageBoxW(None, message, "发票整理工具", MB_OK | icon | MB_SETFOREGROUND)


class SingleInstance:
    def __init__(self, name: str = MUTEX_NAME) -> None:
        self.name = name
        self._handle: int | None = None
        self._kernel32: Any = None

    def acquire(self) -> bool:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        )
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False

        self._kernel32 = kernel32
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is not None:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


def port_is_available(host: str = HOST, port: int = PORT) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def configure_webview(webview_module: Any) -> None:
    webview_module.settings["ALLOW_DOWNLOADS"] = True


class FastAPIServer:
    def __init__(self, application: Any, host: str = HOST, port: int = PORT) -> None:
        config = uvicorn.Config(
            application,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(
            target=self.server.run,
            name="invoice-organizer-fastapi",
            daemon=True,
        )
        self._stop_lock = threading.Lock()
        self._stop_requested = False

    def start(self, timeout: float = 10.0) -> None:
        self.thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.server.started:
                return
            if not self.thread.is_alive():
                raise RuntimeError("FastAPI 服务启动失败，127.0.0.1:8000 可能已被占用。")
            time.sleep(0.05)
        self.stop()
        raise RuntimeError("FastAPI 服务启动超时。")

    def stop(self, timeout: float = 10.0) -> None:
        with self._stop_lock:
            if not self._stop_requested:
                self._stop_requested = True
                self.server.should_exit = True

        if self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(timeout)
            if self.thread.is_alive():
                self.server.force_exit = True
                self.thread.join(timeout)


def main() -> int:
    instance = SingleInstance()
    server: FastAPIServer | None = None
    try:
        try:
            acquired = instance.acquire()
        except OSError:
            show_message(
                "无法启动发票整理工具：单实例检查失败。\n请重启电脑后重试。",
                error=True,
            )
            return 1

        if not acquired:
            show_message("发票整理工具已在运行，请勿重复启动。")
            return 0

        if not port_is_available():
            show_message(
                "无法启动发票整理工具：127.0.0.1:8000 端口已被其他程序占用。\n"
                "请关闭占用该端口的程序后重试。",
                error=True,
            )
            return 1

        try:
            import webview

            configure_webview(webview)
            configure_core_runtime()
            from app.main import app

            server = FastAPIServer(app)
            server.start()
            window = webview.create_window(
                "发票整理工具",
                APP_URL,
                width=1280,
                height=820,
                min_size=(960, 640),
            )

            def close_server(*_: object) -> None:
                server.stop()

            window.events.closed += close_server
            webview.start(gui="edgechromium", debug=not is_frozen())
        except Exception:
            show_message(
                "发票整理工具启动失败。\n"
                "请确认 127.0.0.1:8000 端口未被占用后重试。",
                error=True,
            )
            return 1
        finally:
            if server is not None:
                server.stop()
    finally:
        instance.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
