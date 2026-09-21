#!/usr/bin/env python3
"""CLI entry point for validating organized invoice output."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.common import (  # noqa: E402
    DEFAULT_PLAN_PATH,
    InvoiceOrganizerError,
    WORKBOOK_NAME,
)
from app.core.validate_organization import validate_organization  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="校验 input、output、plan 和 Excel。")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN_PATH)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = validate_organization(args.plan)
    except InvoiceOrganizerError as exc:
        raise SystemExit(str(exc)) from exc
    if result.errors:
        print("校验失败:")
        for error in result.errors:
            print(f"- {error}")
        return 1
    print(f"校验通过: input {result.input_count} 个原始文件保持不变")
    print(f"校验通过: output {result.output_count} 个票据文件 + {WORKBOOK_NAME}")
    print(f"校验通过: 票面总金额合计 {result.grand_total or '空白'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
