#!/usr/bin/env python3
"""Dataset loading + repo config for CodeChameleon.

`read_rows` loads the full official benchmark (data/all_problem.csv = 820 =
AdvBench 520 + shadow_heldout 200 + MaliciousInstruct 100) or any goal CSV, and
`select_rows` applies --limit/--sample. Column names are normalized (problem /
Goal / goal / Behavior / ...) so raw un-annotated datasets also work.
"""
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path
from typing import Any

PAPER_ID = "2402.16717_personalized-encryption-jailbreak"
METHOD_ID = "codechameleon"

SCRIPT_DIR = Path(__file__).resolve().parent
METHOD_DIR = SCRIPT_DIR.parent


def _repo_root(start: Path) -> Path:
    # Walk up to the project root holding the shared `.env` (XSkillForge global env).
    # A method-local `.env` (if present) still wins; otherwise the global one is found
    # by walking up. `.codex` kept for backward compatibility with xsafebench layout.
    for p in [start, *start.parents]:
        if (p / ".codex").exists() or (p / ".env").exists():
            return p
    return start.parents[min(2, len(start.parents) - 1)]


ROOT = _repo_root(SCRIPT_DIR)
# Full official benchmark, vendored into the method dir under data/.
DEFAULT_GOALS = METHOD_DIR / "data" / "all_problem.csv"
PROJECT_ENV = ROOT / ".env"

# Benign goals: smoke/wiring only (never durable evidence).
SAFE_GOALS = [
    {"id": "smoke-0", "goal": "explain how a reversible encoder can be unit tested", "category": "safe", "source_row": 0},
    {"id": "smoke-1", "goal": "summarize why code templates need direct unit checks", "category": "safe", "source_row": 1},
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
            # official dataset uses 'problem'; AdvBench uses Goal/goal/Behavior.
            for key in ("problem", "Goal", "goal", "Behavior", "behavior", "query", "question", "request"):
                goal = (row.get(key) or "").strip()
                if goal:
                    break
            if goal:
                rows.append(
                    {
                        "id": row.get("id") or row.get("Index") or row.get("behavior_id") or str(idx),
                        "goal": goal,
                        "category": row.get("dataset") or row.get("Category") or row.get("category") or "",
                        "source_row": idx,
                    }
                )
    if not rows:
        raise SystemExit("no goals loaded")
    return rows, repo_relative(data_path)


def select_rows(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    selected = list(rows)
    if getattr(args, "limit", None) is not None:
        selected = selected[: args.limit]
    if getattr(args, "sample", None) is not None:
        random.Random(args.seed).shuffle(selected)
        selected = selected[: args.sample]
    if not selected:
        raise SystemExit("no rows selected")
    return selected
