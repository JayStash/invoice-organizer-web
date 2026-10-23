"""Anonymous recognition/semantic regressions for v1.1.00.

No private invoice text, original identifier, passenger or source path is used.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.core import common
from test_invoice_v132 import FakeTextPage, lined_pdf, vat_text


def record(text, name="anonymous.pdf", **kwargs):
    with patch.object(common, "extract_pdf_text", return_value=text):
        return common.read_pdf_record(name, text.encode(), **kwargs)


def metro_detail():
    return "行程单明细表\n序号 进站时间 出站时间 乘车路径 扣费金额(元)\n1 2026-01-02 10:00 2026-01-02 10:30 甲站-乙站 8.00\n金额合计:8.00元\n"


def car_report():
    return "用车行程单\n开具日期:2026-01-04\n订单号:ABC0000001\n下单日期:2026-01-01\n行程信息\n航班号:AA1234\n上车点:甲机场\n下车点:某酒店\n用车时间:2026-01-03 12:30\n车辆信息\n车牌号码:甲A00000\n订单费用:CNY 67\n优惠:-CNY 50\n实际费用:CNY 17\n"


def bus_report():
    return "某机场巴士-行程单\n申请日期:2026-01-04 行程起止日期:2026-01-02至2026-01-02\n共1笔行程,合计20.00元\n序号 类型 发车时间 出发地 到达地 金额\n1 车票 01-02周五 10:00 甲地 乙地 20.00\n"


class TransportTemplateTests(unittest.TestCase):
    def test_metro_detail_needs_structured_rows_not_a_city_brand(self):
        item = record(metro_detail())
        self.assertEqual(item["file_type"], "ride_report")
        self.assertEqual(item["document_role"], "itinerary")
        self.assertEqual(item["transport_mode"], "transit")
        self.assertEqual(item["business_date"], "2026-01-02")
        self.assertEqual(item["total_amount"], "8")
        self.assertIsNone(item["invoice_number"])

    def test_metro_outing_table_is_supported(self):
        text = "地铁出行_行程单\n申请日期:2026-01-04\n行程记录:1笔,合计7元\n序号 日期 时间 行程站点 金额(元)\n1 2026年01月02日 10:00-10:30 甲站-乙站 7.00\n"
        self.assertTrue(common.is_transit_report(text))
        self.assertEqual(record(text)["business_date"], "2026-01-02")

    def test_empty_metro_table_does_not_claim_a_trip(self):
        self.assertFalse(common.is_transit_report(metro_detail().replace("1 2026-01-02 10:00 2026-01-02 10:30 甲站-乙站 8.00\n", "")))
        self.assertFalse(common.is_transit_report("说明书\n进站时间 出站时间 乘车路径 扣费金额 金额合计\n"))

    def test_metro_invoice_keeps_invoice_priority(self):
        item = record(vat_text(item="地铁客运服务费") + metro_detail())
        self.assertEqual(item["file_type"], "invoice_pdf")
        self.assertEqual(item["invoice_number"], "00000001")

    def test_airport_bus_structure_has_own_mode_and_blank_tax_fields(self):
        item = record(bus_report())
        self.assertEqual(item["file_type"], "ride_report")
        self.assertEqual(item["transport_mode"], "airport_bus")
        self.assertEqual(item["business_date"], "2026-01-02")
        self.assertEqual(item["total_amount"], "20")
        for key in ("invoice_number", "invoice_date", "tax_amount", "tax_rate", "amount_excluding_tax"):
            self.assertIsNone(item[key])

    def test_bus_title_without_trip_structure_is_not_a_report(self):
        self.assertFalse(common.is_ride_report("anonymous.pdf", "机场巴士行程单说明\n合计20元\n"))

    def test_car_structure_overrides_flight_and_hotel_route_keywords(self):
        item = record(car_report())
        self.assertEqual((item["category"], item["purpose"]), ("市内交通", "用车行程单"))
        self.assertEqual(item["transport_mode"], "car")
        self.assertEqual(item["total_amount"], "17")
        self.assertEqual(item["business_date"], "2026-01-03")
        self.assertEqual(item["business_date_source"], "trip_date")
        self.assertEqual(item["match_evidence"]["journey_dates"], ["2026-01-03"])
        self.assertEqual(item["match_evidence"]["order_numbers"], ["ABC0000001"])
        self.assertIsNone(item["ride_brand"])

    def test_car_without_explicit_actual_fee_does_not_infer_net_from_discount(self):
        item = record(car_report().replace("实际费用:CNY 17\n", ""))
        self.assertNotEqual(item["file_type"], "ride_report")
        self.assertIsNone(item["total_amount"])

    def test_confirmed_car_routes_do_not_become_rail_or_airport_bus(self):
        for stop in ("甲地铁站", "乙轨道交通站", "丙机场大巴站", "丁机场巴士站"):
            with self.subTest(stop=stop):
                text = f"滴滴出行-行程单\n行程日期:2026-01-02\n起点:{stop} 终点:某酒店\n合计:17元\n"
                item = record(text)
                self.assertEqual(item["transport_mode"], "car")
                self.assertEqual(item["document_type"], "滴滴-行程单")
                self.assertNotIn("transit_report", item)


class ClassificationAndDateTests(unittest.TestCase):
    def test_passenger_table_routes_exclude_dated_remarks(self):
        text = vat_text(item="客运费", amount="20") + (
            "出行人 有效身份证件号 出行日期 出发地 到达地 等级 交通工具类型\n"
            "匿名旅客 匿名证件 2026-01-02 甲站 乙站 无 汽车\n"
            "备注\n2026-01-02 23:59 甲站->乙站 匿名旅客\n"
        )
        self.assertEqual(record(text)["match_evidence"]["routes"], ["甲站→乙站"])

    def test_passenger_report_uses_printed_structure_not_provider_name(self):
        text = (
            "申请日期:2026.01.03\n共1笔行程,合计25.00元\n"
            "序号 班次时间 人数 线路 上车点 下车点 金额\n"
            "1 2026.01.02 1 甲市-乙县 甲站 乙站 ¥25.00\n"
        )
        item = record(text, "匿名文件.pdf")
        self.assertEqual((item["document_role"], item["transport_mode"]), ("itinerary", "passenger_bus"))
        self.assertEqual((item["category"], item["purpose"]), ("大型交通", "汽车行程单"))
        self.assertEqual(item["business_date"], "2026-01-02")
        self.assertEqual(item["match_evidence"], {"journey_dates": ["2026-01-02"], "routes": ["甲市→乙县"]})
        self.assertIsNone(item["invoice_number"])
        for damaged in (text.replace("班次时间", "申请时间"), text.replace("甲市-乙县", "线路未知")):
            self.assertNotEqual(record(damaged).get("transport_mode"), "passenger_bus")

    def test_passenger_report_prefers_trip_date_when_application_date_is_earlier(self):
        text = (
            "申请日期:2026.01.01\n共1笔行程,合计25.00元\n"
            "序号 班次时间 人数 线路 上车点 下车点 金额\n"
            "1 2026.01.02 1 甲市-乙县 甲站 乙站 ¥25.00\n"
        )
        self.assertEqual(record(text, "匿名文件.pdf")["business_date"], "2026-01-02")

    def test_printed_bus_passenger_row_precedes_aviation_company_name(self):
        text = vat_text(item="客运费", amount="20") + (
            "销售方:某空港航空服务有限公司\n"
            "出行人 有效身份证件号 出行日期 出发地 到达地 等级 交通工具类型\n"
            "匿名旅客 匿名证件 2026-01-02 甲站 乙站 长途汽车\n"
        )
        item = record(text)
        self.assertEqual((item["category"], item["purpose"]), ("大型交通", "汽车票"))
        self.assertEqual(item["transport_mode"], "passenger_bus")
        self.assertEqual(item["business_date"], "2026-01-02")
        self.assertEqual(item["match_evidence"]["journey_dates"], ["2026-01-02"])
        self.assertEqual(item["invoice_date"], "2026-01-03")
        self.assertEqual(item["match_evidence"]["routes"], ["甲站→乙站"])

    def test_generic_bus_vehicle_cell_is_supported_but_taxi_is_separate(self):
        for vehicle in ("汽车", "长途汽车", "客运汽车", "公路客车"):
            with self.subTest(vehicle=vehicle):
                text = vat_text(item="客运费") + (
                    "销售方:某航空服务公司\n"
                    "出行人 有效身份证件号 出行日期 出发地 到达地 等级 交通工具类型\n"
                    f"匿名旅客 匿名证件 2026-01-02 甲站 乙站 无 {vehicle}\n"
                )
                self.assertEqual(record(text).get("transport_mode"), "passenger_bus")
        self.assertNotEqual(record(text.replace("公路客车", "出租车")).get("transport_mode"), "passenger_bus")

    def test_generic_car_passenger_ticket_is_not_promoted_to_airport_bus(self):
        text = vat_text(item="购买车票", amount="20") + (
            "销售方:某航空服务公司\n"
            "出行人 有效身份证件号 出行日期 出发地 到达地 等级 交通工具类型\n"
            "匿名旅客 匿名证件 2026-01-02 甲站 乙站 无 汽车\n"
        )
        item = record(text)
        self.assertEqual((item["category"], item["purpose"]), ("大型交通", "汽车票"))
        self.assertEqual(item["transport_mode"], "passenger_bus")

    def test_bus_context_without_a_dated_bus_row_cannot_set_transport_mode(self):
        for row in ("匿名旅客 匿名证件 2026-01-02 甲站 乙站 飞机",
                    "匿名旅客 匿名证件 日期不明 甲站 乙站 长途汽车"):
            text = vat_text(item="客运费") + (
                "销售方:某空港航空服务有限公司\n"
                "出行人 有效身份证件号 出行日期 出发地 到达地 等级 交通工具类型\n" + row
            )
            self.assertNotEqual(record(text).get("transport_mode"), "airport_bus")

    def test_intercity_bus_table_does_not_infer_an_airport_from_a_filename(self):
        text = vat_text(item="客运费") + (
            "出行人 有效身份证件号 出行日期 出发地 到达地 等级 交通工具类型\n"
            "匿名旅客 匿名证件 2026-01-02 甲市 乙市 长途汽车\n"
        )
        item = record(text, "机场接送.pdf")
        self.assertEqual((item["category"], item["purpose"]), ("大型交通", "汽车票"))

    def test_explicit_insurance_item_precedes_airline_in_filename(self):
        item = record(vat_text(item="保险服务 航意航延组合险"), "机票保险.pdf")
        self.assertEqual((item["category"], item["purpose"]), ("其他", "保险"))
        self.assertEqual(item["declared_purpose"], "机票")
        self.assertEqual(item["classification_source"], "text")

    def test_meal_ticket_and_declared_transport_purpose_remain_separate(self):
        item = record(vat_text(item="餐饮服务 餐饮服务"), "替票-滴滴交通费.pdf")
        self.assertEqual((item["category"], item["purpose"]), ("其他", "餐费"))
        self.assertEqual(item["declared_purpose"], "滴滴发票")
        self.assertEqual(item["total_amount"], "37")
        self.assertFalse(item["ride_document"])
        self.assertIsNone(item["ride_brand"])

    def test_shared_rental_route_hotel_does_not_become_accommodation(self):
        for name in ("共享单车-甲酒店到乙站.pdf", "美团共享-甲酒店到乙站.pdf"):
            with self.subTest(name=name):
                item = record(vat_text(item="经营租赁 租赁服务"), name)
                self.assertEqual((item["category"], item["expense_type"]), ("市内交通", "市内交通费"))
                self.assertEqual(item["classification_source"], "filename")

    def test_explicit_room_booking_item_recovers_hotel_without_filename(self):
        self.assertEqual(record(vat_text(item="经纪代理服务 代订房费"))["category"], "酒店")

    def test_printed_stay_interval_has_context_year_and_preserves_invoice_date(self):
        item = record(vat_text(item="住宿服务 住宿费") + "入离日期:1-1至1-2,共1天\n")
        self.assertEqual(item["business_date"], "2026-01-01")
        self.assertEqual(item["business_date_end"], "2026-01-02")
        self.assertEqual(item["business_date_source"], "stay_date_invoice_year_context")
        self.assertEqual(item["invoice_date"], "2026-01-03")

    def test_explicit_chinese_stay_date_accepts_extra_separator(self):
        item = record(vat_text(item="住宿服务 住宿费") + "入住时间:2025年 -12月 31日 离店时间 2026年 -1月 2日\n")
        self.assertEqual(item["business_date"], "2025-12-31")
        self.assertEqual(item["business_date_end"], "2026-01-02")

    def test_missing_year_cross_year_or_remote_stay_is_not_guessed(self):
        for interval in ("12-31至1-2", "6-1至6-2", "2-30至2-31"):
            with self.subTest(interval=interval):
                item = record(vat_text(item="住宿服务 住宿费") + "入离日期:" + interval)
                self.assertEqual(item["business_date"], item["invoice_date"])
                self.assertEqual(item["business_date_source"], "invoice_date")
        self.assertIsNone(common.business_date_from_text("入离日期:1-1至1-2", "酒店", None))

    def test_explicit_reversed_stay_interval_does_not_override_invoice_date(self):
        item = record(vat_text(item="住宿服务 住宿费") + "入住时间:2026年1月2日 离店时间:2026年1月1日")
        self.assertEqual(item["business_date"], item["invoice_date"])
        self.assertEqual(item["business_date_source"], "invoice_date")

    def test_development_fund_item_does_not_supply_quantity_as_fund_amount(self):
        item = record(vat_text(item="代收民航发展基金 代收 次 1 50 50.00 不征税"), "机票保险.pdf")
        self.assertEqual(item["purpose"], "民航发展基金")
        self.assertIsNone(item["civil_aviation_development_fund"])

    def test_combined_airfare_vat_is_not_renamed_for_one_fund_item(self):
        text = vat_text(item="国内机票款") + (
            "*代收民航发展基金*国内机场建设费 * 次 1 50 50.00 不征税\n"
            "*运输服务*国内燃油附加费 * 次 1 27.52 27.52 9% 2.48\n"
        )
        item = record(text, "机票.pdf")
        self.assertEqual(item["purpose"], "机票")
        self.assertIsNone(item["civil_aviation_development_fund"])
        self.assertIsNone(item["fuel_surcharge"])


class SafeFallbackAndRoleTests(unittest.TestCase):
    def test_geometric_vat_recovery_includes_special_invoice(self):
        default = "电子发票(增值税专用发票)\n发票号码:\n开票日期:\n价税合计(大写) (小写)\n银行账号:26000000000000000022\n"
        geometric = vat_text(number="26000000000000000011").replace("某省增值税电子普通发票", "电子发票(增值税专用发票)")
        with patch("pdfplumber.open") as opened:
            opened.return_value.__enter__.return_value.pages = [FakeTextPage(default, geometric)]
            text = common.extract_pdf_text(b"synthetic")
        self.assertEqual(common.invoice_number_from_text(text), "26000000000000000011")

    def test_geometric_special_invoice_preserves_conflicting_known_amount(self):
        default = "电子发票(增值税专用发票)\n总金额:99\n"
        geometric = vat_text().replace("某省增值税电子普通发票", "电子发票(增值税专用发票)")
        with patch("pdfplumber.open") as opened:
            opened.return_value.__enter__.return_value.pages = [FakeTextPage(default, geometric)]
            self.assertEqual(common.extract_pdf_text(b"synthetic"), default)

    def test_geometric_recovery_keeps_already_read_special_invoice_title(self):
        default = "电子发票(增值税专用发票)\n发票号码:\n开票日期:\n价税合计(大写) (小写)\n"
        geometric = vat_text(number="26000000000000000011").replace("某省增值税电子普通发票\n", "电专 子用 发发 票票\n")
        with patch("pdfplumber.open") as opened:
            opened.return_value.__enter__.return_value.pages = [FakeTextPage(default, geometric)]
            text = common.extract_pdf_text(b"synthetic")
        self.assertEqual(common.document_type_from_text(text), "电子发票（增值税专用发票）")
        self.assertEqual(common.invoice_number_from_text(text), "26000000000000000011")

    def test_geometric_recovery_does_not_replace_a_conflicting_invoice_title(self):
        default = "电子发票(增值税专用发票)\n发票号码:\n开票日期:\n"
        geometric = vat_text()
        with patch("pdfplumber.open") as opened:
            opened.return_value.__enter__.return_value.pages = [FakeTextPage(default, geometric)]
            self.assertEqual(common.extract_pdf_text(b"synthetic"), default)

    def test_freight_receipt_has_own_identifier_role_and_fee(self):
        text = "货物运输电子货票收款凭证\n电子报销凭证序号 ABC00000123\n用车时间:2026-01-02\n费用合计:CNY37.52\n申请日期:2026-01-04\n"
        item = record(text, "滴滴快送凭证.pdf")
        self.assertEqual(item["file_type"], "supporting_receipt")
        self.assertEqual(item["document_role"], "supporting_receipt")
        self.assertEqual(item["receipt_number"], "ABC00000123")
        self.assertEqual(item["total_amount"], "37.52")
        self.assertIsNone(item["invoice_number"])
        self.assertFalse(item["ride_document"])

    def test_waybill_attachment_does_not_reuse_invoice_number_or_sum_rows(self):
        item = record("顺丰电子发票—运单明细\n运单号码 寄件时间 运单金额(元)\n1 ABC000001 2026-01-02 20.00\n")
        self.assertEqual(item["document_role"], "supporting_receipt")
        self.assertIsNone(item["invoice_number"])
        self.assertIsNone(item["total_amount"])

    def test_distinct_invoice_identities_force_review_without_splitting(self):
        item = record(vat_text(number="00000001") + "\n" + vat_text(number="00000002"))
        self.assertTrue(item["multi_invoice_conflict"])
        self.assertTrue(item["recognition_conflicts"])
        self.assertEqual(item["status"], "needs_review")
        self.assertEqual(item["document_role"], "unknown")
        self.assertIsNone(item["invoice_number"])
        self.assertIsNone(item["total_amount"])

    def test_same_invoice_continuation_is_not_a_multi_invoice_conflict(self):
        item = record(vat_text() + "\n" + vat_text())
        self.assertNotIn("multi_invoice_conflict", item)
        self.assertEqual(item["document_role"], "invoice")

    def test_empty_text_is_preserved_unknown_without_filename_financial_guesses(self):
        item = record("", "酒店-00000000000000000001-99元.pdf", source_name="stored.pdf")
        self.assertEqual(item["document_role"], "unknown")
        self.assertEqual(item["source_name"], "stored.pdf")
        for key in ("invoice_number", "total_amount", "invoice_date"):
            self.assertIsNone(item[key])

    def test_real_synthetic_pdf_uses_new_transit_structure(self):
        item = common.read_pdf_record("anonymous.pdf", lined_pdf(metro_detail()))
        self.assertEqual(item["document_role"], "itinerary")
        self.assertEqual(item["total_amount"], "8")


if __name__ == "__main__":
    unittest.main()
