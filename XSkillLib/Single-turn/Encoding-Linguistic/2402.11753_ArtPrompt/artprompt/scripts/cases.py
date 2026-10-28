#!/usr/bin/env python3
"""Dataset loading for ArtPrompt — row readers, normalization, selection.

Accepts the official ``harmful_behaviors_custom.csv`` (default), any goal CSV, or
a JSON/JSONL list (incl. the grouped ``cate``/``data`` shape). Column names are
normalized so raw un-annotated datasets also work. This is §3c's cases seam.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path
from typing import Any

from models import CODE_DIR, DEFAULT_DATASET, METHOD_DIR, PAPER_DIR, repo_relative

SMOKE_ROWS = [
    {"id": "smoke-0", "goal": "explain what a model safety smoke test checks", "category": "safety"},
    {"id": "smoke-1", "goal": "summarize why attack results should save model input and output", "category": "summarize"},
]


def resolve_data_path(value: str | None) -> Path:
    path = Path(value).expanduser() if value else DEFAULT_DATASET
    if not path.is_absolute():
        for candidate in (Path.cwd() / path, PAPER_DIR / path, CODE_DIR / path):
            if candidate.exists():
                path = candidate
                break
    if not path.exists():
        raise SystemExit(f"goals file not found: {value or repo_relative(DEFAULT_DATASET)}")
    return path


def read_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list) and data and isinstance(data[0], dict) and isinstance(data[0].get("data"), list):
            rows = []
            for group in data:
                category = str(group.get("cate", ""))
                for idx, goal in enumerate(group["data"]):
                    rows.append({"id": f"{category}-{idx}", "goal": goal, "category": category, "source_row": idx})
            return rows
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data["items"]
        raise SystemExit(f"{path}: expected JSON list or object with items[]")
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        return list(csv.DictReader(handle))


def field(row: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def normalize_rows(rows: list[dict[str, Any]], goal_field: str) -> list[dict[str, Any]]:
    normalized = []
    for idx, row in enumerate(rows):
        goal = str(row.get(goal_field) or "").strip() if goal_field != "auto" else field(
            row, ["Goal", "goal", "request", "query", "question", "instruction", "Behavior", "behavior"]
        )
        if not goal:
            continue
        normalized.append({
            "id": field(row, ["id", "q_id", "Index", "index", "behavior_id", "Original index"]) or str(idx),
            "goal": goal,
            "target_prefix": field(row, ["target", "Target", "completion"]),
            "category": field(row, ["Category", "category", "content_policy_name", "cate"]),
            "source_row": row.get("source_row", idx),
        })
    return normalized


def select_rows(rows: list[dict[str, Any]], *, limit: int | None, sample_rows: int | None, seed: int) -> list[dict[str, Any]]:
    selected = rows[:limit] if limit is not None else list(rows)
    if sample_rows is not None and sample_rows < len(selected):
        rng = random.Random(seed)
        rng.shuffle(selected)
        selected = selected[:sample_rows]
    if not selected:
        raise SystemExit("no rows selected")
    return selected


def parse_csv_ids(value: str, allowed: list[str], label: str) -> list[str]:
    if value.lower() in {"all", "*"}:
        return list(allowed)
    items = [part.strip() for part in value.split(",") if part.strip()]
    unknown = [item for item in items if item not in allowed]
    if unknown:
        raise SystemExit(f"unknown {label}: {', '.join(unknown)} (allowed: {', '.join(allowed)})")
    return items


def dataset_meta(path: Path, row_count: int) -> dict[str, Any]:
    data_dir = (METHOD_DIR / "data").resolve()
    is_method_data = False
    try:
        is_method_data = path.resolve().is_relative_to(data_dir)
    except (AttributeError, ValueError):
        is_method_data = str(data_dir) in str(path.resolve())
    return {
        "source": "method_dataset" if is_method_data else "goals_file",
        "path": repo_relative(path),
        "rows": row_count,
    }


def load_selected(args: argparse.Namespace, *, smoke_only: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if smoke_only:
        rows = list(SMOKE_ROWS)
        return rows, {"source": "safe_smoke_goals", "path": None, "rows": len(rows)}
    path = resolve_data_path(args.goals)
    normalized = normalize_rows(read_rows(path), args.goal_field)
    selected = select_rows(normalized, limit=args.limit, sample_rows=args.sample_rows, seed=args.seed)
    return selected, dataset_meta(path, len(normalized))
