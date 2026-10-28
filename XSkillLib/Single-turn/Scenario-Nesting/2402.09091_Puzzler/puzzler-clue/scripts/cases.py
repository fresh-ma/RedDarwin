#!/usr/bin/env python3
"""Dataset loading for Puzzler — the AdvBench harmful-behaviors CSV loader.

`load_rows` reads a `goal,target` CSV (the paper's AdvBench set) and optionally
truncates to the first `sample_rows` for a `--sample` run.
"""

from __future__ import annotations

import csv
from pathlib import Path


def load_rows(path: Path, sample_rows: int) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("goal")]
    return rows[:sample_rows] if sample_rows else rows
