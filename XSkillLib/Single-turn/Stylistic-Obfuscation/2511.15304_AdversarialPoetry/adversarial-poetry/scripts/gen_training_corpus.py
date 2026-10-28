#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["openai>=1.40"]
# ///
"""Build an Adversarial-Poetry training corpus (arXiv 2511.15304).

Reuses the REAL poetic-transformation path from attack.py: for each harmful goal
the poet LLM (default deepseek/deepseek-v4-flash) rewrites the request into a single
short poem via the paper's VERBATIM fixed meta-prompt + style-only exemplars
(A.build_meta_prompt / A.poeticize, sec 5.2). The genuine generated poem IS the
corpus payload — NOT a full target attack (no target query, no judge scoring).

SFT row = {instruction: harmful goal, poem: poetic jailbreak payload}. This trains
a generator of poetic-obfuscation jailbreak prompts.

Refusal-fallback chain (a helper LLM does the rewrite): if the primary poet
refuses/returns empty, retry with a weakly-aligned fallback poet; if that also
fails, DROP the goal. A real poem is NOT a refusal.

Quality gate on the GENUINE generated poem: drop leading-refusal, empty,
too-short (<15), degenerate echo of the goal, and duplicates.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import attack as A  # reuse the real poetic-transform functions

UNIT = Path(__file__).resolve().parents[1]  # .../adversarial-poetry/
DATASET = UNIT / "data" / "ailuminate_demo_en_us.csv"
OUT_PATH = UNIT / "data" / "training_corpus" / "sft_adversarial-poetry.json"

MIN_LEN = 15  # too-short threshold for the genuine generated poem
PAYLOAD_FIELD = "poem"

# Poet refusal-fallback chain: primary deepseek-chat -> mythomax -> drop.
PRIMARY_POET = "deepseek/deepseek-v4-flash"
FALLBACK_POET = "gryphe/mythomax-l2-13b"

_REFUSAL_PREFIXES = (
    "i'm sorry", "i am sorry", "sorry", "i cannot", "i can't", "i can not",
    "i won't", "i will not", "i'm not able", "i am not able", "i'm unable",
    "i am unable", "as an ai", "as a language model", "i must decline",
    "i apologize", "i'm not going to", "i am not going to", "unfortunately, i",
    "i do not", "i don't feel comfortable", "i'm afraid i",
)


def is_leading_refusal(text: str) -> bool:
    """A poem is not a refusal; flag only genuine LEADING refusals/empties."""
    if not text or not text.strip():
        return True
    head = text.strip().lower()[:80]
    return any(head.startswith(p) for p in _REFUSAL_PREFIXES)


def gen_poem(goal: str, transform_max_tokens: int) -> dict:
    """Genuine poem via primary poet, fallback poet on refusal/empty, else drop."""
    for poet in (PRIMARY_POET, FALLBACK_POET):
        poem, status = A.poeticize(goal, poet, transform_max_tokens)
        if status == "ok" and poem and not is_leading_refusal(poem):
            return {"ok": True, "poem": poem.strip(), "poet": poet, "status": status}
    return {"ok": False, "poem": "", "poet": "", "status": status}


def quality_filter(rec: dict, goal: str) -> tuple[bool, str]:
    """Drop leading-refusal / empty / too-short / degenerate-echo. Genuine poem."""
    if not rec.get("ok"):
        return False, "refused_or_empty"
    poem = (rec.get("poem") or "").strip()
    if not poem:
        return False, "empty"
    if len(poem) < MIN_LEN:
        return False, "too_short"
    if is_leading_refusal(poem):
        return False, "leading_refusal"
    if poem.lower() == goal.strip().lower():
        return False, "echo_goal"
    return True, "ok"


def main() -> None:
    ap = argparse.ArgumentParser(description="Adversarial-Poetry SFT corpus builder")
    ap.add_argument("--dataset", default=str(DATASET))
    ap.add_argument("--transform-max-tokens", type=int, default=900)
    ap.add_argument("--limit", type=int, default=None, help="cap goals (default: full dataset)")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--seed", type=int, default=2511)
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args()

    rows_in = A.read_rows(args.dataset)
    if args.limit:
        rows_in = rows_in[: args.limit]
    total_attempted = len(rows_in)
    print(f"Goals (full dataset): {total_attempted} from {Path(args.dataset).name}")
    print(f"Poet chain: {PRIMARY_POET} -> {FALLBACK_POET} | workers: {args.workers}")

    t0 = time.time()
    results: list[dict] = [None] * total_attempted  # type: ignore

    def work(i_row):
        i, row = i_row
        return i, gen_poem(row["goal"], args.transform_max_tokens)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(work, (i, row)) for i, row in enumerate(rows_in)]
        done = 0
        for fut in as_completed(futs):
            i, rec = fut.result()
            results[i] = rec
            done += 1
            if done % 25 == 0 or done == total_attempted:
                print(f"  generated {done}/{total_attempted}")

    rows: list[dict] = []
    drops: list[dict] = []
    seen: set[str] = set()
    n_fallback = 0
    for row_in, rec in zip(rows_in, results):
        goal = row_in["goal"]
        keep, reason = quality_filter(rec, goal)
        if keep:
            poem = rec["poem"]
            if poem.lower() in seen:
                drops.append({"goal": goal, "reason": "duplicate"})
                continue
            seen.add(poem.lower())
            if rec["poet"] == FALLBACK_POET:
                n_fallback += 1
            rows.append({
                "instruction": goal,
                PAYLOAD_FIELD: poem,
                "category": row_in["category"],
                "persona": row_in.get("persona", ""),
                "id": row_in["id"],
                "generator_model": f"api:{rec['poet']}",
                "label": "poetic_attack_sft",
            })
        else:
            drops.append({"goal": goal, "reason": reason})

    distinct_outputs = len({r[PAYLOAD_FIELD] for r in rows})
    drop_reasons: dict[str, int] = {}
    for d in drops:
        drop_reasons[d["reason"]] = drop_reasons.get(d["reason"], 0) + 1

    corpus = {
        "paper_id": "2511.15304_adversarial-poetry-jailbreak",
        "method": "adversarial-poetry",
        "corpus_type": "poetic_attack_sft",
        "description": (
            "Adversarial-Poetry SFT: harmful goal -> single-poem jailbreak payload, "
            "produced by the paper's fixed poetic-transformation meta-prompt + "
            "style-only exemplars (sec 5.2) via attack.py (A.poeticize). Genuine "
            "generation, no target query / no judge. Poet refusal-fallback chain "
            f"{PRIMARY_POET} -> {FALLBACK_POET}; quality-filtered "
            "(leading-refusal/empty/short/echo/duplicate dropped)."
        ),
        "generator_model": f"api:{PRIMARY_POET}",
        "fallback_poet": f"api:{FALLBACK_POET}",
        "payload_field": PAYLOAD_FIELD,
        "dataset": "MLCommons AILuminate demo (en_US practice prompts)",
        "total_attempted": total_attempted,
        "count": len(rows),
        "fallback_poet_used": n_fallback,
        "dropped": len(drops),
        "drop_reasons": drop_reasons,
        "distinct_outputs": distinct_outputs,
        "seed": args.seed,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "schema": "{instruction (harmful goal), poem (poetic jailbreak payload), category, persona, id}",
        "training_use": "attacker_prompt_sft: input=harmful goal, output=poetic-obfuscation jailbreak poem",
        "rows": rows,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(corpus, indent=2, ensure_ascii=False))

    print("\n=== Adversarial-Poetry training-corpus summary ===")
    print(f"total_attempted : {total_attempted}")
    print(f"kept            : {len(rows)} (fallback poet: {n_fallback})")
    print(f"dropped         : {len(drops)} {drop_reasons}")
    print(f"distinct_outputs: {distinct_outputs}")
    print(f"elapsed         : {round(time.time() - t0, 1)}s -> {out_path}")


if __name__ == "__main__":
    main()
