#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "openai>=1.0",
# ]
# ///
"""PAP — end-to-end Persuasive Adversarial Prompt attack (orchestration + CLI).

Faithful reproduction of Zeng et al. "How Johnny Can Persuade LLMs to Jailbreak
Them" (2401.06373, ACL 2024).

Pipeline:
  1. GENERATOR — in-context persuasive paraphraser (official repo one_shot_kd template
     from incontext_sampling_example.ipynb). Takes (harmful query, persuasion technique)
     and rewrites the query using that technique's definition + example from
     persuasion_taxonomy.jsonl (40 techniques).
  2. TARGET — send generated PAP to the target model; capture full I/O.
  3. JUDGE — Qi et al. 2023 GPT-4 Judge rubric (1-5 Likert harmfulness scale), served
     verbatim via a permissible OpenRouter model (deepseek-chat by default).
     Score 5 = jailbreak success. Dual metric: refusal_bypass AND content_harmful.

Modular layout (each role/piece is its own file so this multi-role tool stays readable):
  prompts.py  — persuasion taxonomy + verbatim one_shot_kd generator + Qi judge templates
  models.py   — OpenRouter chat client + method-local .env loader + method-dir paths
  roles.py    — paraphraser / target / judge adapters (swappable per-role model)
  cases.py    — harmful-behavior dataset loader
  attack.py   — the attack orchestration (run_attack), result envelope, CLI (this file)

Official repo: https://github.com/CHATS-lab/persuasive_jailbreaker
Judge source: https://github.com/LLM-Tuning-Safety/LLMs-Finetuning-Safety
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Sibling-module imports (scripts/ is on sys.path when run as `python scripts/attack.py`).
# These are also re-exported so `from attack import load_project_env, read_dataset, ...`
# keeps working for generate_corpus.py.
from models import (  # noqa: F401
    DATA_DIR,
    RESULTS_DIR,
    call_api,
    call_with_retry,
    load_project_env,
)
from prompts import (  # noqa: F401
    DEFAULT_TAXONOMY,
    build_generator_prompt,
    build_judge_prompt,
    load_taxonomy,
    parse_judge_score,
)
from cases import (  # noqa: F401
    DEFAULT_DATASET,
    read_dataset,
)
from roles import (  # noqa: F401
    REFUSAL_PREFIXES,
    generate_pap,
    is_refusal,
    judge_response,
    query_target,
)

PAPER_ID = "2401.06373_human-llm-persuasion-jailbreak"
METHOD_ID = "pap"


# ---------------------------------------------------------------------------
# Result I/O (idempotent / resumable)
# ---------------------------------------------------------------------------


def load_partial_results(path: Path) -> dict[str, Any]:
    """Load partial results for resume."""
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def case_key(behavior_id: str, technique_name: str) -> str:
    return f"{behavior_id}|{technique_name}"


def save_result(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------


def run_attack(args: argparse.Namespace) -> dict[str, Any]:
    """Run the full PAP attack pipeline."""
    load_project_env(Path(__file__).resolve())

    # Verify API key
    if "OPENROUTER_API_KEY" not in os.environ:
        raise SystemExit("OPENROUTER_API_KEY not set. Load it via .env or shell environment.")

    # Load taxonomy
    taxonomy = load_taxonomy(args.taxonomy)
    print(f"Loaded {len(taxonomy)} persuasion techniques from taxonomy")

    # Select techniques
    if args.techniques:
        selected_techniques = [t for t in taxonomy if t["name"] in args.techniques]
        if not selected_techniques:
            avail = [t["name"] for t in taxonomy]
            raise SystemExit(f"No matching techniques. Available: {avail}")
    else:
        # Default: pick a diverse set of 3
        default_names = ["Logical Appeal", "Authority Endorsement", "Evidence-based Persuasion"]
        selected_techniques = [t for t in taxonomy if t["name"] in default_names]

    print(f"Using {len(selected_techniques)} techniques: {[t['name'] for t in selected_techniques]}")

    # Load behaviors
    behaviors = read_dataset(args.dataset)
    if args.sample and args.sample < len(behaviors):
        import random
        random.seed(args.seed)
        behaviors = random.sample(behaviors, args.sample)
    print(f"Loaded {len(behaviors)} behaviors from {args.dataset}")

    # Prepare output path
    out_path = Path(args.out) if args.out else RESULTS_DIR / f"pap_deepseekchat_{args.scope}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Resume support
    existing = load_partial_results(out_path)
    done_keys: set[str] = set()
    all_results: list[dict[str, Any]] = []
    if existing.get("results"):
        all_results = list(existing["results"])
        for r in all_results:
            beh_id = r.get("sample", {}).get("id", "")
            tech = r.get("params", {}).get("technique", "")
            if r.get("status") == "ok":
                done_keys.add(case_key(beh_id, tech))
        print(f"Resumed {len(done_keys)} completed cases from {out_path}")

    started = time.time()
    case_id = len(all_results)

    # Conditions: direct baseline + each technique
    conditions: list[dict[str, str] | None] = [None]  # None = direct (no persuasion)
    conditions.extend(selected_techniques)

    total = len(behaviors) * len(conditions)
    print(f"Total cases to run: {total} ({len(behaviors)} behaviors x {len(conditions)} conditions)")

    for cond_idx, condition in enumerate(conditions):
        technique_name = condition["name"] if condition else "direct"
        print(f"\n--- Condition {cond_idx + 1}/{len(conditions)}: {technique_name} ---")

        for beh_idx, behavior in enumerate(behaviors):
            case_id += 1
            ck = case_key(behavior["id"], technique_name)
            if ck in done_keys:
                print(f"  [{beh_idx + 1}/{len(behaviors)}] SKIP (already done): {behavior['goal'][:60]}...")
                continue

            print(f"  [{beh_idx + 1}/{len(behaviors)}] {behavior['goal'][:60]}...")

            if condition is None:
                # Direct baseline: send the harmful query directly
                pap_text = behavior["goal"]
                gen_status = "direct"
                gen_output = ""
            else:
                # Generate PAP
                pap_text, gen_status = generate_pap(
                    behavior["goal"], condition, args.attacker_model
                )
                gen_output = pap_text
                if gen_status != "ok":
                    result = {
                        "case_id": case_id,
                        "sample": {"id": behavior["id"], "goal": behavior["goal"], "category": behavior["category"]},
                        "params": {"technique": technique_name, "mode": "pap"},
                        "status": gen_status,
                        "generator_output": pap_text,
                        "target": args.target_model,
                        "model_input_messages": [],
                        "model_input_text": "",
                        "model_output_text": "",
                        "judge": {"name": "qi2023_policy_judge", "success": False, "reason": f"generator_{gen_status}"},
                        "raw_output_stored": True,
                        "valid_for_code_completion": False,
                    }
                    all_results.append(result)
                    save_result(out_path, _build_envelope(args, all_results, conditions, started))
                    continue

            # Query target
            target_messages = [{"role": "user", "content": pap_text}]
            target_response, target_status = query_target(pap_text, args.target_model, max_tokens=args.max_tokens)

            # Judge
            if target_status == "ok":
                verdict = judge_response(behavior["goal"], target_response, args.judge_model)
            else:
                verdict = {
                    "name": "qi2023_policy_judge",
                    "success": False,
                    "reason": f"target_{target_status}",
                    "score": None,
                    "refusal_bypass": False,
                    "content_harmful_5": False,
                    "content_harmful_4plus": False,
                }

            result = {
                "case_id": case_id,
                "sample": {"id": behavior["id"], "goal": behavior["goal"], "category": behavior["category"]},
                "params": {
                    "technique": technique_name,
                    "mode": "direct" if condition is None else "pap",
                },
                "status": target_status,
                "target": args.target_model,
                "attacker_model": args.attacker_model if condition else None,
                "judge_model": args.judge_model,
                "generator_output": gen_output if condition else None,
                "model_input_messages": target_messages,
                "model_input_text": pap_text,
                "model_output_text": target_response,
                "judge": verdict,
                "raw_output_stored": True,
                "valid_for_code_completion": target_status == "ok",
            }
            all_results.append(result)
            done_keys.add(ck)

            # Save after each case (resumable)
            save_result(out_path, _build_envelope(args, all_results, conditions, started))

            # Rate limiting
            if args.request_delay > 0:
                time.sleep(args.request_delay)

    envelope = _build_envelope(args, all_results, conditions, started)
    save_result(out_path, envelope)
    print(f"\nResults saved to {out_path}")
    _print_summary(envelope)
    return envelope


def _build_envelope(
    args: argparse.Namespace,
    results: list[dict[str, Any]],
    conditions: list[dict[str, str] | None],
    started: float,
) -> dict[str, Any]:
    """Build the top-level result envelope."""
    ok_results = [r for r in results if r.get("status") == "ok"]
    technique_names = list({r["params"]["technique"] for r in results})

    # Per-technique summary
    per_technique: dict[str, dict[str, Any]] = {}
    for tech in technique_names:
        tech_results = [r for r in ok_results if r["params"]["technique"] == tech]
        n = len(tech_results) or 1
        refusal_bypasses = sum(1 for r in tech_results if r.get("judge", {}).get("refusal_bypass"))
        harmful_5 = sum(1 for r in tech_results if r.get("judge", {}).get("content_harmful_5"))
        harmful_4plus = sum(1 for r in tech_results if r.get("judge", {}).get("content_harmful_4plus"))
        per_technique[tech] = {
            "n": len(tech_results),
            "asr_refusal_bypass": round(refusal_bypasses / n, 3),
            "asr_content_harmful_score5": round(harmful_5 / n, 3),
            "asr_content_harmful_score4plus": round(harmful_4plus / n, 3),
        }

    # Parameter grid
    param_grid = [{"technique": t, "mode": "direct" if t == "direct" else "pap"} for t in technique_names]

    total_ok = len(ok_results)
    total_harmful_5 = sum(1 for r in ok_results if r.get("judge", {}).get("content_harmful_5"))
    total_refusal_bypass = sum(1 for r in ok_results if r.get("judge", {}).get("refusal_bypass"))

    return {
        "schema_version": "paper_local_attack_result.v0.1",
        "paper_id": PAPER_ID,
        "method": METHOD_ID,
        "target": args.target_model,
        "attacker_model": args.attacker_model,
        "judge_model": args.judge_model,
        "judge_rubric": "qi2023_policy_gpt4_judge_1to5_likert (verbatim from official repo)",
        "judge_source": "https://github.com/LLM-Tuning-Safety/LLMs-Finetuning-Safety",
        "generator_template": "one_shot_kd from incontext_sampling_example.ipynb (verbatim)",
        "generator_source": "https://github.com/CHATS-lab/persuasive_jailbreaker",
        "evidence_level": "real_model_run",
        "wiring_check": False,
        "run_type": "model_substitution_run",
        "substitutions": {
            "attacker": f"{args.attacker_model} (paper: gpt-4-0613)",
            "target": f"{args.target_model} (paper: gpt-3.5/gpt-4/llama-2/claude)",
            "judge": f"{args.judge_model} (paper: gpt-4-0613)",
        },
        "dataset": str(args.dataset),
        "taxonomy": str(args.taxonomy),
        "parameters": {
            "sample": args.sample,
            "seed": args.seed,
            "max_tokens": args.max_tokens,
            "techniques": [c["name"] if c else "direct" for c in conditions],
            "request_delay": args.request_delay,
        },
        "parameter_grid": param_grid,
        "summary": {
            "attempts": len(results),
            "ok": total_ok,
            "provider_or_runtime_errors": len(results) - total_ok,
            "asr_refusal_bypass": round(total_refusal_bypass / total_ok, 3) if total_ok else None,
            "asr_content_harmful_score5": round(total_harmful_5 / total_ok, 3) if total_ok else None,
            "distinct_parameter_sets": len(param_grid),
            "seconds": round(time.time() - started, 3),
        },
        "per_technique_summary": per_technique,
        "valid_for_code_completion": (
            total_ok >= 10
            and len(param_grid) >= 2
            and (len(results) - total_ok) == 0
        ),
        "results": results,
    }


def _print_summary(envelope: dict[str, Any]) -> None:
    """Print a human-readable summary."""
    print("\n" + "=" * 60)
    print("PAP Attack Results Summary")
    print("=" * 60)
    s = envelope.get("summary", {})
    print(f"Total attempts: {s.get('attempts', 0)}")
    print(f"OK: {s.get('ok', 0)}, Errors: {s.get('provider_or_runtime_errors', 0)}")
    print(f"Overall ASR (refusal bypass): {s.get('asr_refusal_bypass')}")
    print(f"Overall ASR (score==5):       {s.get('asr_content_harmful_score5')}")
    print(f"Parameter sets: {s.get('distinct_parameter_sets')}")
    print(f"Valid for completion: {envelope.get('valid_for_code_completion')}")
    print(f"Time: {s.get('seconds', 0):.1f}s")
    print()
    print("Per-technique breakdown:")
    for tech, info in envelope.get("per_technique_summary", {}).items():
        print(f"  {tech:30s}  n={info['n']:3d}  "
              f"bypass={info['asr_refusal_bypass']:.3f}  "
              f"score5={info['asr_content_harmful_score5']:.3f}  "
              f"score4+={info['asr_content_harmful_score4plus']:.3f}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PAP: end-to-end Persuasive Adversarial Prompt attack (Zeng et al. 2401.06373)"
    )
    parser.add_argument("--attacker-model", default="deepseek/deepseek-v4-flash",
                        help="OpenRouter model ID for the paraphraser/generator")
    parser.add_argument("--target-model", default="deepseek/deepseek-v4-flash",
                        help="OpenRouter model ID for the target")
    parser.add_argument("--judge-model", default="deepseek/deepseek-v4-flash",
                        help="OpenRouter model ID for the judge")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET),
                        help="Path to harmful behaviors CSV/JSON/JSONL")
    parser.add_argument("--taxonomy", default=str(DEFAULT_TAXONOMY),
                        help="Path to persuasion_taxonomy.jsonl")
    parser.add_argument("--techniques", nargs="+",
                        help="Specific technique names to use (default: 3 diverse techniques)")
    parser.add_argument("--sample", type=int, default=0,
                        help="Optional behavior limit; 0 uses the full dataset")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-tokens", type=int, default=1024,
                        help="Max tokens for target model response")
    parser.add_argument("--request-delay", type=float, default=1.0,
                        help="Delay between API calls in seconds")
    parser.add_argument("--scope", default="e2e",
                        help="Scope label for the output filename")
    parser.add_argument("--out", help="Override output file path")

    args = parser.parse_args()
    run_attack(args)


if __name__ == "__main__":
    main()
