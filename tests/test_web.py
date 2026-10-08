from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as web
from app.core import OrganizationResult, ValidationResult


class WebFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.input_dir = root / "input"
        self.output_dir = root / "output"
        self.runtime_dir = root / ".runtime"
        self.plan_path = self.runtime_dir / ".invoice-organization-plan.json"
        self.zip_path = self.runtime_dir / web.DOWNLOAD_NAME
        self.path_patch = patch.multiple(
            web,
            PROJECT_ROOT=root,
            INPUT_DIR=self.input_dir,
            OUTPUT_DIR=self.output_dir,
            RUNTIME_DIR=self.runtime_dir,
            ZIP_PATH=self.zip_path,
            DEFAULT_PLAN_PATH=self.plan_path,
        )
        self.path_patch.start()
        web._active_batch = None
        self.client = TestClient(web.app)

    def tearDown(self) -> None:
        self.client.close()
        web._active_batch = None
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def test_index_renders_single_page(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("上传票据", response.text)
        self.assertIn("确认整理内容", response.text)
        self.assertIn("下载发票整理结果", response.text)
        self.assertIn("使用说明", response.text)
        self.assertIn("项目须知", response.text)
        self.assertIn("本工具重命名发票基于俸姐范本：", response.text)
        self.assertLess(response.text.index("本工具重命名发票基于俸姐范本："),
                        response.text.index("双击“发票整理工具-Setup.exe”"))
        image = self.client.get("/static/invoice-naming-reference.png")
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.content, (web.STATIC_DIR / "invoice-naming-reference.png").read_bytes())
        self.assertTrue(image.content.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn('id="update-progress-track"', response.text)
        self.assertIn('id="update-progress-detail"', response.text)
        self.assertIn(f'data-app-version="{web.get_current_version()}"', response.text)

    def test_rejects_unsupported_upload(self) -> None:
        response = self.client.post(
            "/api/scan",
            files=[("files", ("notes.txt", b"not an invoice", "text/plain"))],
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("仅支持 PDF 或 ZIP", response.json()["detail"])

    def test_preview_records_follow_core_sequence_order(self) -> None:
        plan = {
            "records": [
                {
                    "file_type": "invoice_pdf",
                    "status": "planned",
                    "sequence": 8,
                    "new_name": "8、餐费.pdf",
                },
                {
                    "file_type": "ride_report",
                    "status": "planned",
                    "sequence": 5,
                    "new_name": "5、滴滴出行行程报销单B.pdf",
                },
                {
                    "file_type": "invoice_pdf",
                    "status": "planned",
                    "sequence": 1,
                    "new_name": "1、高铁.pdf",
                },
                {
                    "file_type": "invoice_pdf",
                    "status": "planned",
                    "sequence": 5,
                    "new_name": "5、滴滴发票B.pdf",
                },
            ]
        }

        rows = web._preview_records(plan)

        self.assertEqual(
            [row["new_name"] for row in rows],
            [
                "1、高铁.pdf",
                "5、滴滴发票B.pdf",
                "5、滴滴出行行程报销单B.pdf",
                "8、餐费.pdf",
            ],
        )

    def test_scan_confirm_and_download_flow(self) -> None:
        plan = {
            "approval_token": "internal-token",
            "records": [
                {
                    "file_type": "invoice_pdf",
                    "status": "planned",
                    "new_name": "1、酒店-2026-09-20-12345678-88元.pdf",
                    "invoice_number": "12345678",
                    "expense_type": "住宿费",
                    "document_type": "电子发票（普通发票）",
                    "total_amount": "88",
                    "invoice_date": "2026-09-20",
                }
            ],
        }
        organized = OrganizationResult(
            processed_count=1,
            workbook_path=self.output_dir / "发票整理清单.xlsx",
            grand_total=Decimal("88"),
            plan_path=self.plan_path,
        )
        validated = ValidationResult(
            input_count=1,
            output_count=1,
            grand_total="88",
            errors=(),
        )

        with (
            patch.object(web, "scan_invoices", return_value=plan) as scan_mock,
            patch.object(web, "organize_invoices", return_value=organized) as organize_mock,
            patch.object(web, "validate_organization", return_value=validated) as validate_mock,
        ):
            scan_response = self.client.post(
                "/api/scan",
                files=[("files", ("invoice.pdf", b"%PDF-1.4", "application/pdf"))],
            )
            self.assertEqual(scan_response.status_code, 200)
            scan_payload = scan_response.json()
            self.assertNotIn("approval_token", scan_payload)
            self.assertEqual(scan_payload["records"][0]["total_amount"], "88")
            scan_mock.assert_called_once_with(self.input_dir, self.output_dir)

            self.output_dir.mkdir(parents=True, exist_ok=True)
            invoice_name = plan["records"][0]["new_name"]
            (self.output_dir / invoice_name).write_bytes(b"organized invoice")
            (self.output_dir / "发票整理清单.xlsx").write_bytes(b"workbook")

            organize_response = self.client.post(
                "/api/organize",
                json={"batch_id": scan_payload["batch_id"]},
            )
            self.assertEqual(organize_response.status_code, 200)
            organize_mock.assert_called_once_with(self.plan_path, "internal-token")
            validate_mock.assert_called_once_with(self.plan_path)

            download_response = self.client.get(organize_response.json()["download_url"])
            self.assertEqual(download_response.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(download_response.content)) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {invoice_name, "发票整理清单.xlsx", web.FEEDBACK_FILENAME},
                )
                self.assertEqual(archive.read(web.FEEDBACK_FILENAME).decode("utf-8-sig"),
                                 "无法识别的发票请直接抄送至邮箱2016267947@qq.com，以便后续优化更新")

    def test_feedback_is_constant_and_does_not_depend_on_input(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / web.FEEDBACK_FILENAME).write_text("not the feedback", encoding="utf-8")
        for _ in range(2):
            path = web._build_download_zip()
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(archive.namelist(), [web.FEEDBACK_FILENAME])
                self.assertEqual(web.FEEDBACK_FILENAME,
                                 "无法识别的发票请发送至开发者邮箱：2016267947@qq.com.txt")
                self.assertEqual(archive.read(web.FEEDBACK_FILENAME).decode("utf-8-sig"),
                                 web.FEEDBACK_CONTENT)


if __name__ == "__main__":
    unittest.main()
