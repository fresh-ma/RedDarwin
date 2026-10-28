#!/usr/bin/env python3
"""Dataset loading for Crescendo — paper-local AdvBench table + generic CSV/JSON.

`read_goals` parses the skill-local AdvBench CSV (data/advbench/…csv) by
default (the paper's digest/tables/…tex table also works), or any goal/behavior
CSV, into dataset-agnostic rows; `choose` samples a deterministic slice.
`SAFE_GOALS` backs the wiring-only smoke path.
"""
from __future__ import annotations

import csv
import random
from pathlib import Path
from typing import Any

from models import METHOD_ROOT, PAPER_ROOT

DEFAULT_GOALS = METHOD_ROOT / "data" / "advbench" / "harmful_behaviors.csv"

SAFE_GOALS = [
    {"id": "smoke-0", "goal": "explain how multi-turn evaluation can drift from the first user request", "category": "safe", "source_row": 0},
    {"id": "smoke-1", "goal": "summarize why conversation history should be saved in model tests", "category": "safe", "source_row": 1},
]


# --------------------------------------------------------------------------- #
# Dataset loading (dataset-agnostic)
# --------------------------------------------------------------------------- #
def read_advbench_table(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current_category = ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if (
            not stripped
            or "\\textbf" in stripped
            or stripped.startswith(("\\begin", "\\end", "\\toprule", "\\bottomrule", "\\midrule"))
        ):
            continue
        row_text = stripped.removesuffix("\\\\").strip()
        protected = row_text.replace("\\&", "__ESCAPED_AMP__")
        parts = [part.replace("__ESCAPED_AMP__", "&").strip() for part in protected.split("&")]
        if len(parts) != 3:
            continue
        category, task, abbreviation = parts
        category = category.rstrip("\\").strip()
        task = task.rstrip("\\").strip()
        abbreviation = abbreviation.rstrip("\\").strip()
        if category == "&":
            category = current_category
        elif category.endswith("&"):
            category = category.rstrip("&").strip()
        if category:
            current_category = category
        if task and abbreviation:
            rows.append({"id": abbreviation, "goal": task, "category": current_category, "source_row": len(rows)})
    return rows


def read_goals(path: str | Path | None, smoke_only: bool) -> tuple[list[dict[str, Any]], str]:
    if smoke_only:
        return list(SAFE_GOALS), "built_in_safe_goals"
    if not path:
        raise SystemExit("--goals is required outside smoke")
    path = Path(path)
    if path.name == "tab-advbenchtasks.tex":
        rows = read_advbench_table(path)
        if not rows:
            raise SystemExit(f"no paper-local AdvBench tasks parsed from {path}")
        try:
            rel = str(path.relative_to(PAPER_ROOT))
        except ValueError:
            rel = str(path)
        return rows, rel
    rows = []
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
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
    return rows, str(path)


def choose(rows: list[dict[str, Any]], sample_rows: int | None, seed: int) -> list[dict[str, Any]]:
    rows = list(rows)
    if sample_rows is not None:
        random.Random(seed).shuffle(rows)
        rows = rows[:sample_rows]
    if not rows:
        raise SystemExit("no rows selected")
    return rows
