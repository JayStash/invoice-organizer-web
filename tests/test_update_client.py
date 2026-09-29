from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import update_client


class FakeResponse(io.BytesIO):
    def __init__(
        self,
        content: bytes,
        url: str,
        *,
        content_length: int | None = None,
    ) -> None:
        super().__init__(content)
        self._url = url
        self.headers = (
            {"Content-Length": str(content_length)}
            if content_length is not None
            else {}
        )

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class FailingResponse(FakeResponse):
    def __init__(self, content: bytes, url: str) -> None:
        super().__init__(content, url, content_length=len(content) * 2)
        self._first_read = True

    def read(self, size: int = -1) -> bytes:
        if self._first_read:
            self._first_read = False
            return super().read(max(1, min(size, 4)))
        raise OSError("connection lost")


class UpdateMetadataTests(unittest.TestCase):
    def test_version_comparison_is_numeric(self) -> None:
        self.assertGreater(update_client.parse_version("1.0.21"), update_client.parse_version("1.0.2"))
        self.assertGreater(update_client.parse_version("1.0.2"), update_client.parse_version("1.0.1"))

    def test_rejects_download_from_third_party_host(self) -> None:
        with self.assertRaises(ValueError):
            update_client.parse_update_metadata(
                {
                    "version": "1.0.2",
                    "notes": "test",
                    "download_url": "https://example.com/update.exe",
                    "sha256": "a" * 64,
                }
            )

    def test_invalid_metadata_is_silently_ignored(self) -> None:
        response = FakeResponse(b"not-json", update_client.UPDATE_METADATA_URL)
        with patch.object(update_client, "_open_url", return_value=response):
            self.assertIsNone(update_client.check_for_update("1.0.1"))

    def test_only_newer_version_is_returned(self) -> None:
        content = (
            b'{"version":"1.0.2","notes":"fixed",'
            b'"download_url":"http://120.79.151.217/invoice-organizer/releases/setup.exe",'
            b'"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
        )
        with patch.object(
            update_client,
            "_open_url",
            side_effect=lambda *_args, **_kwargs: FakeResponse(
                content, update_client.UPDATE_METADATA_URL
            ),
        ):
            self.assertEqual(
                update_client.check_for_update("1.0.1").version,  # type: ignore[union-attr]
                "1.0.2",
            )
            self.assertIsNone(update_client.check_for_update("1.0.2"))

    def test_changelog_filters_versions_crossed_by_upgrade(self) -> None:
        payload = {
            "version": "1.0.21",
            "notes": "fallback",
            "download_url": "http://120.79.151.217/invoice-organizer/releases/setup.exe",
            "sha256": "a" * 64,
            "changelog": [
                {"version": "1.0.2", "notes": ["v102 change"]},
                {"version": "1.0.21", "notes": ["v1021 change"]},
            ],
        }
        content = json.dumps(payload).encode("utf-8")

        def response(*_args, **_kwargs):
            return FakeResponse(content, update_client.UPDATE_METADATA_URL)

        with patch.object(update_client, "_open_url", side_effect=response):
            from_101 = update_client.check_for_update("1.0.1")
            from_102 = update_client.check_for_update("1.0.2")

        self.assertIsNotNone(from_101)
        self.assertIn("【v1.0.2】", from_101.notes)  # type: ignore[union-attr]
        self.assertIn("【v1.0.21】", from_101.notes)  # type: ignore[union-attr]
        self.assertIsNotNone(from_102)
        self.assertNotIn("【v1.0.2】", from_102.notes)  # type: ignore[union-attr]
        self.assertIn("【v1.0.21】", from_102.notes)  # type: ignore[union-attr]

    def test_metadata_without_changelog_uses_legacy_notes(self) -> None:
        content = (
            b'{"version":"1.0.21","notes":"legacy notes",'
            b'"download_url":"http://120.79.151.217/invoice-organizer/releases/setup.exe",'
            b'"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
        )
        with patch.object(
            update_client,
            "_open_url",
            return_value=FakeResponse(content, update_client.UPDATE_METADATA_URL),
        ):
            update = update_client.check_for_update("1.0.2")
        self.assertEqual(update.notes, "legacy notes")  # type: ignore[union-attr]


