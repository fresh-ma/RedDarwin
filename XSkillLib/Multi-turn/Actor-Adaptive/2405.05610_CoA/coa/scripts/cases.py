#!/usr/bin/env python3
"""Dataset loading for CoA — goal rows + the built-in safe smoke set.

`read_rows` accepts the default AdvBench/PAIR-50 goal CSV (or any CSV with a
goal/behavior/query column), normalizing column names so raw un-annotated data
also works; `--wiring-check`/smoke uses the built-in SAFE_GOALS. `select_rows`
applies --limit / --sample-rows (seeded). Paths resolve relative to the repo root.
"""
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path
from typing import Any

from models import METHOD_DIR, ROOT

DEFAULT_GOALS = METHOD_DIR / "data" / "harmful_behaviors_custom.csv"
SAFE_GOALS = [
    {"id": "smoke-0", "goal": "explain how a multi-turn benchmark can track semantic drift", "category": "safe", "source_row": 0},
    {"id": "smoke-1", "goal": "summarize how conversation history affects model evaluation", "category": "safe", "source_row": 1},
]


def repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def read_rows(path: str | None, smoke_only: bool) -> tuple[list[dict[str, Any]], str]:
    if smoke_only:
        return list(SAFE_GOALS), "built_in_safe_goals"
    if not path:
        raise SystemExit("--goals is required outside smoke")
    rows: list[dict[str, Any]] = []
    data_path = Path(path)
    with data_path.open(newline="", encoding="utf-8", errors="replace") as handle:
        for idx, row in enumerate(csv.DictReader(handle)):
            goal = ""
            for key in ("Goal", "goal", "Behavior", "behavior", "query", "question", "request"):
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
        raise SystemExit("no goals loaded")
    return rows, repo_relative(data_path)


def select_rows(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    selected = list(rows)
    if args.limit is not None:
        selected = selected[: args.limit]
    if args.sample_rows is not None:
        random.Random(args.seed).shuffle(selected)
        selected = selected[: args.sample_rows]
    if not selected:
        raise SystemExit("no rows selected")
    return selected
