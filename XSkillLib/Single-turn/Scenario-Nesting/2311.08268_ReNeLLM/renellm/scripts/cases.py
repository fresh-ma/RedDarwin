#!/usr/bin/env python3
"""Dataset loading for ReNeLLM — the AdvBench goal loader + row selection.

`read_goals` parses the official `harmful_behaviors.csv` (column names normalized
so raw un-annotated goal files also work); `select_rows` applies index/limit/sample
selection. `SMOKE_GOALS` are safe wiring-check placeholders.
"""
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path
from typing import Any

from models import resolve_path


DEFAULT_GOALS = Path(__file__).resolve().parents[1] / "assets/advbench/harmful_behaviors.csv"

SMOKE_GOALS = [
    {"id": "smoke-0", "goal": "explain what a startup wiring check verifies", "target": "", "category": "safe", "source_row": 0},
    {"id": "smoke-1", "goal": "summarize why model inputs and outputs should be saved", "target": "", "category": "safe", "source_row": 1},
]


def read_goals(path: Path, goal_field: str) -> list[dict[str, Any]]:
    path = resolve_path(path)
    if not path.exists():
        raise SystemExit(f"goal file not found: {path}")
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader):
            goal = ""
            if goal_field != "auto":
                goal = (row.get(goal_field) or "").strip()
            if not goal:
                for key in ("goal", "Goal", "behavior", "Behavior", "query", "question", "request"):
                    goal = (row.get(key) or "").strip()
                    if goal:
                        break
            if not goal:
                continue
            rows.append(
                {
                    "id": row.get("id") or row.get("Index") or row.get("behavior_id") or str(idx),
                    "goal": goal,
                    "target": row.get("target") or row.get("Target") or "",
                    "category": row.get("category") or row.get("Category") or "",
                    "source_row": idx,
                }
            )
    if not rows:
        raise SystemExit(f"no goals found in {path}")
    return rows


def select_rows(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.indices:
        wanted = {int(part) for part in args.indices.split(",") if part.strip()}
        rows = [row for row in rows if int(row["source_row"]) in wanted]
    if args.limit is not None:
        rows = rows[: args.limit]
    else:
        rows = list(rows)
    if args.sample_rows is not None:
        random.Random(args.seed).shuffle(rows)
        rows = rows[: args.sample_rows]
    if not rows:
        raise SystemExit("no rows selected")
    return rows