class UpdateDownloadTests(unittest.TestCase):
    def test_hash_mismatch_removes_download(self) -> None:
        update = update_client.UpdateInfo(
            version="1.0.2",
            notes="test",
            download_url="http://120.79.151.217/invoice-organizer/releases/setup.exe",
            sha256="0" * 64,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)
            with patch.object(
                update_client,
                "_open_url",
                return_value=FakeResponse(b"installer", update.download_url),
            ):
                with self.assertRaisesRegex(
                    update_client.UpdateDownloadError, "校验失败"
                ):
                    update_client.download_update(update, updates_dir=target_dir)
            self.assertEqual(list(target_dir.iterdir()), [])

    def test_verified_download_uses_controlled_filename(self) -> None:
        content = b"verified installer"
        update = update_client.UpdateInfo(
            version="1.0.2",
            notes="test",
            download_url="http://120.79.151.217/invoice-organizer/releases/anything.exe",
            sha256=hashlib.sha256(content).hexdigest(),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)
            with patch.object(
                update_client,
                "_open_url",
                return_value=FakeResponse(content, update.download_url),
            ):
                result = update_client.download_update(update, updates_dir=target_dir)
            self.assertEqual(result.name, "发票整理工具-Setup-v1.0.2.exe")
            self.assertEqual(result.read_bytes(), content)

    def test_progress_reports_content_length_and_verification_stage(self) -> None:
        content = b"progress-enabled-installer"
        update = update_client.UpdateInfo(
            version="1.0.21",
            notes="test",
            download_url="http://120.79.151.217/invoice-organizer/releases/setup.exe",
            sha256=hashlib.sha256(content).hexdigest(),
        )
        events: list[update_client.DownloadProgress] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(
                update_client,
                "_open_url",
                return_value=FakeResponse(
                    content,
                    update.download_url,
                    content_length=len(content),
                ),
            ):
                update_client.download_update(
                    update,
                    updates_dir=Path(temp_dir),
                    progress_callback=events.append,
                )
        self.assertEqual(events[0].stage, "downloading")
        self.assertEqual(events[-1].stage, "verifying")
        self.assertEqual(events[-1].downloaded_bytes, len(content))
        self.assertEqual(events[-1].total_bytes, len(content))

    def test_progress_without_content_length_never_reports_a_total(self) -> None:
        content = b"unknown-length-installer"
        update = update_client.UpdateInfo(
            version="1.0.21",
            notes="test",
            download_url="http://120.79.151.217/invoice-organizer/releases/setup.exe",
            sha256=hashlib.sha256(content).hexdigest(),
        )
        events: list[update_client.DownloadProgress] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(
                update_client,
                "_open_url",
                return_value=FakeResponse(content, update.download_url),
            ):
                update_client.download_update(
                    update,
                    updates_dir=Path(temp_dir),
                    progress_callback=events.append,
                )
        self.assertTrue(events)
        self.assertTrue(all(event.total_bytes is None for event in events))
        self.assertEqual(events[-1].downloaded_bytes, len(content))

    def test_download_failure_removes_partial_file(self) -> None:
        content = b"partial-installer"
        update = update_client.UpdateInfo(
            version="1.0.21",
            notes="test",
            download_url="http://120.79.151.217/invoice-organizer/releases/setup.exe",
            sha256=hashlib.sha256(content).hexdigest(),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)
            with patch.object(
                update_client,
                "_open_url",
                return_value=FailingResponse(content, update.download_url),
            ):
                with self.assertRaisesRegex(
                    update_client.UpdateDownloadError, "下载失败"
                ):
                    update_client.download_update(update, updates_dir=target_dir)
            self.assertEqual(list(target_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
