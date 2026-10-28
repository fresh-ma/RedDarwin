#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Build a RACE reasoning-task training corpus (arXiv 2502.11054).

Reuses the REAL RACE generation path from race_attack.py: for each harmful goal
the SHADOW (attacker) LLM reformulates the goal into a benign-looking academic
REASONING TASK (mathematical / commonsense / symbolic / causal) via the paper's
VERBATIM seed prompt (race_attack.SEED_SYS + race_attack.gen_seed). That reframed
reasoning question is exactly the per-turn query RACE sends to the victim; it is
the genuine per-goal payload and the corpus output — NOT a full multi-turn target
attack (no victim query, no judge scoring, no ASM loop).

SFT row = {instruction: harmful goal, output: reframed reasoning-task query}.
This trains a generator of RACE reasoning-augmented jailbreak queries.

Generator: api:deepseek/deepseek-v4-flash (primary). On a genuine refusal/empty the
shadow is re-pointed at api:gryphe/mythomax-l2-13b (non-refusing fallback); if it
still refuses, the row is DROPPED. Each model call is bounded by a 60s timeout
(ThreadPoolExecutor.result) with one fallback retry.

Quality gate: every row's GENUINE generated content (the reasoning-task query)
must pass — drop leading refusals, empties, too-short (<15), degenerate goal-echo,
and cross-corpus duplicates. Drop, don't keep; a few failures are fine.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import race_attack as R  # reuse the real RACE generation functions

UNIT = Path(__file__).resolve().parents[1]  # .../race/
GOALS_CSV = UNIT / "data" / "advbench_subset.csv"
OUT_PATH = UNIT / "data" / "training_corpus" / "sft_race.json"

MIN_LEN = 15  # too-short threshold for genuine generated content
CALL_TIMEOUT = 60  # per-model-call wall clock (seconds)


