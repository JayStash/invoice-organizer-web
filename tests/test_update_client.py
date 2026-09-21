from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import update_client


class FakeResponse(io.BytesIO):
    def __init__(self, content: bytes, url: str) -> None:
        super().__init__(content)
        self._url = url

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class UpdateMetadataTests(unittest.TestCase):
    def test_version_comparison_is_numeric(self) -> None:
        self.assertGreater(
            update_client.parse_version("1.0.10"),
            update_client.parse_version("1.0.2"),
        )

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


if __name__ == "__main__":
    unittest.main()
