#!/usr/bin/env python3
"""Dataset loading for PAP — harmful-behavior cases from CSV/JSON/JSONL.

`read_dataset` accepts the official AdvBench harmful-behaviors CSV (default), or
any goal/prompt/behavior-keyed JSON/JSONL, normalizing column names so raw
un-annotated datasets also work. Each row becomes `{id, goal, category}`.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from models import DATA_DIR

DEFAULT_DATASET = DATA_DIR / "advbench_harmful_behaviors.csv"


def read_dataset(path: str | Path) -> list[dict[str, Any]]:
    """Load harmful behaviors from CSV/JSON/JSONL."""
    path = Path(path)
    if path.suffix == ".csv":
        with path.open(newline="", encoding="utf-8", errors="replace") as fh:
            rows = list(csv.DictReader(fh))
    elif path.suffix == ".jsonl":
        rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    elif path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data if isinstance(data, list) else data.get("items") or data.get("rows") or []
    else:
        raise SystemExit(f"unsupported dataset format: {path.suffix}")
    out = []
    for i, r in enumerate(rows):
        goal = r.get("goal") or r.get("prompt") or r.get("behavior") or r.get("query") or r.get("text")
        if goal is None:
            continue
        out.append({
            "id": str(r.get("id", i)),
            "goal": str(goal).strip(),
            "category": r.get("category") or "unknown",
        })
    return out
