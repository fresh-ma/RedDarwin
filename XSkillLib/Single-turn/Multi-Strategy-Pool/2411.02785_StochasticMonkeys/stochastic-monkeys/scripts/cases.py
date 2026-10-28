"""cases.py — SORRY-Bench dataset loader for Stochastic Monkeys.

The paper's safety set D is SORRY-Bench (202406 release): 450 unsafe instructions across 45 fine-
grained categories (Xie et al., 2024). Loader reads the bundled CSV with the csv module (never
wc -l). Each row: {category, prompt, target}. The attack only needs `prompt` (the original x); the
judge also uses `prompt` as the request-of-record. Raw un-annotated goal lists (a single `prompt`/
`goal` column) also load, so the pipeline is dataset-flexible.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATASET = Path(__file__).resolve().parent.parent / "data" / "sorry_bench_202406.csv"

_PROMPT_KEYS = ("prompt", "goal", "behavior", "instruction", "query", "request")


@dataclass(frozen=True)
class Case:
    index: int
    prompt: str          # the original (un-augmented) harmful request x
    category: str = ""
    target: str = ""


def _pick_prompt_key(fieldnames) -> str:
    for key in _PROMPT_KEYS:
        if fieldnames and key in fieldnames:
            return key
    raise SystemExit(f"dataset needs one of {_PROMPT_KEYS}; got columns {fieldnames}")


def load_cases(path: str | Path = DEFAULT_DATASET, limit: int | None = None) -> list[Case]:
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


if __name__ == "__main__":
    cs = load_cases()
    print(f"loaded {len(cs)} cases from {DEFAULT_DATASET}")
    print("example:", cs[0])
