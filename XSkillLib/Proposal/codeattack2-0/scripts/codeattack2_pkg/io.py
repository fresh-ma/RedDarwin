from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_behaviors(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    out = []
    for idx, row in enumerate(rows):
        out.append(
            {
                "index": row.get("Index") or row.get("index") or str(idx),
                "goal": row.get("goal") or row.get("Goal") or row.get("request") or "",
                "target": row.get("target") or row.get("Target") or "",
                "source": row.get("source") or row.get("Source") or "",
            }
        )
    return out


def summarize_success(records: list[dict[str, Any]], judge_key: str) -> dict[str, Any]:
    judgements = [record.get("judges", {}).get(judge_key, {}) for record in records]
    n_tested = len(records)
    valid_count = sum(1 for judgement in judgements if judgement.get("success") is not None)
    invalid_count = n_tested - valid_count
    success_count = sum(1 for judgement in judgements if judgement.get("success") is True)
    rate = success_count / valid_count if valid_count else 0.0
    return {
        "judge": judge_key,
        "success_count": success_count,
        "n_tested": n_tested,
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "denominator": valid_count,
        "rate": rate,
        "display": f"{success_count}/{valid_count} = {rate:.4f}",
    }

