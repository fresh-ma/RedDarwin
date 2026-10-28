#!/usr/bin/env python3
"""Dataset loading for S2C — the Case DTO + CSV/JSON/JSONL loaders.

`load_cases` accepts the bundled seed behaviors (default), any `goal,target,category`
CSV, or a JSON/JSONL list, plus a single manual `--goal`. Column names are normalized
(goal/behavior/objective, target/target_str, ...) so raw un-annotated datasets (e.g.
JBB-Behaviors, HarmBench) also work.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data" / "s2c_seed_behaviors.csv"

SAFE_CASES = [
    {
        "id": "safe-001",
        "goal": "Explain the purpose of red-team evaluation loops.",
        "target_str": "Sure, here is an explanation of red-team evaluation loops",
        "category": "safe-evaluation",
    }
]


@dataclass
class Case:
    id: str
    goal: str
    target_str: str
    category: str


def normalize_case(row: dict[str, Any], idx: int) -> Case:
    goal = str(row.get("goal") or row.get("behavior") or row.get("objective") or row.get("prompt") or "").strip()
    target = str(row.get("target") or row.get("target_str") or row.get("starting_string") or "").strip()
    if not goal:
        raise ValueError(f"row {idx} has no goal/behavior/objective field")
    if not target:
        target = "Sure, here is the requested response"
    category = str(row.get("category") or row.get("behavior_category") or "unknown").strip()
    case_id = str(row.get("id") or row.get("Original index") or row.get("index") or idx)
    return Case(case_id, goal, target, category)


def load_cases(args: argparse.Namespace, safe_smoke: bool = False) -> list[Case]:
    if safe_smoke:
        return [normalize_case(row, idx) for idx, row in enumerate(SAFE_CASES, 1)]
    if args.goal:
        return [
            Case(
                id=args.case_id or "manual-001",
                goal=args.goal,
                target_str=args.target_str or "Sure, here is the requested response",
                category=args.category or "manual",
            )
        ]
    if not args.data:
        if DEFAULT_DATA.exists():
            args.data = str(DEFAULT_DATA)
        else:
            raise SystemExit(
                "--data or --goal is required outside smoke. "
                "The bundled seed set ships at data/s2c_seed_behaviors.csv (default --data); "
                "pass --data <path> to use JBB-Behaviors / HarmBench."
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
    if args.sample_rows is not None:
        rows = rows[: args.sample_rows]
    return rows
