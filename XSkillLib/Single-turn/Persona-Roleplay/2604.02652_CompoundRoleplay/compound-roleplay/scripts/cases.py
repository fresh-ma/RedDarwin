#!/usr/bin/env python3
"""Dataset DTO + loader for Compound Role-Playing.

Reads the paper's 70-prompt set (7 categories x 10). Accepts any CSV with a
`goal` column; `category` is optional (drives persona selection, defaults to a
generic security expert)."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Case:
    index: int
    category: str
    goal: str


def load_cases(path: Path, sample: int | None = None) -> list[Case]:
    rows: list[Case] = []
    with path.open(newline="", encoding="utf-8") as f:
        for i, r in enumerate(csv.DictReader(f)):
            goal = (r.get("goal") or r.get("prompt") or r.get("behavior")
                    or r.get("request") or "").strip()  # `request`: AdvBench column
            if not goal:
                continue
            category = (r.get("category") or "").strip()
            rows.append(Case(index=len(rows), category=category, goal=goal))
    if sample is not None and sample < len(rows):
        rows = rows[:sample]
    return rows
