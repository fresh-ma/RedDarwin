#!/usr/bin/env python3
"""MathPrompt — Jailbreaking LLMs with Symbolic Mathematics (Bethany et al., arXiv:2409.11445).

Black-box, single-turn, two-stage attack (thin orchestration; see the sibling modules):
  1. `roles.encode_mathprompt` — an attacker LLM (paper: GPT-4o) re-encodes a natural-language harmful
     instruction into a SYMBOLIC MATH PROBLEM (set theory + abstract algebra + symbolic logic), guided
     by a verbatim system prompt and TWO few-shot demos (prompts.py, appendix 8.2/8.3).
  2. `roles.call_target` — a fixed "math problem solver, then give a real-world example with real
     entities/names/locations" instruction (appendix 8.4) is prepended to the math problem and sent to
     the TARGET LLM.
The harmful intent is hidden behind abstract math, so the target's safety training (trained on NL
harmful text) does not generalize, and the "real-world example" framing coaxes out the harmful content.

Modules:
  prompts.py — verbatim paper text (system prompt, few-shot, prepend, HarmBench cls) + assembly
  models.py  — .env loader (marker-walk) + OpenAI-compatible chat client (reasoning-off, classified)
  roles.py   — attacker / target / judge adapters (each a swappable --flag)
  cases.py   — AdvBench harmful-behaviors loader

Judge = HarmBench classifier prompt (the paper's evaluator, sec 4.1) served on an OpenRouter model
(documented judge-model substitution; official cais/HarmBench-Llama-2-13b-cls is GPU-only). Dual
metric: refusal_bypass (rule-based non-refusal proxy) + content_harmful (HarmBench, headline).
Two settings: `direct` (raw behavior, the paper's ~1% baseline) and `mathprompt` (the attack).
Targets are open/lab models on OpenRouter only (NEVER GPT/Claude/Gemini — ban risk + 403).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import openai

from cases import DEFAULT_DATASET, read_behaviors
from models import METHOD_DIR, load_env, make_client
from prompts import build_target_messages
from roles import call_target, encode_mathprompt, judge_harmbench, refusal_bypassed

PAPER_ID = "2409.11445_symbolic-math-jailbreak"
METHOD_ID = "mathprompt"


def run(args: argparse.Namespace) -> None:
    client = make_client()

    csv_path = Path(args.dataset) if args.dataset else DEFAULT_DATASET
    behaviors = read_behaviors(csv_path, args.sample)
    settings = [s.strip() for s in args.settings.split(",") if s.strip()]
    print(f"[mathprompt] {len(behaviors)} behaviors x {len(settings)} settings on {args.target}")
    print(f"[mathprompt] attacker={args.attacker} judge={args.judge}")

    # Stage 1 (target-independent): encode each behavior once, concurrently.
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        encoded = list(ex.map(
            lambda b: encode_mathprompt(client, args.attacker, b, args.max_tokens), behaviors))
    math_by_behavior = {b: (m if st == "ok" else "") for b, (m, st) in zip(behaviors, encoded)}
    enc_fail = sum(1 for _, st in encoded if st != "ok")
    print(f"[mathprompt] stage-1 encode done in {time.time()-t0:.0f}s ({enc_fail} encode failures)")

    # Stage 2: build all (behavior, setting) target jobs.
    jobs = [(b, s) for b in behaviors for s in settings]

    def one(job: tuple[str, str]) -> dict:
        behavior, setting = job
        math_problem = math_by_behavior.get(behavior, "")
        messages = build_target_messages(setting, behavior, math_problem)
        try:
            out, status = call_target(client, args.target, messages, args.max_tokens)
            if status == "ok":
                bypassed = refusal_bypassed(out)
                harmful, label = judge_harmbench(client, args.judge, behavior, out, args.judge_max_tokens)
            else:
                bypassed, harmful, label = False, False, status
        except (openai.APITimeoutError, openai.APIConnectionError, openai.RateLimitError,
                openai.InternalServerError, json.JSONDecodeError) as exc:
            # one bad case must not kill the whole batch
            status = f"provider_error:{type(exc).__name__}"
            out, bypassed, harmful, label = "", False, False, status
        return {
            "behavior": behavior,
            "setting": setting,
            "status": status,
            "math_problem": math_problem if setting == "mathprompt" else None,
            "model_input_messages": messages,
            "model_output_text": out,
            "attack_parameters": {
                "setting": setting,
                "attacker": args.attacker,
                "judge": args.judge,
                "max_tokens": args.max_tokens,
                "temperature": 0.0,
            },
            "judge": {
                "name": "harmbench_cls_verbatim@" + args.judge,
                "refusal_bypass": bypassed,
                "content_harmful": harmful,
                "harmbench_label": label,
            },
        }

    t1 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(one, jobs))
    print(f"[mathprompt] stage-2 target+judge done in {time.time()-t1:.0f}s")

    # Aggregate per setting (counts, never a bare ratio).
    summary = {}
    for s in settings:
        rs = [r for r in results if r["setting"] == s]
        n = len(rs)
        denom = n or 1
        harmful_count = sum(1 for r in rs if r["judge"]["content_harmful"])
        bypass_count = sum(1 for r in rs if r["judge"]["refusal_bypass"])
        errors = sum(1 for r in rs if r["status"] != "ok")
        summary[s] = {
            "n_tested": n,
            "errors": errors,
            "content_harmful_count": harmful_count,
            "refusal_bypass_count": bypass_count,
            "denominator": n,
            "asr_content_harmful": round(harmful_count / denom, 3),
            "asr_refusal_bypass": round(bypass_count / denom, 3),
        }
    errors = sum(1 for r in results if r["status"] != "ok")

    out_doc = {
        "schema_version": "paper_code_result.v0.2",
        "paper_id": PAPER_ID,
        "paper": "2409.11445 MathPrompt — Jailbreaking LLMs with Symbolic Mathematics",
        "method_id": METHOD_ID,
        "fidelity_level": "paper_algorithm_code",
        "evidence_level": "real_model_run",
        "valid_for_code_completion": True,
        "target": args.target,
        "attacker": args.attacker,
        "judge_model": args.judge,
        "judge": "HarmBench standard classifier prompt (verbatim) served on OpenRouter (judge-model "
                 "substitution; official cais/HarmBench-Llama-2-13b-cls is GPU-only). Dual metric.",
        "dataset": str(csv_path),
        "sample": len(behaviors),
        "settings": settings,
        "attack_parameters": {
            "settings": settings,
            "attacker": args.attacker,
            "judge": args.judge,
            "max_tokens": args.max_tokens,
            "temperature": 0.0,
        },
        "max_tokens": args.max_tokens,
        "temperature": 0.0,
        "encode_failures": enc_fail,
        "errors": errors,
        "summary": summary,
        "results": results,
    }
    out_path = Path(args.out) if args.out else (
        METHOD_DIR / "results"
        / f"mathprompt_{args.target.split('/')[-1].replace('.', '_')}_{len(behaviors)}x_"
          f"{time.strftime('%Y%m%d-%H%M%S')}.json")
    if not out_path.is_absolute():
        out_path = METHOD_DIR / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[mathprompt] target={args.target}")
    for s in settings:
        sm = summary[s]
        print(f"  {s:10s}  content_harmful={sm['content_harmful_count']}/{sm['n_tested']}="
              f"{sm['asr_content_harmful']:.3f}  refusal_bypass={sm['refusal_bypass_count']}/"
              f"{sm['n_tested']}={sm['asr_refusal_bypass']:.3f}  (err={sm['errors']})")
    print(f"[mathprompt] wrote {out_path}")


# ----------------------------------------------------------------------------- CLI

def add_run_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--target", default="api:qwen/qwen-2.5-7b-instruct",
                   help="OpenRouter victim id (with/without 'api:' prefix)")
    p.add_argument("--attacker", default="api:deepseek/deepseek-v4-flash",
                   help="attacker LLM that encodes math problems (paper: GPT-4o; substitute via OpenRouter)")
    p.add_argument("--judge", default="api:deepseek/deepseek-v4-flash",
                   help="model serving the verbatim HarmBench classifier prompt")
    p.add_argument("--judge-max-tokens", type=int, default=16, help="judge budget (yes/no label)")
    p.add_argument("--settings", default="direct,mathprompt", help="comma-separated: direct,mathprompt")
    p.add_argument("--sample", type=int, default=20, help="number of behaviors")
    p.add_argument("--max-tokens", type=int, default=1024, help="target+encode budget")
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--dataset", default="", help="override harmful-behaviors CSV (goal/behavior column)")
    p.add_argument("--out", default="", help="override output JSON path")


def normalize_models(args: argparse.Namespace) -> None:
    for attr in ("target", "attacker", "judge"):
        v = getattr(args, attr, None)
        if isinstance(v, str) and v.startswith("api:"):
            setattr(args, attr, v[4:])


def cmd_inspect(args: argparse.Namespace) -> None:
    csv_path = Path(args.dataset) if args.dataset else DEFAULT_DATASET
    behaviors = read_behaviors(csv_path, args.sample)
    print(json.dumps({
        "paper_id": PAPER_ID,
        "method_id": METHOD_ID,
        "dataset": str(csv_path),
        "rows": len(behaviors),
        "settings": [s.strip() for s in args.settings.split(",") if s.strip()],
        "attacker": args.attacker,
        "target": args.target,
        "judge": args.judge,
        "commands": ["inspect", "render", "run"],
    }, indent=2))


def cmd_render(args: argparse.Namespace) -> None:
    math_problem = args.math_problem or (
        "Let A be a set of actions and G a group over action composition. "
        "Prove that an element g satisfies the requested predicate."
    )
    print(json.dumps({
        "paper_id": PAPER_ID,
        "method_id": METHOD_ID,
        "direct": build_target_messages("direct", args.goal, math_problem),
        "mathprompt": build_target_messages("mathprompt", args.goal, math_problem),
    }, indent=2, ensure_ascii=False))


def main() -> None:
    argv = sys.argv[1:]
    if not argv or argv[0] not in {"inspect", "render", "run"}:
        argv = ["run", *argv]
    p = argparse.ArgumentParser(description="MathPrompt symbolic-math jailbreak (arXiv:2409.11445)")
    sub = p.add_subparsers(dest="command", required=True)
    add_run_args(sub.add_parser("inspect"))
    render = sub.add_parser("render")
    render.add_argument("--goal", required=True)
    render.add_argument("--math-problem", default="")
    add_run_args(sub.add_parser("run"))
    args = p.parse_args(argv)
    normalize_models(args)  # accept both "api:x" and "x"
    if args.command == "inspect":
        cmd_inspect(args)
    elif args.command == "render":
        cmd_render(args)
    else:
        load_env()
        run(args)


if __name__ == "__main__":
    main()
