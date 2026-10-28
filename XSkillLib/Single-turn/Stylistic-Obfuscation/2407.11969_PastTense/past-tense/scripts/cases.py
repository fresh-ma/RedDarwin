"""cases.py — dataset DTO + loader + result IO helpers + ASR summariser."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Behavior:
    index: str
    goal: str
    target: str = ""
    behavior: str = ""
    category: str = ""
    source: str = ""


def load_behaviors(path: Path) -> list[Behavior]:
    """Load harmful behaviours from a JBB / AdvBench style CSV (column-name tolerant)."""
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    out: list[Behavior] = []
    for idx, row in enumerate(rows):
        goal = row.get("Goal") or row.get("goal") or row.get("request") or row.get("behavior") or ""
        out.append(
            Behavior(
                index=str(row.get("Index") or idx),
                goal=goal,
                target=row.get("Target") or row.get("target") or "",
                behavior=row.get("Behavior") or "",
                category=row.get("Category") or row.get("category") or "",
                source=row.get("Source") or row.get("source") or "",
            )
        )
    return out


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def summarize_success(records: list[dict[str, Any]], judge_key: str) -> dict[str, Any]:
    """Recompute an ASR from raw per-record judgements as an explicit numerator/denominator.

    Denominator = records with a valid (non-None) judgement, following the official ASR accounting
    (parse-error / empty-output cases are excluded, never silently counted as success or failure).
    """
    n_tested = len(records)
    judgements = [record.get("judges", {}).get(judge_key, {}) for record in records]
    valid = sum(1 for j in judgements if j.get("success") is not None)
    success = sum(1 for j in judgements if j.get("success") is True)
    invalid = n_tested - valid
    rate = success / valid if valid else 0.0
    return {
        "judge": judge_key,
        "success_count": success,
        "n_tested": n_tested,
        "valid_count": valid,
        "invalid_count": invalid,
        "denominator": valid,
        "rate": rate,
        "display": f"{success}/{valid} = {rate:.4f}",
    }
