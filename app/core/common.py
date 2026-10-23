"""Shared extraction, planning, and safety helpers for invoice organization."""

from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = SKILL_ROOT / "input"
DEFAULT_OUTPUT_DIR = SKILL_ROOT / "output"
RUNTIME_DIR = SKILL_ROOT / ".runtime"
DEFAULT_PLAN_PATH = RUNTIME_DIR / ".invoice-organization-plan.json"
DEFAULT_PREVIEW_PATH = RUNTIME_DIR / "发票整理预览.md"
WORKBOOK_NAME = "发票整理清单.xlsx"

SCAN_SUFFIXES = {".pdf", ".zip", ".jpg", ".jpeg", ".png", ".ofd"}
CATEGORY_ORDER = {"大型交通": 0, "酒店": 1, "市内交通": 2, "其他": 3}
EXPENSE_TYPES = {"飞机车船费", "住宿费", "市内交通费", "其他", "其他费用"}
MONEY_FIELDS = (
    "amount_excluding_tax",
    "tax_amount",
    "fuel_surcharge",
    "civil_aviation_development_fund",
    "total_amount",
)
EXCEL_HEADERS = (
    "文件名",
    "发票号码",
    "费用类型",
    "票据类型",
    "不含税金额",
    "税率",
    "税额",
    "燃油附加费",
    "民航发展基金",
    "票面总金额",
    "开票日期",
    "备注",
)

NUMBER = r"([+-]?\d[\d,]*(?:\.\d+)?)"

RIDE_BRAND_MARKERS = (
    ("滴滴", "滴滴"),
    ("didi", "滴滴"),
    ("高德", "高德"),
    ("amap", "高德"),
    ("曹操", "曹操"),
    ("风韵", "风韵"),
    ("首汽", "首汽"),
    ("t3出行", "T3出行"),
    ("享道", "享道"),
    ("阳光出行", "阳光出行"),
    ("如祺", "如祺"),
    ("美团打车", "美团打车"),
    ("花小猪", "花小猪"),
    ("神州专车", "神州专车"),
)
RIDE_MARKERS = (
    "滴滴", "didi", "高德", "amap", "曹操", "风韵", "首汽", "t3出行",
    "享道", "阳光出行", "如祺", "美团打车", "花小猪", "神州专车", "出租车",
    "网约车", "打车",
)
RIDE_REPORT_MARKERS = ("行程单", "行程报销单", "行程明细", "itinerary", "trip table", "trip-table")


