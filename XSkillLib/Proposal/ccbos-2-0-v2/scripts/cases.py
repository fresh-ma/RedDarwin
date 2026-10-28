#!/usr/bin/env python3
"""Dataset DTO + loader for CC-BOS (AdvBench harmful behaviors)."""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Behavior:
    idx: int
    text: str
    behavior_id: str
    row: dict[str, str] = field(default_factory=dict)


def load_behaviors(path: Path, sample: int, seed: int) -> list[Behavior]:
    """Load harmful behaviors. Accepts AdvBench (`goal`), HarmBench (`Behavior`),
    or generic (`prompt`/`text`) columns so the loader stays dataset-flexible."""
    rows: list[Behavior] = []
    with path.open(newline="", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        for idx, row in enumerate(reader):
            text = row.get("goal") or row.get("Behavior") or row.get("prompt") or row.get("text")
            if not text:
                continue
            behavior_id = row.get("BehaviorID") or row.get("id") or f"behavior_{idx}"
            rows.append(Behavior(idx=idx, text=text, behavior_id=behavior_id, row=row))
    rng = random.Random(seed)
    rng.shuffle(rows)
    return rows[:sample] if sample > 0 else rows
