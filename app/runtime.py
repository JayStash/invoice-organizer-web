"""Runtime paths for source development and frozen desktop releases."""

from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path


APP_DATA_DIRNAME = "InvoiceOrganizer"
SOURCE_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    input_dir: Path
    output_dir: Path
    runtime_dir: Path
    plan_path: Path
    preview_path: Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_resource_root() -> Path:
    """Return the source root or PyInstaller's extracted resource root."""
    if is_frozen():
        bundle_root = getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)
        return Path(bundle_root).resolve()
    return SOURCE_ROOT


def get_data_root() -> Path:
    """Keep release data in LocalAppData while preserving source-mode behavior."""
    if not is_frozen():
        return SOURCE_ROOT
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return (base / APP_DATA_DIRNAME).resolve()


def configure_core_runtime(data_root: Path | None = None) -> RuntimePaths:
    """Point the unchanged core modules at the selected writable data root."""
    root = (data_root or get_data_root()).resolve()
    paths = RuntimePaths(
        root=root,
        input_dir=root / "input",
        output_dir=root / "output",
        runtime_dir=root / ".runtime",
        plan_path=root / ".runtime" / ".invoice-organization-plan.json",
        preview_path=root / ".runtime" / "发票整理预览.md",
    )
    for directory in (paths.input_dir, paths.output_dir, paths.runtime_dir):
        directory.mkdir(parents=True, exist_ok=True)

    common = importlib.import_module("app.core.common")
    scan = importlib.import_module("app.core.scan_invoices")
    organize = importlib.import_module("app.core.organize_invoices")

    common.SKILL_ROOT = paths.root
    common.DEFAULT_INPUT_DIR = paths.input_dir
    common.DEFAULT_OUTPUT_DIR = paths.output_dir
    common.RUNTIME_DIR = paths.runtime_dir
    common.DEFAULT_PLAN_PATH = paths.plan_path
    common.DEFAULT_PREVIEW_PATH = paths.preview_path

    scan.DEFAULT_INPUT_DIR = paths.input_dir
    scan.DEFAULT_OUTPUT_DIR = paths.output_dir
    scan.RUNTIME_DIR = paths.runtime_dir
    scan.DEFAULT_PLAN_PATH = paths.plan_path
    scan.DEFAULT_PREVIEW_PATH = paths.preview_path

    organize.RUNTIME_DIR = paths.runtime_dir
    return paths
