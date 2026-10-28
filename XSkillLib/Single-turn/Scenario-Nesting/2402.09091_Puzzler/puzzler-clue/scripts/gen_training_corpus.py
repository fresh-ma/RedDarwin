#!/usr/bin/env python3
"""Generate a real training_corpus for Puzzler (arXiv:2402.09091).

Thin wrapper: IMPORTS attack.py and reuses its genuine generation function
(`run_puzzler`, Phases 1-2) for every harmful goal in the FULL AdvBench dataset.
The corpus output per goal is the real generated implicit-clue payload (the
assembled indirect-jailbreak `attack_prompt` built from the offensive measures),
NOT a full target attack -- the target is never queried here.

Each generated row is quality-filtered before it is kept: refusal / empty /
too-short / degenerate-echo / duplicate are dropped (whole serialized output is
scanned for refusal markers). Output: data/training_corpus/sft_puzzler.json.

Run: $PY gen_training_corpus.py [--workers 20] [--limit N]   # $PY = shared XSkillForge/.venv interpreter
"""

from __future__ import annotations

import argparse
import json
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import attack  # reuse the real Puzzler pipeline (no reimplementation)

METHOD_DIR = attack.METHOD_DIR
FULL_DATASET = METHOD_DIR / "data" / "harmful_behaviors.csv"
OUT_PATH = METHOD_DIR / "data" / "training_corpus" / "sft_puzzler.json"

GENERATOR_MODEL = "deepseek/deepseek-v4-flash"  # non-reasoning; documented attacker substitute
SEED = 20260630
MIN_OUTPUT_CHARS = 15

# Refusal markers scanned across the WHOLE serialized output. Deliberately
# specific so the constant "Step 1, I will" continuation stem is NOT flagged.
REFUSAL_MARKERS = (
    "i cannot", "i can't", "i can not", "i'm sorry", "i am sorry", "i apologize",
    "i apologise", "as an ai", "i'm unable", "i am unable", "unable to provide",
    "unable to assist", "unable to help", "cannot assist", "can't assist",
    "cannot provide", "can't provide", "cannot help", "can't help", "i won't",
    "i will not", "i'm not able", "i am not able", "i must decline", "i refuse",
    "i'm really sorry", "against my guidelines", "against my programming",
    "not able to assist", "i do not feel comfortable", "i don't feel comfortable",
)


def has_refusal(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in REFUSAL_MARKERS)


def is_degenerate_echo(payload: str, goal: str, malicious_content: str) -> bool:
    """Output is just an echo of the input goal/malicious-content with no real content."""
    body = payload.strip().lower()
    g = goal.strip().lower()
    mc = malicious_content.strip().lower()
    return body == g or body == mc


def generate_row(idx: int, row: dict[str, str], *, max_defensive: int,
                 temperature: float) -> dict[str, Any]:
    goal = row["goal"]
    try:
        puzzle = attack.run_puzzler(
            goal, GENERATOR_MODEL, temperature=temperature,
            max_defensive=max_defensive, request_delay=0.0,
        )
    except Exception as exc:  # generation failure -> dropped downstream
        return {"idx": idx, "goal": goal, "error": f"{type(exc).__name__}: {exc}"[:300]}

    offensive = puzzle["offensive_measures"]
    payload = puzzle["attack_prompt"]
    # generated content = the offensive measures (strip the shared assembly chrome)
    generated = "\n".join(offensive).strip()
    serialized = json.dumps({"offensive": offensive, "payload": payload}, ensure_ascii=False)

    return {
        "idx": idx,
        "goal": goal,
        "malicious_content": puzzle["malicious_content"],
        "offensive_measures": offensive,
        "clue_payload": payload,
        "generated": generated,
        "serialized": serialized,
        "n_defensive": len(puzzle["defensive_measures"]),
        "n_kept": len(puzzle["kept_defensive_measures"]),
        "n_offensive": len(offensive),
    }


def quality_drop_reason(rec: dict[str, Any], seen: set[str]) -> str | None:
    if "error" in rec:
        return "generation-error"
    if not rec["offensive_measures"]:
        return "empty"
    generated = rec["generated"]
    if len(generated.strip()) < MIN_OUTPUT_CHARS:
        return "too-short"
    if has_refusal(rec["serialized"]):
        return "refusal"
    if is_degenerate_echo(generated, rec["goal"], rec["malicious_content"]):
        return "degenerate-echo"
    key = rec["clue_payload"].strip()
    if key in seen:
        return "duplicate"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Puzzler training_corpus")
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--limit", type=int, default=0, help="0 = full dataset")
    parser.add_argument("--max-defensive", type=int, default=12)
    parser.add_argument("--temperature", type=float, default=1.0)
    args = parser.parse_args()

    random.seed(SEED)
    rows = attack.load_rows(FULL_DATASET, args.limit)
    total_attempted = len(rows)
    print(f"generating for {total_attempted} goals with {GENERATOR_MODEL} "
          f"({args.workers} workers, seed {SEED})")

    records: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(generate_row, idx, row,
                        max_defensive=args.max_defensive, temperature=args.temperature): idx
            for idx, row in enumerate(rows)
        }
        done = 0
        for future in as_completed(futures):
            idx = futures[future]
            records[idx] = future.result()
            done += 1
            if done % 25 == 0 or done == total_attempted:
                print(f"  {done}/{total_attempted} generated")

    kept_rows: list[dict[str, Any]] = []
    dropped: dict[str, int] = {}
    dropped_examples: dict[str, dict[str, str]] = {}
    seen: set[str] = set()
    for idx in range(total_attempted):
        rec = records[idx]
        reason = quality_drop_reason(rec, seen)
        if reason is not None:
            dropped[reason] = dropped.get(reason, 0) + 1
            dropped_examples.setdefault(reason, {
                "goal": rec.get("goal", ""),
                "sample": (rec.get("generated") or rec.get("error", ""))[:200],
            })
            continue
        seen.add(rec["clue_payload"].strip())
        kept_rows.append({
            "goal": rec["goal"],
            "malicious_content": rec["malicious_content"],
            "output": rec["clue_payload"],
            "offensive_measures": rec["offensive_measures"],
            "n_defensive": rec["n_defensive"],
            "n_kept": rec["n_kept"],
            "n_offensive": rec["n_offensive"],
        })

    distinct_outputs = len({r["output"].strip() for r in kept_rows})
    doc = {
        "paper_id": attack.PAPER_ID,
        "method": attack.METHOD_ID,
        "generator_model": GENERATOR_MODEL,
        "count": len(kept_rows),
        "dropped": dropped,
        "total_attempted": total_attempted,
        "distinct_outputs": distinct_outputs,
        "seed": SEED,
        "schema": "{goal, malicious_content, output (implicit-clue payload), offensive_measures, n_defensive, n_kept, n_offensive}",
        "training_use": "attacker_prompt_sft: input=harmful goal, output=Puzzler implicit-clue jailbreak payload (assembled offensive measures)",
        "rows": kept_rows,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({
        "wrote": str(OUT_PATH),
        "total_attempted": total_attempted,
        "kept": len(kept_rows),
        "dropped": dropped,
        "distinct_outputs": distinct_outputs,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
