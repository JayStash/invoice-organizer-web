"""Synthetic regressions for urban railway classification and ZIP PDFs.

The fixtures use invented identifiers, companies, amounts and dates.  They do
not depend on private invoice files or local diagnostic/release directories.
"""
from __future__ import annotations

import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.core import common
from test_invoice_v132 import FakeTextPage, lined_pdf, vat_text


def urban_vat_text():
    return vat_text(number="00000120", code="000000000123", amount="17", item="客运服务费") + (
        "销售方名称:某市市域铁路运营有限公司\n"
        "地址:某市轨道交通服务中心\n"
    )


class InvoiceV1100ExtractionTests(unittest.TestCase):
    def test_suburban_railway_vat_uses_local_transport_without_filename_hint(self):
        text = urban_vat_text()
        self.assertEqual(
            common.classify("anonymous.pdf", text),
            ("市内交通", "市内交通", "市内交通费"),
        )

    def test_actual_railway_eticket_retains_priority_over_urban_railway_context(self):
        text = (
            "铁路电子客票 中国铁路 12306\n"
            "发票号码:26000000000000000120\n"
            "备注:可换乘市域铁路\n"
        )
        self.assertEqual(common.document_type_from_text(text), "铁路电子客票")
        self.assertEqual(
            common.classify("anonymous.pdf", text),
            ("大型交通", "高铁", "飞机车船费"),
        )

    def test_existing_intercity_and_metro_classifications_remain_unchanged(self):
        self.assertEqual(
            common.classify("anonymous.pdf", vat_text(item="城际铁路客运服务费")),
            ("大型交通", "高铁", "飞机车船费"),
        )
        self.assertEqual(
            common.classify("anonymous.pdf", vat_text(item="地铁客运服务费")),
            ("市内交通", "市内交通", "市内交通费"),
        )

    def test_layered_vat_recovery_keeps_city_railway_identity_and_fields(self):
        blank_form = (
            "某省增值税电子普通发票\n发票代码:\n发票号码:\n"
            "开票日期: 年 月 日\n价税合计(大写) (小写)\n"
        )
        with patch("pdfplumber.open") as opened:
            opened.return_value.__enter__.return_value.pages = [FakeTextPage(blank_form, urban_vat_text())]
            record = common.read_pdf_record("anonymous.pdf", b"anonymous-layered-pdf")
        self.assertEqual(record["invoice_number"], "00000120")
        self.assertEqual(record["invoice_code"], "000000000123")
        self.assertEqual(record["invoice_date"], "2026-01-03")
        self.assertEqual(record["total_amount"], "17")
        self.assertEqual(record["category"], "市内交通")
        records, issues = common.assign_plan([record], Path("output"))
        self.assertEqual(issues, [])
        self.assertEqual(records[0]["new_name"], "1、市内交通-00000120-17元.pdf")

    def test_generated_anonymous_city_railway_pdf_has_a_complete_plan(self):
        payload = lined_pdf(urban_vat_text())
        digest = common.sha256_bytes(payload)
        record = common.read_pdf_record("anonymous.pdf", payload)
        records, issues = common.assign_plan([record], Path("output"))
        self.assertEqual(issues, [])
        self.assertEqual(records[0]["status"], "planned")
        self.assertEqual(records[0]["new_name"], "1、市内交通-00000120-17元.pdf")
        self.assertEqual(common.sha256_bytes(payload), digest)
        self.assertEqual(records[0]["source_sha256"], digest)


class InvoiceV1100ArchiveScanTests(unittest.TestCase):
    def test_duplicate_zip_names_keep_their_exact_entry_bytes_and_indices(self):
        first, second = lined_pdf(urban_vat_text()), lined_pdf(vat_text(number="00000121"))
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "anonymous.zip"
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(source, "w") as archive:
                    archive.writestr("nested/", b"")
                    archive.writestr("nested/repeated.pdf", first)
                    archive.writestr("note.txt", b"anonymous")
                    archive.writestr("nested/repeated.pdf", second)
            before = common.sha256_file(source)
            records, ignored = common.scan_input(Path(temporary))
            members = [item for item in records if item.get("archive_member", "").endswith(".pdf")]
            self.assertEqual(ignored, [])
            self.assertEqual(len(members), 2)
            self.assertEqual([item["archive_member_index"] for item in members], [1, 3])
            self.assertEqual([item["member_sha256"] for item in members],
                             [common.sha256_bytes(first), common.sha256_bytes(second)])
            self.assertEqual([item["invoice_number"] for item in members], ["00000120", "00000121"])
            self.assertEqual(common.sha256_file(source), before)

    def test_unextractable_pdf_does_not_stop_later_zip_members(self):
        first, second = b"anonymous-unextractable-pdf", b"anonymous-extractable-pdf"
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "anonymous.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("first.pdf", first)
                archive.writestr("second.pdf", second)
            before = common.sha256_file(source)
            successful = {"original_name": "second.pdf", "file_type": "archive_pdf", "source_sha256": common.sha256_bytes(second)}
            with patch.object(common, "read_pdf_record", side_effect=[RuntimeError("synthetic extraction failure"), successful]):
                records, ignored = common.scan_input(Path(temporary))
            members = [item for item in records if item.get("archive_member")]
            self.assertEqual(ignored, [])
            self.assertEqual(len(members), 2)
            self.assertEqual(records[0]["status"], "source_only")
            failed = members[0]
            self.assertEqual(failed["file_type"], "other")
            self.assertEqual(failed["status"], "needs_review")
            self.assertEqual(failed["archive_source"], "anonymous.zip")
            self.assertEqual(failed["archive_member_index"], 0)
            self.assertEqual(failed["source_sha256"], common.sha256_bytes(first))
            self.assertEqual(failed["member_sha256"], common.sha256_bytes(first))
            self.assertEqual(members[1]["file_type"], "archive_pdf")
            self.assertEqual(members[1]["archive_member_index"], 1)
            self.assertEqual(common.sha256_file(source), before)


if __name__ == "__main__":
    unittest.main()
