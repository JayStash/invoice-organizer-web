"""Local single-user FastAPI interface for invoice organization."""

from __future__ import annotations

import logging
import re
import shutil
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from secrets import token_urlsafe

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.runtime import configure_web_runtime, get_resource_root, is_link_or_junction
from app.update_client import get_current_version


RUNTIME_PATHS = configure_web_runtime()

from app.core import (
    InvoiceOrganizerError,
    organize_invoices,
    scan_invoices,
    validate_organization,
)
from app.core.common import DEFAULT_PLAN_PATH, output_records


RESOURCE_ROOT = get_resource_root()
PROJECT_ROOT = RUNTIME_PATHS.root
INPUT_DIR = RUNTIME_PATHS.input_dir
OUTPUT_DIR = RUNTIME_PATHS.output_dir
RUNTIME_DIR = RUNTIME_PATHS.runtime_dir
TEMPLATES_DIR = RESOURCE_ROOT / "app" / "templates"
STATIC_DIR = RESOURCE_ROOT / "app" / "static"
DOWNLOAD_NAME = "发票整理结果.zip"
FEEDBACK_FILENAME = "无法识别的发票请发送至开发者邮箱：2016267947@qq.com.txt"
FEEDBACK_CONTENT = "无法识别的发票请直接抄送至邮箱2016267947@qq.com，以便后续优化更新"
ZIP_PATH = RUNTIME_DIR / DOWNLOAD_NAME
PREVIEW_PATH = RUNTIME_PATHS.preview_path
ALLOWED_SUFFIXES = {".pdf", ".zip"}
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
logger = logging.getLogger(__name__)


class BatchCleanupError(RuntimeError):
    """Web temporary files could not safely be cleared before a new batch."""


@dataclass
class ActiveBatch:
    batch_id: str
    approval_token: str
    completed: bool = False


class ConfirmRequest(BaseModel):
    batch_id: str


app = FastAPI(
    title="发票整理",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

_batch_lock = threading.Lock()
_active_batch: ActiveBatch | None = None


def _safe_upload_name(raw_name: str | None) -> str:
    name = Path((raw_name or "").replace("\\", "/")).name.strip()
    if not name or name in {".", ".."} or INVALID_FILENAME_CHARS.search(name):
        raise HTTPException(status_code=400, detail="文件名无效。")
    if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"仅支持 PDF 或 ZIP：{name}")
    return name


def _clear_directory(directory: Path) -> None:
    # Only these two Web-owned leaf directories contain disposable ticket
    # copies. Never recurse into directories, even inside this workspace.
    suffixes = {
        INPUT_DIR: ALLOWED_SUFFIXES,
        OUTPUT_DIR: {".pdf", ".xlsx"},
    }
    if (
        directory not in suffixes
        or PROJECT_ROOT.resolve() != PROJECT_ROOT
        or is_link_or_junction(PROJECT_ROOT)
        or is_link_or_junction(directory)
    ):
        raise BatchCleanupError("拒绝清理非网页临时目录或目录链接。")
    resolved = directory.resolve()
    if resolved.parent != PROJECT_ROOT:
        raise BatchCleanupError("拒绝清理网页工作区外目录。")
    resolved.mkdir(parents=True, exist_ok=True)
    for entry in resolved.iterdir():
        if entry.name == ".gitkeep" or entry.suffix.lower() not in suffixes[directory]:
            continue
        if is_link_or_junction(entry):
            raise BatchCleanupError("拒绝清理临时文件链接。")
        if entry.is_file():
            entry.unlink()


def _clear_managed_data() -> None:
    for directory in (INPUT_DIR, OUTPUT_DIR):
        _clear_directory(directory)
    # Shared .runtime may contain regression evidence and release reports.
    # Even in the private Web runtime, remove only the three named artifacts.
    if is_link_or_junction(RUNTIME_DIR) or RUNTIME_DIR.resolve().parent != PROJECT_ROOT:
        raise BatchCleanupError("拒绝清理非网页运行目录。")
    for path in (DEFAULT_PLAN_PATH, PREVIEW_PATH, ZIP_PATH):
        if path.parent != RUNTIME_DIR or is_link_or_junction(path):
            raise BatchCleanupError("拒绝清理非网页临时文件。")
        path.unlink(missing_ok=True)


def _cleanup_failed_upload() -> None:
    try:
        _clear_managed_data()
    except Exception:
        logger.exception("清理失败批次时出错；保留上传或识别的原始异常。")


