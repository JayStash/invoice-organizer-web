from __future__ import annotations

import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from app import runtime
from desktop import FastAPIServer, configure_webview


class RuntimePathTests(unittest.TestCase):
    def test_frozen_data_uses_local_app_data(self) -> None:
        with (
            tempfile.TemporaryDirectory() as local_app_data,
            patch.object(runtime.sys, "frozen", True, create=True),
            patch.dict(os.environ, {"LOCALAPPDATA": local_app_data}),
        ):
            self.assertEqual(
                runtime.get_data_root(),
                (Path(local_app_data) / "InvoiceOrganizer").resolve(),
            )


class WebviewConfigurationTests(unittest.TestCase):
    def test_downloads_are_enabled(self) -> None:
        class FakeWebview:
            settings = {"ALLOW_DOWNLOADS": False}

        configure_webview(FakeWebview)

        self.assertTrue(FakeWebview.settings["ALLOW_DOWNLOADS"])


class FastAPIServerTests(unittest.TestCase):
    def test_server_thread_stops_cleanly(self) -> None:
        application = FastAPI()

        @application.get("/")
        def index() -> dict[str, bool]:
            return {"ok": True}

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        server = FastAPIServer(application, port=port)
        try:
            server.start()
            response = httpx.get(f"http://127.0.0.1:{port}/", timeout=2)
            self.assertEqual(response.json(), {"ok": True})
        finally:
            server.stop()

        self.assertFalse(server.thread.is_alive())


if __name__ == "__main__":
    unittest.main()
