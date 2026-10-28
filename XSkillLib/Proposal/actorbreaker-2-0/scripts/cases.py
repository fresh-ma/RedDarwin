#!/usr/bin/env python3
"""Dataset DTO + loader for ActorBreaker.

The seed harmful behaviours are the official HarmBench slice the paper attacks
(``data/harmbench.csv``, 200 goals) and the circuit-breaker training set
(``data/circuit_breaker_train.csv``, 1000 goals). Each row's ``Goal`` column is
the raw harmful instruction fed into the pre-attack stage.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_DATASET = _DATA_DIR / "harmbench.csv"


@dataclass(frozen=True)
class Case:
    goal: str


def load_cases(csv_path: Path | str, n: int | None = None) -> list[Case]:
    """Load harmful behaviours; accepts Goal/goal/instruction/behavior/request columns."""
    path = Path(csv_path)
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    cases: list[Case] = []
    for r in rows:
        goal = (r.get("Goal") or r.get("goal") or r.get("instruction")
                or r.get("behavior") or r.get("request"))
        if goal:
            cases.append(Case(goal=goal))
    return cases[:n] if n else cases
