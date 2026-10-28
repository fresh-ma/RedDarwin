#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Distill the CIA contextual multi-turn training_corpus from the canonical
audited run.

The genuine CIA attack payload is the auxiliary LLM's *epsilon ladder*: the
multi-turn contextual question sequence that disassembles a harmful AdvBench
goal into benign-looking escalating turns. The canonical audited result already
contains these real, run-and-judged payloads (10 goals x 2 auxiliary configs),
so we distill them rather than re-spend API calls. Payload field =
`epsilon_sequence` (also kept joined as `attack_prompt` for convenience).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

METHOD_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SRC = METHOD_DIR / "result" / "cia_context_v4flash_tokfix_20260626_audited.json"
OUT = METHOD_DIR / "data" / "training_corpus" / "sft_cia-context.json"

MIN_TURNS = 2          # a contextual multi-turn ladder needs >= 2 turns
MIN_CHARS = 15


def _is_refusal_seq(seq: list[str]) -> bool:
    if not seq:
        return True
    head = (seq[0] or "").strip().lower()
    return head.startswith((
        "i can't", "i cannot", "i'm sorry", "i am sorry", "i won't",
        "i'm unable", "i am unable", "as an ai",
    ))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(DEFAULT_SRC),
                    help="result JSON to distill the epsilon-ladder payloads from")
    args = ap.parse_args()
    SRC = Path(args.src)
    if not SRC.is_absolute():
        SRC = (Path.cwd() / SRC).resolve()
    src = json.loads(SRC.read_text(encoding="utf-8"))
    cases = src["results"]
    rows: list[dict] = []
    seen: set[str] = set()
    drop = {"refused": 0, "too_short": 0, "too_few_turns": 0, "leading_refusal": 0, "duplicate": 0}

    for c in cases:
        aux = c.get("auxiliary") or {}
        seq = [s.strip() for s in (aux.get("epsilon_sequence") or []) if isinstance(s, str) and s.strip()]
        if aux.get("refused"):
            drop["refused"] += 1
            continue
        if _is_refusal_seq(seq):
            drop["leading_refusal"] += 1
            continue
        if len(seq) < MIN_TURNS:
            drop["too_few_turns"] += 1
            continue
        joined = "\n".join(seq)
        if len(joined) < MIN_CHARS:
            drop["too_short"] += 1
            continue
        if joined in seen:
            drop["duplicate"] += 1
            continue
        seen.add(joined)
        v = c.get("verdicts") or {}
        final = (c.get("final_response") or "").strip()
        rows.append({
            "case_id": c.get("case_id"),
            "goal": c.get("goal"),
            "config_id": c.get("config_id"),
            "auxiliary_model": aux.get("model"),
            "epsilon_sequence": seq,
            "attack_prompt": joined,
            "num_turns": len(seq),
            # folded from the deprecated Harvest.json: full triple (goal -> ladder -> target response, labelled)
            "target_response": final,
            "label": "positive" if v.get("content_harmful") else "negative",
            "chatgpt_rating": v.get("chatgpt_rating"),
            "refusal_bypass": v.get("refusal_bypass"),
        })

    out = {
        "paper_id": src.get("paper_id"),
        "method": "CIA contextual multi-turn (epsilon-ladder)",
        "capability": "attacker_prompt_sft",
        "payload_field": "epsilon_sequence",
        "joined_field": "attack_prompt",
        "input_field": "goal",
        "output_field": "target_response",
        "label_field": "label",
        "schema_note": "SFT mapping: input=goal -> output=epsilon_sequence (the attack payload). target_response+label+chatgpt_rating fold in the full goal->ladder->response triple from the deprecated Harvest.json (now removed; result JSON is the source of truth).",
        "generator_model": "auxiliary LLM epsilon-ladder decomposition (deepseek-chat / qwen-2.5-72b); distilled from canonical audited run",
        "provenance": (str(SRC.relative_to(METHOD_DIR)) if SRC.is_relative_to(METHOD_DIR) else SRC.name),
        "count": len(rows),
        "distinct_outputs": len(seen),
        "quality_cleaned_dropped": drop,
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"kept": len(rows), "distinct": len(seen), "dropped": drop, "out": str(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
