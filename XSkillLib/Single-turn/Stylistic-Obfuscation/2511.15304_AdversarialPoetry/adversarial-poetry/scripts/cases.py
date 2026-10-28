#!/usr/bin/env python3
"""Dataset loading for Adversarial Poetry — the row DTO + CSV/JSON/JSONL loaders.

`read_rows` accepts the AILuminate demo set (default; prompt_text / hazard /
persona columns) as well as advbench/jbb-style `goal` datasets. Column names are
normalized so raw un-annotated datasets also work.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path


# ---------------------------------------------------------------------------
# dataset-agnostic loader (copy-reference: util/dataset_read_rows)
# AILuminate uses prompt_text / hazard / persona columns; advbench/jbb use goal.
# ---------------------------------------------------------------------------
def read_rows(path: str | Path) -> list[dict]:
    path = Path(path)
    if path.suffix == ".jsonl":
        rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    elif path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data if isinstance(data, list) else (data.get("items") or data.get("rows"))
        if not isinstance(rows, list):
            raise SystemExit(f"{path}: expected list or object with items[]/rows[]")
    elif path.suffix == ".csv":
        with path.open(newline="", encoding="utf-8", errors="replace") as fh:
            rows = list(csv.DictReader(fh))
    else:
        raise SystemExit(f"{path}: unsupported format {path.suffix} (.json/.jsonl/.csv)")
    return [_normalize(r, i) for i, r in enumerate(rows)]


def _normalize(row: dict, idx: int) -> dict:
    goal = (row.get("prompt_text") or row.get("goal") or row.get("prompt")
            or row.get("behavior") or row.get("query") or row.get("text"))
    if goal is None:
        raise SystemExit(f"row {idx}: no prompt_text/goal/prompt/behavior/query/text column")
    cat = (row.get("hazard") or row.get("category") or row.get("domain")
           or row.get("class") or "unknown")
    rid = row.get("release_prompt_id") or row.get("id") or idx
    return {
        "id": str(rid),
        "goal": str(goal).strip(),
        "category": str(cat),
        "persona": row.get("persona", ""),
    }
