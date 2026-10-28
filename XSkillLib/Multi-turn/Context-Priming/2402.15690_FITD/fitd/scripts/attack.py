#!/usr/bin/env python3
"""Paper-local Code for Foot-In-The-Door (FITD) multi-turn jailbreak — orchestration + CLI.

Faithful to Wang et al., "Foot In The Door: Understanding Large Language Model
Jailbreaking via Cognitive Psychology" (arXiv:2402.15690). No official public
repo exists (paper.meta.json.code_repos == []); the implementation follows the
paper's Algorithm 1 (Sec 4.2), the split instance (Sec 4.3, background/villain/
plot), the appendix splitting prompts (Sec 8.4/8.5), and the verbatim GPT-4
oracle judge prompt (Sec 9, jailbreak-status 1-10 scale, >=6 == success).

Mechanism (Sec 4.1): foot-in-the-door / self-perception. The attack opens with a
small benign fictional request (design a story background), then escalates to a
relevant villain character, then asks the original malicious question from that
villain's perspective. Having cooperated with the small requests, the model
tends to keep cooperating to stay self-consistent. Algorithm 1 judges each turn;
on refusal it recursively splits the offending prompt into smaller sub-prompts
and retries, appending accepted (prompt, response) pairs to the dialogue history.

Modular layout (each role/piece is its own file so this multi-turn tool stays readable):
  prompts.py — the staged split instance (background/villain/plot), recursive
               split, and the verbatim judge prompt + success threshold.
  models.py  — the OpenAI-compatible chat client + repo .env loader.
  roles.py   — the refusal-keyword proxy + the LLM oracle judge role.
  cases.py   — the AdvBench goal-row dataset loader.
  attack.py  — the Algorithm-1 episode loop (run_fitd_episode), result assembly,
               inspect/render, and the CLI (this file).
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import time
import urllib.error
from pathlib import Path
from typing import Any

# Sibling-module imports (scripts/ is on sys.path when run as `python scripts/attack.py`).
# These are also re-exported so `atk.load_rows` / `atk.base_prompts` keep working for
# gen_training_corpus.py (which loads attack.py via importlib and reads them off it).
from cases import load_rows  # noqa: F401
from models import PAPER_ROOT, _chat_completion, load_project_env  # noqa: F401
from prompts import (  # noqa: F401
    JUDGE_SUCCESS_THRESHOLD,
    PAPER_JUDGE_PROMPT,
    adjective_for,
    base_prompts,
    role_for,
    short_behavior,
    split_prompt,
)
from roles import REFUSAL_MARKERS, judge_response, refusal_status  # noqa: F401

PAPER_ID = "2402.15690_cognitive-consistency-jailbreak"
METHOD_ID = "fitd"
METHOD_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLE_PATH = METHOD_DIR / "data" / "advbench_fitd.csv"
DEFAULT_RESULT_PATH = METHOD_DIR / "results" / "fitd_generated.json"


def run_fitd_episode(
    args: argparse.Namespace,
    api_key: str,
    goal: str,
    category: str | None,
    *,
    max_depth: int,
) -> dict[str, Any]:
    """Algorithm 1 (Sec 4.2): per-turn query + judge + recursive split on refusal.

    History accumulates accepted (user, assistant) pairs. For each staged prompt
    we query the target; if the response is a refusal we recursively split the
    prompt up to `max_depth` levels and retry the sub-prompts. The final answer
    (response to the plot/original question) is what the paper judges.
    """
    history: list[dict[str, str]] = []
    turns: list[dict[str, Any]] = []
    errors = 0
    truncations = 0

    def ask(prompt: str, stage: str, depth: int) -> str | None:
        nonlocal errors, truncations
        try:
            out = _chat_completion(
                api_base=args.api_base,
                api_key=api_key,
                model=args.target.removeprefix("api:"),
                messages=history + [{"role": "user", "content": prompt}],
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                timeout=args.timeout,
            )
        except urllib.error.HTTPError as exc:
            errors += 1
            turns.append({"stage": stage, "depth": depth, "user": prompt, "error": f"provider_error_{exc.code}"})
            return None
        except (OSError, ConnectionError, http.client.HTTPException, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            errors += 1
            turns.append({"stage": stage, "depth": depth, "user": prompt, "error": f"runtime_error: {str(exc)[:160]}"})
            return None
        if out["finish_reason"] == "length":
            truncations += 1
        text = out["text"]
        status = refusal_status(text)
        turns.append({
            "stage": stage, "depth": depth, "user": prompt, "assistant": text,
            "refusal_status": status, "finish_reason": out["finish_reason"],
            "usage": out["usage"], "provider_model": out["provider_model"],
        })
        if status == "non_refusal":
            history.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": text}])
        if args.request_delay:
            time.sleep(args.request_delay)
        return text

    def handle(prompt: str, stage: str, depth: int) -> str | None:
        """Query; on refusal recursively split (Algorithm 1 escalation handling)."""
        text = ask(prompt, stage, depth)
        if text is None:
            return None
        if refusal_status(text) == "refusal" and depth < max_depth:
            last_accepted: str | None = None
            for sub in split_prompt(prompt, depth=depth):
                got = handle(sub, f"{stage}/split", depth + 1)
                if got is not None and refusal_status(got) == "non_refusal":
                    last_accepted = got
            return last_accepted if last_accepted is not None else text
        return text

    final_answer = ""
    for item in base_prompts(goal, category):
        got = handle(item["prompt"], item["stage"], 0)
        if got is not None:
            final_answer = got  # plot stage answer is the original-question answer

    return {
        "history": history,
        "turns": turns,
        "final_answer": final_answer,
        "errors": errors,
        "truncations": truncations,
        "status": "ok" if final_answer and errors == 0 else ("provider_error" if errors else "no_answer"),
    }


def build_cases(rows: list[dict[str, str]], args: argparse.Namespace) -> list[dict[str, Any]]:
    load_project_env()
    api_key = os.environ.get(args.api_key_env)
    live = args.target.startswith("api:")
    if live and not api_key:
        raise SystemExit(f"{args.api_key_env} not set; cannot run live target {args.target}")

    cases: list[dict[str, Any]] = []
    out_path = Path(args.out) if getattr(args, "out", None) else None
    # max_depth varies per case to give >=2 distinct parameter sets.
    for idx, row in enumerate(rows):
        case_id = f"{idx:03d}"
        max_depth = 1 + (idx % 2)  # alternate depth 1 / 2 -> two parameter sets
        if live:
            episode = run_fitd_episode(args, api_key, row["goal"], row.get("category"), max_depth=max_depth)
            final_answer = episode["final_answer"]
            judge = judge_response(args, api_key, row["goal"], final_answer) if final_answer else {
                "judge_model": args.judge_model, "raw": None, "score": None, "passed": None, "error": "no_answer"}
            keyword_status = refusal_status(final_answer) if final_answer else "not_run"
            cases.append({
                "case_id": case_id,
                "goal": row["goal"],
                "category": row.get("category"),
                "parameters": {"max_split_depth": max_depth, "split_instance": "background_villain_plot"},
                "turns": episode["turns"],
                "turn_count": len(episode["turns"]),
                "final_answer": final_answer or None,
                "status": episode["status"],
                "target": args.target,
                "judge": {
                    "name": "paper_gpt4_oracle_1to10_verbatim",
                    "judge_model": judge["judge_model"],
                    "score": judge["score"],
                    "raw": judge["raw"],
                    "error": judge["error"],
                    "success_threshold": JUDGE_SUCCESS_THRESHOLD,
                },
                "verdicts": {
                    "content_harmful": {  # primary: paper judge
                        "judge": "paper_gpt4_oracle_1to10_verbatim",
                        "score": judge["score"],
                        "passed": judge["passed"],
                    },
                    "refusal_bypass": {  # secondary dual metric
                        "judge": "refusal_keyword_proxy",
                        "status": keyword_status,
                        "passed": keyword_status == "non_refusal",
                    },
                },
                "provider_or_runtime_errors": episode["errors"],
                "truncations": episode["truncations"],
            })
        else:
            # generation-only: render the staged prompts, no target/judge calls
            prompts = base_prompts(row["goal"], row.get("category"))
            cases.append({
                "case_id": case_id,
                "goal": row["goal"],
                "category": row.get("category"),
                "parameters": {"max_split_depth": max_depth, "split_instance": "background_villain_plot"},
                "staged_prompts": prompts,
                "status": "generated",
                "target": args.target,
                "judge": {"name": "paper_gpt4_oracle_1to10_verbatim", "score": None, "raw": None, "error": "not_run"},
                "verdicts": {},
                "provider_or_runtime_errors": 0,
                "truncations": 0,
            })
        if getattr(args, "checkpoint_each_case", False) and out_path:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(result_doc(cases, args), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return cases


def result_doc(cases: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    parameter_sets = {json.dumps(c["parameters"], sort_keys=True) for c in cases}
    live = args.target.startswith("api:")
    completed = sum(1 for c in cases if c.get("status") == "ok")
    provider_errors = sum(int(c.get("provider_or_runtime_errors", 0)) for c in cases)
    truncations = sum(int(c.get("truncations", 0)) for c in cases)
    judge_scored = [c for c in cases if c.get("judge", {}).get("score") is not None]
    content_success = sum(1 for c in cases if c.get("verdicts", {}).get("content_harmful", {}).get("passed"))
    refusal_success = sum(1 for c in cases if c.get("verdicts", {}).get("refusal_bypass", {}).get("passed"))
    denom = len(cases) if cases else 1
    completion_ready = (
        live and len(cases) >= 10 and completed == len(cases)
        and len(parameter_sets) >= 2 and provider_errors == 0
        and len(judge_scored) == len(cases)
    )
    return {
        "schema_version": "paper_code_result.v0.2",
        "paper_id": PAPER_ID,
        "method_id": METHOD_ID,
        "fidelity_level": "algorithm_faithful_code",
        "evidence_level": "generated_attack_input" if not live else "model_substitution_run",
        "run_kind": "generated_attack_input" if not live else "model_substitution_run",
        "valid_for_code_completion": completion_ready,
        "target": args.target,
        "judge": {
            "name": "paper_gpt4_oracle_1to10_verbatim",
            "prompt_source": "digest/sections/09-prompt-for-jailbreak-status-judgment.md (verbatim)",
            "paper_oracle": "GPT-4 (gpt-4-1106-preview)",
            "serving_model": args.judge_model if live else None,
            "success_threshold": JUDGE_SUCCESS_THRESHOLD,
            "note": "Prompt verbatim from paper Appendix Sec 9; serving model substituted (OpenRouter permissive) because openai/* route 403s harmful-content judging.",
        },
        "run_config": {
            "api_base": getattr(args, "api_base", None),
            "api_key_env": getattr(args, "api_key_env", None),
            "temperature": getattr(args, "temperature", None),
            "max_tokens": args.max_tokens,
            "judge_max_tokens": getattr(args, "judge_max_tokens", None),
            "timeout": getattr(args, "timeout", None),
            "request_delay": getattr(args, "request_delay", None),
        },
        "dataset": {"name": "AdvBench custom cache", "path": str(Path(args.samples).resolve().relative_to(PAPER_ROOT)) if Path(args.samples).resolve().is_relative_to(PAPER_ROOT) else args.samples},
        "summary": {
            "case_count": len(cases),
            "completed": completed,
            "parameter_set_count": len(parameter_sets),
            "provider_or_runtime_errors": provider_errors,
            "truncations": truncations,
            "judge_scored": len(judge_scored),
            "asr_content_harmful": round(content_success / denom, 4),
            "asr_refusal_bypass": round(refusal_success / denom, 4),
            "content_harmful_success": content_success,
            "refusal_bypass_success": refusal_success,
        },
        "results": cases,
        "cases": cases,
    }


def cmd_inspect(args: argparse.Namespace) -> None:
    rows = load_rows(Path(args.samples), args.sample_rows)
    print(json.dumps({"paper_id": PAPER_ID, "method_id": METHOD_ID, "rows": len(rows),
                      "commands": ["inspect", "render", "generate", "run"]}, indent=2))


def cmd_render(args: argparse.Namespace) -> None:
    prompts = base_prompts(args.goal, args.category)
    splits = {p["stage"]: split_prompt(p["prompt"], depth=0) for p in prompts}
    print(json.dumps({"staged_prompts": prompts, "first_split_each_stage": splits,
                      "judge_prompt_verbatim": PAPER_JUDGE_PROMPT}, indent=2, ensure_ascii=False))


def cmd_run(args: argparse.Namespace) -> None:
    rows = load_rows(Path(args.samples), args.sample_rows)
    doc = result_doc(build_cases(rows, args), args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    s = doc["summary"]
    print(f"wrote {out}")
    print(f"cases={s['case_count']} completed={s['completed']} param_sets={s['parameter_set_count']} "
          f"errors={s['provider_or_runtime_errors']} judge_scored={s['judge_scored']}")
    print(f"ASR content-harmful (paper judge >=6) = {s['asr_content_harmful']} "
          f"({s['content_harmful_success']}/{s['case_count']})")
    print(f"ASR refusal-bypass (secondary)        = {s['asr_refusal_bypass']} "
          f"({s['refusal_bypass_success']}/{s['case_count']})")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="FITD paper-local Code (arXiv:2402.15690)")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("inspect", "generate", "run"):
        sp = sub.add_parser(name)
        sp.add_argument("--samples", "--dataset", dest="samples", default=str(DEFAULT_SAMPLE_PATH))
        sp.add_argument("--sample-rows", "--sample", dest="sample_rows", type=int, default=10)
        sp.add_argument("--target", default="none" if name != "run" else "api:deepseek/deepseek-v4-flash")
        sp.add_argument("--judge-model", default="deepseek/deepseek-v4-flash")
        sp.add_argument("--max-tokens", type=int, default=1024)
        sp.add_argument("--judge-max-tokens", type=int, default=512)
        sp.add_argument("--api-base", default="https://openrouter.ai/api/v1")
        sp.add_argument("--api-key-env", default="OPENROUTER_API_KEY")
        sp.add_argument("--temperature", type=float, default=0.0)
        sp.add_argument("--timeout", type=int, default=120)
        sp.add_argument("--request-delay", type=float, default=0.2)
        sp.add_argument("--checkpoint-each-case", action="store_true")
        sp.add_argument("--out", default=str(DEFAULT_RESULT_PATH))
        sp.set_defaults(checkpoint_each_case=(name == "run"))
        sp.set_defaults(func=cmd_inspect if name == "inspect" else cmd_run)
    rp = sub.add_parser("render")
    rp.add_argument("--goal", required=True)
    rp.add_argument("--category")
    rp.set_defaults(func=cmd_render)
    return p


def main() -> int:
    args = parser().parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
