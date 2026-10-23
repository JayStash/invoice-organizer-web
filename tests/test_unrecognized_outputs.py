"""Anonymous PDF conservation and lowest-priority preview fallback checks."""

from __future__ import annotations

import importlib
import io
import json
import tempfile
import unittest
import warnings
import zipfile
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as web
from app import runtime
from app.core import InvoiceOrganizerError, organize_invoices, scan_invoices, validate_organization
from test_invoice_v131 import NUMBER, synthetic_aviation_pdf
from test_invoice_v132 import lined_pdf, transit_report_text


class UnrecognizedOutputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        core_globals = {
            "app.core.common": ("SKILL_ROOT", "DEFAULT_INPUT_DIR", "DEFAULT_OUTPUT_DIR",
                                "RUNTIME_DIR", "DEFAULT_PLAN_PATH", "DEFAULT_PREVIEW_PATH"),
            "app.core.scan_invoices": ("DEFAULT_INPUT_DIR", "DEFAULT_OUTPUT_DIR", "RUNTIME_DIR",
                                       "DEFAULT_PLAN_PATH", "DEFAULT_PREVIEW_PATH"),
            "app.core.organize_invoices": ("RUNTIME_DIR",),
        }
        for module_name, names in core_globals.items():
            module = importlib.import_module(module_name)
            self.patches.enter_context(patch.multiple(
                module, **{name: getattr(module, name) for name in names}
            ))
        self.paths = runtime.configure_web_runtime(self.root)
        self.patches.enter_context(patch.multiple(
            web, PROJECT_ROOT=self.paths.root, INPUT_DIR=self.paths.input_dir,
            OUTPUT_DIR=self.paths.output_dir, RUNTIME_DIR=self.paths.runtime_dir,
            DEFAULT_PLAN_PATH=self.paths.plan_path, PREVIEW_PATH=self.paths.preview_path,
            ZIP_PATH=self.paths.runtime_dir / web.DOWNLOAD_NAME, _active_batch=None,
        ))
        self.client = TestClient(web.app)
        self.addCleanup(self.client.close)
        self.invoice = synthetic_aviation_pdf()

    def scan(self, files):
        response = self.client.post("/api/scan", files=[
            ("files", (name, data, "application/zip" if name.lower().endswith(".zip") else "application/pdf"))
            for name, data in files
        ])
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def organize(self, scan):
        response = self.client.post("/api/organize", json={"batch_id": scan["batch_id"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(validate_organization(self.paths.plan_path).is_valid)
        return response.json()

    def downloaded_pdfs(self, organized):
        response = self.client.get(organized["download_url"])
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            entries = [(item.filename, archive.read(item)) for item in archive.infolist()
                       if not item.is_dir() and item.filename.lower().endswith(".pdf")]
        self.assertEqual(len(entries), len({name.casefold() for name, _ in entries}))
        return entries

    def test_mixed_unknown_and_broken_pdfs_remain_unchanged_with_complete_repeat_result(self):
        unknown = lined_pdf("匿名说明\n合计29元\n")
        broken = b"%PDF-synthetic unreadable source\x00\xff"
        files = [("invoice.pdf", self.invoice), ("unknown.PDF", unknown), ("broken.pdf", broken)]
        scan = self.scan(files)
        self.assertEqual(scan["planned_count"], 1)
        self.assertEqual(scan["review_count"], 2)
        self.assertCountEqual(scan["unrecognized_files"], ["unknown.PDF", "broken.pdf"])
        fallback = [row for row in scan["records"] if row["is_unrecognized"]]
        self.assertEqual(len(fallback), 2)
        for row in fallback:
            self.assertEqual(row["new_name"], row["original_name"])
            self.assertEqual(row["invoice_number"], "[无有效发票号码]")
        result = self.organize(scan)
        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["failed_count"], 2)
        self.assertCountEqual(result["failed_files"], ["unknown.PDF", "broken.pdf"])
        self.assertEqual(Counter(data for _, data in self.downloaded_pdfs(result)), Counter(data for _, data in files))
        repeated = self.client.post("/api/organize", json={"batch_id": scan["batch_id"]})
        self.assertEqual(repeated.json(), result)
        plan = json.loads(self.paths.plan_path.read_text(encoding="utf-8"))
        self.assertEqual(len(list(self.paths.input_dir.iterdir())), len(files))
        self.assertEqual(
            Counter(path.read_bytes() for path in self.paths.input_dir.iterdir()),
            Counter(data for _, data in files),
        )
        for record in plan["records"]:
            self.assertEqual((self.paths.input_dir / record["source_name"]).read_bytes(), dict(files)[record["original_name"]])

    def test_all_unknown_batch_can_be_confirmed_and_keeps_original_names(self):
        files = [("unrecognized.PdF", lined_pdf("匿名文件内容")), ("empty.pdf", b"broken")]
        scan = self.scan(files)
        self.assertTrue(scan["can_organize"])
        self.assertEqual(scan["planned_count"], 0)
        result = self.organize(scan)
        self.assertEqual(result["success_count"], 0)
        self.assertEqual(result["failed_count"], 2)
        self.assertIsNone(result["grand_total"] or None)
        self.assertEqual(dict(self.downloaded_pdfs(result)), dict(files))

    def test_recognized_itinerary_uses_its_rule_and_blank_invoice_number(self):
        report = lined_pdf(transit_report_text())
        scan = self.scan([("route.pdf", report)])
        self.assertEqual(scan["unrecognized_files"], [])
        self.assertFalse(scan["records"][0]["is_unrecognized"])
        self.assertIn("轨道交通行程单", scan["records"][0]["new_name"])
        self.assertEqual(scan["records"][0]["invoice_number"], "")
        result = self.organize(scan)
        self.assertEqual((result["success_count"], result["failed_count"]), (1, 0))
        self.assertEqual([data for _, data in self.downloaded_pdfs(result)], [report])

    def test_reviewable_itinerary_keeps_original_name_fields_and_counts_as_failed(self):
        report = lined_pdf("高德打车行程单\n行程日期:2026-01-02\n")
        scan = self.scan([("route.pdf", report)])
        row = scan["records"][0]
        self.assertFalse(row["is_unrecognized"])
        self.assertEqual(row["new_name"], "route.pdf")
        self.assertEqual(row["invoice_number"], "")
        self.assertEqual(scan["unrecognized_files"], [])
        result = self.organize(scan)
        self.assertEqual((result["success_count"], result["failed_count"]), (0, 1))
        self.assertEqual(self.downloaded_pdfs(result), [(row["new_name"], report)])
        self.assertEqual(self.organize(scan), result)

    def test_duplicate_electronic_invoices_are_retained_as_two_failed_originals(self):
        files = [("first.pdf", self.invoice), ("second.pdf", self.invoice)]
        scan = self.scan(files)
        result = self.organize(scan)
        self.assertEqual((result["success_count"], result["failed_count"]), (0, 2))
        self.assertEqual(dict(self.downloaded_pdfs(result)), dict(files))

    def test_zip_duplicate_members_case_collisions_and_organized_name_collision_keep_every_pdf(self):
        generated_name = f"1、机票-{NUMBER}-448.86元.pdf"
        members = [
            (f"first/{generated_name}", b"unknown conflicts with organized"),
            ("first/same.pdf", b"unknown first basename"),
            ("second/same.pdf", b"unknown second basename"),
            ("case/SAME.PDF", b"unknown upper case basename"),
            ("repeat/exact.pdf", b"unknown repeated name one"),
            ("repeat/exact.pdf", b"unknown repeated name two"),
        ]
        source = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(source, "w") as archive:
                for name, data in members:
                    archive.writestr(name, data)
                archive.writestr("ignored.txt", "anonymous non-PDF attachment")
        scan = self.scan([("invoice.pdf", self.invoice), ("bundle.zip", source.getvalue())])
        result = self.organize(scan)
        self.assertEqual((result["success_count"], result["failed_count"]), (1, len(members)))
        entries = self.downloaded_pdfs(result)
        self.assertEqual(Counter(data for _, data in entries), Counter([self.invoice, *[data for _, data in members]]))
        self.assertEqual(dict(entries)[generated_name], self.invoice)
        by_bytes = {data: name for name, data in entries}
        for name, data in members:
            self.assertEqual(Path(by_bytes[data]).name, Path(name).name)
        self.assertTrue(any(name.startswith("未整理/") for name, _ in entries))

    def test_source_change_before_confirmation_is_rejected_instead_of_claiming_success(self):
        scan = self.scan([("unknown.pdf", b"original anonymous source")])
        plan = json.loads(self.paths.plan_path.read_text(encoding="utf-8"))
        source_name = plan["records"][0]["source_name"]
        (self.paths.input_dir / source_name).write_bytes(b"changed anonymous source")
        response = self.client.post("/api/organize", json={"batch_id": scan["batch_id"]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("SHA256", response.json()["detail"])
        self.assertFalse(web._active_batch.completed)

    def test_zip_read_permission_failure_is_not_reported_as_success(self):
        scan = self.scan([("unknown.pdf", b"original anonymous source")])
        with patch.object(web, "_read_output_payload", side_effect=PermissionError("synthetic locked source")):
            with self.assertLogs(web.logger, level="ERROR"):
                response = self.client.post("/api/organize", json={"batch_id": scan["batch_id"]})
        self.assertEqual(response.status_code, 500)
        self.assertFalse(web._active_batch.completed)
        result = self.organize(scan)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(self.downloaded_pdfs(result), [("unknown.pdf", b"original anonymous source")])

    def test_partially_unreadable_zip_is_rejected_by_web_and_core(self):
        source = io.BytesIO()
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("first.pdf", self.invoice)
            archive.writestr("blocked.pdf", b"synthetic inaccessible member")
            archive.writestr("last.pdf", lined_pdf("anonymous final PDF"))
        read = zipfile.ZipFile.read

        def fail_member(archive, member, *args, **kwargs):
            if getattr(member, "filename", member) == "blocked.pdf":
                raise zipfile.BadZipFile("synthetic CRC failure")
            return read(archive, member, *args, **kwargs)

        with patch.object(zipfile.ZipFile, "read", fail_member), self.assertLogs(web.logger, level="ERROR"):
            response = self.client.post("/api/scan", files={
                "files": ("bundle.zip", source.getvalue(), "application/zip")
            })
        self.assertEqual(response.status_code, 400)
        self.assertIn("ZIP 无法完整读取", response.json()["detail"])
        self.assertIsNone(web._active_batch)
        (self.paths.input_dir / "bundle.zip").write_bytes(source.getvalue())
        with patch.object(zipfile.ZipFile, "read", fail_member):
            plan = scan_invoices(self.paths.input_dir, self.paths.output_dir)
        with self.assertRaisesRegex(InvoiceOrganizerError, "ZIP 无法完整读取"):
            organize_invoices(self.paths.plan_path, plan["approval_token"])
        self.assertEqual(list(self.paths.output_dir.iterdir()), [])

    def test_conflicting_review_targets_keep_original_basenames_in_download(self):
        first = b"first anonymous preserved PDF"
        second = b"second anonymous preserved PDF"
        (self.paths.input_dir / "first.pdf").write_bytes(first)
        (self.paths.input_dir / "second.PDF").write_bytes(second)
        from app.core.common import sha256_bytes
        plan = {"records": [
            {"original_name": name, "new_name": "待人工复核、same.pdf", "file_type": "ride_report",
             "status": "needs_review", "source_sha256": sha256_bytes(data)}
            for name, data in (("first.pdf", first), ("second.PDF", second))
        ]}
        with zipfile.ZipFile(web._build_download_zip(plan)) as archive:
            pdfs = {item.filename: archive.read(item) for item in archive.infolist()
                    if item.filename.lower().endswith(".pdf")}
        self.assertEqual(pdfs, {"first.pdf": first, "second.PDF": second})

    def test_consecutive_unknown_and_recognized_batches_keep_unmanaged_evidence(self):
        evidence = self.root / ".runtime" / "release-report.md"
        evidence.parent.mkdir(exist_ok=True)
        evidence.write_bytes(b"retained historical report")
        unmanaged = self.paths.output_dir / "retained" / "history.pdf"
        unmanaged.parent.mkdir()
        unmanaged.write_bytes(b"retained unrelated nested PDF")
        first_scan = self.scan([("unknown.pdf", b"unknown original")])
        # An unrelated pre-existing output directory must not be erased. It is
        # removed here only from this test fixture before a real organization.
        self.assertEqual(unmanaged.read_bytes(), b"retained unrelated nested PDF")
        unmanaged.unlink()
        unmanaged.parent.rmdir()
        first = self.organize(first_scan)
        second_scan = self.scan([("invoice.pdf", self.invoice)])
        second = self.organize(second_scan)
        self.assertEqual(self.client.get(first["download_url"]).status_code, 404)
        self.assertEqual(second["success_count"], 1)
        self.assertEqual(evidence.read_bytes(), b"retained historical report")
        self.assertEqual(list(self.paths.output_dir.glob("*.pdf"))[0].read_bytes(), self.invoice)


if __name__ == "__main__":
    unittest.main()
