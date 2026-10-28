"""cases.py — dataset DTO + loader + result IO + dual-metric ASR summariser."""
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
    category: str = ""
    source_row: int = 0


def load_behaviors(path: Path) -> list[Behavior]:
    """Load AdvBench-style CSV (column-name tolerant). Count with csv module, not wc -l."""
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        rows = list(csv.DictReader(handle))
    out: list[Behavior] = []
    for idx, row in enumerate(rows):
        goal = ""
        for key in ("goal", "Goal", "Behavior", "behavior", "query", "question", "request"):
            goal = (row.get(key) or "").strip()
            if goal:
                break
        if not goal:
            continue
        out.append(
            Behavior(
                index=str(row.get("id") or row.get("Index") or row.get("Original index") or idx),
                goal=goal,
                target=(row.get("target") or row.get("Target") or "").strip(),
                category=row.get("category") or row.get("Category") or "",
                source_row=idx,
            )
        )
    if not out:
        raise SystemExit(f"no goals loaded from {path}")
    return out


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_dual(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Recompute dual-metric ASR from raw per-case judge scores (counts, not bare ratios)."""
    n = len(records)
    ok = [r for r in records if r.get("status") == "ok"]
    denom = len(ok)

    def _count(key: str) -> int:
        return sum(1 for r in ok if (r.get("judge") or {}).get(key) is True)

    rb = _count("refusal_bypass")
    ch = _count("content_harmful")
    matching = _count("matching")
    paper_asr = _count("paper_asr_refusal_vocab")

    return {
        "case_count": n,
        "ok_count": denom,
        "provider_errors": n - denom,
        "metrics": {
            "refusal_bypass": {
                "success_count": rb,
                "denominator": denom,
                "rate": round(rb / denom, 4) if denom else 0.0,
                "display": f"{rb}/{denom} = {rb / denom if denom else 0.0:.4f}",
            },
            "content_harmful": {
                "success_count": ch,
                "denominator": denom,
                "rate": round(ch / denom, 4) if denom else 0.0,
                "display": f"{ch}/{denom} = {ch / denom if denom else 0.0:.4f}",
            },
            "matching": {
                "success_count": matching,
                "denominator": denom,
                "rate": round(matching / denom, 4) if denom else 0.0,
                "display": f"{matching}/{denom} = {matching / denom if denom else 0.0:.4f}",
            },
            "paper_asr_refusal_vocab": {
                "success_count": paper_asr,
                "denominator": denom,
                "rate": round(paper_asr / denom, 4) if denom else 0.0,
                "display": f"{paper_asr}/{denom} = {paper_asr / denom if denom else 0.0:.4f}",
            },
        },
    }
