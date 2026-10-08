"""Anonymized text fixtures for the v1.0.30 real-sample layouts."""
from pathlib import Path
import unittest
from unittest.mock import patch

from app.core.common import (
    assign_plan, classify, goods_name_from_text, output_records, read_pdf_record,
)


NUMBER = "26000000000000000001"
GOODS_HEADER = "项目名称 规格型号 单位 数量 单价 金额 税率/征收率 税额"
GOODS_ROWS = (
    "*金属制品*某品牌螺丝刀套装十 螺丝刀 套 1 29.91 29.91 13% 3.89",
    "*分析仪器*某品牌封口膜parafilm实验室密封膜 封口膜 盒 1 19.97 19.97 13% 2.60",
)


def invoice_record(text, name="unlabeled.pdf"):
    with patch("app.core.common.extract_pdf_text", return_value=text):
        return read_pdf_record(name, text.encode("utf-8"))


class InvoiceV130Tests(unittest.TestCase):
    def test_both_aviation_rows_preserve_explicit_columns(self):
        for fare, tax, total in [("330.28", "35.50", "480.00"), ("383.49", "40.29", "538.00")]:
            with self.subTest(total=total):
                text = f"""电子发票(航空运输电子客票行程单)
发票号码:{NUMBER}
承运人 航班号 座位等级 日期 时间
自:甲机场 某航空 AB1234 V 2026年08月25日 15:05
票价 燃油附加费 增值税税率 增值税税额 民航发展基金 其他税费 合计
至: CNY {fare} CNY 64.22 9% CNY {tax} CNY 50.00 CNY 0.00 CNY {total}
电子客票号码:0000000000000 填开日期:2026年09月29日
"""
                record = invoice_record(text)
                self.assertEqual(record["invoice_number"], NUMBER)
                self.assertEqual(record["document_type"], "航空运输电子客票行程单")
                self.assertEqual(record["expense_type"], "飞机车船费")
                self.assertEqual(record["invoice_date"], "2026-09-29")
                self.assertEqual(record["business_date"], "2026-08-25")
                self.assertEqual(record["amount_excluding_tax"], fare)
                self.assertEqual(record["tax_amount"], tax.rstrip("0").rstrip("."))
                self.assertEqual(record["tax_rate"], "9%")
                self.assertEqual(record["fuel_surcharge"], "64.22")
                self.assertEqual(record["civil_aviation_development_fund"], "50")
                self.assertEqual(record["total_amount"], total.removesuffix(".00"))

    def test_rail_refund_naming_without_filename_hint_or_inferred_tax(self):
        for amount, normalized in [("33.50", "33.5"), ("17.50", "17.5")]:
            with self.subTest(amount=amount):
                record = invoice_record(f"""电子发票(统铁一发路票监电子客票)
发票号码:{NUMBER} 开票日期:2026年09月29日
2026年09月22日 10:56开
¥{amount}
退票费:
电子客票号:00000 退票 中国铁路 买票请到12306
""")
                self.assertEqual(record["purpose"], "高铁退票")
                self.assertEqual(record["expense_type"], "飞机车船费")
                self.assertEqual(record["total_amount"], normalized)
                self.assertEqual(record["invoice_number"], NUMBER)
                self.assertEqual(record["invoice_date"], "2026-09-29")
                self.assertEqual(record["business_date"], "2026-09-22")
                for field in ("tax_rate", "tax_amount", "amount_excluding_tax"):
                    self.assertIsNone(record[field])
                records, issues = assign_plan([record], Path("output"))
                self.assertFalse(issues)
                self.assertEqual(records[0]["new_name"], f"1、高铁退票-{NUMBER}-{normalized}元.pdf")

    def test_normal_rail_ticket_does_not_become_refund_from_filename(self):
        text = "铁路电子客票 车次G100 票价:¥88.00"
        self.assertEqual(classify("高铁退票.pdf", text), ("大型交通", "高铁", "飞机车船费"))

    def test_displaced_hotel_headers_and_totals(self):
        for amount, rate, tax, total in [("775.47", "6%", "46.53", "822"), ("604.82", "1%", "6.05", "610.87")]:
            with self.subTest(total=total):
                record = invoice_record(f"""电子发票(增值税专用发票)
发票号码:
开票日期:
项目名称 规格型号 单 位 数 量 单 价 金 额 税率/征收率 税 额
下载次数:1
国
统一发票监
制 {NUMBER}
全 章
国家税务总局 2026年09月23日
某省税务局
*生产生活服务*住宿费 天 3 201.60726039604 {amount} {rate} {tax}
合 计 ¥{amount} ¥{tax}
价税合计(大写) 金额文字 (小写) ¥ {total}
""")
                self.assertEqual(record["invoice_number"], NUMBER)
                self.assertEqual(record["document_type"], "电子发票（增值税专用发票）")
                self.assertEqual(record["expense_type"], "住宿费")
                self.assertEqual(record["invoice_date"], "2026-09-23")
                self.assertEqual(record["amount_excluding_tax"], amount)
                self.assertEqual(record["tax_rate"], rate)
                self.assertEqual(record["tax_amount"], tax)
                self.assertEqual(record["total_amount"], total)

    def test_metro_header_after_labels_and_totals_before_sum(self):
        record = invoice_record(f"""电⼦发票(普通发票)
发票号码:
开票日期:
统一发票监
制 {NUMBER}
国家税务总局 2026年09月21日
项目名称 单价 数量 金额 税率/征收率 税额
*交通运输服务*交通费 15.60 9% 1.40
¥15.60 ¥1.40
合 计
出行日期 2026-09-08 交通工具类型 公共交通
价税合计(大写) 壹拾柒圆整 (小写)¥ 17.00
""")
        self.assertEqual(record["invoice_number"], NUMBER)
        self.assertEqual(record["invoice_date"], "2026-09-21")
        self.assertEqual(record["expense_type"], "市内交通费")
        self.assertEqual(record["amount_excluding_tax"], "15.6")
        self.assertEqual(record["tax_rate"], "9%")
        self.assertEqual(record["tax_amount"], "1.4")
        self.assertEqual(record["total_amount"], "17")

    def test_goods_name_comes_from_confirmed_table_columns(self):
        for row, name, subtotal, tax, total in [
            (GOODS_ROWS[0], "螺丝刀套装", "29.91", "3.89", "33.8"),
            (GOODS_ROWS[1], "封口膜", "19.97", "2.6", "22.57"),
        ]:
            with self.subTest(name=name):
                record = invoice_record(f"""电子发票(增值税专用发票)
发票号码:{NUMBER} 开票日期:2026年09月18日
{GOODS_HEADER}
{row}
后续商品描述
合 计 ¥{subtotal} ¥{tax}
价税合计(大写) 金额文字 (小写)  ́{total}
""")
                self.assertEqual(record["purpose"], "其他-" + name)
                self.assertEqual(record["expense_type"], "其他")
                self.assertEqual(record["amount_excluding_tax"], subtotal)
                self.assertEqual(record["tax_amount"], tax)
                self.assertEqual(record["tax_rate"], "13%")
                self.assertEqual(record["total_amount"], total)
                records, issues = assign_plan([record], Path("output"))
                self.assertFalse(issues)
                self.assertEqual(records[0]["new_name"], f"1、其他-{name}-{NUMBER}-{total}元.pdf")

    def test_goods_rule_generalizes_to_other_product_names(self):
        text = GOODS_HEADER + "\n*文具*某品牌文件夹 文件夹 个 1 10.00 10.00 13% 1.30"
        self.assertEqual(goods_name_from_text(text), "文件夹")

    def test_ambiguous_goods_keep_generic_name(self):
        for rows in (
            "\n".join(GOODS_ROWS),
            GOODS_ROWS[0].replace("螺丝刀 套", "通用型 套"),
            GOODS_ROWS[0].replace("螺丝刀 套", "X-123 套"),
            "*金属制品*某品牌工具 1 29.91 13% 3.89",
        ):
            with self.subTest(rows=rows):
                text = f"发票号码:{NUMBER}\n{GOODS_HEADER}\n{rows}"
                self.assertIsNone(goods_name_from_text(text))
                self.assertEqual(classify("其他-随意名称.pdf", text), ("其他", "其他", "其他"))

    def test_ride_pairs_preserve_sequence_letter_order_and_blank_tax(self):
        for brand in ("滴滴", "高德", "曹操"):
            with self.subTest(brand=brand):
                invoice = invoice_record(f"电子发票(普通发票)\n发票号码:{NUMBER}\n开票日期:2026年09月23日\n{brand}出行 总金额:25.00")
                report = invoice_record(f"{brand}行程单\n行程日期:2026年09月23日\n总金额:25.00", "trip.pdf")
                records, issues = assign_plan([report, invoice], Path("output"))
                self.assertFalse(issues)
                self.assertEqual([r["new_name"] for r in output_records(records)],
                                 [f"1、{brand}发票A-{NUMBER}-25元.pdf", f"1、{brand}行程单A.pdf"])
                for field in ("invoice_number", "invoice_date", "tax_rate", "tax_amount", "amount_excluding_tax"):
                    self.assertIsNone(report[field])


if __name__ == "__main__":
    unittest.main()
