#!/usr/bin/env python3
"""Goal CSV loader for Compound Roleplay 2.0 (copied from the parent skill).

Accepts any CSV with a `goal`, `prompt`, `behavior`, or `request` column
(`request` covers AdvBench). `category` is optional and unused by the v1
mechanism (generic persona — no category-keyed branching).
"""
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
        for r in csv.DictReader(f):
            goal = (r.get("goal") or r.get("prompt") or r.get("behavior")
                    or r.get("request") or "").strip()
            if not goal:
                continue
            category = (r.get("category") or "").strip()
            rows.append(Case(index=len(rows), category=category, goal=goal))
    if sample is not None and sample < len(rows):
        rows = rows[:sample]
    return rows