def _preview_records(plan: dict) -> list[dict[str, str]]:
    fields = (
        "new_name",
        "invoice_number",
        "expense_type",
        "document_type",
        "total_amount",
        "invoice_date",
    )
    records = plan.get("records", [])
    ordered_records = output_records(records)
    ordered_ids = {id(record) for record in ordered_records}
    ordered_records.extend(
        record
        for record in records
        if id(record) not in ordered_ids
        and record.get("file_type") not in {"archive", "archive_member"}
    )
    rows: list[dict[str, str]] = []
    for record in ordered_records:
        if record.get("file_type") in {"archive", "archive_member"}:
            continue
        rows.append(
            {
                field: "" if record.get(field) is None else str(record.get(field))
                for field in fields
            }
        )
    return rows


def _build_download_zip() -> Path:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    output_files = sorted(
        (
            path
            for path in OUTPUT_DIR.iterdir()
            if path.is_file() and path.name not in {".gitkeep", FEEDBACK_FILENAME}
        ),
        key=lambda path: path.name.casefold(),
    )
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in output_files:
            archive.write(path, arcname=path.name)
        archive.writestr(FEEDBACK_FILENAME, FEEDBACK_CONTENT.encode("utf-8-sig"))
    return ZIP_PATH


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"app_version": get_current_version()},
    )


@app.post("/api/scan")
def scan_uploads(files: list[UploadFile] = File(...)) -> dict:
    global _active_batch

    if not files:
        raise HTTPException(status_code=400, detail="请选择至少一个 PDF 或 ZIP 文件。")
    names = [_safe_upload_name(upload.filename) for upload in files]
    folded_names = [name.casefold() for name in names]
    if len(folded_names) != len(set(folded_names)):
        raise HTTPException(status_code=400, detail="同一批次不能包含同名文件。")

    with _batch_lock:
        _active_batch = None
        try:
            try:
                _clear_managed_data()
            except Exception as exc:
                logger.exception("无法清理上一批网页临时文件。")
                raise HTTPException(
                    status_code=409,
                    detail="无法清理上一批临时文件，请关闭正在使用的文件并检查文件权限后重试。",
                ) from exc
            for upload, name in zip(files, names, strict=True):
                target = INPUT_DIR / name
                with target.open("xb") as destination:
                    shutil.copyfileobj(upload.file, destination, length=1024 * 1024)
            plan = scan_invoices(INPUT_DIR, OUTPUT_DIR)
        except HTTPException:
            raise
        except InvoiceOrganizerError as exc:
            logger.exception("发票上传或识别失败。")
            _cleanup_failed_upload()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("发票上传或识别失败。")
            _cleanup_failed_upload()
            raise HTTPException(status_code=500, detail="上传或识别失败。") from exc
        finally:
            for upload in files:
                try:
                    upload.file.close()
                except Exception:
                    logger.exception("关闭上传文件时出错。")

        _active_batch = ActiveBatch(
            batch_id=token_urlsafe(18),
            approval_token=plan["approval_token"],
        )
        planned_count = sum(
            1
            for record in plan.get("records", [])
            if record.get("new_name") and record.get("status") != "needs_review"
        )
        review_count = sum(
            1
            for record in plan.get("records", [])
            if record.get("status") == "needs_review"
        )
        return {
            "batch_id": _active_batch.batch_id,
            "uploaded_count": len(files),
            "planned_count": planned_count,
            "review_count": review_count,
            "can_organize": planned_count > 0,
            "records": _preview_records(plan),
        }


@app.post("/api/organize")
def confirm_organization(payload: ConfirmRequest) -> dict:
    global _active_batch

    with _batch_lock:
        if _active_batch is None or payload.batch_id != _active_batch.batch_id:
            raise HTTPException(status_code=409, detail="当前批次已失效，请重新上传。")
        if _active_batch.completed and ZIP_PATH.is_file():
            return {"download_url": f"/download/{_active_batch.batch_id}"}

        try:
            result = organize_invoices(DEFAULT_PLAN_PATH, _active_batch.approval_token)
            validation = validate_organization(DEFAULT_PLAN_PATH)
        except InvoiceOrganizerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="整理执行失败。") from exc

        if not validation.is_valid:
            detail = "；".join(validation.errors)
            raise HTTPException(status_code=500, detail=f"整理结果校验失败：{detail}")

        archive_path = _build_download_zip()
        _active_batch.completed = True
        return {
            "processed_count": result.processed_count,
            "grand_total": "" if result.grand_total is None else str(result.grand_total),
            "archive_size": archive_path.stat().st_size,
            "download_url": f"/download/{_active_batch.batch_id}",
        }


@app.get("/download/{batch_id}")
def download_result(batch_id: str) -> FileResponse:
    with _batch_lock:
        if (
            _active_batch is None
            or batch_id != _active_batch.batch_id
            or not _active_batch.completed
            or not ZIP_PATH.is_file()
        ):
            raise HTTPException(status_code=404, detail="下载文件不存在或已失效。")
        return FileResponse(
            ZIP_PATH,
            media_type="application/zip",
            filename=DOWNLOAD_NAME,
        )
