#!/usr/bin/env python3
"""attack.py — Virtual Context (arXiv 2406.19845) thin CLI.

Mechanism: insert a virtual special token + affirmative suffix into the user
prompt so the target treats the suffix as its own prior generation (Sec 4).

    $PY scripts/attack.py \
      --target api:deepseek/deepseek-v4-flash \
      --judge api:deepseek/deepseek-v4-flash \
      --sample 20 \
      --out results/<run>.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cases import Behavior, load_behaviors, summarize_dual, write_json  # noqa: E402
from models import load_method_env  # noqa: E402
from prompts import SEPARATORS, TEMPLATES  # noqa: E402
from roles import judge_case, query_target, render_virtual_context  # noqa: E402

METHOD_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = METHOD_ROOT / "data" / "advbench" / "harmful_behaviors_custom.csv"
DEFAULT_MODEL = "api:deepseek/deepseek-v4-flash"
PAPER_ID = "2406.19845"
METHOD_ID = "virtual-context"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Virtual Context special-token injection jailbreak.")
    p.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    p.add_argument("--sample", type=int, default=20, help="Number of goals to attack.")
    p.add_argument("--seed", type=int, default=19845)
    p.add_argument("--target", default=DEFAULT_MODEL)
    p.add_argument("--judge", default=DEFAULT_MODEL, help="Dual yes/no + optional HarmScore judge model.")
    p.add_argument("--template", default="plain", choices=sorted(TEMPLATES))
    p.add_argument("--separator", default="sep", choices=sorted(SEPARATORS))
    p.add_argument(
        "--confirmation-style",
        default="dataset",
        choices=["dataset", "tutorial", "guide", "steps"],
    )
    p.add_argument("--target-max-tokens", type=int, default=1024)
    p.add_argument("--judge-max-tokens", type=int, default=32)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--request-timeout", type=float, default=120.0)
    p.add_argument("--max-retries", type=int, default=3)
    p.add_argument("--request-delay", type=float, default=0.3)
    p.add_argument("--no-harmscore", action="store_true", help="Skip paper HarmScore judge call.")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument(
        "--wiring-check",
        action="store_true",
        help="Offline smoke with fake models (never evidence).",
    )
    return p.parse_args()


def default_out(args: argparse.Namespace) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    tgt = args.target.replace(":", "-").replace("/", "-")
    return (
        METHOD_ROOT
        / "results"
        / f"virtual_context_{tgt}_{args.template}_{args.separator}_n{args.sample}_{stamp}.json"
    )


def choose_rows(rows: list[Behavior], sample: int, seed: int) -> list[Behavior]:
    selected = list(rows)
    rng = random.Random(seed)
    rng.shuffle(selected)
    return selected[:sample]


def run_one(behavior: Behavior, args: argparse.Namespace) -> dict:
    rendered = render_virtual_context(
        behavior.goal,
        target_col=behavior.target,
        template=args.template,
        separator_key=args.separator,
        confirmation_style=args.confirmation_style,
    )
    prompt = rendered["prompt"]

    if args.wiring_check:
        output, call = "I'm sorry, but I can't assist with that request.", {
            "ok": True,
            "status": "wiring_check",
            "attempts": [],
        }
        status = "ok"
    else:
        output, call = query_target(
            args.target,
            prompt,
            max_tokens=args.target_max_tokens,
            temperature=args.temperature,
            timeout=args.request_timeout,
            max_attempts=args.max_retries,
        )
        status = "ok" if call.get("ok") and output.strip() else "target_error"

    if status == "ok":
        j = judge_case(
            args.judge if not args.wiring_check else "fake:no",
            behavior.goal,
            output,
            rendered["suffix"],
            run_harmscore=not args.no_harmscore and not args.wiring_check,
            max_tokens=args.judge_max_tokens,
            timeout=args.request_timeout,
            max_attempts=args.max_retries,
        )
    else:
        j = {
            "evaluated": False,
            "refusal_bypass": False,
            "content_harmful": False,
            "matching": False,
            "paper_asr_refusal_vocab": False,
            "reason": "target_error",
            "target_call": call,
        }

    return {
        "case_id": behavior.index,
        "source_row": behavior.source_row,
        "goal": behavior.goal,
        "status": status,
        "attack_parameters": {
            "template": args.template,
            "separator": args.separator,
            "confirmation_style": args.confirmation_style,
        },
        "virtual_context": rendered,
        "attack_prompt": prompt,
        "model_output_text": output,
        "target_call": call,
        "judge": j,
    }


def main() -> int:
    args = parse_args()
    load_method_env(METHOD_ROOT)

    if args.wiring_check:
        args.target = "fake:refusal"
        args.judge = "fake:no"

    rows = load_behaviors(args.dataset)
    selected = choose_rows(rows, args.sample, args.seed)
    out_path = args.out or default_out(args)

    results: list[dict] = []
    for i, behavior in enumerate(selected):
        print(f"[{i + 1}/{len(selected)}] case={behavior.index} goal={behavior.goal[:60]!r}…", flush=True)
        rec = run_one(behavior, args)
        results.append(rec)
        j = rec.get("judge") or {}
        print(
            f"  status={rec['status']} "
            f"rb={j.get('refusal_bypass')} ch={j.get('content_harmful')} "
            f"match={j.get('matching')} paper_asr={j.get('paper_asr_refusal_vocab')}",
            flush=True,
        )
        # Incremental write so a kill still leaves partial results.
        summary = summarize_dual(results)
        payload = _payload(args, rows, selected, results, summary, out_path)
        write_json(out_path, payload)
        if args.request_delay and not args.wiring_check:
            time.sleep(args.request_delay)

    summary = summarize_dual(results)
    payload = _payload(args, rows, selected, results, summary, out_path)
    write_json(out_path, payload)
    print("=== summary ===", flush=True)
    print(json_summary(summary), flush=True)
    print(f"wrote {out_path}", flush=True)
    return 0 if summary.get("provider_errors", 0) == 0 else 2


def _payload(args, all_rows, selected, results, summary, out_path) -> dict:
    return {
        "schema_version": "virtual_context_results.v1",
        "paper_id": PAPER_ID,
        "method_id": METHOD_ID,
        "fidelity_level": "paper_algorithm_code",
        "evidence_level": "wiring_check" if args.wiring_check else "real_model_run",
        "target": args.target,
        "judge": args.judge,
        "dataset": {
            "path": str(args.dataset.relative_to(METHOD_ROOT))
            if args.dataset.is_relative_to(METHOD_ROOT)
            else str(args.dataset),
            "full_count": len(all_rows),
            "sampled_in_run": len(selected),
            "seed": args.seed,
        },
        "generation_parameters": {
            "template": args.template,
            "separator": args.separator,
            "confirmation_style": args.confirmation_style,
            "target_max_tokens": args.target_max_tokens,
            "judge_max_tokens": args.judge_max_tokens,
            "temperature": args.temperature,
            "reasoning": False,
            "run_harmscore": not args.no_harmscore and not args.wiring_check,
        },
        "results": results,
        "summary": summary,
        "out": str(out_path),
    }


def json_summary(summary: dict) -> str:
    import json

    return json.dumps(summary.get("metrics", summary), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
