"""Backward-compatible entry point for the canonical data pipeline.

Historically this module read raw packages and the previous frontend output in
the same pass. It now delegates to :mod:`tools.data_pipeline`, so every
frontend record has first passed through ``normalized/rankingselect.sqlite``.

Prefer the explicit command in new automation::

    python -m tools.data_pipeline all
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from tools.data_pipeline import ROOT, run_all


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build canonical data and export frontend JSON.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="frontend JSON directory (default: frontend/public/data)",
    )
    args = parser.parse_args(argv)
    report = run_all(
        ROOT,
        frontend_dir=args.output or ROOT / "frontend" / "public" / "data",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
