"""cases.py — dataset loader for Stochastic Monkeys 2.0."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Case:
    index: int
    prompt: str          # the original (un-augmented) harmful request x
    category: str = ""
    target: str = ""


_PROMPT_KEYS = ("request", "prompt", "goal", "behavior", "instruction", "query")


def _pick_prompt_key(fieldnames) -> str:
    for key in _PROMPT_KEYS:
        if fieldnames and key in fieldnames:
            return key
    raise SystemExit(f"dataset needs one of {_PROMPT_KEYS}; got columns {fieldnames}")


def load_cases(path: str | Path, limit: int | None = None) -> list[Case]:
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"dataset not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        prompt_key = _pick_prompt_key(reader.fieldnames)
        cases: list[Case] = []
        for i, row in enumerate(reader):
            prompt = (row.get(prompt_key) or "").strip()
            if not prompt:
                continue
            cases.append(Case(
                index=i,
                prompt=prompt,
                category=str(row.get("category", "")),
                target=str(row.get("target", "")),
            ))
    if limit is not None:
        cases = cases[:limit]
    return cases
