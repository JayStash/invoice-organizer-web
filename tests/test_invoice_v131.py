"""Synthetic, privacy-safe regressions for aviation tables with empty cells.

All identifiers, dates, amounts and PDF objects are generated here.  No real
invoice, passenger information or source filename is needed by these tests.
"""
from __future__ import annotations

import io
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from app.core import common


HEADERS = (
    ("票价", "fare"),
    ("燃油附加费", "fuel_surcharge"),
    ("增值税税率", "tax_rate"),
    ("增值税税额", "tax_amount"),
    ("民航发展基金", "civil_aviation_fund"),
    ("其他税费", "other_tax"),
    ("合计", "total_amount"),
)
VALUES = ("321.09", "45.67", "9%", "32.10", "50.00", None, "448.86")
EXPECTED = {
    "fare": "321.09",
    "fuel_surcharge": "45.67",
    "tax_rate": "9%",
    "tax_amount": "32.1",
    "civil_aviation_fund": "50",
    "total_amount": "448.86",
}
NUMBER = "26000000000000000002"
FONT_SIZE = 7.25
COLUMN_STARTS = tuple(40 + index * 120 for index in range(len(HEADERS)))


def word(text: str, x0: float, top: float, *, width: float | None = None) -> dict:
    return {
        "text": text,
        "x0": x0,
        "x1": x0 + (width if width is not None else len(text) * FONT_SIZE),
        "top": top,
        "bottom": top + FONT_SIZE,
        "doctop": top,
        "upright": True,
    }


def table_words(values=VALUES, *, header_top=100, data_top=120) -> list[dict]:
    result = []
    for index, ((label, _), value) in enumerate(zip(HEADERS, values)):
        x0 = COLUMN_STARTS[index]
        result.append(word(label, x0, header_top))
        if value is None:
            continue
        if index == 2:
            result.append(word(value, x0, data_top))
        else:
            result.append(word("CNY", x0, data_top))
            result.append(word(value, x0 + 4 * FONT_SIZE, data_top))
    return result


class FakePage:
    width = 900
    height = 360
    page_number = 1

    def __init__(self, words):
        self.words = words

    def extract_words(self, *args, **kwargs):
        return deepcopy(self.words)


