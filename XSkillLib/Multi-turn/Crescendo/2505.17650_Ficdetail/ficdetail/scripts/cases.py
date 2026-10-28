#!/usr/bin/env python3
"""Dataset loading for FicDetail — the full AdvBench harmful_behaviors set.

The paper evaluates on the entire AdvBench (520 harmful instructions). `read_goals`
parses AdvBench harmful_behaviors.csv by default, or any goal/behavior CSV, into
dataset-agnostic rows; `choose` samples a deterministic slice. `SAFE_GOALS` backs
the wiring-only smoke path.
"""
from __future__ import annotations

import csv
import random
from pathlib import Path
from typing import Any

from models import METHOD_ROOT

DEFAULT_GOALS = METHOD_ROOT / "data" / "advbench" / "harmful_behaviors.csv"

SAFE_GOALS = [
    {"id": "smoke-0", "goal": "bake an elaborate birthday cake for a fictional chef character", "category": "safe", "source_row": 0},
    {"id": "smoke-1", "goal": "plan a surprise garden party for a retiring professor", "category": "safe", "source_row": 1},
]

_GOAL_KEYS = ("goal", "Goal", "behavior", "Behavior", "query", "question", "request", "prompt")


def read_goals(path: str | Path | None, smoke_only: bool) -> tuple[list[dict[str, Any]], str]:
    if smoke_only:
        return list(SAFE_GOALS), "built_in_safe_goals"
    if not path:
        raise SystemExit("--goals is required outside smoke")
    path = Path(path)
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        for idx, row in enumerate(csv.DictReader(handle)):
            goal = ""
            for key in _GOAL_KEYS:
                goal = (row.get(key) or "").strip()
                if goal:
                    break
            if goal:
                rows.append(
                    {
                        "id": row.get("id") or row.get("Index") or row.get("behavior_id") or str(idx),
                        "goal": goal,
                        "category": row.get("Category") or row.get("category") or "",
                        "source_row": idx,
                    }
                )
    if not rows:
        raise SystemExit(f"no goals loaded from {path}")
    return rows, str(path)


def choose(rows: list[dict[str, Any]], sample_rows: int | None, seed: int) -> list[dict[str, Any]]:
    rows = list(rows)
    if sample_rows is not None:
        random.Random(seed).shuffle(rows)
        rows = rows[:sample_rows]
    if not rows:
        raise SystemExit("no rows selected")
    return rows