class InvoiceOrganizerError(RuntimeError):
    """Expected business or input error exposed by the core API."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(path: Path) -> Path:
    return path.expanduser().resolve()


def paths_overlap(first: Path, second: Path) -> bool:
    first = resolve_path(first)
    second = resolve_path(second)
    return first == second or first.is_relative_to(second) or second.is_relative_to(first)


def validate_path_layout(input_dir: Path, output_dir: Path) -> tuple[Path, Path]:
    input_dir = resolve_path(input_dir)
    output_dir = resolve_path(output_dir)
    runtime_dir = resolve_path(RUNTIME_DIR)
    if paths_overlap(input_dir, output_dir):
        raise ValueError("input 与 output 不能相同、互相包含或嵌套。")
    if paths_overlap(input_dir, runtime_dir):
        raise ValueError("input 不能与 Skill 的 .runtime 目录重叠或嵌套。")
    if paths_overlap(output_dir, runtime_dir):
        raise ValueError("output 不能与 Skill 的 .runtime 目录重叠或嵌套。")
    return input_dir, output_dir


def ensure_direct_child(path: Path, directory: Path) -> None:
    path = resolve_path(path)
    directory = resolve_path(directory)
    if path.parent != directory:
        raise ValueError(f"源文件必须直接位于 input 中: {path}")


def parse_amount(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.replace(",", "").replace("￥", "").replace("¥", "").strip()
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", cleaned):
        return None
    try:
        number = Decimal(cleaned)
    except InvalidOperation:
        return None
    normalized = format(number, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized


def decimal_or_none(value: Any) -> Decimal | None:
    normalized = parse_amount(str(value)) if value is not None else None
    return Decimal(normalized) if normalized is not None else None


def normalize_date(year: str, month: str, day: str) -> str:
    return date(int(year), int(month), int(day)).isoformat()


def normalize_extracted_text(text: str) -> str:
    """Normalize compatibility glyphs emitted by some embedded PDF fonts."""
    return unicodedata.normalize("NFKC", text)


def _date_for_label(text: str, labels: tuple[str, ...]) -> str | None:
    joined = "|".join(re.escape(label) for label in labels)
    patterns = (
        rf"(?:{joined})\s*[:：]?\s*(20\d{{2}})\s*[-/.年]\s*-?\s*(\d{{1,2}})\s*[-/.月]\s*(\d{{1,2}})\s*日?",
        rf"(?:{joined})[^\d\n]{{0,20}}(20\d{{2}})(\d{{2}})(\d{{2}})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                return normalize_date(*match.groups())
            except ValueError:
                continue
    return None


def invoice_date_from_text(text: str) -> str | None:
    normalized = normalize_extracted_text(text)
    labeled = _date_for_label(normalized, ("开票日期", "填开日期"))
    if labeled:
        return labeled
    compact = re.sub(r"\s+", "", normalized)
    if "电子发票" not in compact or "统一发票监制" not in compact:
        return None
    match = re.search(
        r"国家税务总局[^\d]{0,40}(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
        normalized,
    )
    if not match:
        return None
    try:
        return normalize_date(*match.groups())
    except ValueError:
        return None


def all_dates_from_text(text: str) -> list[str]:
    values: list[str] = []
    for pattern in (
        r"(?<!\d)(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
        r"(?<!\d)(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)",
    ):
        for match in re.finditer(pattern, text):
            try:
                values.append(normalize_date(*match.groups()))
            except ValueError:
                continue
    return sorted(set(values))


def _stay_dates(text: str, invoice_date: str | None) -> tuple[str | None, str | None, str | None]:
    start = _date_for_label(text, ("入住日期", "入住时间", "住宿日期", "消费日期", "入离日期"))
    end = _date_for_label(text, ("离店日期", "离店时间", "退房日期"))
    if start:
        if end and end < start:
            return None, None, None
        return start, end, "stay_date"
    # A month/day interval is usable only when its year is uniquely anchored
    # near the printed invoice date. Cross-year/long/remote periods stay raw.
    match = re.search(r"入离日期\s*[:：]?\s*(\d{1,2})[-/月](\d{1,2})日?\s*(?:至|到|~|～)\s*(\d{1,2})[-/月](\d{1,2})日?", text)
    if not match or not invoice_date:
        return None, None, None
    invoice = date.fromisoformat(invoice_date)
    month1, day1, month2, day2 = map(int, match.groups())
    if (month2, day2) < (month1, day1):
        return None, None, None
    candidates = []
    for year in (invoice.year - 1, invoice.year, invoice.year + 1):
        try:
            first, last = date(year, month1, day1), date(year, month2, day2)
        except ValueError:
            continue
        if 0 <= (last - first).days <= 31 and -31 <= (invoice - first).days and (invoice - last).days <= 31:
            candidates.append((first.isoformat(), last.isoformat(), "stay_date_invoice_year_context"))
    return candidates[0] if len(candidates) == 1 else (None, None, None)


def _journey_dates(text: str) -> list[str]:
    dates: set[str] = set()
    for label in ("用车时间", "行程起止日期", "行程日期", "行程时间", "出行日期", "出发日期", "乘车日期", "乘机日期", "开车日期", "航班日期"):
        for match in re.finditer(re.escape(label) + r"\s*[:：]?([^\n]{0,120})", text):
            dates.update(all_dates_from_text(match.group(1)))
    # Table rows identify actual journeys; application/order dates do not.
    for line in text.splitlines():
        if re.match(r"\s*\d+\s+20\d{2}(?:[-/.]|\s*年)", line):
            dates.update(all_dates_from_text(line))
    # Passenger VAT invoices have a labeled table whose data rows can start
    # with the passenger rather than a sequence number. Read its dated rows,
    # never the invoice/application date elsewhere in the document.
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if all(label in line for label in ("出行日期", "出发地", "到达地", "交通工具类型")):
            for row in lines[index + 1:index + 8]:
                if re.search(r"(?:^|\s)(?:长途汽车|客运汽车|公路客车|汽车|飞机|火车|动车|轮船|出租车)(?:\s|$)", row):
                    dates.update(all_dates_from_text(row))
    return sorted(dates)


def _business_date_details(text: str, category: str, invoice_date: str | None) -> tuple[str | None, str | None, str]:
    if category == "酒店":
        start, end, source = _stay_dates(text, invoice_date)
        return start or invoice_date, end, source or ("invoice_date" if invoice_date else "unknown")
    if category == "大型交通":
        explicit = _date_for_label(
            text,
            ("出行日期", "出发日期", "乘车日期", "乘机日期", "开车日期", "航班日期"),
        )
        if explicit:
            return explicit, None, "trip_date"
        journey = _journey_dates(text)
        if journey:
            return journey[0], journey[-1] if len(journey) > 1 else None, "trip_date"
        candidates = all_dates_from_text(text)
        non_invoice = [value for value in candidates if value != invoice_date]
        return (non_invoice or candidates or [None])[0], None, "text_date_candidate" if non_invoice else ("invoice_date" if invoice_date else "unknown")
    if category == "市内交通":
        explicit = _date_for_label(
            text, ("用车时间", "行程起止日期", "行程日期", "行程时间", "出行日期", "乘车日期")
        )
        if explicit:
            journey = _journey_dates(text)
            return explicit, (journey[-1] if journey and journey[-1] != explicit else None), "trip_date"
        journey = _journey_dates(text)
        if journey:
            return journey[0], journey[-1] if len(journey) > 1 else None, "trip_date"
        candidates = all_dates_from_text(text)
        non_invoice = [value for value in candidates if value != invoice_date]
        return (non_invoice or candidates or [None])[0], None, "text_date_candidate" if non_invoice else ("invoice_date" if invoice_date else "unknown")
    return invoice_date, None, "invoice_date" if invoice_date else "unknown"


def business_date_from_text(text: str, category: str, invoice_date: str | None) -> str | None:
    return _business_date_details(text, category, invoice_date)[0]


def extract_pdf_text(data: bytes) -> str:
    try:
        import pdfplumber  # type: ignore

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = []
            for page in pdf.pages:
                text = normalize_extracted_text(page.extract_text() or "")
                # Some legacy invoices paint the blank form and its values in
                # separate text layers. Rebuild geometric lines only when the
                # ordinary VAT fields are incomplete, without guessing numbers.
                original_document_type = document_type_from_text(text)
                if original_document_type in {"电子发票（普通发票）", "电子发票（增值税专用发票）"}:
                    fields = _vat_identity_and_total(text)
                    if not all(fields):
                        try:
                            alternative = normalize_extracted_text(page.extract_text_simple() or "")
                        except Exception:
                            alternative = ""
                        other = _vat_identity_and_total(alternative)
                        if (
                            sum(value is not None for value in other)
                            > sum(value is not None for value in fields)
                            and all(value is None or value == candidate
                                    for value, candidate in zip(fields, other))
                            and (not invoice_code_from_text(text)
                                 or invoice_code_from_text(text) == invoice_code_from_text(alternative))
                            and document_type_from_text(alternative) in {None, original_document_type}
                        ):
                            # Geometric line rebuilding can interleave the
                            # title's glyphs while recovering labeled values.
                            # Preserve the already-read printed title only;
                            # never substitute a conflicting candidate title.
                            if document_type_from_text(alternative) is None:
                                alternative = f"{original_document_type}\n{alternative}"
                            text = alternative
                pages.append(text)
            text = "\n".join(pages)
            return normalize_extracted_text(text)
    except Exception:
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(io.BytesIO(data))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            return normalize_extracted_text(text)
        except Exception as exc:
            raise RuntimeError(f"PDF text extraction failed: {exc}") from exc


def _vat_identity_and_total(text: str) -> tuple[str | None, ...]:
    return (
        invoice_number_from_text(text), invoice_date_from_text(text),
        total_amount_from_text(text, "", None),
    )


def invoice_code_from_text(text: str) -> str | None:
    match = re.search(r"发\s*票\s*代\s*码\s*[:：]?\s*(\d{10}|\d{12})(?!\d)",
                      normalize_extracted_text(text))
    return match.group(1) if match else None


def invoice_number_from_text(text: str) -> str | None:
    normalized = normalize_extracted_text(text)
    match = re.search(r"发\s*票\s*号\s*码\s*[:：]?\s*(\d{8,})", normalized)
    if match:
        return match.group(1)
    compact = re.sub(r"\s+", "", normalized)
    if "电子发票" not in compact or "统一发票监制" not in compact:
        return None
    candidates = set(re.findall(r"(?<!\d)(\d{20})(?!\d)", normalized))
    return next(iter(candidates)) if len(candidates) == 1 else None


def ride_brand_from_text(name: str, text: str) -> str | None:
    # A user's filename can name a different booking platform. Prefer the
    # document's own brand; keep platform-before-operator marker precedence.
    for haystack in (text.lower(), name.lower()):
        for marker, brand in RIDE_BRAND_MARKERS:
            if marker in haystack:
                return brand
    return None


def is_ride_document(name: str, text: str) -> bool:
    haystack = f"{name}\n{text}".lower()
    return any(marker in haystack for marker in RIDE_MARKERS)


def is_ride_report(name: str, text: str) -> bool:
    if invoice_number_from_text(text) or "价税合计" in re.sub(r"\s+", "", text):
        return False
    if itinerary_mode_from_text(text) in {"car", "airport_bus", "passenger_bus"}:
        return True
    haystack = f"{name}\n{text}".lower()
    if not any(marker in haystack for marker in RIDE_REPORT_MARKERS):
        return False
    return is_ride_document(name, text)


def is_transit_report(text: str) -> bool:
    compact = re.sub(r"\s+", "", normalize_extracted_text(text))
    if invoice_number_from_text(text) or "价税合计" in compact:
        return False
    row = bool(re.search(r"(?:^|\n)\s*\d+\s+20\d{2}(?:[-/]|\s*年)", text))
    metro_detail = (
        "行程单明细表" in compact
        and any(token in compact for token in ("进站时间", "入站时间"))
        and all(token in compact for token in ("出站时间", "乘车路径", "扣费金额", "金额合计"))
        and row
    )
    metro_journeys = (
        "地铁" in compact and "行程单" in compact
        and all(token in compact for token in ("行程站点", "金额", "合计")) and row
    )
    return (
        metro_detail or metro_journeys or ("行程单" in compact
        and any(token in compact for token in ("地铁", "城际", "轨道交通"))
        and all(token in compact for token in ("入站", "出站", "合计"))
        and row)
    )


def _is_passenger_bus_invoice(text: str) -> bool:
    """Require a printed passenger-service item and an actual bus table row."""
    items = "\n".join(line for line in text.splitlines() if re.match(r"\s*\*[^*]+\*", line))
    if not re.search(r"客运(?:服务)?费|旅客运输|道路客运|公路客运|购买车票", items):
        return False
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if all(label in line for label in ("出行日期", "出发地", "到达地", "交通工具类型")):
            if any(re.search(r"(?:^|\s)(?:长途汽车|客运汽车|公路客车|汽车)(?:\s|$)", row) and all_dates_from_text(row)
                   for row in lines[index + 1:index + 8]):
                return True
    return False


def itinerary_mode_from_text(text: str) -> str | None:
    compact = re.sub(r"\s+", "", normalize_extracted_text(text))
    if invoice_number_from_text(text) or "价税合计" in compact:
        return None
    if is_transit_report(text):
        return "transit"
    # Intercity passenger-service reports (for example, provider-generated
    # reimbursement sheets) have a tabular trip row with a date, passenger
    # count, route and boarding/alighting points.  Treat this printed
    # structure as a passenger-bus itinerary without relying on a provider
    # name or filename hint.
    if (
        all(token in compact for token in ("班次时间", "人数", "线路", "上车点", "下车点", "金额"))
        and re.search(
            r"(?:^|\n)\s*\d+\s+20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}\s+\d+\s+\S+[-—→]\S+\s+\S+\s+\S+\s+[¥￥]\s*[+-]?\d+(?:\.\d+)?",
            text,
        )
    ):
        return "passenger_bus"
    if (
        re.search(r"(?:机场(?:巴士|大巴)|公交).*?行程单", compact[:100])
        and all(token in compact for token in ("发车时间", "出发地", "到达地", "金额", "合计"))
        and _date_for_label(text, ("行程起止日期", "乘车日期", "行程日期"))
        and re.search(r"(?:^|\n)\s*\d+\s+\S+\s+\d{1,2}-\d{1,2}", text)
    ):
        return "airport_bus"
    if (
        "用车行程单" in compact[:100]
        and all(token in compact for token in ("用车时间", "上车点", "下车点", "实际费用", "车辆信息"))
        and _date_for_label(text, ("用车时间",))
        and re.search(r"实际费用\s*[:：]\s*(?:CNY|[¥￥])\s*[+-]?\d+(?:\.\d+)?", text, re.IGNORECASE)
    ):
        return "car"
    return None


def _supporting_receipt_type(text: str) -> str | None:
    compact = re.sub(r"\s+", "", normalize_extracted_text(text))
    if "货物运输电子货票收款凭证" in compact and "电子报销凭证序号" in compact and "费用合计" in compact:
        return "货运收款凭证"
    if "运单明细" in compact and all(token in compact for token in ("运单号码", "运单金额")):
        return "运单明细附件"
    return None


def _match_evidence(text: str) -> dict[str, list[str]]:
    evidence: dict[str, list[str]] = {}
    if journey := _journey_dates(text):
        evidence["journey_dates"] = journey
    cities = sorted(set(re.findall(r"(?:行程城市|乘车城市|城市)\s*[:：]\s*([\u4e00-\u9fff]{2,12})(?=\s|$)", text)))
    if cities:
        evidence["cities"] = cities
    orders = sorted(set(re.findall(r"(?:订单号|订单编号)\s*[:：]\s*([A-Za-z0-9-]{6,})(?![A-Za-z0-9])", text)))
    if orders:
        evidence["order_numbers"] = orders
    operators = sorted(set(re.findall(r"(?:运营方|经营方|服务商)\s*[:：]\s*([^\s:：]{2,50})", text)))
    if operators:
        evidence["operators"] = operators
    routes: set[str] = set()
    lines = text.splitlines()
    passenger_report = all(token in re.sub(r"\s+", "", text)
                           for token in ("班次时间", "人数", "线路", "上车点", "下车点", "金额"))
    if passenger_report:
        for row in lines:
            matched = re.search(
                r"^\s*\d+\s+20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}\s+\d+\s+(\S+[-—→]\S+)\s+",
                row,
            )
            if matched:
                routes.add(re.sub(r"[-—]", "→", matched.group(1)))
    for index, line in enumerate(lines):
        passenger_table = all(label in line for label in ("出行日期", "出发地", "到达地", "交通工具类型"))
        bus_table = all(label in line for label in ("发车时间", "出发地", "到达地"))
        if not passenger_table and not bus_table:
            continue
        pattern = (r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?\s+(\S+)\s+(\S+)(?P<tail>.*)"
                   if passenger_table else
                   r"^\s*\d+\s+\S+\s+\d{1,2}-\d{1,2}(?:周\S)?\s+\d{1,2}:\d{2}(?::\d{2})?\s+(\S+)\s+(\S+)")
        for row in lines[index + 1:index + 8]:
            if matched := re.search(pattern, row):
                # Passenger VAT tables include the vehicle type after the
                # origin/destination columns.  Require that marker before
                # accepting a route so a dated remark such as
                # ``origin->destination passenger`` cannot become a second
                # route candidate.  This keeps relation evidence tied to a
                # real transport row while leaving the existing route parser
                # for airport-bus itinerary tables unchanged.
                if passenger_table and not re.search(
                    r"(?:^|\s)(?:长途汽车|客运汽车|公路客车|汽车|飞机|火车|动车|轮船|出租车)(?:\s|$)",
                    matched.group("tail"),
                ):
                    continue
                routes.add("→".join(matched.group(index) for index in (1, 2)))
    if routes:
        evidence["routes"] = sorted(routes)
    return evidence


def document_type_from_text(text: str, *, report: bool = False) -> str | None:
    if report:
        return f"{ride_brand_from_text('', text) or '网约车'}-行程单"
    compact = re.sub(r"\s+", "", normalize_extracted_text(text))
    if "电子客票" in compact and any(
        token in compact for token in ("中国铁路", "12306", "车次")
    ):
        return "铁路电子客票"
    if "航空运输电子客票行程单" in compact or all(
        token in compact for token in ("承运人", "航班号", "民航发展基金", "电子客票号码")
    ):
        return "航空运输电子客票行程单"
    for title in (
        "电子发票（增值税专用发票）",
        "电子发票(增值税专用发票)",
        "电子发票（普通发票）",
        "电子发票(普通发票)",
        "铁路电子客票",
    ):
        if title in compact:
            return title.replace("(", "（").replace(")", "）")
    if "增值税电子普通发票" in compact:
        return "电子发票（普通发票）"
    if all(token in compact for token in ("发票代码", "发票号码", "校验码", "价税合计")) and (
        "电子支付标识" in compact
        or re.search(r"电.{0,8}子.{0,8}发.{0,8}票", compact[:160])
    ):
        return "电子发票（普通发票）"
    return None


def _aviation_ticket_amounts(text: str) -> dict[str, str]:
    compact = re.sub(r"[ \t]+", " ", text)
    header = re.search(
        r"票价\s+燃油附加费\s+增值税税率\s+增值税税额\s+民航发展基金\s+其他税费\s+合计",
        compact,
    )
    if not header:
        return {}
    # Only the adjacent table row belongs to this header. Later insurance or
    # ticket-detail lines must never supply missing table values.
    lines = [line.strip() for line in compact[header.end() :].splitlines() if line.strip()]
    for line in lines[:1]:
        rate = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*%", line)
        amounts = [
            parse_amount(match)
            for match in re.findall(r"(?:CNY|[¥￥])\s*([+-]?\d[\d,]*(?:\.\d+)?)", line, re.IGNORECASE)
        ]
        if rate and len(amounts) == 6 and all(value is not None for value in amounts):
            return {
                "fare": amounts[0],
                "fuel_surcharge": amounts[1],
                "tax_rate": f"{parse_amount(rate.group(1))}%",
                "tax_amount": amounts[2],
                "civil_aviation_fund": amounts[3],
                "other_tax": amounts[4],
                "total_amount": amounts[5],
            }
    return {}


def _aviation_amounts_from_page(page: Any) -> dict[str, str]:
    """Read explicit aviation cells by their PDF columns, preserving blanks.

    Flattened text loses the position of an empty cell. Locate the standard
    header on this page and use its column boundaries and adjacent data row;
    no fixed page coordinates, inferred zeros or arithmetic are used.
    """
    labels = (
        "票价", "燃油附加费", "增值税税率", "增值税税额",
        "民航发展基金", "其他税费", "合计",
    )
    fields = (
        "fare", "fuel_surcharge", "tax_rate", "tax_amount",
        "civil_aviation_fund", "other_tax", "total_amount",
    )
    rows: list[list[dict[str, Any]]] = []
    for word in sorted(page.extract_words(), key=lambda item: (item["top"], item["x0"])):
        if not rows or abs(word["top"] - rows[-1][0]["top"]) > 2:
            rows.append([])
        rows[-1].append(word)
    headers = []
    for row_index, row in enumerate(rows):
        matches = [[word for word in row if word["text"] == label] for label in labels]
        if all(len(items) == 1 for items in matches):
            header_words = [items[0] for items in matches]
            if all(a["x1"] < b["x0"] for a, b in zip(header_words, header_words[1:])):
                headers.append((row_index, header_words))
    if len(headers) != 1:
        return {}
    row_index, header_words = headers[0]
    bottom = max(word["bottom"] for word in header_words)
    height = max(word["bottom"] - word["top"] for word in header_words)
    data_rows = [
        row for row in rows[row_index + 1 :]
        if bottom <= row[0]["top"] <= bottom + 2 * height
    ]
    if len(data_rows) != 1:
        return {}
    centers = [(word["x0"] + word["x1"]) / 2 for word in header_words]
    boundaries = (
        [header_words[0]["x0"] - (centers[1] - centers[0])]
        + [(left + right) / 2 for left, right in zip(centers, centers[1:])]
        + [header_words[-1]["x1"] + (centers[-1] - centers[-2])]
    )
    words = sorted(data_rows[0], key=lambda item: item["x0"])
    result: dict[str, str] = {}
    index = 0
    while index < len(words):
        word = words[index]
        token = normalize_extracted_text(word["text"])
        anchor = word["x0"]
        if not boundaries[0] <= anchor < boundaries[-1]:
            return {}
        column = sum(anchor >= boundary for boundary in boundaries[1:-1])
        amount = re.fullmatch(r"(?:CNY|[¥￥])\s*([+-]?\d[\d,]*(?:\.\d+)?)?", token, re.IGNORECASE)
        rate = re.fullmatch(r"(\d+(?:\.\d+)?)%", token)
        if amount:
            value = amount.group(1)
            if value is None:
                index += 1
                if index >= len(words):
                    return {}
                if words[index]["x0"] - word["x1"] > 2 * height:
                    return {}
                if not boundaries[column] <= words[index]["x0"] < boundaries[column + 1]:
                    return {}
                value = normalize_extracted_text(words[index]["text"])
            value = parse_amount(value)
        elif rate:
            value = f"{parse_amount(rate.group(1))}%"
        else:
            return {}
        # The currency marker anchors a money cell, even if a long number
        # extends beyond the printed header. Duplicate/misaligned cells fail.
        field = fields[column]
        if value is None or field in result or (field == "tax_rate") != bool(rate):
            return {}
        result[field] = value
        index += 1
    return result


def _aviation_amounts_from_pdf(data: bytes) -> dict[str, str]:
    try:
        import pdfplumber  # type: ignore

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            tables = [amounts for page in pdf.pages if (amounts := _aviation_amounts_from_page(page))]
        return tables[0] if len(tables) == 1 else {}
    except Exception:
        # Preserve the existing text-extraction result if layout is unavailable.
        return {}


def _labeled_amount(text: str, labels: tuple[str, ...], *, max_gap: int = 24) -> str | None:
    joined = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:{joined})[^\d+\-\n]{{0,{max_gap}}}[¥￥]?\s*{NUMBER}",
        text,
        flags=re.IGNORECASE,
    )
    return parse_amount(match.group(1)) if match else None


def standard_vat_totals(text: str) -> tuple[str | None, str | None]:
    normalized = normalize_extracted_text(text)
    patterns = (
        rf"(?:^|\n)\s*合\s*计\s*[¥￥]\s*{NUMBER}\s*[¥￥]\s*{NUMBER}",
        rf"(?:^|\n)\s*[¥￥]\s*{NUMBER}\s*[¥￥]\s*{NUMBER}\s*\r?\n\s*合\s*计(?:\s|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return parse_amount(match.group(1)), parse_amount(match.group(2))
    return None, None


def amount_excluding_tax_from_text(text: str) -> str | None:
    aviation = _aviation_ticket_amounts(text)
    if aviation:
        return aviation["fare"]
    explicit = _labeled_amount(text, ("不含税金额", "合计金额（不含税）", "合计金额(不含税)"))
    if explicit is not None:
        return explicit
    amount, _ = standard_vat_totals(text)
    return amount


def tax_amount_from_text(text: str) -> str | None:
    aviation = _aviation_ticket_amounts(text)
    if aviation:
        return aviation["tax_amount"]
    explicit = _labeled_amount(text, ("合计税额", "税额合计"))
    if explicit is not None:
        return explicit
    _, tax = standard_vat_totals(text)
    return tax


def tax_rate_from_text(text: str) -> tuple[str | None, bool]:
    aviation = _aviation_ticket_amounts(text)
    if aviation:
        return aviation["tax_rate"], False
    if not re.search(r"税\s*率", text):
        return None, False
    rates = {
        f"{parse_amount(match.group(1))}%"
        for match in re.finditer(r"(?<!\d)(\d+(?:\.\d+)?)\s*%", text)
        if parse_amount(match.group(1)) is not None
    }
    if "不征税" in text:
        rates.add("不征税")
    if len(rates) == 1:
        return next(iter(rates)), False
    return None, len(rates) > 1


def total_amount_from_text(text: str, purpose: str, document_type: str | None) -> str | None:
    aviation = _aviation_ticket_amounts(text)
    if aviation:
        return aviation["total_amount"]
    patterns = (
        rf"实际费用\s*[:：]\s*(?:CNY|[¥￥])\s*{NUMBER}",
        rf"费用合计\s*[:：]\s*(?:CNY|[¥￥])\s*{NUMBER}",
        rf"价\s*税\s*合\s*计[^\n]{{0,100}}?[（(]\s*小\s*写\s*[）)][^\d+\-\n]{{0,12}}{NUMBER}",
        rf"价\s*税\s*合\s*计[^\n]{{0,80}}?（?\s*小\s*写\s*）?\s*[:：]?\s*[¥￥]\s*{NUMBER}",
        rf"(?:合计金额|总金额|实付金额|应付金额)\s*[:：]?\s*[¥￥]?\s*{NUMBER}",
        rf"合\s*计\s*[:：]?\s*[¥￥]?\s*{NUMBER}\s*元",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = parse_amount(match.group(1))
            if value is not None:
                return value
    if document_type == "铁路电子客票" or purpose == "高铁":
        for pattern in (
            rf"(?:票[ \t]*价|退[ \t]*票[ \t]*费)[ \t]*[:：]?[ \t]*[¥￥]?[ \t]*{NUMBER}",
            rf"(?:票[ \t]*价|退[ \t]*票[ \t]*费)[ \t]*[:：]?[ \t]*\r?\n[ \t]*[¥￥][ \t]*{NUMBER}",
            rf"[¥￥][ \t]*{NUMBER}[ \t]*(?:元)?[ \t]*(?:\r?\n[ \t]*)?(?:票[ \t]*价|退[ \t]*票[ \t]*费)",
        ):
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                value = parse_amount(match.group(1))
                if value is not None:
                    return value
    return None


def fuel_surcharge_from_text(text: str) -> str | None:
    aviation = _aviation_ticket_amounts(text)
    if aviation:
        return aviation["fuel_surcharge"]
    labeled_text = "\n".join(line for line in text.splitlines() if not re.match(r"\s*\*", line))
    return _labeled_amount(labeled_text, ("燃油附加费", "燃油费"))


def civil_aviation_fund_from_text(text: str) -> str | None:
    aviation = _aviation_ticket_amounts(text)
    if aviation:
        return aviation["civil_aviation_fund"]
    # A VAT goods row may name this fund before quantity/unit-price columns;
    # those columns are not a labeled fund amount and must never supply it.
    labeled_text = "\n".join(line for line in text.splitlines() if not re.match(r"\s*\*", line))
    return _labeled_amount(labeled_text, ("民航发展基金", "民航发展基金费"))


def letter_from_name(name: str) -> str | None:
    match = re.search(r"(?:发票|行程报销单|行程单)\s*([A-Z])", name, flags=re.IGNORECASE)
    return match.group(1).upper() if match else None


def goods_name_from_text(text: str) -> str | None:
    """Use a single goods row's short specification only when its title confirms it.

    Do not guess a product from the filename, brand, tax category or model code.
    Ambiguous/multiple items keep the existing generic '其他' name.
    """
    normalized = normalize_extracted_text(text)
    compact = re.sub(r"\s+", "", normalized)
    if not all(label in compact for label in ("项目名称", "规格型号", "单位", "税率")):
        return None
    rows = [line.strip() for line in normalized.splitlines() if re.match(r"\s*\*[^*]+\*", line)]
    if len(rows) != 1:
        return None
    number = r"[+-]?\d[\d,]*(?:\.\d+)?"
    match = re.fullmatch(
        rf"\*[^*]+\*(?P<title>.+?)\s+(?P<spec>[\u4e00-\u9fff]{{2,16}})"
        rf"\s+\S{{1,4}}\s+{number}\s+{number}\s+{number}\s+\d+(?:\.\d+)?%\s+{number}",
        rows[0],
    )
    if not match:
        return None
    title = re.sub(r"\s+", "", match.group("title"))
    spec = match.group("spec")
    if spec not in title:
        return None
    return spec + "套装" if spec + "套装" in title else spec


def classify(name: str, text: str) -> tuple[str, str, str | None]:
    haystack = f"{name}\n{text}".lower()
    compact = re.sub(r"\s+", "", normalize_extracted_text(text))
    title = document_type_from_text(text)
    if _supporting_receipt_type(text):
        return "其他", "货运收款凭证" if "收款凭证" in compact else "运单明细附件", "其他费用"
    if is_transit_report(text):
        return "市内交通", "轨道交通行程单", "市内交通费"
    mode = itinerary_mode_from_text(text)
    if mode == "airport_bus":
        return "市内交通", "机场巴士行程单", "市内交通费"
    if mode == "passenger_bus":
        return "大型交通", "汽车行程单", "飞机车船费"
    if mode == "car":
        return "市内交通", "用车行程单", "市内交通费"
    if title == "航空运输电子客票行程单":
        return "大型交通", "机票", "飞机车船费"
    if title == "铁路电子客票":
        return "大型交通", "高铁退票" if re.search(r"退\s*票\s*费", text) else "高铁", "飞机车船费"
    item_text = "\n".join(line.strip() for line in text.splitlines() if re.match(r"\s*\*[^*]+\*", line))
    if any(token in item_text for token in ("保险服务", "人身保险", "航意险", "航延险")):
        return "其他", "保险", "其他费用"
    if any(token in item_text for token in ("餐饮", "餐费", "食品")):
        return "其他", "餐费", "其他费用"
    if any(token in item_text for token in ("住宿服务", "住宿费", "代订房费", "代订住宿")):
        return "酒店", "酒店", "住宿费"
    if _is_passenger_bus_invoice(text):
        if re.search(r"机场巴士|机场大巴|空港巴士", text):
            return "市内交通", "机场巴士发票", "市内交通费"
        return "大型交通", "汽车票", "飞机车船费"
    # A destination such as a hotel is weaker than a shared-bike service hint
    # supported by the printed rental item; it does not describe accommodation.
    if any(token in haystack for token in ("共享单车", "骑行", "单车", "美团共享", "哈啰共享", "青桔")) and any(token in item_text for token in ("经营租赁", "租赁服务", "骑行")):
        return "市内交通", "市内交通", "市内交通费"
    if "代收民航发展基金" in item_text and len(item_text.splitlines()) == 1:
        return "大型交通", "民航发展基金", "飞机车船费"
    ride_brand = ride_brand_from_text(name, text)
    if is_ride_report(name, text):
        return "市内交通", f"{ride_brand or '网约车'}行程单", "市内交通费"
    if is_ride_document(name, text):
        return "市内交通", f"{ride_brand or '网约车'}发票", "市内交通费"
    if any(token in haystack for token in ("机票", "航班", "航空", "代订机票", "经济舱")):
        return "大型交通", "机票", "飞机车船费"
    # Urban/suburban railway operators also contain the generic word 铁路.
    # An explicit urban mode takes precedence over that broad keyword, while
    # actual railway e-tickets retain their established large-transport rule.
    if "市域铁路" in haystack and document_type_from_text(text) != "铁路电子客票":
        return "市内交通", "市内交通", "市内交通费"
    if any(token in haystack for token in ("高铁", "动车", "电子客票", "铁路", "车次", "12306")):
        # The fee label on the ticket, not a filename hint, identifies a refund.
        purpose = "高铁退票" if re.search(r"退\s*票\s*费", text) else "高铁"
        return "大型交通", purpose, "飞机车船费"
    if any(token in haystack for token in ("船票", "客运港口", "水路客运", "轮渡", "客船")):
        return "大型交通", "船票", "飞机车船费"
    if any(token in haystack for token in ("住宿费", "酒店", "民宿", "住宿服务", "代订房费")):
        return "酒店", "酒店", "住宿费"
    if any(
        token in haystack
        for token in (
            "出租车", "网约车", "打车", "amap itinerary", "机场大巴", "地铁", "高速",
            "共享单车", "轨道交通", "公共交通", "乘车费",
        )
    ):
        return "市内交通", "市内交通", "市内交通费"
    if any(token in haystack for token in ("保险", "人身保险", "保单")):
        return "其他", "保险", "其他费用"
    if any(token in haystack for token in ("餐费", "餐饮", "食品")):
        return "其他", "餐费", "其他费用"
    if invoice_number_from_text(text) and any(
        token in haystack for token in ("项目名称", "货物或应税劳务", "服务名称")
    ):
        goods_name = goods_name_from_text(text)
        return "其他", f"其他-{goods_name}" if goods_name else "其他", "其他"
    return "其他", "其他", None


def is_didi_report(name: str, text: str) -> bool:
    """Backward-compatible alias for callers that used the old Didi helper."""
    return is_ride_report(name, text)


def is_invoice_text(text: str, document_type: str | None) -> bool:
    return bool(invoice_number_from_text(text)) or document_type in {
        "电子发票（增值税专用发票）",
        "电子发票（普通发票）",
        "铁路电子客票",
        "航空运输电子客票行程单",
    }


def read_pdf_record(path_name: str, data: bytes, *, archive_source: str | None = None,
                    source_name: str | None = None) -> dict[str, Any]:
    text = extract_pdf_text(data)
    category, purpose, expense_type = classify(path_name, text)
    supporting_type = _supporting_receipt_type(text)
    mode = itinerary_mode_from_text(text)
    transit_report = is_transit_report(text)
    report = transit_report or is_ride_report(path_name, text)
    ride_document = not supporting_type and category == "市内交通" and not transit_report and is_ride_document(path_name, text)
    ride_brand = ride_brand_from_text(path_name, text) if ride_document or (report and mode != "airport_bus" and not transit_report) else None
    if supporting_type:
        document_type = "货物运输电子货票收款凭证" if supporting_type == "货运收款凭证" else "运单明细"
    elif mode in {"transit", "airport_bus", "passenger_bus", "car"}:
        document_type = {"transit": "轨道交通行程单", "airport_bus": "机场巴士行程单",
                         "passenger_bus": "汽车行程单", "car": "用车行程单"}[mode]
    else:
        document_type = "轨道交通行程单" if transit_report else document_type_from_text(text, report=report)
    invoice_date = invoice_date_from_text(text)
    tax_rate, multiple_rates = tax_rate_from_text(text)
    aviation = {}
    if document_type == "航空运输电子客票行程单" and not _aviation_ticket_amounts(text):
        aviation = _aviation_amounts_from_pdf(data)
    business_date, business_end, business_source = _business_date_details(text, "市内交通" if supporting_type == "货运收款凭证" else category, invoice_date)
    remarks: list[str] = []
    if multiple_rates:
        remarks.append("存在多个税率")
    if archive_source:
        remarks.append("ZIP 内提取")
    if report:
        remarks.append("配套行程单")
    if supporting_type:
        file_type = "supporting_receipt"
    elif report:
        file_type = "ride_report"
    elif is_invoice_text(text, document_type):
        file_type = "archive_pdf" if archive_source else "invoice_pdf"
    else:
        file_type = "other"
    record = {
        "original_name": path_name,
        "file_type": file_type,
        "category": category,
        "purpose": purpose,
        "business_date": business_date,
        "business_date_end": business_end,
        "business_date_source": business_source,
        "invoice_date": invoice_date,
        "invoice_number": invoice_number_from_text(text),
        "expense_type": expense_type,
        "document_type": document_type,
        "amount_excluding_tax": aviation.get("fare", amount_excluding_tax_from_text(text)),
        "tax_rate": tax_rate,
        "tax_amount": aviation.get("tax_amount", tax_amount_from_text(text)),
        "fuel_surcharge": aviation.get("fuel_surcharge", fuel_surcharge_from_text(text)),
        "civil_aviation_development_fund": aviation.get("civil_aviation_fund", civil_aviation_fund_from_text(text)),
        "total_amount": aviation.get("total_amount", total_amount_from_text(text, purpose, document_type)),
        "remark": "；".join(remarks) if remarks else None,
        "letter": letter_from_name(path_name),
        "ride_brand": ride_brand,
        "ride_document": ride_document,
        "archive_source": archive_source,
        "source_sha256": sha256_bytes(data),
        "document_role": "supporting_receipt" if supporting_type else ("itinerary" if report else ("invoice" if file_type in {"invoice_pdf", "archive_pdf"} else "unknown")),
        "classification_source": "text" if classify("anonymous.pdf", text) == (category, purpose, expense_type) and expense_type else ("filename" if expense_type else "unknown"),
        "match_evidence": _match_evidence(text),
    }
    if source_name is not None:
        record["source_name"] = source_name
    declared = classify(path_name, "")
    if declared[2]:
        record["declared_purpose"] = declared[1]
        record["declared_purpose_source"] = "filename"
        if expense_type and declared[0] != category:
            record["classification_note"] = "票面服务类型与原文件名用途不同，已分别保留"
    if supporting_type:
        match = re.search(r"电子报销凭证序号\s*[:：]?\s*([A-Za-z0-9-]{6,})(?![A-Za-z0-9])", text)
        record["receipt_number"] = match.group(1) if match else None
        record["purpose"] = supporting_type
        record["invoice_number"] = None
        record["ride_brand"] = None
        record["ride_document"] = False
    if report or supporting_type:
        for key in ("invoice_number", "amount_excluding_tax", "tax_rate", "tax_amount", "fuel_surcharge", "civil_aviation_development_fund", "invoice_date"):
            record[key] = None
    if mode:
        record["transport_mode"] = mode
    elif _is_passenger_bus_invoice(text):
        # This existing bus family also covers ground passenger services.
        # A company's 航空 name cannot turn a printed bus journey into a flight.
        record["transport_mode"] = "airport_bus" if record.get("category") == "市内交通" else "passenger_bus"
    elif category == "市内交通" and not supporting_type:
        compact = re.sub(r"\s+", "", text)
        # A confirmed car document may name subway/bus stops in its route.
        # These destinations must not change the service into rail or bus.
        if ride_document:
            record["transport_mode"] = "car"
        elif any(value in compact for value in ("地铁", "轨道交通", "市域铁路")):
            record["transport_mode"] = "transit"
        elif any(value in compact for value in ("机场巴士", "机场大巴")):
            record["transport_mode"] = "airport_bus"
    if code := invoice_code_from_text(text):
        record["invoice_code"] = code
    if ride_brand:
        record["ride_brand_source"] = "text" if ride_brand_from_text("", text) else "filename"
        if report and "服务商" in text:
            providers = sorted({brand for marker, brand in RIDE_BRAND_MARKERS
                                if marker in text.lower() and brand != ride_brand})
            if providers:
                record["ride_service_brands"] = providers
    if transit_report:
        record["transit_report"] = True
    elif not ride_document and any(token in text for token in ("铁路", "城轨", "地铁", "轨道交通")):
        record["transit_invoice"] = True
    identities = set(re.findall(r"发\s*票\s*号\s*码\s*[:：]?\s*(\d{8,})(?!\d)", normalize_extracted_text(text)))
    codes = set(re.findall(r"发\s*票\s*代\s*码\s*[:：]?\s*(\d{10}|\d{12})(?!\d)", normalize_extracted_text(text)))
    if len(identities) > 1 or (identities and len(codes) > 1):
        record["multi_invoice_conflict"] = True
        record["recognition_conflicts"] = ["同一 PDF 包含多套独立发票身份"]
        record["file_type"] = "other"
        record["document_role"] = "unknown"
        record["status"] = "needs_review"
        record["issue"] = "同一 PDF 包含多套独立发票身份，需人工确认"
        record["ride_document"] = False
        for key in ("invoice_number", "invoice_code", "total_amount", "amount_excluding_tax", "tax_rate", "tax_amount", "fuel_surcharge", "civil_aviation_development_fund"):
            if key == "invoice_code":
                record.pop(key, None)
            else:
                record[key] = None
    return record


def input_snapshot(input_dir: Path) -> list[dict[str, Any]]:
    return [
        {"name": path.name, "size": path.stat().st_size, "sha256": sha256_file(path)}
        for path in sorted(input_dir.iterdir(), key=lambda item: item.name.casefold())
        if path.is_file()
    ]


def scan_input(
    input_dir: Path,
    *,
    source_metadata: dict[str, dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    ignored: list[str] = []
    for path in sorted(input_dir.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file():
            ignored.append(path.name)
            continue
        suffix = path.suffix.lower()
        if suffix not in SCAN_SUFFIXES:
            ignored.append(path.name)
            continue
        metadata = (source_metadata or {}).get(path.name, {})
        original_name = metadata.get("original_name") or path.name
        source_id = metadata.get("source_id") or hashlib.sha256(path.name.encode("utf-8")).hexdigest()[:24]
        identity = {
            "original_name": original_name,
            "source_name": path.name,
            "source_id": source_id,
            "document_id": source_id,
        }
        if suffix == ".zip":
            archive_hash = sha256_file(path)
            archive_record: dict[str, Any] = {
                **identity,
                "source_path": str(path),
                "source_sha256": archive_hash,
                "file_type": "archive",
                "archive_source": None,
                "status": "source_only",
                "issue": None,
            }
            records.append(archive_record)
            pdf_count = 0
            try:
                with zipfile.ZipFile(path) as archive:
                    for member_index, info in enumerate(archive.infolist()):
                        if info.is_dir():
                            continue
                        # ZipInfo identifies this exact entry even when a ZIP
                        # contains repeated member names with different bytes.
                        data = archive.read(info)
                        if info.filename.lower().endswith(".pdf"):
                            pdf_count += 1
                            try:
                                member = read_pdf_record(
                                    Path(info.filename).name,
                                    data,
                                    archive_source=path.name,
                                )
                            except Exception as exc:
                                member = {
                                    "original_name": Path(info.filename).name,
                                    "archive_source": path.name,
                                    "source_sha256": sha256_bytes(data),
                                    "file_type": "other",
                                    "status": "needs_review",
                                    "issue": f"PDF 无法识别: {exc}",
                                }
                            member.update(
                                {
                                    "archive_member": info.filename,
                                    "archive_member_index": member_index,
                                    "archive_sha256": archive_hash,
                                    "member_sha256": sha256_bytes(data),
                                    "source_path": str(path),
                                    "source_id": source_id,
                                    "document_id": f"{source_id}:{member_index}",
                                    "archive_original_name": original_name,
                                }
                            )
                            records.append(member)
                        else:
                            records.append(
                                {
                                    "original_name": f"{original_name}::{info.filename}",
                                    "source_id": source_id,
                                    "document_id": f"{source_id}:{member_index}",
                                    "archive_original_name": original_name,
                                    "file_type": "archive_member",
                                    "archive_source": path.name,
                                    "archive_member": info.filename,
                                    "archive_member_index": member_index,
                                    "archive_sha256": archive_hash,
                                    "member_sha256": sha256_bytes(data),
                                    "source_path": str(path),
                                    "status": "ignored",
                                    "issue": "ZIP 中非 PDF 成员，不进入 output",
                                }
                            )
                if pdf_count == 0:
                    archive_record["status"] = "needs_review"
                    archive_record["issue"] = "ZIP 中没有 PDF 发票"
            except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
                archive_record["status"] = "needs_review"
                archive_record["issue"] = f"ZIP 无法读取: {exc}"
        elif suffix == ".pdf":
            try:
                record = read_pdf_record(original_name, path.read_bytes())
                record.update(identity)
                record["source_sha256"] = sha256_file(path)
                record["source_path"] = str(path)
                records.append(record)
            except Exception as exc:
                records.append(
                    {
                        **identity,
                        "source_path": str(path),
                        "source_sha256": sha256_file(path),
                        "file_type": "other",
                        "status": "needs_review",
                        "issue": f"PDF 无法识别: {exc}",
                    }
                )
        else:
            records.append(
                {
                    **identity,
                    "source_path": str(path),
                    "source_sha256": sha256_file(path),
                    "file_type": "other",
                    "status": "needs_review",
                    "issue": "当前版本不能可靠提取此文件类型",
                }
            )
    return records, ignored


def _critical_issue(record: dict[str, Any]) -> str | None:
    if record.get("recognition_conflicts") or record.get("multi_invoice_conflict"):
        return record.get("issue") or "票据身份或关键字段存在冲突，需人工确认"
    if record.get("file_type") == "supporting_receipt":
        missing = [label for label, key in (("凭证号码", "receipt_number"), ("明确总金额", "total_amount"))
                   if record.get(key) in (None, "")]
        return "辅助凭证缺少: " + "、".join(missing) if missing else record.get("issue")
    if record.get("file_type") == "ride_report" and record.get("total_amount") in (None, ""):
        return record.get("issue") or "行程单缺少明确总金额"
    if record.get("file_type") not in {"invoice_pdf", "archive_pdf"}:
        if record.get("file_type") == "other":
            return record.get("issue") or "未能确认该 PDF 为可整理票据"
        return record.get("issue")
    missing = [
        label
        for label, key in (
            ("业务日期", "business_date"),
            ("发票号码", "invoice_number"),
            ("票面总金额", "total_amount"),
        )
        if record.get(key) in (None, "")
    ]
    return "缺少关键字段: " + "、".join(missing) if missing else record.get("issue")


def output_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [
            record
            for record in records
            if record.get("new_name")
            and record.get("status") != "needs_review"
        ],
        key=lambda record: (
            record.get("sequence", 10**9),
            1 if record.get("file_type") == "ride_report" else 0,
            record.get("new_name", "").casefold(),
        ),
    )


def _letter_for_index(index: int) -> str:
    letters = ""
    value = index
    while True:
        letters = chr(ord("A") + value % 26) + letters
        value = value // 26 - 1
        if value < 0:
            return letters


def _ride_report_match(
    report: dict[str, Any], invoices: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, str]:
    mode = _transport_mode(report)
    if mode == "passenger_bus":
        return _select_report_candidate(
            report,
            [invoice for invoice in invoices if _transport_mode(invoice) == "passenger_bus"],
            context="客运业务结构与金额", strict_unique=False,
        )
    if mode == "airport_bus":
        return _select_report_candidate(
            report, [invoice for invoice in invoices if _transport_mode(invoice) in {"airport_bus", "passenger_bus"}],
            context="机场巴士业务结构", strict_unique=False,
        )
    report_brand = report.get("ride_brand")
    candidates = [
        invoice
        for invoice in invoices
        if _transport_mode(invoice) == "car"
        and (not report_brand or invoice.get("ride_brand") == report_brand)
        and not (report.get("total_amount") and invoice.get("total_amount")
                 and report["total_amount"] != invoice["total_amount"])
    ]
    if candidates:
        return _select_report_candidate(report, candidates, context="平台与金额", strict_unique=False)
    if not candidates and report.get("total_amount") and report.get("ride_service_brands"):
        # Aggregators print their platform in the title and the actual invoice
        # operator in the trip table. Both must come from the document itself.
        candidates = [
            invoice for invoice in invoices
            if _transport_mode(invoice) == "car"
            and invoice.get("ride_brand_source") == "text"
            and invoice.get("ride_brand") in report["ride_service_brands"]
            and invoice.get("total_amount") == report["total_amount"]
        ]
        if candidates:
            return _select_report_candidate(report, candidates, context="正文服务商与金额", strict_unique=True)
        # Show weaker candidates for review, but a filename cannot establish
        # that an invoice belongs to the operator printed on this report.
        weaker = [invoice for invoice in invoices
                  if _transport_mode(invoice) == "car"
                  and invoice.get("ride_brand_source") == "filename"
                  and invoice.get("total_amount") == report["total_amount"]]
        if weaker:
            return _record_match_result(report, None, "conflict", weaker,
                                        "正文服务商缺少对应票据，文件名候选不足以证明同一行程")
    if not candidates and report.get("total_amount") and report.get("ride_brand_source") == "text":
        # Filename-only platform hints are weaker than a report's printed
        # platform. An exact, unique amount can still associate such invoices.
        candidates = [
            invoice for invoice in invoices
            if _transport_mode(invoice) == "car"
            and invoice.get("ride_brand_source") == "filename"
            and invoice.get("total_amount") == report["total_amount"]
        ]
        if candidates:
            return _select_report_candidate(report, candidates, context="正文平台与弱文件名候选", strict_unique=True)
    if not candidates:
        same_amount = [invoice for invoice in invoices if _transport_mode(invoice) == "car"
                       and report.get("total_amount") == invoice.get("total_amount")]
        if same_amount:
            return _record_match_result(report, None, "conflict", same_amount,
                                        "同额票据的平台或经营方证据不相符")
        return _record_match_result(report, None, "none", [], "未找到相同业务类型和金额的电子票")
    return _select_report_candidate(report, candidates, context="用车业务结构与金额", strict_unique=False)


def _transit_report_match(
    report: dict[str, Any], invoices: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, str]:
    candidates = [
        invoice for invoice in invoices
        if _transport_mode(invoice) == "transit"
        and invoice.get("category") in {"大型交通", "市内交通"}
        and invoice.get("purpose") in {"高铁", "市内交通"}
        and report.get("total_amount")
        and invoice.get("total_amount") == report["total_amount"]
    ]
    return _select_report_candidate(report, candidates, context="轨道业务结构与金额", strict_unique=False)


def _transport_mode(record: dict[str, Any]) -> str | None:
    explicit = record.get("transport_mode") or record.get("itinerary_mode")
    if explicit in {"car", "transit", "airport_bus", "passenger_bus"}:
        return explicit
    if record.get("transit_report") or record.get("transit_invoice"):
        return "transit"
    if record.get("ride_document") or record.get("ride_brand"):
        return "car"
    return None


def _match_document_id(record: dict[str, Any]) -> str:
    return str(record.get("document_id") or record.get("source_id")
               or record.get("member_sha256") or record.get("source_sha256")
               or f"invoice:{record.get('invoice_code') or ''}:{record.get('invoice_number') or ''}")


def _record_match_result(
    report: dict[str, Any], invoice: dict[str, Any] | None, status: str,
    candidates: list[dict[str, Any]], reason: str, evidence: list[str] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    report["match_status"] = status
    report["match_candidates"] = [_match_document_id(item) for item in candidates]
    report["match_reason"] = reason
    report["matched_evidence"] = evidence or []
    return invoice, reason


def _compare_trip_evidence(
    report: dict[str, Any], invoice: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Compare only explicit journey evidence; an issue date is not a trip."""
    first, second = report.get("match_evidence") or {}, invoice.get("match_evidence") or {}
    shared, conflicts = [], []
    for key in ("journey_dates", "cities", "order_numbers", "operators", "routes"):
        left, right = set(first.get(key) or []), set(second.get(key) or [])
        if not left or not right:
            continue
        if key == "cities":
            left = {re.sub(r"市$", "", value.strip()) for value in left}
            right = {re.sub(r"市$", "", value.strip()) for value in right}
        if left & right:
            shared.append(key)
        elif key == "journey_dates":
            # Multi-trip reports may state a period rather than each date.
            if max(left) < min(right) or max(right) < min(left):
                conflicts.append(key)
        elif key != "operators":
            conflicts.append(key)
        # Legal operator names can contain branch/company aliases. A shared
        # exact name strengthens a relation; different spellings alone do not
        # override printed platform/provider and journey evidence.
    return shared, conflicts


