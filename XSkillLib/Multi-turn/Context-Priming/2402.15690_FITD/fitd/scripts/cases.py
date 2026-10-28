#!/usr/bin/env python3
"""Dataset loading for FITD — the AdvBench goal-row loader.

`load_rows` reads a `goal,category` CSV (the AdvBench cache) and returns the
harmful goal rows; the stock AdvBench `request,target` header is accepted as a
`goal` alias. `sample_rows=0` returns the full pool.
"""

from __future__ import annotations

import csv
from pathlib import Path


def load_rows(path: Path, sample_rows: int) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = []
        for row in csv.DictReader(handle):
            # accept the stock AdvBench `request,target` header as a `goal` alias
            goal = row.get("goal") or row.get("request")
            if goal:
                row["goal"] = goal
                rows.append(row)
    rows = rows[:sample_rows] if sample_rows else rows
    if not rows:
        raise SystemExit(f"no goal rows found in {path}")
    return rows
