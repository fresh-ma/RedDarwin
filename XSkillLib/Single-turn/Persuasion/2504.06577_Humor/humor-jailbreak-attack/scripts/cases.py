"""cases — harmful-request dataset loading for the humor attack.

The paper (Sec 4) evaluates on three public sets: JBB (D1, 100), AdvBench (D2, 520),
HEx-PHI (D3, 300). All three are bundled under data/; AdvBench is the default (the
repo-canonical benchmark). A goal is inserted VERBATIM into the humor template.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

METHOD_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = METHOD_DIR / "data"

DATASETS = {
    "advbench": DATA_DIR / "advbench_harmful_behaviors.json",  # D2, 520
    "jbb": DATA_DIR / "jbb_harmful_behaviors.json",            # D1, 100
    "hexphi": DATA_DIR / "hexphi_harmful_behaviors.json",      # D3, 300
}
DEFAULT_DATASET = DATASETS["advbench"]


@dataclass(frozen=True)
class Goal:
    row_id: str
    goal: str
    source_row: int


def resolve_dataset(name_or_path: str) -> Path:
    """Accept a short name ('advbench'/'jbb'/'hexphi') or a filesystem path."""
    if name_or_path in DATASETS:
        return DATASETS[name_or_path]
    return Path(name_or_path)


def _read_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8", errors="replace") as handle:
            return list(csv.DictReader(handle))
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []
    if text.startswith("["):
        return [row for row in json.loads(text) if isinstance(row, dict)]
    rows = []
    for line in text.splitlines():
        if line.strip():
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _first_text(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def load_goals(path: Path) -> list[Goal]:
    goals = []
    for idx, row in enumerate(_read_rows(path), start=1):
        text = _first_text(row, ("goal", "Goal", "behavior", "Behavior", "query", "question", "request"))
        if not text:
            continue
        goals.append(Goal(row_id=str(row.get("id") or idx), goal=text, source_row=idx))
    return goals
