from __future__ import annotations

import unittest

from app.core.common import (
    assign_plan,
    classify,
    document_type_from_text,
    tax_rate_from_text,
    total_amount_from_text,
)
from pathlib import Path


class CoreRegressionTests(unittest.TestCase):
    def test_rail_ticket_amount_before_label_does_not_use_id_number(self) -> None:
        text = "￥212.00\n票价:\n4503282002****0036"
        self.assertEqual(total_amount_from_text(text, "高铁", None), "212")

    def test_rail_ticket_document_type_uses_rail_context(self) -> None:
        text = "电子发票（统铁一发路票监电子客票）\n买票请到12306\n中国铁路"
        self.assertEqual(document_type_from_text(text), "铁路电子客票")

    def test_local_transport_uses_requested_expense_type(self) -> None:
        self.assertEqual(classify("滴滴发票A.pdf", "滴滴出行")[2], "市内交通费")
        self.assertEqual(classify("出租车票.pdf", "出租车")[2], "市内交通费")

    def test_amap_ride_invoice_is_local_transport(self) -> None:
        category, purpose, expense_type = classify(
            "【曹操出行-87.96元-1个行程】高德打车电子发票.pdf",
            "旅客运输服务\n*交通运输服务*客运服务费",
        )

        self.assertEqual((category, purpose, expense_type), ("市内交通", "市内交通", "市内交通费"))

    def test_explicit_non_taxable_rate_is_preserved(self) -> None:
        self.assertEqual(tax_rate_from_text("税率/征收率 不征税"), ("不征税", False))
        self.assertEqual(
            tax_rate_from_text("税率/征收率 3%\n其他项目 不征税"),
            (None, True),
        )

    def test_planned_filename_uses_ideographic_comma(self) -> None:
        record = {
            "original_name": "rail.pdf",
            "file_type": "invoice_pdf",
            "category": "大型交通",
            "purpose": "高铁",
            "business_date": "2026-08-14",
            "invoice_number": "26449124086000120595",
            "total_amount": "212",
            "source_sha256": "test-hash",
        }

        records, issues = assign_plan([record], Path("output"))

        self.assertEqual(issues, [])
        self.assertEqual(
            records[0]["new_name"],
            "1、高铁-26449124086000120595-212元.pdf",
        )


if __name__ == "__main__":
    unittest.main()
