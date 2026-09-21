#!/usr/bin/env python3
"""CLI entry point for creating an invoice organization plan."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.common import (  # noqa: E402
    DEFAULT_INPUT_DIR,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PLAN_PATH,
    DEFAULT_PREVIEW_PATH,
    InvoiceOrganizerError,
)
from app.core.scan_invoices import scan_invoices  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="只读扫描 input，并在 .runtime 中生成预览和计划。")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        plan = scan_invoices(args.input, args.output)
    except InvoiceOrganizerError as exc:
        raise SystemExit(str(exc)) from exc
    planned = sum(1 for record in plan["records"] if record.get("new_name"))
    unresolved = sum(
        1 for record in plan["records"] if record.get("status") == "needs_review"
    )
    print(f"只读扫描完成: {len(plan['input_snapshot'])} 个 input 文件")
    print(f"拟输出票据: {planned}")
    print(f"待人工确认: {unresolved}")
    print(f"计划: {DEFAULT_PLAN_PATH}")
    print(f"预览: {DEFAULT_PREVIEW_PATH}")
    print(f"审批令牌: {plan['approval_token']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