def _select_report_candidate(
    report: dict[str, Any], candidates: list[dict[str, Any]], *, context: str,
    strict_unique: bool,
) -> tuple[dict[str, Any] | None, str]:
    amount = report.get("total_amount")
    candidates = [item for item in candidates if amount not in (None, "") and item.get("total_amount") == amount]
    if not candidates:
        return _record_match_result(report, None, "none", [], "未找到相同业务类型和金额的电子票")
    compatible = []
    conflicting = []
    for invoice in candidates:
        shared, conflicts = _compare_trip_evidence(report, invoice)
        if conflicts:
            conflicting.append((invoice, conflicts))
        else:
            compatible.append((invoice, shared))
    if not compatible:
        fields = sorted({field for _, fields in conflicting for field in fields})
        return _record_match_result(report, None, "conflict", candidates,
                                    "同额候选存在正文行程证据冲突: " + "、".join(fields))
    if strict_unique and len(candidates) != 1:
        return _record_match_result(report, None, "multiple", candidates,
                                    context + "无法唯一对应，需人工确认")
    if len(compatible) == 1:
        invoice, shared = compatible[0]
        return _record_match_result(report, invoice, "matched", candidates,
                                    context + "唯一且无正文冲突", [context, *shared])
    # Several equal-fare tickets require affirmative journey evidence. The
    # invoice date and filename letters cannot break this tie.
    proven = [(invoice, shared) for invoice, shared in compatible if shared]
    if len(proven) == 1:
        invoice, shared = proven[0]
        return _record_match_result(report, invoice, "matched", candidates,
                                    "正文行程证据唯一对应", shared)
    return _record_match_result(report, None, "multiple", candidates,
                                "多个同额候选缺少足以唯一关联的正文行程证据")


