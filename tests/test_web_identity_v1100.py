"""Anonymous Web identities and complete delivery for every accepted PDF."""
from __future__ import annotations

import importlib
import io
import json
import tempfile
import unittest
import zipfile
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as web
from app import runtime
from test_invoice_v132 import lined_pdf, ride_invoice_text, ride_report_text, vat_text


class WebIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        globals_to_restore = {
            "app.core.common": ("SKILL_ROOT", "DEFAULT_INPUT_DIR", "DEFAULT_OUTPUT_DIR",
                                "RUNTIME_DIR", "DEFAULT_PLAN_PATH", "DEFAULT_PREVIEW_PATH"),
            "app.core.scan_invoices": ("DEFAULT_INPUT_DIR", "DEFAULT_OUTPUT_DIR", "RUNTIME_DIR",
                                       "DEFAULT_PLAN_PATH", "DEFAULT_PREVIEW_PATH"),
            "app.core.organize_invoices": ("RUNTIME_DIR",),
        }
        for module_name, names in globals_to_restore.items():
            module = importlib.import_module(module_name)
            self.patches.enter_context(patch.multiple(module, **{name: getattr(module, name) for name in names}))
        self.paths = runtime.configure_web_runtime(self.root)
        self.patches.enter_context(patch.multiple(
            web, PROJECT_ROOT=self.paths.root, INPUT_DIR=self.paths.input_dir,
            OUTPUT_DIR=self.paths.output_dir, RUNTIME_DIR=self.paths.runtime_dir,
            DEFAULT_PLAN_PATH=self.paths.plan_path, PREVIEW_PATH=self.paths.preview_path,
            ZIP_PATH=self.paths.runtime_dir / web.DOWNLOAD_NAME, _active_batch=None,
        ))
        self.client = TestClient(web.app)
        self.addCleanup(self.client.close)

    def scan(self, entries):
        response = self.client.post("/api/scan", files=[("files", (name, data, "application/octet-stream")) for name, data in entries])
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def organize(self, scanned):
        response = self.client.post("/api/organize", json={"batch_id": scanned["batch_id"]})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertTrue(result["delivery_complete"])
        self.assertEqual(result["delivery_failed_count"], 0)
        return result

    def delivered(self, result):
        response = self.client.get(result["download_url"])
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            entries = [(entry.filename, archive.read(entry)) for entry in archive.infolist()
                       if not entry.is_dir() and entry.filename.lower().endswith(".pdf")]
        self.assertEqual(len(entries), len({name.casefold() for name, _ in entries}))
        return entries

    def test_same_names_case_variants_and_repeated_content_have_independent_sources(self):
        first = lined_pdf("匿名普通文件甲")
        second = lined_pdf("匿名普通文件乙")
        entries = [("same.pdf", first), ("same.pdf", second), ("SAME.PDF", first)]
        scan = self.scan(entries)
        self.assertEqual(scan["uploaded_count"], 3)
        self.assertEqual(scan["input_pdf_count"], 3)
        self.assertEqual(len({item["source_id"] for item in scan["sources"]}), 3)
        self.assertEqual(len({item["document_id"] for item in scan["records"]}), 3)
        self.assertCountEqual([item["original_name"] for item in scan["records"]], [name for name, _ in entries])
        stored = list(self.paths.input_dir.glob("*.pdf"))
        self.assertEqual(len(stored), 3)
        self.assertTrue(all(path.name.startswith("upload-") for path in stored))
        self.assertEqual(Counter(path.read_bytes() for path in stored), Counter(data for _, data in entries))
        self.assertTrue(all(item["is_unrecognized"] for item in scan["records"]))
        result = self.organize(scan)
        self.assertEqual((result["success_count"], result["failed_count"], result["delivered_count"]), (0, 3, 3))
        delivered = self.delivered(result)
        self.assertEqual(Counter(data for _, data in delivered), Counter(data for _, data in entries))
        self.assertCountEqual([Path(name).name for name, _ in delivered], [name for name, _ in entries])

    def test_same_name_distinct_invoices_keep_filename_hints_and_both_succeed(self):
        entries = [("票据.pdf", lined_pdf(vat_text(number="00000001", amount="37"))),
                   ("票据.pdf", lined_pdf(vat_text(number="00000002", amount="41")))]
        scan = self.scan(entries)
        self.assertEqual(scan["planned_count"], 2)
        self.assertTrue(all(not item["recognition_failed"] for item in scan["records"]))
        self.assertEqual(len({item["document_id"] for item in scan["records"]}), 2)
        result = self.organize(scan)
        self.assertEqual((result["success_count"], result["failed_count"], result["delivered_count"]), (2, 0, 2))
        self.assertEqual(Counter(data for _, data in self.delivered(result)), Counter(data for _, data in entries))

    def test_same_name_zip_uploads_keep_container_and_member_relationships(self):
        contents = []
        for text in ("匿名压缩包甲", "匿名压缩包乙"):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as archive:
                archive.writestr("receipts/same.pdf", lined_pdf(text))
            contents.append(stream.getvalue())
        scan = self.scan([("bundle.zip", data) for data in contents])
        self.assertEqual(scan["input_pdf_count"], 2)
        self.assertEqual(len({row["source_id"] for row in scan["records"]}), 2)
        self.assertEqual(len({row["document_id"] for row in scan["records"]}), 2)
        self.assertTrue(all(row["source_label"] == "bundle.zip / receipts/same.pdf" for row in scan["records"]))
        plan = json.loads(self.paths.plan_path.read_text(encoding="utf-8"))
        members = [row for row in plan["records"] if row.get("archive_member")]
        self.assertEqual(len({row["archive_source"] for row in members}), 2)
        self.assertTrue(all(row["archive_original_name"] == "bundle.zip" for row in members))
        result = self.organize(scan)
        expected = []
        for data in contents:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                expected.append(archive.read("receipts/same.pdf"))
        self.assertEqual(Counter(data for _, data in self.delivered(result)), Counter(expected))

    def test_ambiguous_itinerary_is_failed_with_original_name_and_own_fields(self):
        entries = [("one.pdf", lined_pdf(ride_invoice_text("高德", number="26000000000000000011", amount="25"))),
                   ("two.pdf", lined_pdf(ride_invoice_text("高德", number="26000000000000000012", amount="25"))),
                   ("route.pdf", lined_pdf(ride_report_text("高德", amount="25")))]
        scan = self.scan(entries)
        row = next(row for row in scan["records"] if row["original_name"] == "route.pdf")
        self.assertTrue(row["recognition_failed"])
        self.assertFalse(row["is_unrecognized"])
        self.assertEqual(row["new_name"], "route.pdf")
        self.assertEqual(row["invoice_number"], "")
        self.assertEqual(row["total_amount"], "25")
        self.assertIn("route.pdf", scan["failed_files"])
        self.assertNotIn("route.pdf", scan["unrecognized_files"])
        result = self.organize(scan)
        self.assertEqual((result["success_count"], result["failed_count"]), (2, 1))
        self.assertEqual(dict(self.delivered(result))["route.pdf"], entries[2][1])
        self.assertEqual(result["failed_records"][0]["document_id"], row["document_id"])
        self.assertEqual(self.organize(scan), result)

    def test_partial_invoice_preserves_valid_fields_without_unknown_marker(self):
        text = vat_text().replace("开票日期:2026年01月03日\n", "")
        pdf = lined_pdf(text)
        scan = self.scan([("incomplete.pdf", pdf)])
        row = scan["records"][0]
        self.assertTrue(row["recognition_failed"])
        self.assertFalse(row["is_unrecognized"])
        self.assertEqual(row["invoice_number"], "00000001")
        self.assertEqual(row["total_amount"], "37")
        self.assertEqual(row["new_name"], "incomplete.pdf")
        result = self.organize(scan)
        self.assertEqual((result["success_count"], result["failed_count"]), (0, 1))
        self.assertEqual(self.delivered(result), [("incomplete.pdf", pdf)])

    def test_delivery_error_is_http_failure_and_never_marked_complete(self):
        scan = self.scan([("unknown.pdf", lined_pdf("匿名不可识别文件"))])
        with patch.object(web, "_build_download_zip", side_effect=OSError("synthetic disk full")), self.assertLogs(web.logger, level="ERROR"):
            response = self.client.post("/api/organize", json={"batch_id": scan["batch_id"]})
        self.assertEqual(response.status_code, 500)
        self.assertFalse(web._active_batch.completed)
        self.assertNotIn("delivery_complete", response.json())
        result = self.organize(scan)
        self.assertEqual((result["failed_count"], result["delivered_count"]), (1, 1))
        self.assertEqual(len(self.delivered(result)), 1)


if __name__ == "__main__":
    unittest.main()
