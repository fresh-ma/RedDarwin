#!/usr/bin/env python3
"""Dataset loading for Mastermind — the Case DTO + HarmBench/StrongReject loaders.

Paper (arXiv 2601.05445, sec 5.1) evaluates on two test benchmarks:
  * HarmBench standard subset — 200 harmful-behavior instances
    (`data/harmbench_standard_200.csv`, FunctionalCategory==standard).
  * StrongReject custom small set — 60 instances with natural, realistic wording
    (`data/strongreject_small_60.csv`, column `forbidden_prompt`).
A separate auxiliary set of 200 harmful queries is used ONLY for the Phase-1
knowledge-accumulation bootstrap (see gen_knowledge.py; that set is unreleased in
the paper, substituted here by an AdvBench slice — see data/README.md).

`load_cases` defaults to the HarmBench standard set, keeps only the standard
FunctionalCategory rows when that column is present, and also accepts any
`goal|Behavior|forbidden_prompt[,category]` CSV/JSON/JSONL or a single `--goal`.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data" / "harmbench_standard_200.csv"

SAFE_CASES = [
    {
        "goal": "Explain the purpose of multi-turn red-team evaluation loops.",
        "id": "safe-001",
        "category": "safe-evaluation",
    }
]


@dataclass(frozen=True)
class Case:
    id: str
    goal: str
    category: str
    context: str = ""


def normalize_case(row: dict[str, Any], idx: int) -> Case:
    goal = str(
        row.get("goal")
        or row.get("Behavior")
        or row.get("behavior")
        or row.get("forbidden_prompt")
        or row.get("objective")
        or row.get("prompt")
        or ""
    ).strip()
    if not goal:
        raise ValueError(f"row {idx} has no goal/Behavior/forbidden_prompt/objective field")
    category = str(
        row.get("category") or row.get("SemanticCategory") or row.get("behavior_category") or "unknown"
    ).strip()
    case_id = str(row.get("id") or row.get("BehaviorID") or row.get("behavior_id") or row.get("index") or idx)
    context = str(row.get("context") or row.get("ContextString") or "").strip()
    return Case(id=case_id, goal=goal, category=category, context=context)


def _standard_only(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """HarmBench standard subset filter when the FunctionalCategory column is present."""
    if rows and "FunctionalCategory" in rows[0]:
        filtered = [r for r in rows if str(r.get("FunctionalCategory", "")).strip() == "standard"]
        return filtered or rows
    return rows


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
    if not args.data:
        if DEFAULT_DATA.exists():
            args.data = str(DEFAULT_DATA)
        else:
            raise SystemExit(
                "--data or --goal is required outside smoke. "
                "The HarmBench standard set ships at data/harmbench_standard_200.csv (default --data)."
            )
    path = Path(args.data)
    if not path.exists():
        raise FileNotFoundError(f"data file not found: {path}")
    suffix = path.suffix.lower()
    raw_rows: list[dict[str, Any]]
    if suffix == ".jsonl":
        raw_rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    elif suffix == ".json":
        obj = json.loads(path.read_text(encoding="utf-8"))
        raw_rows = obj if isinstance(obj, list) else obj.get("data", [])
    else:
        with path.open(newline="", encoding="utf-8") as handle:
            raw_rows = list(csv.DictReader(handle))
    if not args.include_all_categories:
        raw_rows = _standard_only(raw_rows)
    rows = [normalize_case(row, idx) for idx, row in enumerate(raw_rows, 1)]
    rng = random.Random(args.seed)
    rng.shuffle(rows)
    if args.sample_rows is not None:
        rows = rows[: args.sample_rows]
    return rows
