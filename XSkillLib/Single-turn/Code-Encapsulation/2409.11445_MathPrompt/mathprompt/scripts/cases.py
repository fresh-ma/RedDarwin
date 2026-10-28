#!/usr/bin/env python3
"""Dataset loading for MathPrompt.

The paper evaluates on the Liu et al. (2024) 120 harmful-behavior set (80% drawn from AdvBench /
GPTFuzzer / MASTERKEY / TDC). We vendor the full AdvBench `harmful_behaviors.csv` (520 goals) under
data/ as a faithful representative of those harmful behaviors and read its `goal` column. Column
names are normalized (goal / behavior / Goal / Behavior) so a raw un-annotated CSV also works.
"""
from __future__ import annotations

import csv
from pathlib import Path

METHOD_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = METHOD_DIR / "data" / "advbench" / "harmful_behaviors.csv"

# "request" added so the shared bench CSV (XSkillForge/bench/AdvBench.csv: request,target)
# can be fed directly via --dataset.
_GOAL_COLS = ("goal", "behavior", "Goal", "Behavior", "problem", "prompt", "request")


def read_behaviors(csv_path: Path, n: int) -> list[str]:
    """Read up to `n` harmful-behavior goals from a CSV (goal/behavior column, normalized)."""
    rows: list[str] = []
    with csv_path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            g = ""
            for col in _GOAL_COLS:
                if r.get(col):
                    g = str(r[col]).strip()
                    break
            if g:
                rows.append(g)
            if len(rows) >= n:
                break
    return rows