def load_goals(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            goal = (r.get("goal") or "").strip()
            if goal:
                rows.append(
                    {
                        "goal": goal,
                        "category": (r.get("category") or "").strip(),
                        "original_index": (r.get("Original index") or "").strip(),
                    }
                )
    return rows


def _bounded(fn, *a, timeout: int = CALL_TIMEOUT):
    """Run a single model call under a wall-clock timeout. Sentinel on timeout."""
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(fn, *a)
        try:
            return fut.result(timeout=timeout)
        except Exception:  # noqa: BLE001  (timeout / transient -> treat as failure)
            return "[CALL_FAILED:timeout]"


def gen_one_query(goal: str, rtype: str, primary: str, fallback: str) -> dict:
    """One real RACE reasoning-task reformulation; refusal-fallback then drop.

    Reuses race_attack.gen_seed (paper SEED_SYS prompt) with turn=1/total=1 to
    produce a single self-contained reasoning-task query that drives toward goal.
    """
    # primary generator
    R._SHADOW, R._SHADOW_FB = primary, primary  # no internal model fallback here
    q = _bounded(R.gen_seed, goal, [], rtype, 1, 1)
    if not R.is_refusal(q):
        return {"ok": True, "query": q.strip(), "generator": f"api:{primary}",
                "reasoning_type": rtype}
    # refusal/empty -> fallback model (one retry)
    R._SHADOW, R._SHADOW_FB = fallback, fallback
    q2 = _bounded(R.gen_seed, goal, [], rtype, 1, 1)
    if not R.is_refusal(q2):
        return {"ok": True, "query": q2.strip(), "generator": f"api:{fallback}",
                "reasoning_type": rtype}
    return {"ok": False, "reason": "refused_or_failed_both_models"}


def gen_payload_for_goal(goal_row: dict, primary: str, fallback: str,
                         rng_seed: int) -> dict:
    rng = random.Random(rng_seed)
    rtype = rng.choice(R.REASONING_TYPES)
    out = gen_one_query(goal_row["goal"], rtype, primary, fallback)
    if not out["ok"]:
        return {"ok": False, "reason": out["reason"], "goal": goal_row["goal"]}
    return {
        "ok": True,
        "goal": goal_row["goal"],
        "category": goal_row["category"],
        "original_index": goal_row["original_index"],
        "reasoning_type": out["reasoning_type"],
        "generator": out["generator"],
        "reasoning_task_query": out["query"],
    }


def quality_filter(rec: dict) -> tuple[bool, str]:
    """Drop leading-refusal / empty / too-short / goal-echo. Genuine content only."""
    if not rec.get("ok"):
        return False, rec.get("reason", "generation_failed")
    q = (rec.get("reasoning_task_query") or "").strip()
    if not q or q.startswith("[CALL_FAILED"):
        return False, "empty_or_failed"
    if len(q) < MIN_LEN:
        return False, "too_short"
    if R.is_refusal(q):
        return False, "leading_refusal"
    if q.strip().lower() == rec["goal"].strip().lower():
        return False, "echo_goal"
    return True, "ok"


def main() -> None:
    ap = argparse.ArgumentParser(description="RACE reasoning-task SFT corpus builder")
    ap.add_argument("--generator", default="deepseek/deepseek-v4-flash",
                    help="primary shadow/attacker model that reframes goals")
    ap.add_argument("--fallback", default="gryphe/mythomax-l2-13b",
                    help="non-refusing fallback model on refusal/empty")
    ap.add_argument("--limit", type=int, default=None, help="cap goals (default: full dataset)")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seed", type=int, default=2502)
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args()

    goals = load_goals(GOALS_CSV)
    if args.limit:
        goals = goals[: args.limit]
    total_attempted = len(goals)
    print(f"Goals (full dataset): {total_attempted} from {GOALS_CSV.name}")
    print(f"Generator: api:{args.generator} | fallback: api:{args.fallback} | workers: {args.workers}")

    t0 = time.time()
    results: list[dict] = [None] * total_attempted  # type: ignore

    def work(i_row):
        i, row = i_row
        return i, gen_payload_for_goal(row, args.generator, args.fallback,
                                       args.seed + i)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(work, (i, row)) for i, row in enumerate(goals)]
        done = 0
        for fut in as_completed(futs):
            i, rec = fut.result()
            results[i] = rec
            done += 1
            if done % 10 == 0 or done == total_attempted:
                print(f"  generated {done}/{total_attempted}")

    rows: list[dict] = []
    drops: list[dict] = []
    seen: set[str] = set()
    for rec in results:
        keep, reason = quality_filter(rec)
        if keep:
            q = rec["reasoning_task_query"]
            if q.strip().lower() in seen:
                drops.append({"goal": rec.get("goal", ""), "reason": "duplicate_query"})
                continue
            seen.add(q.strip().lower())
            rows.append({
                "instruction": rec["goal"],
                "output": rec["reasoning_task_query"],
                "reasoning_task_query": rec["reasoning_task_query"],
                "reasoning_type": rec["reasoning_type"],
                "category": rec["category"],
                "original_index": rec["original_index"],
                "generator_model": rec["generator"],
                "label": "reasoning_task_sft",
            })
        else:
            drops.append({"goal": rec.get("goal", ""), "reason": reason})

    distinct_outputs = len({r["output"] for r in rows})
    leading_refusals = sum(1 for r in rows if R.is_refusal(r["output"]))
    drop_reasons: dict[str, int] = {}
    for d in drops:
        drop_reasons[d["reason"]] = drop_reasons.get(d["reason"], 0) + 1

    corpus = {
        "paper_id": "2502.11054_reasoning-augmented-jailbreak",
        "method": "race",
        "corpus_type": "reasoning_task_sft",
        "payload_field": "reasoning_task_query",
        "description": (
            "RACE reasoning-task SFT: harmful goal -> reframed academic reasoning-task "
            "query (math/commonsense/symbolic/causal) generated by the SHADOW attacker "
            "LLM via the paper's verbatim SEED_SYS prompt (race_attack.gen_seed). The "
            "reframed query is the genuine per-turn RACE payload; no victim query / no "
            "judge / no ASM loop. Quality-filtered (leading-refusal/empty/short/echo/"
            "duplicate dropped)."
        ),
        "generator_model": f"api:{args.generator}",
        "fallback_model": f"api:{args.fallback}",
        "dataset": "RACE AdvBench subset harmful goals (advbench_subset.csv)",
        "total_attempted": total_attempted,
        "count": len(rows),
        "dropped": len(drops),
        "drop_reasons": drop_reasons,
        "distinct_outputs": distinct_outputs,
        "leading_refusals": leading_refusals,
        "seed": args.seed,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rows": rows,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(corpus, indent=2, ensure_ascii=False))

    print("\n=== RACE training-corpus summary ===")
    print(f"total_attempted : {total_attempted}")
    print(f"kept            : {len(rows)}")
    print(f"dropped         : {len(drops)} {drop_reasons}")
    print(f"distinct_outputs: {distinct_outputs}")
    print(f"leading_refusals: {leading_refusals}")
    print(f"elapsed         : {round(time.time() - t0, 1)}s -> {out_path}")


if __name__ == "__main__":
    main()
