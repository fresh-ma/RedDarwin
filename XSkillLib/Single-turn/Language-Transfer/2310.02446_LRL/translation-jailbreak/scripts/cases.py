#!/usr/bin/env python3
"""Dataset loading for the low-resource-language jailbreak.

`load_goals` reads the harmful-behaviour goals (csv/json/jsonl) into a uniform list of
`{id, goal, source_row}` rows, with optional seeded sampling. `SMOKE_GOALS` are safe
built-in goals used only for smoke/wiring checks.
"""

from __future__ import annotations

import json
import random
from typing import Any

from models import display_path, read_csv_rows, resolve_path


SMOKE_GOALS = [
    {"id": "smoke-0", "goal": "explain what multilingual red-team testing checks", "source_row": 0},
    {"id": "smoke-1", "goal": "summarize why back-translation is useful for review", "source_row": 1},
]


def load_goals(path_value: str | None, sample_rows: int | None, seed: int, smoke_only: bool = False) -> tuple[list[dict[str, Any]], str]:
    path = resolve_path(path_value)
    if path and path.exists():
        rows: list[dict[str, Any]] = []
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            items = data if isinstance(data, list) else data.get("goals", data.get("questions", []))
            for idx, item in enumerate(items):
                text = str(item.get("goal") or item.get("text") or item.get("question") or item.get("Behavior") or item).strip()
                if text:
                    rows.append({"id": item.get("id") or item.get("index") or str(idx), "goal": text, "source_row": idx})
        elif path.suffix.lower() == ".jsonl":
            for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
                if not line.strip():
                    continue
                item = json.loads(line)
                text = str(item.get("goal") or item.get("text") or item.get("question") or item.get("Behavior") or "").strip()
                if text:
                    rows.append({"id": item.get("id") or item.get("index") or str(idx), "goal": text, "source_row": idx})
        else:
            for idx, row in enumerate(read_csv_rows(path)):
                text = ""
                for key in ("Goal", "goal", "Behavior", "behavior", "text", "question", "query", "request"):
                    text = (row.get(key) or "").strip()
                    if text:
                        break
                if text:
                    rows.append({"id": row.get("id") or row.get("Index") or row.get("index") or row.get("behavior_id") or str(idx), "goal": text, "source_row": idx})
        source = display_path(path)
    elif smoke_only:
        rows = list(SMOKE_GOALS)
        source = "built_in_safe_goals"
    else:
        raise SystemExit("--goals is required for Code runs; built-in safe goals are smoke-only")
    if sample_rows is not None:
        rows = list(rows)
        random.Random(seed).shuffle(rows)
        rows = rows[:sample_rows]
    if not rows:
        raise SystemExit("no goals loaded")
    return rows, source
