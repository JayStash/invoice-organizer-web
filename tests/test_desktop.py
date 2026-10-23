from __future__ import annotations

import os
import socket
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, sentinel

import httpx
from fastapi import FastAPI

from app import runtime
from desktop import FastAPIServer, configure_webview


class RuntimePathTests(unittest.TestCase):
    def test_source_web_runtime_has_a_private_data_root(self) -> None:
        with (
            tempfile.TemporaryDirectory() as source,
            patch.object(runtime, "SOURCE_ROOT", Path(source)),
            patch.object(runtime.sys, "frozen", False, create=True),
            patch.object(runtime, "configure_core_runtime", return_value=sentinel.paths) as configure,
        ):
            self.assertIs(runtime.configure_web_runtime(), sentinel.paths)
            configure.assert_called_once_with(Path(source).resolve() / ".runtime" / "web-batch")

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

    def test_frozen_web_runtime_uses_app_data_and_keeps_bundle_resources_separate(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(runtime.sys, "frozen", True, create=True),
            patch.object(runtime.sys, "_MEIPASS", str(Path(temporary) / "bundle"), create=True),
            patch.dict(os.environ, {"LOCALAPPDATA": str(Path(temporary) / "local")}),
            patch.object(runtime, "configure_core_runtime", return_value=sentinel.paths) as configure,
        ):
            self.assertIs(runtime.configure_web_runtime(), sentinel.paths)
            configure.assert_called_once_with(
                (Path(temporary) / "local" / "InvoiceOrganizer" / ".runtime" / "web-batch").resolve()
            )
            self.assertEqual(runtime.get_resource_root(), (Path(temporary) / "bundle").resolve())

    def test_web_runtime_rejects_links_before_core_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for linked in (root / ".runtime", root / ".runtime" / "web-batch",
                           root / ".runtime" / "web-batch" / "input",
                           root / ".runtime" / "web-batch" / "output",
                           root / ".runtime" / "web-batch" / ".runtime"):
                with (
                    self.subTest(linked=linked),
                    patch.object(runtime, "is_link_or_junction", side_effect=lambda path: path == linked),
                    patch.object(runtime, "configure_core_runtime") as configure,
                ):
                    with self.assertRaises(RuntimeError):
                        runtime.configure_web_runtime(root)
                    configure.assert_not_called()

    def test_link_detection_includes_windows_directory_junction_attributes(self) -> None:
        for metadata in (
            SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0),
            SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT),
        ):
            with self.subTest(metadata=metadata), patch.object(Path, "lstat", return_value=metadata):
                self.assertTrue(runtime.is_link_or_junction(Path("linked-directory")))


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
