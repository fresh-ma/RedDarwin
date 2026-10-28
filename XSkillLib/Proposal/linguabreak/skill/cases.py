#!/usr/bin/env python3
"""Dataset loading for LATS — the Case DTO + CSV/JSON/JSONL loaders.

Each Case is a single harmful goal, the attacker's target query P* (Algorithm's
`Seed prompt P*`). Column names are normalized so a raw `goal`-only dataset also works.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data" / "advbench_harmful_behaviors.csv"

SAFE_CASES = [
    {
        "id": "safe-001",
        "goal": "Explain the purpose of red-team evaluation loops for LLM safety.",
        "category": "safe-evaluation",
    }
]


@dataclass(frozen=True)
class Case:
    id: str
    goal: str  # the attacker's target query P*
    category: str


def normalize_case(row: dict[str, Any], idx: int) -> Case:
    goal = str(
        row.get("goal") or row.get("behavior") or row.get("objective")
        or row.get("prompt") or row.get("question") or ""
    ).strip()
    if not goal:
        raise ValueError(f"row {idx} has no goal/behavior/objective field")
    category = str(row.get("category") or row.get("behavior_category") or "unknown").strip()
    case_id = str(row.get("id") or row.get("Original index") or row.get("index") or idx)
    return Case(id=case_id, goal=goal, category=category)


def load_cases(args: argparse.Namespace, safe_smoke: bool = False) -> list[Case]:
    if safe_smoke:
        return [normalize_case(row, idx) for idx, row in enumerate(SAFE_CASES, 1)]
    if getattr(args, "goal", None):
        return [
            Case(
                id=args.case_id or "manual-001",
                goal=args.goal,
                category=args.category or "manual",
            )
        ]
    if not getattr(args, "data", None):
        if DEFAULT_DATA.exists():
            args.data = str(DEFAULT_DATA)
        else:
            raise SystemExit(
                "--data or --goal is required outside smoke. "
                "Full AdvBench (520) ships at data/advbench_harmful_behaviors.csv (default --data); "
                "a 25-goal curated quick-sample is data/advbench_seed.csv; pass --data <path> for another."
            )
    path = Path(args.data)
    if not path.exists():
        raise FileNotFoundError(f"data file not found: {path}")
    suffix = path.suffix.lower()
    rows: list[Case] = []
    if suffix == ".jsonl":
        for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                rows.append(normalize_case(json.loads(line), idx))
    elif suffix == ".json":
        obj = json.loads(path.read_text(encoding="utf-8"))
        source = obj if isinstance(obj, list) else obj.get("data", [])
        rows = [normalize_case(row, idx) for idx, row in enumerate(source, 1)]
    else:
        with path.open(newline="", encoding="utf-8") as handle:
            rows = [normalize_case(row, idx) for idx, row in enumerate(csv.DictReader(handle), 1)]
    rng = random.Random(args.seed)
    rng.shuffle(rows)
    if getattr(args, "sample_rows", None) is not None:
        rows = rows[: args.sample_rows]
    return rows
