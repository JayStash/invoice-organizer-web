"""Anonymous regressions for legacy VAT layouts and transport attachments.

All text, identifiers, dates, amounts and PDF objects below are synthetic.
These fixtures must remain independent of private invoice and release folders.
"""
from __future__ import annotations

import importlib
import io
import tempfile
import unittest
import zipfile
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from app import runtime
from app.core import common, organize_invoices, scan_invoices, validate_organization
from test_invoice_v131 import FONT_SIZE, synthetic_aviation_pdf


NUMBER = "00000001"
CODE = "000000000011"
DATE = "2026-01-03"


def vat_text(*, number=NUMBER, code=CODE, amount="37", item="城际铁路客运服务费"):
    code_line = f"发票代码:{code}\n" if code else ""
    return (
        "某省增值税电子普通发票\n"
        f"{code_line}发票号码:{number}\n开票日期:2026年01月03日\n"
        f"项目名称 金额 税率/征收率 税额\n*运输服务*{item} 33.94 9% 3.06\n"
        f"合计 ¥33.94 ¥3.06\n价税合计(大写) 金额文字 (小写) ¥{amount}\n"
    )


def ride_invoice_text(brand="", *, number="26000000000000000011", amount="25"):
    return (
        "电子发票(普通发票)\n"
        f"发票号码:{number}\n开票日期:2026年01月03日\n"
        f"{brand}出行\n*运输服务*客运服务费\n总金额:{amount}\n"
    )


def ride_report_text(brand="高德", *, amount="25"):
    return f"{brand}打车行程单\n行程日期:2026年01月02日\n合计:{amount}元\n"


def transit_report_text(*, amount="37", title="某城际轨道交通—行程单"):
    return (
        f"{title}\n申请时间:2026-01-03\n"
        "序号 出站时间 入站站点 出站站点 金额(元)\n"
        f"1 2026-01-02 12:00:00 甲站 乙站 {amount}\n合计:{amount}元\n"
    )


def paper_taxi_report_text(*, amount="11.55", count=1, car_type="超值出租车"):
    rows = [f"1 {car_type} 01-02 10:00 甲市 甲站 乙站 1.50 {amount}"]
    if count > 1:
        rows.append("2 经济型网约车 01-02 11:00 甲市 丙站 丁站 1.00 5.00")
    return (
        "滴滴出行-行程单\n"
        f"共{count}个行程，合计{amount}元\n"
        "申请日期:2026-01-03 行程起止日期:2026-01-02 至 2026-01-02\n"
        "序号 车型 上车时间 城市 起点 终点 里程[公里] 金额[元] 备注\n"
        + "\n".join(rows) + "\n页码:1/1\n"
    )


def record(text, name="anonymous.pdf"):
    with patch.object(common, "extract_pdf_text", return_value=text):
        return common.read_pdf_record(name, text.encode("utf-8"))


