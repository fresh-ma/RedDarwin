#!/usr/bin/env python3
"""Dataset loaders for AutoDAN-Turbo (official harmful_behavior_requests.json)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Case:
    case_id: str
    goal: str
    split: str
    index: int


def method_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_dataset() -> Path:
    return method_root() / "data" / "harmful_behavior_requests.json"


def load_behaviors(
    path: str | Path | None = None,
    split: str = "lifelong",
    sample: int | None = None,
    offset: int = 0,
) -> list[Case]:
    """Load official warm_up / lifelong string lists as Case DTOs.

    full_count: warm_up=50, lifelong=400 (HarmBench-style harmful requests from official repo).
    """
    p = Path(path) if path else default_dataset()
    raw = json.loads(p.read_text(encoding="utf-8"))
    if split not in raw:
        raise KeyError(f"split {split!r} not in {p}; keys={list(raw)}")
    rows = list(raw[split])
    if offset:
        rows = rows[offset:]
    if sample is not None:
        rows = rows[:sample]
    return [
        Case(case_id=f"{split}-{offset + i}", goal=str(g), split=split, index=offset + i)
        for i, g in enumerate(rows)
    ]


def full_count(path: str | Path | None = None, split: str = "lifelong") -> int:
    p = Path(path) if path else default_dataset()
    raw = json.loads(p.read_text(encoding="utf-8"))
    return len(raw[split])
