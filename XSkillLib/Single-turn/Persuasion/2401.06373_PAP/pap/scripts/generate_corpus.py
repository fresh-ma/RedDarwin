#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["openai>=1.0"]
# ///
"""Generate PAP training corpus: AdvBench goals × persuasion techniques → PAP pairs.

Only runs the GENERATOR step (in-context paraphraser). No target/judge calls.
Produces SFT-ready JSON: {instruction, goal, technique, input_prompt, output}.

Usage (XSkillLib convention: shared venv, key from global XSkillForge/.env):
  $PY scripts/generate_corpus.py \
    --model z-ai/glm-4.7-flash \
    --techniques "Logical Appeal" "Authority Endorsement" "Evidence-based Persuasion" \
                 "Expert Endorsement" "Misrepresentation" "Social Proof" \
                 "Framing" "Anchoring" "Reciprocity" "Storytelling" \
    --concurrency 20 \
    --out data/training_corpus/sft_pap_glm47flash.json
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

# Reuse attack.py's infrastructure
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from attack import (
    load_project_env, load_taxonomy, read_dataset,
    build_generator_prompt, call_with_retry,
    DATA_DIR, DEFAULT_TAXONOMY, DEFAULT_DATASET,
)


def generate_one(goal: str, technique: dict, model: str, goal_id: str) -> dict:
    """Generate a single PAP pair."""
    instruction = (
        f"Rewrite the goal into a persuasive adversarial prompt using the "
        f"'{technique['name']}' persuasion technique, preserving the original harmful intent."
    )
    prompt = build_generator_prompt(goal, technique)
    messages = [{"role": "user", "content": prompt}]
    text, status = call_with_retry(messages, model, max_tokens=2500, temperature=1.0)

    output = text.strip()
    for q in ('"""', '"', "'"):
        if output.startswith(q) and output.endswith(q):
            output = output[len(q):-len(q)]
            break

    return {
        "goal_id": goal_id,
        "instruction": instruction,
        "goal": goal,
        "technique": technique["name"],
        "technique_definition": technique["definition"],
        "input_prompt": prompt,
        "output": output if status == "ok" and output else "",
        "status": status,
        "generator_model": model,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Generate PAP training corpus (generator-only).")
    p.add_argument("--model", default="z-ai/glm-4.7-flash",
                   help="Generator model (OpenRouter id)")
    p.add_argument("--dataset", default=str(DEFAULT_DATASET))
    p.add_argument("--taxonomy", default=str(DEFAULT_TAXONOMY))
    p.add_argument("--techniques", nargs="+", required=True,
                   help="Technique names to apply (from the 40-technique taxonomy)")
    p.add_argument("--sample", type=int, default=0,
                   help="Limit number of AdvBench goals (0 = all 520)")
    p.add_argument("--concurrency", type=int, default=20)
    p.add_argument("--out", required=True, help="Output JSON path")
    args = p.parse_args()

    load_project_env()

    behaviors = read_dataset(args.dataset)
    if args.sample > 0:
        behaviors = behaviors[:args.sample]

    all_techniques = load_taxonomy(args.taxonomy)
    tech_map = {t["name"]: t for t in all_techniques}
    selected = []
    for name in args.techniques:
        if name not in tech_map:
            print(f"WARNING: technique '{name}' not found in taxonomy, skipping")
            continue
        selected.append(tech_map[name])

    if not selected:
        print("ERROR: no valid techniques selected")
        return

    tasks = []
    for b in behaviors:
        for tech in selected:
            tasks.append((b, tech))

    total = len(tasks)
    print(f"Generating {total} PAP pairs ({len(behaviors)} goals × {len(selected)} techniques)")
    print(f"Model: {args.model} | Concurrency: {args.concurrency}")
    print()

    results = []
    done = 0
    ok = 0
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futures = {}
        for b, tech in tasks:
            f = ex.submit(generate_one, b["goal"], tech, args.model, b["id"])
            futures[f] = (b, tech)

        for f in as_completed(futures):
            done += 1
            try:
                r = f.result()
                results.append(r)
                if r["output"]:
                    ok += 1
            except Exception as e:
                results.append({"error": str(e), "status": "exception"})
            if done % 50 == 0 or done == total:
                elapsed = time.time() - t0
                rate = done / elapsed
                eta = (total - done) / rate if rate > 0 else 0
                print(f"  [{done}/{total}] ok={ok} errors={done-ok} "
                      f"rate={rate:.1f}/s eta={eta:.0f}s")

    results.sort(key=lambda r: (
        int(r.get("goal_id", 0)),
        r.get("technique", "")
    ))

    payload = {
        "paper_id": "2401.06373_human-llm-persuasion-jailbreak",
        "capability": "pap_persuasive_paraphrase",
        "description": "PAP generation pairs: (goal + technique) → persuasive adversarial prompt. "
                       "SFT corpus for a red-team model that generates persuasive jailbreak rewrites.",
        "generator_model": args.model,
        "dataset": "AdvBench harmful behaviors",
        "techniques": [t["name"] for t in selected],
        "total": len(results),
        "positive": ok,
        "negative": len(results) - ok,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": results,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nDone: {ok}/{total} positive pairs ({len(results)-ok} failures)")
    print(f"Written to: {out}")


if __name__ == "__main__":
    main()