def text_pdf(placements):
    """Reuse the existing embedded-font fixture, replacing only its text.

    A generated ToUnicode map contains every fixture glyph, so this exercises
    real PDF extraction without reportlab, host fonts or private samples.
    """
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject

    reader = PdfReader(io.BytesIO(synthetic_aviation_pdf()))
    writer = PdfWriter()
    page = writer.add_page(reader.pages[0])
    characters = sorted(set("".join(text for text, _, _ in placements)))
    mappings = "\n".join(f"<{ord(char):04X}> <{ord(char):04X}>" for char in characters)
    cmap = DecodedStreamObject()
    cmap.set_data((
        "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /AnonymousTransit def\n/CMapType 2 def\n"
        "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
        f"{len(characters)} beginbfchar\n{mappings}\nendbfchar\n"
        "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
    ).encode("ascii"))
    page["/Resources"]["/Font"]["/F1"][NameObject("/ToUnicode")] = writer._add_object(cmap)
    contents = DecodedStreamObject()
    contents.set_data("\n".join(
        f"BT /F1 {FONT_SIZE} Tf 1 0 0 1 {x} {360 - top} Tm "
        f"<{text.encode('utf-16-be').hex()}> Tj ET"
        for text, x, top in placements
    ).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(contents)
    target = io.BytesIO()
    writer.write(target)
    return target.getvalue()


def lined_pdf(text):
    return text_pdf([(line, 35, 25 + index * 17) for index, line in enumerate(text.splitlines())])


class FakeTextPage:
    def __init__(self, default, geometric):
        self.default = default
        self.geometric = geometric

    def extract_text(self, *args, **kwargs):
        return self.default

    def extract_text_simple(self, *args, **kwargs):
        return self.geometric


class InvoiceV132ExtractionTests(unittest.TestCase):
    def extract_fake_page(self, default, geometric):
        with patch("pdfplumber.open") as opened:
            opened.return_value.__enter__.return_value.pages = [FakeTextPage(default, geometric)]
            return common.extract_pdf_text(b"anonymous-placeholder")

    def test_geometric_vat_text_is_selected_when_complete_and_consistent(self):
        default = "某省增值税电子普通发票\n发票代码:\n发票号码:\n开票日期: 年 月 日\n价税合计(大写) (小写)\n"
        geometric = vat_text()
        recovered = self.extract_fake_page(default, geometric)
        self.assertEqual(common.invoice_number_from_text(recovered), NUMBER)
        self.assertEqual(common.invoice_date_from_text(recovered), DATE)
        self.assertEqual(common.total_amount_from_text(recovered, "高铁", None), "37")

    def test_geometric_fallback_must_not_replace_a_conflicting_known_field(self):
        for known in (f"发票号码:{NUMBER}", "开票日期:2026年01月04日", "总金额:99"):
            with self.subTest(known=known):
                default = f"某省增值税电子普通发票\n{known}\n"
                geometric = vat_text(number="00000002")
                self.assertEqual(self.extract_fake_page(default, geometric), default)

    def test_geometric_fallback_preserves_an_already_identified_invoice_code(self):
        default = f"某省增值税电子普通发票\n发票代码:{CODE}\n发票号码:\n开票日期:\n"
        geometric = vat_text(code="000000000022")
        self.assertEqual(self.extract_fake_page(default, geometric), default)

    def test_complete_existing_vat_and_non_vat_text_remain_unchanged(self):
        complete = vat_text()
        self.assertEqual(self.extract_fake_page(complete, vat_text(amount="99")), complete)
        unrelated = "普通说明书\n发票号码:\n开票日期:\n"
        self.assertEqual(self.extract_fake_page(unrelated, vat_text()), unrelated)

    def test_fallback_does_not_select_an_incomplete_candidate(self):
        default = "某省增值税电子普通发票\n发票号码:\n开票日期:\n"
        geometric = "某省增值税电子普通发票\n机器编号:000000000099\n订单号:00000002\n"
        self.assertEqual(self.extract_fake_page(default, geometric), default)

    def test_legacy_code_and_number_preserve_leading_zeroes(self):
        legacy = record(vat_text())
        self.assertEqual(legacy["invoice_number"], NUMBER)
        self.assertEqual(legacy.get("invoice_code"), CODE)
        self.assertEqual(common.invoice_code_from_text("发票代码:0000000001"), "0000000001")
        self.assertIsNone(common.invoice_code_from_text("机器编号:000000000011\n订单号:00000001"))
        modern = record(ride_invoice_text("滴滴"))
        self.assertIsNone(modern.get("invoice_code"))

    def test_same_legacy_number_with_different_codes_is_not_a_duplicate(self):
        first = record(vat_text(code="000000000011", amount="37"), "first.pdf")
        second = record(vat_text(code="000000000022", amount="41"), "second.pdf")
        planned, issues = common.assign_plan([first, second], Path("output"))
        self.assertEqual(issues, [])
        self.assertTrue(all(item["status"] == "planned" for item in planned))

    def test_same_code_and_number_and_missing_code_keep_duplicate_protection(self):
        for code in (CODE, None):
            with self.subTest(code=code):
                records = [record(vat_text(code=code, amount=amount), f"{index}.pdf")
                           for index, amount in enumerate(("37", "41"))]
                planned, issues = common.assign_plan(records, Path("output"))
                self.assertTrue(issues)
                self.assertTrue(all(item["status"] == "needs_review" for item in planned))


class InvoiceV132AttachmentTests(unittest.TestCase):
    def test_report_brand_uses_its_text_before_the_filename(self):
        report = record(ride_report_text(), "滴滴行程单.pdf")
        self.assertEqual(report["ride_brand"], "高德")
        self.assertEqual(report.get("ride_brand_source"), "text")
        self.assertEqual(report["document_type"], "高德-行程单")
        self.assertEqual(common.ride_brand_from_text("曹操发票.pdf", "高德打车 曹操出行"), "高德")
        invoice = record(ride_invoice_text(), "滴滴发票.pdf")
        self.assertEqual(invoice["ride_brand"], "滴滴")
        self.assertEqual(invoice.get("ride_brand_source"), "filename")

    def test_transit_reports_need_ticket_content_and_do_not_override_invoices(self):
        report = record(transit_report_text(), "plain.pdf")
        self.assertEqual(report["file_type"], "ride_report")
        self.assertTrue(report.get("transit_report"))
        self.assertEqual(report["document_type"], "轨道交通行程单")
        for text, filename in (("欢迎乘坐地铁\n行程单", "plain.pdf"),
                               ("普通收据\n合计:37元", "地铁行程单.pdf")):
            with self.subTest(filename=filename, text=text):
                self.assertNotEqual(record(text, filename)["file_type"], "ride_report")
        invoice = record(vat_text(item="地铁客运服务费"), "地铁行程单.pdf")
        self.assertEqual(invoice["file_type"], "invoice_pdf")

    def test_transit_attachment_pairs_by_exact_amount_and_keeps_own_fields(self):
        rail_invoice = record(vat_text(), "rail.pdf")
        metro_invoice = record(vat_text(number="00000002", amount="15", item="地铁客运服务费"), "metro.pdf")
        rail_report = record(transit_report_text(), "route.pdf")
        metro_report = record(transit_report_text(amount="15", title="某地铁—行程单"), "metro-route.pdf")
        records, issues = common.assign_plan([metro_report, rail_invoice, rail_report, metro_invoice], Path("output"))
        self.assertEqual(issues, [])
        for attachment, invoice in ((rail_report, rail_invoice), (metro_report, metro_invoice)):
            self.assertEqual(attachment["status"], "planned")
            self.assertEqual(attachment["sequence"], invoice["sequence"])
            self.assertEqual(attachment["category"], invoice["category"])
            self.assertEqual(attachment["ride_relation"], invoice["new_name"])
            for field in ("invoice_number", "invoice_date", "amount_excluding_tax", "tax_rate", "tax_amount"):
                self.assertIsNone(attachment.get(field), field)
        self.assertEqual(len(common.output_records(records)), 4)

    def test_transit_attachment_marks_missing_invoice_as_paper_and_keeps_ambiguity_reviewable(self):
        for amounts in (("41",), ("37", "37")):
            with self.subTest(amounts=amounts):
                invoices = [record(vat_text(number=f"{index + 1:08}", amount=amount), f"{index}.pdf")
                            for index, amount in enumerate(amounts)]
                report = record(transit_report_text(), "route.pdf")
                records, _ = common.assign_plan([report, *invoices], Path("output"))
                self.assertEqual(report["status"], "planned" if amounts == ("41",) else "needs_review")
                self.assertEqual(bool(report.get("standalone_paper_invoice")), amounts == ("41",))
                self.assertNotIn("ride_relation", report)
                self.assertIn(report, common.output_records(records))

    def test_transit_attachment_cannot_pair_with_a_non_rail_local_transport_invoice(self):
        invoice = record(vat_text(item="机场大巴乘车费"), "airport-bus.pdf")
        report = record(transit_report_text(), "route.pdf")
        self.assertEqual(invoice["category"], "市内交通")
        common.assign_plan([invoice, report], Path("output"))
        self.assertEqual(report["status"], "planned")
        self.assertTrue(report.get("standalone_paper_invoice"))
        self.assertNotIn("ride_relation", report)

    def test_matching_report_cannot_claim_an_invoice_already_used_by_another(self):
        invoice = record(vat_text(), "invoice.pdf")
        reports = [record(transit_report_text(), f"route-{index}.pdf") for index in range(2)]
        common.assign_plan([invoice, *reports], Path("output"))
        self.assertLessEqual(sum(item["status"] == "planned" for item in reports), 1)
        self.assertTrue(any(item["status"] == "needs_review" for item in reports))

    def test_ride_report_with_no_equal_amount_invoice_uses_paper_annotation(self):
        invoice = record(ride_invoice_text("高德", amount="30"))
        report = record(ride_report_text(amount="25"), "trip.pdf")
        common.assign_plan([invoice, report], Path("output"))
        self.assertEqual(report["status"], "planned")
        self.assertTrue(report.get("standalone_paper_invoice"))
        self.assertNotIn("ride_relation", report)

    def test_text_brand_report_can_match_unique_filename_only_brand_invoice(self):
        same_brand_wrong_amount = record(ride_invoice_text("高德", amount="30"))
        filename_only = record(ride_invoice_text(number="26000000000000000012", amount="25"), "滴滴发票.pdf")
        report = record(ride_report_text(amount="25"), "滴滴行程单.pdf")
        records, issues = common.assign_plan([same_brand_wrong_amount, report, filename_only], Path("output"))
        self.assertEqual(issues, [])
        self.assertEqual(report["status"], "planned")
        self.assertEqual(report["ride_relation"], filename_only["new_name"])
        self.assertEqual(report["ride_brand"], "高德")
        self.assertIn("高德", report["new_name"])
        self.assertEqual(len(common.output_records(records)), 3)

    def test_brand_fallback_must_not_override_another_explicit_text_brand(self):
        invoice = record(ride_invoice_text("滴滴", amount="25"), "滴滴发票.pdf")
        report = record(ride_report_text("高德", amount="25"), "trip.pdf")
        common.assign_plan([invoice, report], Path("output"))
        self.assertEqual(report["status"], "needs_review")
        self.assertNotIn("ride_relation", report)

    def test_filename_brand_fallback_requires_unique_amount_without_date_tiebreak(self):
        first = record(ride_invoice_text(amount="25"), "滴滴发票.pdf")
        second = record(ride_invoice_text(number="26000000000000000012", amount="25"), "曹操发票.pdf")
        first["business_date"] = "2026-01-02"
        second["business_date"] = "2026-01-01"
        report = record(ride_report_text(amount="25"), "trip.pdf")
        common.assign_plan([first, report, second], Path("output"))
        self.assertEqual(report["status"], "needs_review")
        self.assertNotIn("ride_relation", report)

    def test_aggregate_platform_report_matches_its_printed_service_operator(self):
        invoice = record(ride_invoice_text("风韵", amount="25"), "operator-invoice.pdf")
        report = record(ride_report_text("高德", amount="25")
                        + "序号 服务商 车型 上车时间 金额\n1 风韵出行 经济型 2026-01-02 25.00\n",
                        "trip.pdf")
        self.assertEqual(report.get("ride_service_brands"), ["风韵"])
        self.assertEqual(invoice.get("ride_brand_source"), "text")
        common.assign_plan([invoice, report], Path("output"))
        self.assertEqual(report["status"], "planned")
        self.assertEqual(report["ride_relation"], invoice["new_name"])
        self.assertEqual(report["ride_brand"], "高德")
        self.assertIn("高德", report["new_name"])
        self.assertIsNone(report.get("invoice_number"))
        self.assertIsNone(report.get("tax_amount"))

    def test_service_operator_match_keeps_missing_paper_and_ambiguous_invoice_cases_distinct(self):
        for amounts in (("30",), ("25", "25")):
            with self.subTest(amounts=amounts):
                invoices = [record(ride_invoice_text("风韵", number=f"260000000000000000{index + 11}",
                                                     amount=amount), f"operator-{index}.pdf")
                            for index, amount in enumerate(amounts)]
                report = record(ride_report_text("高德", amount="25")
                                + "序号 服务商 车型 金额\n1 风韵出行 经济型 25.00\n", "trip.pdf")
                # The service-operator fallback requires an exact unique amount,
                # even when a date could otherwise break a tie.
                invoices[0]["business_date"] = report["business_date"]
                common.assign_plan([*invoices, report], Path("output"))
                self.assertEqual(report["status"], "planned" if amounts == ("30",) else "needs_review")
                self.assertEqual(bool(report.get("standalone_paper_invoice")), amounts == ("30",))
                self.assertNotIn("ride_relation", report)

    def test_service_operator_fallback_requires_printed_provider_table_evidence(self):
        invoice = record(ride_invoice_text("风韵", amount="25"), "operator-invoice.pdf")
        report = record(ride_report_text("高德", amount="25") + "其他文字:风韵出行\n", "trip.pdf")
        self.assertNotIn("ride_service_brands", report)
        common.assign_plan([invoice, report], Path("output"))
        self.assertEqual(report["status"], "needs_review")
        self.assertNotIn("ride_relation", report)

    def test_standalone_ride_report_with_amount_is_named_and_annotated_as_paper(self):
        invoice = record(ride_invoice_text("滴滴", amount="25"), "invoice.pdf")
        report = record(ride_report_text("滴滴", amount="11.55"), "single-trip.pdf")
        records, _ = common.assign_plan([invoice, report], Path("output"))
        self.assertEqual(report["status"], "planned")
        self.assertTrue(report.get("standalone_paper_invoice"))
        self.assertIn("（对应纸质发票）", report.get("remark", ""))
        self.assertNotIn("待人工复核", report["new_name"])
        self.assertIn(report, common.output_records(records))
        self.assertIsNone(report.get("invoice_number"))
        self.assertIsNone(report.get("tax_amount"))
        self.assertEqual(report["total_amount"], "11.55")

    def test_single_taxi_paper_report_gets_normal_name_and_continuous_sequence(self):
        rail = record(vat_text(), "rail.pdf")
        hotel = record(vat_text(number="00000002", amount="80", item="住宿费"), "hotel.pdf")
        invoice = record(ride_invoice_text("滴滴", amount="25"), "ride.pdf")
        attachment = record(ride_report_text("滴滴", amount="25"), "ride-trip.pdf")
        paper = record(paper_taxi_report_text(), "taxi-trip.pdf")
        records, issues = common.assign_plan([attachment, invoice, paper, hotel, rail], Path("output"))
        self.assertEqual(issues, [])
        self.assertEqual(paper["status"], "planned")
        self.assertTrue(paper.get("standalone_paper_invoice"))
        self.assertEqual(paper["new_name"], "3、滴滴行程单-2026-01-02-11.55元（对应纸质发票）.pdf")
        self.assertIn("（对应纸质发票）", paper.get("remark", ""))
        self.assertNotIn("ride_relation", paper)
        self.assertEqual([item["sequence"] for item in common.output_records(records)], [1, 2, 3, 4, 4])
        for field in ("invoice_number", "invoice_date", "amount_excluding_tax", "tax_rate", "tax_amount"):
            self.assertIsNone(paper.get(field), field)

    def test_single_taxi_paper_rule_is_independent_of_the_report_amount(self):
        paper = record(paper_taxi_report_text(amount="19.75"), "taxi-trip.pdf")
        common.assign_plan([paper], Path("output"))
        self.assertEqual(paper["status"], "planned")
        self.assertTrue(paper.get("standalone_paper_invoice"))
        self.assertEqual(paper["new_name"], "1、滴滴行程单-2026-01-02-19.75元（对应纸质发票）.pdf")

    def test_taxi_report_with_a_matching_electronic_invoice_remains_paired(self):
        invoice = record(ride_invoice_text("滴滴", amount="11.55"), "invoice.pdf")
        report = record(paper_taxi_report_text(), "taxi-trip.pdf")
        common.assign_plan([invoice, report], Path("output"))
        self.assertEqual(report["status"], "planned")
        self.assertFalse(report.get("standalone_paper_invoice", False))
        self.assertEqual(report["sequence"], invoice["sequence"])
        self.assertEqual(report["ride_relation"], invoice["new_name"])
        self.assertNotIn("（对应纸质发票）", report.get("remark", ""))

    def test_multiple_trips_with_missing_invoice_use_paper_but_ambiguous_electronic_matches_do_not(self):
        mixed = record(paper_taxi_report_text(count=2), "mixed-trip.pdf")
        common.assign_plan([mixed], Path("output"))
        self.assertTrue(mixed.get("standalone_paper_invoice"))
        self.assertEqual(mixed["status"], "planned")
        self.assertIn("（对应纸质发票）", mixed.get("remark", ""))
        invoices = [record(ride_invoice_text("滴滴", number=f"260000000000000000{index + 11}",
                                            amount="11.55"), f"invoice-{index}.pdf")
                    for index in range(2)]
        report = record(paper_taxi_report_text(), "taxi-trip.pdf")
        common.assign_plan([*invoices, report], Path("output"))
        self.assertEqual(report["status"], "needs_review")
        self.assertFalse(report.get("standalone_paper_invoice", False))
        self.assertNotIn("ride_relation", report)

    def test_paper_report_without_printed_date_does_not_invent_a_date(self):
        report = record("高德打车行程单\n合计:19.75元\n", "undated-trip.pdf")
        common.assign_plan([report], Path("output"))
        self.assertEqual(report["status"], "planned")
        self.assertTrue(report.get("standalone_paper_invoice"))
        self.assertIsNone(report.get("business_date"))
        self.assertIsNone(report.get("invoice_date"))
        self.assertEqual(report["new_name"], "1、高德行程单-19.75元（对应纸质发票）.pdf")

    def test_report_without_printed_amount_remains_reviewable(self):
        report = record("高德打车行程单\n行程日期:2026-01-02\n", "amountless-trip.pdf")
        common.assign_plan([report], Path("output"))
        self.assertEqual(report["status"], "needs_review")
        self.assertFalse(report.get("standalone_paper_invoice", False))

    def test_duplicate_electronic_invoices_do_not_make_a_report_look_like_paper(self):
        cases = ((ride_invoice_text("滴滴", amount="25"), ride_report_text("滴滴", amount="25")),
                 (vat_text(), transit_report_text()))
        for invoice_text, report_text in cases:
            with self.subTest(transit="城际" in invoice_text):
                invoices = [record(invoice_text, f"duplicate-{index}.pdf") for index in range(2)]
                report = record(report_text, "trip.pdf")
                records, issues = common.assign_plan([*invoices, report], Path("output"))
                self.assertTrue(issues)
                self.assertTrue(all(item["status"] == "needs_review" for item in invoices))
                self.assertEqual(report["status"], "needs_review")
                self.assertFalse(report.get("standalone_paper_invoice", False))
                self.assertNotIn("ride_relation", report)
                self.assertNotIn("（对应纸质发票）", report.get("remark", ""))
                self.assertIn(report, common.output_records(records))

    def test_reviewable_electronic_invoice_still_prevents_a_false_paper_annotation(self):
        cases = ((ride_invoice_text("滴滴", amount="25"), ride_report_text("滴滴", amount="25")),
                 (vat_text(), transit_report_text()))
        for invoice_text, report_text in cases:
            with self.subTest(transit="城际" in invoice_text):
                incomplete = invoice_text.replace("开票日期:2026年01月03日\n", "")
                invoice = record(incomplete, "incomplete-invoice.pdf")
                self.assertIsNone(invoice["business_date"])
                report = record(report_text, "trip.pdf")
                common.assign_plan([invoice, report], Path("output"))
                self.assertEqual(invoice["status"], "needs_review")
                self.assertEqual(report["status"], "needs_review")
                self.assertFalse(report.get("standalone_paper_invoice", False))
                self.assertNotIn("ride_relation", report)
                self.assertNotIn("（对应纸质发票）", report.get("remark", ""))


class InvoiceV132PdfFlowTests(unittest.TestCase):
    def test_real_generated_pdf_and_zip_attachments_organize_and_validate(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as patches:
            core_globals = {
                "app.core.common": ("SKILL_ROOT", "DEFAULT_INPUT_DIR", "DEFAULT_OUTPUT_DIR",
                                    "RUNTIME_DIR", "DEFAULT_PLAN_PATH", "DEFAULT_PREVIEW_PATH"),
                "app.core.scan_invoices": ("DEFAULT_INPUT_DIR", "DEFAULT_OUTPUT_DIR", "RUNTIME_DIR",
                                           "DEFAULT_PLAN_PATH", "DEFAULT_PREVIEW_PATH"),
                "app.core.organize_invoices": ("RUNTIME_DIR",),
            }
            for name, names in core_globals.items():
                module = importlib.import_module(name)
                patches.enter_context(patch.multiple(module, **{key: getattr(module, key) for key in names}))
            paths = runtime.configure_core_runtime(Path(temporary))
            invoice_pdf = lined_pdf(vat_text())
            report_pdf = lined_pdf(transit_report_text())
            # Generic ride evidence intentionally has no taxi/single-trip hint.
            paper_pdf = lined_pdf(ride_report_text("滴滴", amount="11.55"))
            direct_pdf = lined_pdf(vat_text(number="00000002", amount="15", item="地铁客运服务费"))
            (paths.input_dir / "direct.pdf").write_bytes(direct_pdf)
            archive_path = paths.input_dir / "attachments.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("invoices/legacy.pdf", invoice_pdf)
                archive.writestr("routes/attachment.pdf", report_pdf)
                archive.writestr("routes/paper-taxi.pdf", paper_pdf)
                archive.writestr("notes.txt", "anonymous ignored member")
            before = {p.name: p.read_bytes() for p in paths.input_dir.iterdir()}
            plan = scan_invoices(paths.input_dir, paths.output_dir)
            self.assertEqual(plan["issues"], [])
            expected = common.output_records(deepcopy(plan["records"]))
            self.assertEqual(len(expected), 4)
            self.assertTrue(all(item["status"] == "planned" for item in expected))
            result = organize_invoices(paths.plan_path, plan["approval_token"])
            self.assertEqual(result.processed_count, 4)
            validation = validate_organization(paths.plan_path)
            self.assertTrue(validation.is_valid, validation.errors)
            payloads = {"legacy.pdf": invoice_pdf, "attachment.pdf": report_pdf,
                        "direct.pdf": direct_pdf, "paper-taxi.pdf": paper_pdf}
            for item in expected:
                self.assertEqual((paths.output_dir / item["new_name"]).read_bytes(), payloads[item["original_name"]])
            self.assertEqual({p.name: p.read_bytes() for p in paths.input_dir.iterdir()}, before)
            workbook = load_workbook(result.workbook_path, data_only=True)
            try:
                rows = list(workbook.active.iter_rows(min_row=2, values_only=True))
                report = next(item for item in expected if item.get("transit_report"))
                report_row = next(row for row in rows if row[0] == report["new_name"])
                self.assertEqual(report_row[3], "轨道交通行程单")
                for index in (1, 4, 5, 6, 10):
                    self.assertIsNone(report_row[index])
                self.assertEqual(report_row[9], 37)
                paper = next(item for item in expected if item.get("standalone_paper_invoice"))
                self.assertEqual(paper["sequence"], 2)
                paper_row = next(row for row in rows if row[0] == paper["new_name"])
                self.assertEqual(paper_row[9], 11.55)
                self.assertIn("（对应纸质发票）", paper_row[11])
                for index in (1, 4, 5, 6, 10):
                    self.assertIsNone(paper_row[index])
            finally:
                workbook.close()


if __name__ == "__main__":
    unittest.main()
