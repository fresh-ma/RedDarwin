#!/usr/bin/env python3
"""Generate a real multi-turn training corpus for the Crescendo unit.

Thin driver over the paper-local Crescendo Code (``attack.py``). It reuses the
REAL escalation loop (``run_case``), the verbatim PyRIT prompts, and the dual
judges — nothing is reimplemented here. For every seed goal it runs the genuine
attacker-LLM-driven Crescendo attack and keeps, as the payload, the multi-turn
ESCALATION CONVERSATION: the ordered sequence of attacker user-turns that were
actually sent and survived backtracking (the "foot-in-the-door" path), plus the
full alternating transcript.

LLM-driven: yes. The attacker LLM emits each escalating turn; target + two
judges run per turn. Goals are run concurrently (ThreadPoolExecutor); within a
goal the Crescendo loop is inherently sequential. Per-call timeout 60s,
max_retries=1. If the primary attacker yields an empty/refused conversation we
retry the whole goal with the weakly-aligned fallback attacker
(api:gryphe/mythomax-l2-13b); if still empty we DROP the goal.
"""
from __future__ import annotations

import argparse
import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openai import OpenAI

import attack  # paper-local Crescendo Code (same scripts/ dir)

METHOD_ID = "crescendo"
METHOD_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = METHOD_ROOT / "data" / "training_corpus" / f"sft_{METHOD_ID}.json"

PRIMARY_ATTACKER = attack.default_role_model()  # local ollama:uncensored, else api:deepseek/deepseek-v4-flash
FALLBACK_ATTACKER = "api:gryphe/mythomax-l2-13b"  # weakly-aligned refusal fallback
TARGET = "api:deepseek/deepseek-v4-flash"
JUDGE = "api:deepseek/deepseek-v4-flash"

PAYLOAD_FIELD = "conversation"  # the escalating user-turn sequence (the payload)
MIN_CHARS = 15


def base_args() -> argparse.Namespace:
    """PyRIT Crescendo defaults; per-call timeout 60s (recipe)."""
    return argparse.Namespace(
        attacker=PRIMARY_ATTACKER,
        target=TARGET,
        judge_model=JUDGE,
        max_turns=5,
        max_backtracks=attack.DEFAULT_MAX_BACKTRACKS,
        json_retries=2,
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        target_temperature=0.0,
        attacker_temperature=0.7,
        target_max_tokens=1024,
        attacker_max_tokens=1024,
        judge_max_tokens=1024,
        request_timeout=60.0,
        request_delay=0.0,
        wiring_check=False,
        seed=20260610,
    )


def build_client(args: argparse.Namespace) -> OpenAI:
    import os

    attack.load_env_from_nearest(attack.PAPER_ROOT)
    api_key = os.environ[args.api_key_env]
    # Per-call timeout 60s, max_retries=1 (recipe).
    return OpenAI(base_url=args.base_url, api_key=api_key, timeout=args.request_timeout, max_retries=1)


def extract_conversation(case: dict) -> tuple[list[str], list[dict]]:
    """Pull the surviving escalation path: user-turns + alternating transcript."""
    user_turns: list[str] = []
    messages: list[dict] = []
    for t in case.get("turns", []):
        if t.get("action") != "scored":
            continue  # backtracked / parse-failed turns never stuck
        q = (t.get("attacker_question") or "").strip()
        if not q:
            continue
        user_turns.append(q)
        messages.append({"role": "user", "content": q})
        messages.append({"role": "assistant", "content": t.get("target_output_text", "")})
    return user_turns, messages


def gen_for_goal(row: dict, client: OpenAI, prompts: dict) -> dict | None:
    """Run genuine Crescendo for one goal; fall back to weak attacker if empty."""
    for attacker in (PRIMARY_ATTACKER, FALLBACK_ATTACKER):
        args = base_args()
        args.attacker = attacker
        try:
            case = attack.run_case(row, args, client, client, prompts)
        except Exception:
            continue
        user_turns, messages = extract_conversation(case)
        if user_turns:
            return {
                "id": row["id"],
                "category": row.get("category", ""),
                "source_row": row.get("source_row"),
                "goal": row["goal"],
                PAYLOAD_FIELD: user_turns,
                "messages": messages,
                "executed_turns": case.get("executed_turns"),
                "backtrack_count": case.get("backtrack_count"),
                "outcome": case.get("outcome"),
                "refusal_bypass": case.get("refusal_bypass"),
                "content_harmful": case.get("content_harmful"),
                "final_objective_normalized": case.get("final_objective_normalized"),
                "attacker_model": attacker,
                "target_model": TARGET,
                "judge_model": JUDGE,
            }
    return None  # both attempts empty/refused -> drop


def quality_filter(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    kept: list[dict] = []
    dropped: list[dict] = []
    seen: set[str] = set()
    for r in rows:
        conv = r[PAYLOAD_FIELD]
        joined = "\n".join(conv).strip()
        reason = None
        if not conv:
            reason = "empty"
        elif len(joined) < MIN_CHARS:
            reason = "too_short"
        elif len(set(c.strip().lower() for c in conv)) == 1 and len(conv) > 1:
            reason = "degenerate_echo"
        elif any(c.strip().lower() == r["goal"].strip().lower() for c in conv) and len(conv) == 1:
            reason = "degenerate_echo_goal"
        else:
            key = joined.lower()
            if key in seen:
                reason = "duplicate"
            else:
                seen.add(key)
        if reason:
            dropped.append({"id": r["id"], "goal": r["goal"], "reason": reason})
        else:
            kept.append(r)
    return kept, dropped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="probe: cap number of goals")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    rows, source = attack.read_goals(str(attack.DEFAULT_GOALS), smoke_only=False)
    if args.limit:
        rows = rows[: args.limit]
    attempted = len(rows)

    obj_system, lo, hi = attack.render_objective_scorer_system_prompt()
    prompts = {
        "objective_system": obj_system,
        "lo": lo,
        "hi": hi,
        "refusal_system": attack.refusal_scorer_system_prompt(),
    }
    client = build_client(base_args())

    raw: list[dict] = []
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(gen_for_goal, row, client, prompts): row for row in rows}
        for fut in as_completed(futs):
            res = fut.result()
            if res is not None:
                with lock:
                    raw.append(res)

    raw.sort(key=lambda r: r.get("source_row") or 0)
    kept, dropped = quality_filter(raw)

    leading_refusal = 0  # parse-failed/refused attacker turns never become scored turns

    out = {
        "schema_version": "training_corpus.v1",
        "paper_id": attack.PAPER_ID,
        "method": METHOD_ID,
        "payload_field": PAYLOAD_FIELD,
        "payload_semantics": "multi-turn Crescendo escalation: ordered sequence of attacker user-turns (foot-in-the-door) that survived backtracking; full alternating transcript in `messages`.",
        "generator": "crescendo/scripts/gen_training_corpus.py (reuses attack.py run_case + verbatim PyRIT prompts/judges)",
        "dataset": source,
        "attacker_primary": PRIMARY_ATTACKER,
        "attacker_fallback": FALLBACK_ATTACKER,
        "target_model": TARGET,
        "judge_model": JUDGE,
        "seed": base_args().seed,
        "attempted": attempted,
        "kept": len(kept),
        "dropped": len(dropped),
        "leading_refusal_dropped": leading_refusal,
        "drop_detail": dropped,
        "rows": kept,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"attempted={attempted} kept={len(kept)} dropped={len(dropped)} -> {OUT_PATH}")


if __name__ == "__main__":
    main()