def synthetic_aviation_pdf(values=VALUES) -> bytes:
    """Create selectable Chinese PDF text with explicit column coordinates.

    pypdf is already a runtime dependency.  A minimal ToUnicode CMap avoids an
    extra PDF-generation package and makes extraction independent of host fonts.
    """
    from pypdf import PdfWriter
    from pypdf.generic import (
        ArrayObject, DecodedStreamObject, DictionaryObject, NameObject,
        NumberObject, TextStringObject,
    )

    writer = PdfWriter()
    page = writer.add_blank_page(width=900, height=360)
    placements = [
        ("电子发票(航空运输电子客票行程单)", 40, 25),
        (f"发票号码:{NUMBER}", 40, 45),
        ("乘机日期:2026年01月02日", 40, 65),
        ("填开日期:2026年01月03日", 450, 65),
        ("电子客票号码:0000000000000", 40, 160),
    ]
    for index, ((label, _), value) in enumerate(zip(HEADERS, values)):
        x0 = COLUMN_STARTS[index]
        placements.append((label, x0, 100))
        if value is not None:
            placements.append((value if index == 2 else f"CNY {value}", x0, 120))

    characters = sorted(set("".join(text for text, _, _ in placements)))
    mappings = "\n".join(f"<{ord(char):04X}> <{ord(char):04X}>" for char in characters)
    cmap = DecodedStreamObject()
    cmap.set_data((
        "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /SyntheticInvoice def\n/CMapType 2 def\n"
        "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
        f"{len(characters)} beginbfchar\n{mappings}\nendbfchar\n"
        "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
    ).encode("ascii"))
    descriptor = DictionaryObject({
        NameObject("/Type"): NameObject("/FontDescriptor"),
        NameObject("/FontName"): NameObject("/STSong-Light"),
        NameObject("/Flags"): NumberObject(4),
        NameObject("/FontBBox"): ArrayObject([NumberObject(v) for v in (0, -200, 1000, 900)]),
        NameObject("/Ascent"): NumberObject(800),
        NameObject("/Descent"): NumberObject(-200),
        NameObject("/CapHeight"): NumberObject(700),
        NameObject("/ItalicAngle"): NumberObject(0),
        NameObject("/StemV"): NumberObject(80),
    })
    descendant = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/CIDFontType0"),
        NameObject("/BaseFont"): NameObject("/STSong-Light"),
        NameObject("/CIDSystemInfo"): DictionaryObject({
            NameObject("/Registry"): TextStringObject("Adobe"),
            NameObject("/Ordering"): TextStringObject("Identity"),
            NameObject("/Supplement"): NumberObject(0),
        }),
        NameObject("/DW"): NumberObject(1000),
        NameObject("/FontDescriptor"): writer._add_object(descriptor),
    })
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type0"),
        NameObject("/BaseFont"): NameObject("/STSong-Light"),
        NameObject("/Encoding"): NameObject("/Identity-H"),
        NameObject("/DescendantFonts"): ArrayObject([writer._add_object(descendant)]),
        NameObject("/ToUnicode"): writer._add_object(cmap),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)}),
    })
    content = DecodedStreamObject()
    content.set_data("\n".join(
        f"BT /F1 {FONT_SIZE} Tf 1 0 0 1 {x0} {360 - top} Tm "
        f"<{text.encode('utf-16-be').hex()}> Tj ET"
        for text, x0, top in placements
    ).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(content)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class InvoiceV131Tests(unittest.TestCase):
    def test_five_plain_text_amounts_do_not_guess_the_empty_column(self):
        text = " ".join(label for label, _ in HEADERS) + "\n" + (
            "CNY 321.09 CNY 45.67 9% CNY 32.10 CNY 50.00 CNY 448.86"
        )
        self.assertEqual(common._aviation_ticket_amounts(text), {})
        with patch("app.core.common.extract_pdf_text", return_value=text):
            record = common.read_pdf_record("synthetic.pdf", b"not-a-pdf")
        for field in (
            "amount_excluding_tax", "tax_amount", "fuel_surcharge",
            "civil_aviation_development_fund", "total_amount",
        ):
            self.assertIsNone(record[field], field)

    def test_empty_other_tax_is_recovered_from_explicit_coordinates(self):
        amounts = common._aviation_amounts_from_page(FakePage(table_words()))
        self.assertEqual(amounts, EXPECTED)
        self.assertNotIn("other_tax", amounts)

    def test_each_empty_money_column_preserves_every_other_column(self):
        full_values = list(VALUES)
        full_values[5] = "12.34"
        full_expected = {**EXPECTED, "other_tax": "12.34"}
        for index, (_, field) in enumerate(HEADERS):
            if field == "tax_rate":
                continue
            with self.subTest(empty_column=field):
                values = list(full_values)
                values[index] = None
                expected = {key: value for key, value in full_expected.items() if key != field}
                amounts = common._aviation_amounts_from_page(FakePage(table_words(values)))
                self.assertEqual(amounts, expected)
                self.assertNotIn(field, amounts)

    def test_zero_signed_and_thousands_amounts_keep_the_printed_total(self):
        values = ("-1,234.50", "0.00", "9%", "-110.11", "+50.00", "-2.00", "999.99")
        amounts = common._aviation_amounts_from_page(FakePage(table_words(values)))
        self.assertEqual(amounts, {
            "fare": "-1234.5", "fuel_surcharge": "0", "tax_rate": "9%",
            "tax_amount": "-110.11", "civil_aviation_fund": "50",
            "other_tax": "-2", "total_amount": "999.99",
        })

    def test_short_row_does_not_borrow_amounts_from_insurance_or_footer(self):
        values = ("321.09", None, "9%", None, None, None, "448.86")
        words = table_words(values)
        words += [word("保险费", 40, 145), word("CNY", COLUMN_STARTS[1], 145),
                  word("88.00", COLUMN_STARTS[1] + 4 * FONT_SIZE, 145),
                  word("电子客票号码", 40, 165), word("1234567890123", 180, 165)]
        amounts = common._aviation_amounts_from_page(FakePage(words))
        self.assertEqual(amounts, {"fare": "321.09", "tax_rate": "9%", "total_amount": "448.86"})

    def test_values_after_a_footer_are_not_a_table_row(self):
        words = table_words((None,) * len(HEADERS))
        words.append(word("电子客票号码:0000000000000", 40, 120))
        words += [entry for entry in table_words(data_top=145) if entry["top"] == 145]
        self.assertEqual(common._aviation_amounts_from_page(FakePage(words)), {})

    def test_duplicate_amount_in_one_column_is_ambiguous(self):
        words = table_words()
        words.append(word("99.99", COLUMN_STARTS[3] + 75, 120))
        self.assertEqual(common._aviation_amounts_from_page(FakePage(words)), {})

    def test_currency_far_outside_the_first_or_last_column_is_rejected(self):
        for column, distant_x0 in ((0, -500), (6, 1500)):
            with self.subTest(column=column):
                words = table_words()
                shift = distant_x0 - COLUMN_STARTS[column]
                for entry in words:
                    if entry["top"] == 120 and entry["x0"] in (
                        COLUMN_STARTS[column], COLUMN_STARTS[column] + 4 * FONT_SIZE,
                    ):
                        entry["x0"] += shift
                        entry["x1"] += shift
                self.assertEqual(common._aviation_amounts_from_page(FakePage(words)), {})

    def test_close_currency_and_number_cannot_cross_a_column_boundary(self):
        words = [entry for entry in table_words() if not (
            entry["top"] == 120 and entry["x0"] in (40, 40 + 4 * FONT_SIZE)
        )]
        # The synthetic fare/fuel boundary is x=112.6875. A three-point gap
        # still leaves the currency in fare and the number starting in fuel.
        words += [word("CNY", 89, 120, width=22), word("321.09", 114, 120)]
        self.assertEqual(common._aviation_amounts_from_page(FakePage(words)), {})

    def test_joined_currency_and_amount_use_the_cell_start(self):
        for fare in ("321.09", "123,456,789,012.34"):
            with self.subTest(fare=fare):
                values = (fare, *VALUES[1:])
                words = table_words((None,) * len(HEADERS))
                for index, value in enumerate(values):
                    if value is not None:
                        token = value if index == 2 else f"CNY{value}"
                        words.append(word(token, COLUMN_STARTS[index], 120))
                expected = {**EXPECTED, "fare": fare.replace(",", "")}
                self.assertEqual(common._aviation_amounts_from_page(FakePage(words)), expected)

    def test_multiple_adjacent_data_rows_are_ambiguous(self):
        words = table_words(data_top=111)
        words += [entry for entry in table_words(data_top=120) if entry["top"] == 120]
        self.assertEqual(common._aviation_amounts_from_page(FakePage(words)), {})

    def test_multiple_aviation_tables_on_a_page_are_ambiguous(self):
        words = table_words()
        words += table_words(header_top=190, data_top=210)
        self.assertEqual(common._aviation_amounts_from_page(FakePage(words)), {})

    def test_wrong_header_order_does_not_remap_values(self):
        words = table_words()
        for entry in words:
            if entry["top"] == 100:
                if entry["text"] == "其他税费":
                    entry["text"] = "合计"
                elif entry["text"] == "合计":
                    entry["text"] = "其他税费"
        self.assertEqual(common._aviation_amounts_from_page(FakePage(words)), {})

    def test_coordinate_words_may_arrive_out_of_order(self):
        self.assertEqual(common._aviation_amounts_from_page(FakePage(list(reversed(table_words())))), EXPECTED)

    def test_legacy_six_amount_plain_text_remains_supported(self):
        text = " ".join(label for label, _ in HEADERS) + "\n" + (
            "至: CNY 321.09 CNY 45.67 9% CNY 32.10 CNY 50.00 CNY 0.00 CNY 448.86"
        )
        self.assertEqual(common._aviation_ticket_amounts(text), {**EXPECTED, "other_tax": "0"})

    def test_real_pdf_extraction_recovers_empty_other_tax_and_plans_filename(self):
        data = synthetic_aviation_pdf()
        text = common.extract_pdf_text(data)
        self.assertIn("票价 燃油附加费", text)
        self.assertEqual(common._aviation_ticket_amounts(text), {})
        record = common.read_pdf_record("synthetic-aviation.pdf", data)
        self.assertEqual(record["invoice_number"], NUMBER)
        self.assertEqual(record["document_type"], "航空运输电子客票行程单")
        self.assertEqual(record["expense_type"], "飞机车船费")
        self.assertEqual(record["invoice_date"], "2026-01-03")
        self.assertEqual(record["business_date"], "2026-01-02")
        for record_field, amount_field in (
            ("amount_excluding_tax", "fare"), ("tax_amount", "tax_amount"),
            ("tax_rate", "tax_rate"), ("fuel_surcharge", "fuel_surcharge"),
            ("civil_aviation_development_fund", "civil_aviation_fund"),
            ("total_amount", "total_amount"),
        ):
            self.assertEqual(record[record_field], EXPECTED[amount_field])
        records, issues = common.assign_plan([record], Path("output"))
        self.assertEqual(issues, [])
        self.assertEqual(records[0]["new_name"], f"1、机票-{NUMBER}-448.86元.pdf")

    def test_real_pdf_missing_fuel_does_not_shift_fund_or_total(self):
        values = ("321.09", None, "9%", "32.10", "50.00", "12.34", "448.86")
        record = common.read_pdf_record("synthetic-aviation.pdf", synthetic_aviation_pdf(values))
        self.assertIsNone(record["fuel_surcharge"])
        self.assertEqual(record["amount_excluding_tax"], "321.09")
        self.assertEqual(record["tax_amount"], "32.1")
        self.assertEqual(record["civil_aviation_development_fund"], "50")
        self.assertEqual(record["total_amount"], "448.86")


if __name__ == "__main__":
    unittest.main()
