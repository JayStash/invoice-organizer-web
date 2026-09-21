"""Windows desktop entry point backed by FastAPI and pywebview."""

from __future__ import annotations

import ctypes
import json
import socket
import subprocess
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

import uvicorn

from app.runtime import configure_core_runtime, is_frozen
from app.update_client import (
    UpdateDownloadError,
    UpdateInfo,
    check_for_update,
    download_update,
)


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


class DesktopApi:
    """Small pywebview bridge that owns the update lifecycle."""

    def __init__(self) -> None:
        self._window: Any = None
        self._update: UpdateInfo | None = None
        self._pending_installer: Path | None = None
        self._check_started = False
        self._download_lock = threading.Lock()

    @property
    def pending_installer(self) -> Path | None:
        return self._pending_installer

    def attach_window(self, window: Any) -> None:
        self._window = window

    def start_update_check(self, *_: object) -> None:
        if self._check_started:
            return
        self._check_started = True
        threading.Thread(
            target=self._check_for_update,
            name="invoice-organizer-update-check",
            daemon=True,
        ).start()

    def _check_for_update(self) -> None:
        update = check_for_update()
        if update is None or self._window is None:
            return
        self._update = update
        payload = json.dumps(update.as_public_dict(), ensure_ascii=True)
        try:
            self._window.evaluate_js(
                "window.invoiceOrganizer && "
                f"window.invoiceOrganizer.showUpdate({payload});"
            )
        except Exception:
            return

    def install_update(self) -> dict[str, object]:
        if not self._download_lock.acquire(blocking=False):
            return {"ok": False, "message": "更新正在下载，请稍候。"}
        try:
            if self._update is None:
                return {"ok": False, "message": "更新信息已失效，请稍后重试。"}
            try:
                installer = download_update(self._update)
            except UpdateDownloadError as exc:
                return {"ok": False, "message": str(exc)}
            except Exception:
                return {"ok": False, "message": "更新下载失败，请稍后重试。"}

            self._pending_installer = installer
            threading.Thread(
                target=self._close_for_update,
                name="invoice-organizer-update-close",
                daemon=True,
            ).start()
            return {"ok": True}
        finally:
            self._download_lock.release()

    def _close_for_update(self) -> None:
        time.sleep(0.4)
        try:
            if self._window is not None:
                self._window.destroy()
        except Exception:
            self._pending_installer = None


def main() -> int:
    instance = SingleInstance()
    server: FastAPIServer | None = None
    desktop_api: DesktopApi | None = None
    installer_to_launch: Path | None = None
    exit_code = 0
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
            desktop_api = DesktopApi()
            window = webview.create_window(
                "发票整理工具",
                APP_URL,
                width=1280,
                height=820,
                min_size=(960, 640),
                js_api=desktop_api,
            )
            desktop_api.attach_window(window)

            def close_server(*_: object) -> None:
                server.stop()

            window.events.closed += close_server
            window.events.loaded += desktop_api.start_update_check
            webview.start(gui="edgechromium", debug=not is_frozen())
        except Exception:
            show_message(
                "发票整理工具启动失败。\n"
                "请确认 127.0.0.1:8000 端口未被占用后重试。",
                error=True,
            )
            exit_code = 1
        finally:
            if server is not None:
                server.stop()
            if desktop_api is not None:
                installer_to_launch = desktop_api.pending_installer
    finally:
        instance.release()

    if installer_to_launch is not None:
        try:
            subprocess.Popen(
                [str(installer_to_launch)],
                cwd=str(installer_to_launch.parent),
                close_fds=True,
            )
        except OSError:
            show_message(
                "安装程序无法启动。\n请稍后重新打开软件并重试。",
                error=True,
            )
            return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