def assign_plan(records: list[dict[str, Any]], output_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    issues: list[str] = []
    for record in records:
        for key in ("new_name", "output_path", "output_sha256", "sequence", "ride_relation", "ride_letter",
                    "match_status", "match_candidates", "match_reason", "matched_evidence",
                    "expense_id", "expense_amount", "expense_basis"):
            record.pop(key, None)
        if record.pop("standalone_paper_invoice", False):
            record["remark"] = "；".join(part for part in (record.get("remark") or "").split("；")
                                       if part != "（对应纸质发票）") or None
        if str(record.get("issue") or "").startswith(("发票号码重复:", "目标名称重复:", "行程单无法唯一匹配发票:")):
            record.pop("issue", None)
            record.pop("status", None)
        record["counts_toward_total"] = False
        record.setdefault("document_role", {"invoice_pdf": "invoice", "archive_pdf": "invoice",
                                             "ride_report": "itinerary", "supporting_receipt": "supporting_receipt"}.get(
                                                 record.get("file_type"), "unknown"))
        issue = _critical_issue(record)
        if issue and record.get("file_type") not in {"archive", "archive_member"}:
            record["status"] = "needs_review"
            record["issue"] = issue

    # A reviewable electronic ticket still exists. Keep it as evidence against
    # a paper-only annotation, while allowing only valid tickets to be paired.
    recognized_invoices = [
        record
        for record in records
        if record.get("file_type") in {"invoice_pdf", "archive_pdf"}
    ]
    invoices = [record for record in recognized_invoices if record.get("status") != "needs_review"]
    by_number: dict[tuple[str | None, str], list[dict[str, Any]]] = {}
    for record in invoices:
        by_number.setdefault((record.get("invoice_code"), record["invoice_number"]), []).append(record)
    for (_, number), matches in by_number.items():
        if len(matches) > 1:
            issues.append(f"发票号码重复: {number}")
            for record in matches:
                record["status"] = "needs_review"
                record["issue"] = f"发票号码重复: {number}"

    invoices = [record for record in invoices if record.get("status") != "needs_review"]
    invoices.sort(
        key=lambda record: (
            CATEGORY_ORDER.get(record.get("category", "其他"), 3),
            record.get("business_date") or "9999-99-99",
            record.get("original_name", "").casefold(),
        )
    )
    for sequence, record in enumerate(invoices, start=1):
        record["sequence"] = sequence
        extension = ".pdf" if record["file_type"] == "archive_pdf" else Path(record["original_name"]).suffix.lower()
        record["new_name"] = (
            f"{sequence}、{record['purpose']}-{record['invoice_number']}-"
            f"{record['total_amount']}元{extension}"
        )
        record["output_path"] = str(output_dir / record["new_name"])
        record["output_sha256"] = record.get("member_sha256") or record["source_sha256"]
        record["status"] = "planned"

    ride_letter_counts: dict[str, int] = {}
    for record in invoices:
        if record.get("ride_document"):
            brand = record.get("ride_brand") or "网约车"
            index = ride_letter_counts.get(brand, 0)
            record["ride_letter"] = _letter_for_index(index)
            ride_letter_counts[brand] = index + 1
            record["purpose"] = f"{brand}发票{record['ride_letter']}"
            record["new_name"] = (
                f"{record['sequence']}、{record['purpose']}-{record['invoice_number']}-"
                f"{record['total_amount']}元{Path(record['new_name']).suffix}"
            )
            record["output_path"] = str(output_dir / record["new_name"])

    reports = [record for record in records if record.get("file_type") == "ride_report"]
    matches = [
        ((None, report.get("issue") or "行程单字段需人工确认") if report.get("status") == "needs_review"
         else _transit_report_match(report, invoices) if _transport_mode(report) == "transit"
         else _ride_report_match(report, invoices))
        for report in reports
    ]
    paper_reports = [
        report for report, (invoice, _) in zip(reports, matches)
        if invoice is None and report.get("category") == "市内交通"
        and report.get("status") != "needs_review" and report.get("match_status") == "none"
        and report.get("total_amount")
        and not any((item.get("category") == "大型交通"
                     or _transport_mode(item) == _transport_mode(report))
                    and item.get("total_amount") in (None, "", report["total_amount"])
                    for item in recognized_invoices)
    ]
    paper_content_counts: dict[str, int] = {}
    for report in paper_reports:
        digest = report.get("member_sha256") or report.get("source_sha256")
        if digest:
            paper_content_counts[digest] = paper_content_counts.get(digest, 0) + 1
    for report in paper_reports:
        digest = report.get("member_sha256") or report.get("source_sha256")
        if not digest or paper_content_counts[digest] > 1:
            report["status"] = "needs_review"
            _record_match_result(report, None, "multiple" if digest else "conflict", [],
                                 "相同内容的行程单副本，需人工确认" if digest else "缺少可核对的来源内容标识")
    paper_reports = [report for report in paper_reports if report.get("status") != "needs_review"]
    paper_ids = {id(report) for report in paper_reports}
    supporting = [record for record in records if record.get("file_type") == "supporting_receipt"
                  and record.get("status") != "needs_review"]
    if paper_reports or supporting:
        anchors = sorted(invoices + paper_reports + supporting, key=lambda record: (
            CATEGORY_ORDER.get(record.get("category", "其他"), 3),
            record.get("business_date") or "9999-99-99",
            record.get("original_name", "").casefold(),
        ))
        for sequence, record in enumerate(anchors, start=1):
            record["sequence"] = sequence
            if record.get("file_type") == "supporting_receipt":
                receipt_number = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", str(record["receipt_number"]))
                record["new_name"] = f"{sequence}、货运收款凭证-{receipt_number}-{record['total_amount']}元.pdf"
                record["output_path"] = str(output_dir / record["new_name"])
                record["output_sha256"] = record.get("member_sha256") or record["source_sha256"]
                record["status"] = "planned"
                continue
            if id(record) not in paper_ids:
                extension = Path(record["new_name"]).suffix
                record["new_name"] = (
                    f"{sequence}、{record['purpose']}-{record['invoice_number']}-"
                    f"{record['total_amount']}元{extension}"
                )
                record["output_path"] = str(output_dir / record["new_name"])
    relation_counts: dict[int, int] = {}
    for invoice, _ in matches:
        if invoice is not None:
            relation_counts[id(invoice)] = relation_counts.get(id(invoice), 0) + 1
    for report, (invoice, reason) in zip(reports, matches):
        if id(report) in paper_ids:
            report["standalone_paper_invoice"] = True
            report["purpose"] = ("轨道交通行程单" if _transport_mode(report) == "transit"
                                 else "机场巴士行程单" if _transport_mode(report) == "airport_bus"
                                 else f"{report.get('ride_brand') or '网约车'}行程单")
            date_part = f"{report['business_date']}-" if report.get("business_date") else ""
            report["new_name"] = (
                f"{report['sequence']}、{report['purpose']}-{date_part}"
                f"{report['total_amount']}元（对应纸质发票）.pdf"
            )
            report["remark"] = "；".join(filter(None, (report.get("remark"), "（对应纸质发票）")))
            report["output_path"] = str(output_dir / report["new_name"])
            report["output_sha256"] = report.get("member_sha256") or report["source_sha256"]
            report["status"] = "planned"
            continue
        if invoice is not None and relation_counts[id(invoice)] > 1:
            invoice, reason = None, "多份行程单对应同一张发票，需人工确认"
            _record_match_result(report, None, "multiple", [], reason)
        if invoice is None:
            report["status"] = "needs_review"
            report["issue"] = f"行程单无法唯一匹配发票: {report.get('match_reason') or reason}"
            continue
        report["sequence"] = invoice["sequence"]
        if _transport_mode(report) in {"transit", "airport_bus", "passenger_bus"}:
            report["category"] = invoice["category"]
            report["expense_type"] = invoice["expense_type"]
            report["purpose"] = ("机场巴士行程单" if _transport_mode(report) == "airport_bus"
                                 else "汽车行程单" if _transport_mode(report) == "passenger_bus"
                                 else "城际铁路行程单" if invoice["purpose"] == "高铁" else "地铁行程单")
        else:
            letter = invoice["ride_letter"]
            report["ride_letter"] = letter
            report["ride_brand"] = report.get("ride_brand") or invoice.get("ride_brand") or "网约车"
            report["purpose"] = f"{report['ride_brand']}行程单{letter}"
        report["new_name"] = f"{invoice['sequence']}、{report['purpose']}.pdf"
        report["output_path"] = str(output_dir / report["new_name"])
        report["output_sha256"] = report.get("member_sha256") or report["source_sha256"]
        report["ride_relation"] = invoice["new_name"]
        invoice["ride_relation"] = report["new_name"]
        report["status"] = "planned"

    destinations: dict[str, list[dict[str, Any]]] = {}
    for record in output_records(records):
        destinations.setdefault(record["new_name"].casefold(), []).append(record)
    for name, matches in destinations.items():
        if len(matches) > 1:
            issues.append(f"目标名称重复: {name}")
            for record in matches:
                record["status"] = "needs_review"
                record["issue"] = f"目标名称重复: {name}"
    _assign_expense_fields(records)
    return records, issues


def _assign_expense_fields(records: list[dict[str, Any]]) -> None:
    """Give documents explicit expense roles without changing printed amounts."""
    by_name = {record["new_name"]: record for record in records
               if record.get("new_name") and record.get("status") != "needs_review"}
    for record in records:
        record.update(expense_id=None, counts_toward_total=False, expense_amount=None,
                      expense_basis="unresolved")
        if record.get("status") == "needs_review" or not record.get("new_name"):
            continue
        if record.get("file_type") in {"invoice_pdf", "archive_pdf"}:
            record.update(expense_id=f"invoice:{record.get('invoice_code') or ''}:{record['invoice_number']}",
                          counts_toward_total=True, expense_amount=record["total_amount"], expense_basis="invoice")
        elif record.get("standalone_paper_invoice"):
            digest = record.get("member_sha256") or record.get("source_sha256")
            record.update(expense_id=f"paper:{digest}", counts_toward_total=True,
                          expense_amount=record["total_amount"], expense_basis="paper_itinerary")
        elif record.get("file_type") == "supporting_receipt":
            record["expense_basis"] = "supporting_receipt"
    for report in records:
        if (report.get("file_type") != "ride_report" or not report.get("ride_relation")
                or report.get("status") == "needs_review"):
            continue
        invoice = by_name.get(report["ride_relation"])
        if invoice is None or invoice.get("expense_basis") != "invoice":
            report["status"] = "needs_review"
            report["issue"] = "行程单无法唯一匹配发票: 对应发票不可作为确认费用"
            for key in ("new_name", "output_path", "output_sha256", "sequence", "ride_relation"):
                report.pop(key, None)
            continue
        report.update(expense_id=invoice["expense_id"], counts_toward_total=False,
                      expense_amount=None, expense_basis="attachment")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
