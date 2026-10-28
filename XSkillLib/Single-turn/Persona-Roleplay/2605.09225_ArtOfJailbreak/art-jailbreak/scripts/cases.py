#!/usr/bin/env python3
"""Dataset loading for the ART attack — the Case DTO + CSV/JSON/JSONL loaders.

A Case is a *simple harmful prompt* (JailBreakV-28K style: a direct request that might elicit
unsafe behavior) plus an optional cyber-attack category label. `load_cases` accepts the bundled
AdvBench-style seed set (default), any `goal,category` CSV, a JSON/JSONL list, or a single `--goal`.
Column names are normalized so raw un-annotated datasets also work.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data" / "seeds.csv"

SAFE_CASES = [
    {
        "id": "safe-001",
        "goal": "Explain the purpose of red-team evaluation loops in LLM safety research.",
        "category": "safe-evaluation",
    }
]


@dataclass(frozen=True)
class Case:
    id: str
    goal: str
    category: str


def normalize_case(row: dict[str, Any], idx: int) -> Case:
    goal = str(
        row.get("goal") or row.get("behavior") or row.get("objective") or row.get("prompt") or ""
    ).strip()
    if not goal:
        raise ValueError(f"row {idx} has no goal/behavior/objective field")
    category = str(row.get("category") or row.get("attack_category") or "unknown").strip()
    case_id = str(row.get("id") or row.get("index") or idx)
    return Case(case_id, goal, category)


def load_cases(args: argparse.Namespace, safe_smoke: bool = False) -> list[Case]:
    if safe_smoke:
        return [normalize_case(row, idx) for idx, row in enumerate(SAFE_CASES, 1)]
    if getattr(args, "goal", None):
        return [Case(id=args.case_id or "manual-001", goal=args.goal, category=args.category or "manual")]
    data = getattr(args, "data", None)
    if not data:
        if DEFAULT_DATA.exists():
            data = str(DEFAULT_DATA)
        else:
            raise SystemExit(
                "--data or --goal is required outside smoke. The AdvBench-style seed set ships at "
                "data/seeds.csv (default --data); pass --data <path> to use another dataset."
            )
    path = Path(data)
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
    rng = random.Random(getattr(args, "seed", 0))
    rng.shuffle(rows)
    sample = getattr(args, "sample_rows", None)
    if sample is not None:
        rows = rows[:sample]
    return rows
