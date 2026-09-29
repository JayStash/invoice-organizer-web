from __future__ import annotations

import unittest

from app.core.common import (
    amount_excluding_tax_from_text,
    assign_plan,
    business_date_from_text,
    civil_aviation_fund_from_text,
    classify,
    document_type_from_text,
    fuel_surcharge_from_text,
    invoice_date_from_text,
    invoice_number_from_text,
    tax_amount_from_text,
    tax_rate_from_text,
    total_amount_from_text,
)
from pathlib import Path


class CoreRegressionTests(unittest.TestCase):
    AVIATION_TICKET_TEXT = """电子发票（航空运输电子客票行程单）
国内国际标识: 国内 开票状态: 正常
发票号码:26000000000000000001
承运人 航班号 座位等级 日期 时间
自:甲机场 某航空 AB1234 V 2026年08月25日 15:05
票价 燃油附加费 增值税税率 增值税税额 民航发展基金 其他税费 合计
至: CNY 330.28 CNY 64.22 9% CNY 35.50 CNY 50.00 CNY 0.00 CNY 480.00
电子客票号码:0000000000000 填开日期:2026年09月29日
"""
    MISORDERED_EINVOICE_TEXT = """电⼦发票（普通发票）
发票号码：
开票日期：
统一发票监
制 26000000000000000001
旅客运输服务 全 章
国家税务总局 2026年09月21日
某省税务局
项目名称 金额 税率/征收率 税额
*交通运输服务*交通费 15.60 9% 1.40
¥15.60 ¥1.40
合 计
出行日期 2026-09-08 交通工具类型 公共交通
价税合计（大写） 壹拾柒圆整 （小写）¥17.00
"""

    def test_rail_ticket_amount_before_label_does_not_use_id_number(self) -> None:
        text = "￥212.00\n票价:\n4503282002****0036"
        self.assertEqual(total_amount_from_text(text, "高铁", None), "212")

    def test_rail_ticket_document_type_uses_rail_context(self) -> None:
        text = "电子发票（统铁一发路票监电子客票）\n买票请到12306\n中国铁路"
        self.assertEqual(document_type_from_text(text), "铁路电子客票")

    def test_rail_refund_uses_explicit_refund_fee(self) -> None:
        text = "中国铁路\n￥17.50\n退票费:\n电子客票号:000000000000000"
        self.assertEqual(total_amount_from_text(text, "高铁", "铁路电子客票"), "17.5")

    def test_aviation_ticket_is_not_classified_as_rail(self) -> None:
        self.assertEqual(
            classify("电子行程单.pdf", self.AVIATION_TICKET_TEXT),
            ("大型交通", "机票", "飞机车船费"),
        )
        self.assertEqual(
            document_type_from_text(self.AVIATION_TICKET_TEXT),
            "航空运输电子客票行程单",
        )
        self.assertEqual(invoice_date_from_text(self.AVIATION_TICKET_TEXT), "2026-09-29")
        self.assertEqual(
            business_date_from_text(self.AVIATION_TICKET_TEXT, "大型交通", "2026-09-29"),
            "2026-08-25",
        )

    def test_aviation_ticket_fields_follow_labeled_columns(self) -> None:
        text = self.AVIATION_TICKET_TEXT
        self.assertEqual(amount_excluding_tax_from_text(text), "330.28")
        self.assertEqual(fuel_surcharge_from_text(text), "64.22")
        self.assertEqual(tax_rate_from_text(text), ("9%", False))
        self.assertEqual(tax_amount_from_text(text), "35.5")
        self.assertEqual(civil_aviation_fund_from_text(text), "50")
        self.assertEqual(
            total_amount_from_text(text, "机票", "航空运输电子客票行程单"),
            "480",
        )

    def test_spaced_legacy_invoice_date_and_small_total(self) -> None:
        text = """广东增值税电子普通发票
发票代码:000000000000 发票号码:00000001
开票日期:2024 年 11 月 04 日 校验码:00000
价税合计(大写) 壹佰肆拾圆整 (小写) ¥140.00
"""
        self.assertEqual(invoice_date_from_text(text), "2024-11-04")
        self.assertEqual(document_type_from_text(text), "电子发票（普通发票）")
        self.assertEqual(total_amount_from_text(text, "其他", None), "140")
        self.assertEqual(
            business_date_from_text(text, "市内交通", "2024-11-04"),
            "2024-11-04",
        )

    def test_small_total_accepts_explicit_nonstandard_currency_mark(self) -> None:
        text = "价税合计(大写) 叁拾叁圆捌角 (小写) ´33.80"
        self.assertEqual(total_amount_from_text(text, "其他", None), "33.8")

    def test_ship_service_is_large_transport(self) -> None:
        text = "*物流辅助服务*客运港口码头服务*甲港-乙港\n出发日期:2024-10-23 18:30"
        self.assertEqual(
            classify("客运凭证.pdf", text),
            ("大型交通", "船票", "飞机车船费"),
        )
        self.assertEqual(
            business_date_from_text(text, "大型交通", "2024-11-04"),
            "2024-10-23",
        )

    def test_metro_evidence_is_local_transport_without_filename_hint(self) -> None:
        text = "*交通运输服务*乘车费\n销售方：某轨道交通运营有限公司\n交通工具类型 公共交通"
        self.assertEqual(
            classify("电子发票.pdf", text),
            ("市内交通", "市内交通", "市内交通费"),
        )

    def test_confirmed_general_goods_invoice_uses_other_expense(self) -> None:
        text = "发票号码:26000000000000000001\n项目名称 *金属制品*螺丝刀套装"
        self.assertEqual(classify("电子发票.pdf", text), ("其他", "其他", "其他"))

    def test_misordered_einvoice_header_fields_are_recovered(self) -> None:
        text = self.MISORDERED_EINVOICE_TEXT
        self.assertEqual(invoice_number_from_text(text), "26000000000000000001")
        self.assertEqual(invoice_date_from_text(text), "2026-09-21")
        self.assertEqual(document_type_from_text(text), "电子发票（普通发票）")

    def test_misordered_einvoice_totals_are_read_without_calculation(self) -> None:
        text = self.MISORDERED_EINVOICE_TEXT
        self.assertEqual(amount_excluding_tax_from_text(text), "15.6")
        self.assertEqual(tax_rate_from_text(text), ("9%", False))
        self.assertEqual(tax_amount_from_text(text), "1.4")
        self.assertEqual(total_amount_from_text(text, "市内交通", None), "17")

    def test_local_transport_uses_requested_expense_type(self) -> None:
        self.assertEqual(classify("滴滴发票A.pdf", "滴滴出行")[2], "市内交通费")
        self.assertEqual(classify("出租车票.pdf", "出租车")[2], "市内交通费")

    def test_amap_ride_invoice_is_local_transport(self) -> None:
        category, purpose, expense_type = classify(
            "【曹操出行-87.96元-1个行程】高德打车电子发票.pdf",
            "旅客运输服务\n*交通运输服务*客运服务费",
        )

        self.assertEqual((category, purpose, expense_type), ("市内交通", "高德发票", "市内交通费"))

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
