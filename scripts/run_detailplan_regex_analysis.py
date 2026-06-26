"""Run the regex-only detail-plan analyzer for one local PDF."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.detailplan_analyzer.analyzer import process_planning_pdf  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf_path")
    parser.add_argument("--address", default="")
    args = parser.parse_args()

    result = process_planning_pdf(args.pdf_path, args.address)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
