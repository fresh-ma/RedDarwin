#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["openai>=1.0"]
# ///
"""Generate a CoA attacker-chain SFT training corpus over the FULL PAIR-50 goal set.

Thin wrapper: imports the real CoA chain-generation step from attack.py
(chain_generation_messages -> call_chat[role=attacker] -> parse_chain) and reuses
it per goal. The genuine generated payload (the multi-turn escalating attack chain)
is the corpus output. Quality-filters every row (drop refusal/empty/short/degenerate);
drop, don't keep.

Generator = api:deepseek/deepseek-v4-flash (cheap, non-reasoning; content non-null).
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import attack  # noqa: E402  (real CoA generation logic, reused verbatim)

METHOD_DIR = SCRIPT_DIR.parent
GOALS_CSV = METHOD_DIR / "data" / "harmful_behaviors_custom.csv"
OUT_PATH = METHOD_DIR / "data" / "training_corpus" / "sft_coa.json"

REFUSAL_HINTS = attack.REFUSAL_HINTS
MIN_LEN = 15


def is_refusal(text: str) -> bool:
    lowered = (text or "").lower()
    return any(h in lowered for h in REFUSAL_HINTS)


def quality_check(goal: str, rounds: list[str], raw: str, max_rounds: int) -> str | None:
    """Return a drop-reason string, or None if the row is clean."""
    if not rounds:
        return "empty_chain"
    if all(is_refusal(r) or not r.strip() for r in rounds):
        return "all_refusal_or_empty_rounds"
    joined = " ".join(rounds).strip()
    if len(joined) < MIN_LEN:
        return "too_short"
    distinct = {r.strip().lower() for r in rounds if r.strip()}
    if max_rounds >= 2 and len(distinct) < 2:
        return "degenerate_no_escalation"
    if all(r.strip().lower() == goal.strip().lower() for r in rounds):
        return "degenerate_goal_echo"
    return None


def gen_one(row: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    goal = row["goal"]
    messages = attack.chain_generation_messages(goal, args)
    raw, status = attack.call_chat(messages, args.attacker, args, role="attacker")
    if status != "ok":
        return {"row": row, "status": status, "drop": status, "raw": raw[:300]}
    try:
        rounds = attack.parse_chain(raw, args.max_rounds)
    except Exception as exc:  # parse failure = attacker did not emit a usable chain
        return {"row": row, "status": "ok", "drop": f"parse_error:{type(exc).__name__}", "raw": raw[:300]}
    drop = quality_check(goal, rounds, raw, args.max_rounds)
    return {"row": row, "status": "ok", "drop": drop, "rounds": rounds, "raw": raw}


def main() -> None:
    parser = argparse.ArgumentParser(description="CoA attacker-chain SFT corpus generator.")
    parser.add_argument("--goals", default=str(GOALS_CSV))
    parser.add_argument("--attacker", default=None,
                        help="chain generator; default: local ollama:uncensored, else api:deepseek/deepseek-v4-flash")
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--seed", type=int, default=20260608)
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    parser.add_argument("--api-key-env", default="OPENROUTER_API_KEY")
    parser.add_argument("--attacker-temperature", type=float, default=0.8)
    parser.add_argument("--attacker-max-tokens", type=int, default=1024)
    parser.add_argument("--out", default=str(OUT_PATH))
    args = parser.parse_args()

    if args.attacker is None:
        args.attacker = attack.default_attacker_model()

    attack.load_env_file(attack.PROJECT_ENV)
    rows, source = attack.read_rows(args.goals, smoke_only=False)
    started = time.time()

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    lock = threading.Lock()
    done = 0

    def worker(row: dict[str, Any]) -> dict[str, Any]:
        return gen_one(row, args)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(worker, row): row for row in rows}
        for fut in as_completed(futures):
            res = fut.result()
            row = res["row"]
            with lock:
                done += 1
                if done % 10 == 0:
                    print(f"  [{done}/{len(rows)}] kept={len(kept)} dropped={len(dropped)}", flush=True)
            if res.get("drop"):
                dropped.append({"id": row["id"], "goal": row["goal"], "reason": res["drop"],
                                "sample": (res.get("raw") or "")[:200]})
                continue
            rounds = res["rounds"]
            output = "\n".join(f"Round {i}: {p}" for i, p in enumerate(rounds, 1))
            kept.append({
                "instruction": row["goal"],
                "output": output,
                "rounds": rounds,
                "goal_id": row["id"],
                "category": row.get("category", ""),
                "source_row": row.get("source_row"),
                "max_rounds": args.max_rounds,
                "generator_model": args.attacker,
                "label": "positive",
            })

    kept.sort(key=lambda r: int(r["source_row"]) if str(r["source_row"]).isdigit() else 0)
    distinct_outputs = len({r["output"] for r in kept})

    payload = {
        "paper_id": attack.PAPER_ID,
        "method": attack.METHOD_ID,
        "artifact": "attacker_chain_sft",
        "schema": "coa_training_corpus.v1",
        "description": (
            "CoA (Chain-of-Attack) multi-turn semantic jailbreak payloads. Each row: an "
            "AdvBench/PAIR-50 harmful goal (instruction) -> the genuine CoA escalating "
            "attack chain (output) generated by the real attacker step in coa/scripts/attack.py "
            "(chain_generation_messages -> parse_chain) with a DeepSeek generator. The chain "
            "starts broadly-related/safe and becomes more semantically related each round. "
            "Trains an attacker that turns a raw harmful goal into a multi-turn CoA attack chain."
        ),
        "generator_model": args.attacker,
        "chain_logic": "coa/scripts/attack.py (chain_generation_messages + parse_chain, verbatim)",
        "dataset": source,
        "max_rounds": args.max_rounds,
        "seed": args.seed,
        "count": len(kept),
        "dropped": len(dropped),
        "total_attempted": len(rows),
        "distinct_outputs": distinct_outputs,
        "drop_reasons": _reason_counts(dropped),
        "seconds": round(time.time() - started, 3),
        "rows": kept,
        "dropped_rows": dropped,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nWrote {out}")
    print(f"  attempted={len(rows)} kept={len(kept)} dropped={len(dropped)} distinct={distinct_outputs}")
    print(f"  drop_reasons={payload['drop_reasons']}")


def _reason_counts(dropped: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for d in dropped:
        counts[d["reason"]] = counts.get(d["reason"], 0) + 1
    return counts


if __name__ == "__main__":
    main()
