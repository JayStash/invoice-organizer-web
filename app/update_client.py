"""Non-blocking desktop update metadata and installer download helpers."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path
from time import monotonic
from typing import BinaryIO, Callable

from app.runtime import get_data_root, get_resource_root


UPDATE_METADATA_URL = "http://120.79.151.217/invoice-organizer/latest.json"
ALLOWED_UPDATE_HOST = "120.79.151.217"
UPDATE_TIMEOUT_SECONDS = 5.0
MAX_METADATA_BYTES = 64 * 1024
PROGRESS_INTERVAL_SECONDS = 0.2
VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


class UpdateDownloadError(RuntimeError):
    """A user-facing update download or verification failure."""


@dataclass(frozen=True)
class ChangelogEntry:
    version: str
    notes: tuple[str, ...]


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    notes: str
    download_url: str
    sha256: str
    changelog: tuple[ChangelogEntry, ...] = ()

    def as_public_dict(self) -> dict[str, str]:
        return {"version": self.version, "notes": self.notes}


@dataclass(frozen=True)
class DownloadProgress:
    stage: str
    downloaded_bytes: int
    total_bytes: int | None

    def as_public_dict(self) -> dict[str, str | int | None]:
        return {
            "stage": self.stage,
            "downloaded": self.downloaded_bytes,
            "total": self.total_bytes,
        }


def get_current_version() -> str:
    version_path = get_resource_root() / "VERSION"
    version = version_path.read_text(encoding="utf-8").strip()
    parse_version(version)
    return version


def parse_version(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid version")
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def _parse_changelog(value: object) -> tuple[ChangelogEntry, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError("invalid changelog")
    entries: list[ChangelogEntry] = []
    seen_versions: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("invalid changelog")
        version = item.get("version")
        notes = item.get("notes")
        if (
            not isinstance(version, str)
            or not isinstance(notes, list)
            or not notes
            or version in seen_versions
        ):
            raise ValueError("invalid changelog")
        parse_version(version)
        if not all(isinstance(note, str) and 0 < len(note) <= 2_000 for note in notes):
            raise ValueError("invalid changelog")
        seen_versions.add(version)
        entries.append(ChangelogEntry(version=version, notes=tuple(notes)))
    return tuple(entries)


def _notes_for_upgrade(update: UpdateInfo, current_version: str) -> str:
    if not update.changelog:
        return update.notes
    current = parse_version(current_version)
    latest = parse_version(update.version)
    selected = sorted(
        (
            entry
            for entry in update.changelog
            if current < parse_version(entry.version) <= latest
        ),
        key=lambda entry: parse_version(entry.version),
    )
    if not selected:
        return update.notes
    return "\n\n".join(
        f"【v{entry.version}】\n" + "\n".join(f"- {note}" for note in entry.notes)
        for entry in selected
    )


def _validate_update_url(url: str) -> str:
    if not isinstance(url, str):
        raise ValueError("invalid download URL")
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname != ALLOWED_UPDATE_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("invalid download URL")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid download URL") from exc
    if port is not None and port not in {80, 443}:
        raise ValueError("invalid download URL")
    return url


def parse_update_metadata(payload: object) -> UpdateInfo:
    if not isinstance(payload, dict):
        raise ValueError("invalid metadata")
    version = payload.get("version")
    notes = payload.get("notes")
    download_url = payload.get("download_url")
    sha256 = payload.get("sha256")
    if not all(isinstance(value, str) for value in (version, notes, download_url, sha256)):
        raise ValueError("invalid metadata")
    parse_version(version)
    if len(notes) > 20_000:
        raise ValueError("invalid notes")
    _validate_update_url(download_url)
    if SHA256_PATTERN.fullmatch(sha256) is None:
        raise ValueError("invalid SHA256")
    changelog = _parse_changelog(payload.get("changelog"))
    return UpdateInfo(
        version=version,
        notes=notes,
        download_url=download_url,
        sha256=sha256.lower(),
        changelog=changelog,
    )


class _RestrictedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        resolved_url = urllib.parse.urljoin(req.full_url, newurl)
        _validate_update_url(resolved_url)
        return super().redirect_request(req, fp, code, msg, headers, resolved_url)


def _open_url(url: str, timeout: float) -> BinaryIO:
    _validate_update_url(url)
    opener = urllib.request.build_opener(_RestrictedRedirectHandler())
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"InvoiceOrganizer/{get_current_version()}"},
    )
    response = opener.open(request, timeout=timeout)
    _validate_update_url(response.geturl())
    return response


def check_for_update(
    current_version: str | None = None,
    *,
    metadata_url: str = UPDATE_METADATA_URL,
    timeout: float = UPDATE_TIMEOUT_SECONDS,
) -> UpdateInfo | None:
    """Return newer validated metadata, silently ignoring all check failures."""
    try:
        local_version = current_version or get_current_version()
        with _open_url(metadata_url, timeout) as response:
            raw = response.read(MAX_METADATA_BYTES + 1)
        if len(raw) > MAX_METADATA_BYTES:
            return None
        payload = json.loads(raw.decode("utf-8"))
        update = parse_update_metadata(payload)
        if parse_version(update.version) <= parse_version(local_version):
            return None
        return replace(update, notes=_notes_for_upgrade(update, local_version))
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError, urllib.error.URLError):
        return None


def download_update(
    update: UpdateInfo,
    *,
    updates_dir: Path | None = None,
    timeout: float = 30.0,
    progress_callback: Callable[[DownloadProgress], None] | None = None,
) -> Path:
    """Download a Setup to a controlled path and return it only after SHA256 verification."""
    try:
        validated_url = _validate_update_url(update.download_url)
        parse_version(update.version)
        if SHA256_PATTERN.fullmatch(update.sha256) is None:
            raise ValueError("invalid SHA256")
    except ValueError as exc:
        raise UpdateDownloadError("更新信息无效，请稍后重试。") from exc

    target_dir = updates_dir or (get_data_root() / "updates")
    target_dir.mkdir(parents=True, exist_ok=True)
    final_path = target_dir / f"发票整理工具-Setup-v{update.version}.exe"
    partial_path = final_path.with_suffix(final_path.suffix + ".part")
    partial_path.unlink(missing_ok=True)

    digest = hashlib.sha256()
    try:
        with _open_url(validated_url, timeout) as response, partial_path.open("xb") as output:
            raw_total = getattr(response, "headers", {}).get("Content-Length")
            try:
                total_bytes = int(raw_total) if raw_total is not None else None
            except (TypeError, ValueError):
                total_bytes = None
            if total_bytes is not None and total_bytes <= 0:
                total_bytes = None
            downloaded_bytes = 0
            last_reported_bytes = -1
            last_reported_at = monotonic()
            if progress_callback is not None:
                progress_callback(DownloadProgress("downloading", 0, total_bytes))
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
                downloaded_bytes += len(chunk)
                now = monotonic()
                if progress_callback is not None and (
                    downloaded_bytes == total_bytes
                    or now - last_reported_at >= PROGRESS_INTERVAL_SECONDS
                ):
                    progress_callback(
                        DownloadProgress("downloading", downloaded_bytes, total_bytes)
                    )
                    last_reported_bytes = downloaded_bytes
                    last_reported_at = now
            if progress_callback is not None and last_reported_bytes != downloaded_bytes:
                progress_callback(
                    DownloadProgress("downloading", downloaded_bytes, total_bytes)
                )
            if progress_callback is not None:
                progress_callback(
                    DownloadProgress("verifying", downloaded_bytes, total_bytes)
                )
        if digest.hexdigest().lower() != update.sha256.lower():
            raise UpdateDownloadError("安装包校验失败，请稍后重试。")
        partial_path.replace(final_path)
        return final_path
    except UpdateDownloadError:
        partial_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise
    except (OSError, ValueError, urllib.error.URLError) as exc:
        partial_path.unlink(missing_ok=True)
        raise UpdateDownloadError("更新下载失败，请检查网络后重试。") from exc
