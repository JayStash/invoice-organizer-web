"""Anonymous relationship and expense-role regressions for v1.1.00."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from app.core import common
from test_invoice_v132 import vat_text


def invoice(number="26000000000000000101", amount="30", *, mode="car", brand="滴滴", evidence=None):
    return {
        "original_name": f"invoice-{number}.pdf", "file_type": "invoice_pdf", "document_role": "invoice",
        "invoice_number": number, "invoice_code": None, "total_amount": amount,
        "source_sha256": f"invoice-{number}", "category": "市内交通", "purpose": "市内交通",
        "expense_type": "市内交通费", "business_date": "2026-03-02", "invoice_date": "2026-03-03",
        "ride_document": mode == "car", "ride_brand": brand if mode == "car" else None,
        "ride_brand_source": "text", "transport_mode": mode, "transit_invoice": mode == "transit",
        "match_evidence": evidence or {},
    }


def itinerary(amount="30", *, mode="car", brand="滴滴", evidence=None, suffix="1"):
    return {
        "original_name": f"itinerary-{suffix}.pdf", "file_type": "ride_report", "document_role": "itinerary",
        "invoice_number": None, "total_amount": amount, "source_sha256": f"report-{suffix}",
        "category": "市内交通", "purpose": "行程单", "expense_type": "市内交通费",
        "business_date": "2026-03-02", "business_date_source": "trip_date", "invoice_date": None,
        "ride_document": mode == "car", "ride_brand": brand if mode == "car" else None,
        "ride_brand_source": "text", "transport_mode": mode, "transit_report": mode == "transit",
        "match_evidence": evidence or {},
    }


class ExpenseRelationTests(unittest.TestCase):
    def plan(self, *records):
        planned, _ = common.assign_plan(list(records), Path("output"))
        return planned

    def test_pair_keeps_both_printed_amounts_but_only_invoice_contributes(self):
        ticket, report = invoice(), itinerary()
        self.plan(ticket, report)
        self.assertEqual(ticket["expense_id"], report["expense_id"])
        self.assertTrue(ticket["counts_toward_total"])
        self.assertEqual(ticket["expense_amount"], "30")
        self.assertFalse(report["counts_toward_total"])
        self.assertIsNone(report["expense_amount"])
        self.assertEqual(report["expense_basis"], "attachment")
        self.assertEqual(report["total_amount"], "30")
        self.assertIsNone(report["invoice_number"])

    def test_airport_bus_invoices_pair_by_printed_journey_date_and_charge_once(self):
        tickets = []
        for number, day in (("00000101", "2026-01-02"), ("00000102", "2026-01-04")):
            text = vat_text(number=number, amount="20", item="客运费") + (
                "销售方:某空港航空服务有限公司\n"
                "出行人 有效身份证件号 出行日期 出发地 到达地 等级 交通工具类型\n"
                f"匿名旅客 匿名证件 {day} 甲站 乙站 长途汽车\n"
            )
            with patch.object(common, "extract_pdf_text", return_value=text):
                tickets.append(common.read_pdf_record(number + ".pdf", text.encode()))
        report = itinerary(amount="20", mode="airport_bus", evidence={"journey_dates":["2026-01-02"]})
        self.plan(*tickets, report)
        self.assertEqual(report["ride_relation"], tickets[0]["new_name"])
        self.assertEqual(report["expense_id"], tickets[0]["expense_id"])
        self.assertFalse(report["counts_toward_total"])
        self.assertNotIn("standalone_paper_invoice", report)
        self.assertEqual(sum(int(item["expense_amount"]) for item in [*tickets, report] if item["counts_toward_total"]), 40)

    def test_unresolved_mode_of_same_fare_transport_invoice_blocks_paper_claim(self):
        ticket = invoice(amount="20", mode=None, brand=None)
        ticket.update(ride_document=False, ride_brand=None, transport_mode=None,
                      category="大型交通", purpose="汽车票", expense_type="飞机车船费")
        report = itinerary(amount="20", mode="airport_bus")
        self.plan(ticket, report)
        self.assertEqual(report["status"], "needs_review")
        self.assertNotIn("standalone_paper_invoice", report)
        self.assertFalse(report["counts_toward_total"])

    def test_same_date_and_fare_buses_need_compatible_printed_routes(self):
        first = invoice("00000111", "20", mode="airport_bus", brand=None,
                        evidence={"journey_dates":["2026-01-02"], "routes":["甲站→乙站"]})
        other = invoice("00000112", "20", mode="airport_bus", brand=None,
                        evidence={"journey_dates":["2026-01-02"], "routes":["丙站→丁站"]})
        report = itinerary(amount="20", mode="airport_bus",
                           evidence={"journey_dates":["2026-01-02"], "routes":["甲站→乙站"]})
        self.plan(first, other, report)
        self.assertEqual(report["ride_relation"], first["new_name"])
        self.assertFalse(report["counts_toward_total"])
        conflicting = itinerary(amount="20", mode="airport_bus", suffix="different",
                                evidence={"journey_dates":["2026-01-02"], "routes":["戊站→己站"]})
        self.plan(first, other, conflicting)
        self.assertEqual(conflicting["status"], "needs_review")
        self.assertNotIn("standalone_paper_invoice", conflicting)

    def test_same_fare_different_ground_transport_type_blocks_paper_claim(self):
        ticket = invoice(amount="20", mode="passenger_bus", brand=None,
                         evidence={"journey_dates":["2026-02-03"], "routes":["甲机场→乙酒店"]})
        report = itinerary(amount="20", mode="airport_bus",
                           evidence={"journey_dates":["2026-02-03"], "routes":["丙地→丁地"]})
        self.plan(ticket, report)
        self.assertEqual(report["status"], "needs_review")
        self.assertNotIn("standalone_paper_invoice", report)

    def test_passenger_reports_pair_by_date_and_route_without_double_counting(self):
        first = invoice("00000111", "25", mode="passenger_bus", brand=None,
                        evidence={"journey_dates": ["2026-01-02"], "routes": ["甲市→乙县"]})
        second = invoice("00000112", "25", mode="passenger_bus", brand=None,
                         evidence={"journey_dates": ["2026-01-03"], "routes": ["乙县→甲市"]})
        reports = []
        for index, ticket in enumerate((first, second)):
            report = itinerary(amount="25", mode="passenger_bus", suffix=str(index),
                               evidence=ticket["match_evidence"])
            report.update(category="大型交通", purpose="汽车行程单", expense_type="飞机车船费")
            reports.append(report)
        self.plan(first, second, *reports)
        for ticket, report in zip((first, second), reports):
            self.assertEqual(report["ride_relation"], ticket["new_name"])
            self.assertEqual(report["purpose"], "汽车行程单")
            self.assertFalse(report["counts_toward_total"])
            self.assertNotIn("standalone_paper_invoice", report)
            self.assertEqual(report["expense_id"], ticket["expense_id"])

    def test_genuinely_missing_invoice_preserves_paper_rule_for_all_city_modes(self):
        for mode in ("car", "transit", "airport_bus"):
            with self.subTest(mode=mode):
                report = itinerary(mode=mode)
                self.plan(report)
                self.assertEqual(report["status"], "planned")
                self.assertEqual(report["expense_basis"], "paper_itinerary")
                self.assertTrue(report["counts_toward_total"])
                self.assertIn("（对应纸质发票）", report["new_name"])
                self.assertIsNone(report["invoice_number"])

    def test_city_and_explicit_journey_conflicts_cannot_become_paper(self):
        for field, first, second in (("cities", ["甲市"], ["乙市"]),
                                     ("journey_dates", ["2026-03-01"], ["2026-03-02"]),
                                     ("order_numbers", ["ANON-001"], ["ANON-002"])):
            with self.subTest(field=field):
                ticket, report = invoice(evidence={field: first}), itinerary(evidence={field: second})
                self.plan(ticket, report)
                self.assertEqual(report["match_status"], "conflict")
                self.assertEqual(report["status"], "needs_review")
                self.assertNotIn("new_name", report)
                self.assertNotIn("standalone_paper_invoice", report)
                self.assertFalse(report["counts_toward_total"])
                self.assertEqual(report["total_amount"], "30")

    def test_invoice_issue_date_does_not_conflict_with_actual_trip_date(self):
        ticket = invoice(evidence={})
        ticket["invoice_date"] = "2026-03-20"
        ticket["business_date"] = "2026-03-20"
        report = itinerary(evidence={"journey_dates": ["2026-03-02"]})
        self.plan(ticket, report)
        self.assertEqual(report["match_status"], "matched")

    def test_multiple_same_fares_cannot_be_broken_by_filename_letters_or_issue_date(self):
        first, second, report = invoice(), invoice("26000000000000000102"), itinerary()
        report["letter"] = "A"
        first["invoice_date"] = "2026-03-02"
        second["invoice_date"] = "2026-03-04"
        self.plan(first, second, report)
        self.assertEqual(report["match_status"], "multiple")
        self.assertNotIn("new_name", report)
        self.assertFalse(report["counts_toward_total"])

    def test_explicit_order_can_distinguish_same_amount_candidates(self):
        first = invoice(evidence={"order_numbers": ["ANON-001"]})
        second = invoice("26000000000000000102", evidence={"order_numbers": ["ANON-002"]})
        report = itinerary(evidence={"order_numbers": ["ANON-002"]})
        self.plan(first, second, report)
        self.assertEqual(report["ride_relation"], second["new_name"])

    def test_same_amount_generic_local_fee_is_not_a_universal_itinerary_match(self):
        ticket, report = invoice(mode="unknown"), itinerary(mode="transit")
        self.plan(ticket, report)
        self.assertNotIn("ride_relation", report)
        self.assertTrue(report.get("standalone_paper_invoice"))

    def test_service_operator_zero_candidates_does_not_silently_auto_match_filename(self):
        ticket = invoice(brand="滴滴")
        ticket["ride_brand_source"] = "filename"
        report = itinerary(brand="高德")
        report["ride_service_brands"] = ["如祺"]
        self.plan(ticket, report)
        self.assertEqual(report["match_status"], "conflict")
        self.assertTrue(report["match_candidates"])
        self.assertNotIn("new_name", report)

    def test_duplicate_or_incomplete_electronic_invoice_blocks_paper_claim(self):
        for incomplete in (False, True):
            with self.subTest(incomplete=incomplete):
                first = invoice()
                tickets = [first, deepcopy(first)]
                if incomplete:
                    first["business_date"] = None
                    tickets = [first]
                report = itinerary()
                self.plan(*tickets, report)
                self.assertEqual(report["status"], "needs_review")
                self.assertNotIn("new_name", report)
                self.assertNotIn("standalone_paper_invoice", report)
                self.assertFalse(report["counts_toward_total"])

    def test_different_trips_claiming_same_invoice_both_remain_original_review(self):
        ticket = invoice()
        first = itinerary(evidence={"journey_dates": ["2026-03-01"]})
        second = itinerary(evidence={"journey_dates": ["2026-03-02"]}, suffix="2")
        planned = self.plan(ticket, first, second)
        self.assertEqual(common.output_records(planned), [ticket])
        for report in (first, second):
            self.assertEqual(report["status"], "needs_review")
            self.assertNotIn("new_name", report)
            self.assertFalse(report["counts_toward_total"])

    def test_duplicate_paper_itinerary_content_is_preserved_for_review_not_billed_twice(self):
        first, second = itinerary(), itinerary(suffix="2")
        second["source_sha256"] = first["source_sha256"]
        self.plan(first, second)
        self.assertTrue(all(item["status"] == "needs_review" for item in (first, second)))
        self.assertTrue(all(not item["counts_toward_total"] for item in (first, second)))

    def test_supporting_receipt_has_sequence_and_own_number_without_invoice_or_expense(self):
        receipt = {"original_name": "receipt.pdf", "file_type": "supporting_receipt",
                   "document_role": "supporting_receipt", "receipt_number": "ANON-RECEIPT-1",
                   "invoice_number": None, "total_amount": "12", "source_sha256": "receipt-hash",
                   "category": "其他", "purpose": "货运收款凭证", "business_date": "2026-03-04"}
        ticket, report = invoice(), itinerary()
        self.plan(receipt, ticket, report)
        self.assertEqual(receipt["sequence"], 2)
        self.assertEqual(report["sequence"], ticket["sequence"])
        self.assertIn("ANON-RECEIPT-1", receipt["new_name"])
        self.assertEqual(receipt["expense_basis"], "supporting_receipt")
        self.assertFalse(receipt["counts_toward_total"])
        self.assertIsNone(receipt["invoice_number"])

    def test_identity_conflict_does_not_get_a_name_or_an_expense(self):
        ticket = invoice()
        ticket["recognition_conflicts"] = ["multiple_invoice_identities"]
        self.plan(ticket)
        self.assertEqual(ticket["status"], "needs_review")
        self.assertNotIn("new_name", ticket)
        self.assertFalse(ticket["counts_toward_total"])


if __name__ == "__main__":
    unittest.main()
