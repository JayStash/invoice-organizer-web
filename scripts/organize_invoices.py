#!/usr/bin/env python3
"""CLI entry point for executing an approved invoice plan."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.common import DEFAULT_PLAN_PATH, InvoiceOrganizerError  # noqa: E402
from app.core.organize_invoices import organize_invoices  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="根据已确认计划向 output 创建整理结果。")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN_PATH)
    parser.add_argument("--confirm", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = organize_invoices(args.plan, args.confirm)
    except InvoiceOrganizerError as exc:
        raise SystemExit(str(exc)) from exc
    total = result.grand_total if result.grand_total is not None else "空白"
    print(f"整理完成: {result.processed_count} 个票据文件")
    print(f"Excel: {result.workbook_path}")
    print(f"票面总金额合计: {total}")
    print("input 未修改；ZIP 原文件已保留。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
