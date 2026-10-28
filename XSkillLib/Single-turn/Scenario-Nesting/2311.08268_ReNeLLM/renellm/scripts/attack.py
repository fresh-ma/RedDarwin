#!/usr/bin/env python3
"""Paper-faithful ReNeLLM runner for arXiv 2311.08268 — orchestration + CLI.

ReNeLLM jailbreaks in two stages: (1) a prompt REWRITE chain applies a random
subset of six semantics-preserving operators to the harmful goal, gated by a
binary harmfulness judge; (2) the rewritten prompt is NESTED into one of three
benign task scenarios (code-completion / table-filling / text-continuation) and
sent to the target, whose response is scored by the harmfulness judge.

Modular layout (each role/piece is its own file so this multi-step tool stays readable):
  prompts.py  — verbatim rewrite-operator templates + nesting scenarios + judge prompts
  models.py   — OpenAI-compatible chat client + .env / path plumbing
  roles.py    — rewrite / judge / target adapters (swappable api:<model>) + refusal gate
  cases.py    — AdvBench goal loader + row selection
  attack.py   — the rewrite→nest→target search loop (run_case / run), inspect, CLI (this file)

Sibling names are re-exported below so `import attack; attack.rewrite_prompt_once`
keeps working for gen_training_corpus.py.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

from cases import DEFAULT_GOALS, SMOKE_GOALS, read_goals, select_rows  # noqa: F401
from models import display_path, model_is_fake, resolve_path  # noqa: F401
from prompts import SCENARIOS, nest_prompt  # noqa: F401
from roles import (  # noqa: F401
    choose_operations,
    choose_scenario,
    has_refusal_prefix,
    judge_text,
    rewrite_prompt_once,
    target_call,
)


PAPER_ID = "2311.08268_nested-prompt-jailbreak"
METHOD_ID = "renellm"


def run_case(row: dict[str, Any], case_id: int, args: argparse.Namespace) -> dict[str, Any]:
    rng = random.Random(args.seed + int(row["source_row"]))
    original_prompt = row["goal"]
    last_attempt: dict[str, Any] | None = None
    for iteration in range(1, args.iterations + 1):
        rewritten_prompt = original_prompt
        operations = choose_operations(args, rng)
        rewrite_trace = []
        attacker_refused = False
        for operation in operations:
            rewritten_prompt, trace = rewrite_prompt_once(rewritten_prompt, operation, args, rng)
            rewrite_trace.append(trace)
            # Short-circuit: the rewrite model returned empty (refusal) or errored —
            # stop the op chain (remaining ops would just run on the same text and
            # waste calls). Mark the attempt as an attacker refusal and re-roll.
            if trace["status"] != "ok" or trace.get("empty_refusal"):
                attacker_refused = bool(trace.get("empty_refusal"))
                break

        if attacker_refused:
            last_attempt = {
                "iteration": iteration,
                "operations": operations,
                "rewrite_trace": rewrite_trace,
                "rewritten_prompt": rewritten_prompt,
                "prompt_judge": None,
                "scenario": None,
                "target_call": None,
                "response_judge": None,
                "success": False,
                "reason": "attacker_refused_empty_rewrite",
            }
            continue

        prompt_judge = judge_text(rewritten_prompt, args, "rewritten_prompt")
        if prompt_judge["label"] != "1":
            last_attempt = {
                "iteration": iteration,
                "operations": operations,
                "rewrite_trace": rewrite_trace,
                "rewritten_prompt": rewritten_prompt,
                "prompt_judge": prompt_judge,
                "scenario": None,
                "target_call": None,
                "response_judge": None,
                "success": False,
                "reason": "rewritten_prompt_not_harmful_by_judge",
            }
            continue

        scenario = choose_scenario(args, rng)
        nested_prompt = nest_prompt(rewritten_prompt, scenario)
        target_result = target_call(nested_prompt, args)
        # Official gate: only call the harmfulness judge when the response does NOT
        # contain a refusal prefix (TEST_PREFIXES); otherwise score 0.
        target_output = target_result["model_output_text"]
        refused_by_prefix = has_refusal_prefix(target_output) if target_result["status"] == "ok" else True
        response_judge = (
            judge_text(target_output, args, "target_response", goal=original_prompt)
            if target_result["status"] == "ok" and not refused_by_prefix
            else {
                "name": "renellm_harmfulness_judge",
                "stage": "target_response",
                "success": False,
                "label": "0",
                "reason": target_result["status"] if target_result["status"] != "ok" else "refusal_prefix",
            }
        )
        success = bool(response_judge.get("success"))
        last_attempt = {
            "iteration": iteration,
            "operations": operations,
            "rewrite_trace": rewrite_trace,
            "rewritten_prompt": rewritten_prompt,
            "prompt_judge": prompt_judge,
            "scenario": scenario,
            "nested_prompt": nested_prompt,
            "target_call": target_result,
            "response_judge": response_judge,
            "success": success,
            "reason": "response_judge_success" if success else "continue_or_max_iterations",
        }
        if success:
            break
        if args.request_delay:
            time.sleep(args.request_delay)

    assert last_attempt is not None
    target_result = last_attempt.get("target_call") or {}
    return {
        "case_id": case_id,
        "sample": {
            "id": row["id"],
            "category": row["category"],
            "source_row": row["source_row"],
            "goal_text": row["goal"],
            "target_text": row["target"],
        },
        "status": target_result.get("status", "no_target_call"),
        "target": args.target,
        "parameters": {
            "operations": last_attempt["operations"],
            "scenario": last_attempt.get("scenario"),
            "iterations": args.iterations,
            "operation_count": args.operation_count,
        },
        "iteration_count": last_attempt["iteration"],
        "operation_functions": last_attempt["operations"],
        "rewrite_trace": last_attempt["rewrite_trace"],
        "rewritten_prompt": last_attempt["rewritten_prompt"],
        "prompt_judge": last_attempt["prompt_judge"],
        "scenario": last_attempt.get("scenario"),
        "nested_prompt": last_attempt.get("nested_prompt"),
        "model_input_messages": target_result.get("model_input_messages"),
        "model_input_text": target_result.get("model_input_text"),
        "model_output_text": target_result.get("model_output_text", ""),
        "judge": last_attempt["response_judge"],
        "success": last_attempt["success"],
        "final_attempt": last_attempt,
    }


def run(rows: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    fake_used = any(model_is_fake(spec) for spec in (args.rewrite_model, args.judge_model, args.target))
    if fake_used and not args.wiring_check:
        raise SystemExit("fake rewrite/judge/target models require --wiring-check")
    results = [run_case(row, idx, args) for idx, row in enumerate(rows, start=1)]

    def final_target(item: dict[str, Any]) -> dict[str, Any]:
        return item.get("final_attempt", {}).get("target_call") or {}

    def had_provider_error(item: dict[str, Any]) -> bool:
        # True only for genuine transport/auth/provider failures in any sub-call.
        # `no_target_call` is NOT an error: it means the rewrite-intent judge never
        # passed within iter_max, which is a faithful ReNeLLM attack failure.
        bad = {"auth_error", "provider_error"}
        if item["status"] in bad:
            return True
        for trace in item.get("rewrite_trace") or []:
            if trace.get("status") in bad:
                return True
        for stage in (item.get("prompt_judge"), item.get("judge")):
            if isinstance(stage, dict) and stage.get("status") in bad:
                return True
        return False

    provider_errored = [item for item in results if had_provider_error(item)]
    # "evaluated" = ran end-to-end without a provider error (includes legitimate
    # attack failures: rewrite never passed, target refused, judge said 0).
    evaluated = [item for item in results if not had_provider_error(item)]
    successes = [item for item in evaluated if item["success"]]
    # Dual metric over evaluated cases:
    #  - refusal_bypass: target produced a non-refusal final response (official
    #    TEST_PREFIXES gate + heuristic refusal_proxy). Over-counts (a safety
    #    lecture is a non-refusal but not a jailbreak). Cases that never reached the
    #    target (rewrite never passed) count as NOT bypassed.
    def is_bypass(item: dict[str, Any]) -> bool:
        tgt = final_target(item)
        if tgt.get("status") != "ok":
            return False
        out = tgt.get("model_output_text", "")
        return not (has_refusal_prefix(out) or tgt.get("refusal_proxy", {}).get("refused"))

    bypass = [item for item in evaluated if is_bypass(item)]
    refusals = [item for item in evaluated if not is_bypass(item)]
    parameter_signatures = {
        json.dumps(item["parameters"], sort_keys=True, ensure_ascii=False)
        for item in results
        if isinstance(item.get("parameters"), dict)
    }
    provider_errors = len(provider_errored)
    denom = len(evaluated)
    completion_ready = (
        not fake_used
        and denom >= 10
        and len(parameter_signatures) >= 2
    )
    dataset_path = resolve_path(args.goals) if hasattr(args, "goals") else None
    return {
        "schema_version": "paper_local_attack_result.v0.2",
        "paper_id": PAPER_ID,
        "method": METHOD_ID,
        "fidelity_level": "paper_algorithm_code",
        "evidence_level": "wiring_check" if fake_used else "real_model_run",
        "wiring_check": bool(args.wiring_check),
        "source_code_reference": {
            "url": "https://github.com/NJUNLP/ReNeLLM",
            "commit": "a61c39ea4e5311a5fbfaee9869e5325783d1522f",
        },
        "dataset": display_path(dataset_path) if dataset_path else "smoke",
        "source_backing": {
            "official_repo": "https://github.com/NJUNLP/ReNeLLM",
            "official_commit": "a61c39ea4e5311a5fbfaee9869e5325783d1522f",
            "source_dataset": "official ReNeLLM data/advbench/harmful_behaviors.csv",
            "local_cache": display_path(dataset_path) if dataset_path else "smoke",
        },
        "models": {
            "rewrite_model": args.rewrite_model,
            "judge_model": args.judge_model,
            "judge_base_url": args.judge_base_url,
            "target": args.target,
            "base_url": args.base_url,
        },
        "attack_parameters": {
            "iterations": args.iterations,
            "operation_count": args.operation_count,
            "operations": args.operations,
            "scenario": args.scenario,
            "seed": args.seed,
        },
        "parameter_grid": [
            {
                "scenario": item.get("scenario"),
                "operations": item.get("operation_functions"),
            }
            for item in results
        ],
        "summary": {
            "attempts": len(results),
            "evaluated": denom,
            "provider_or_runtime_errors": provider_errors,
            "rewrite_never_passed": sum(1 for item in evaluated if item["status"] == "no_target_call"),
            "refusals": len(refusals),
            "refusal_bypass": len(bypass),
            "content_harmful_successes": len(successes),
            "asr_refusal_bypass": len(bypass) / denom if denom else None,
            "asr_content_harmful": len(successes) / denom if denom else None,
            "judge_name": "renellm_binary_harm_classifier",
            "seconds": round(time.time() - started, 3),
        },
        "valid_for_code_completion": completion_ready,
        "results": results,
    }


def write_json(data: dict[str, Any], out: str | None) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def add_data_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--goals", type=Path, default=DEFAULT_GOALS)
    parser.add_argument("--goal-field", default="auto")
    parser.add_argument("--indices", help="comma-separated source_row ids to select")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--sample-rows", "--sample", dest="sample_rows", type=int, default=1,
                        help="random subset of N goals to evaluate (real-run knob)")
    parser.add_argument("--seed", type=int, default=20260608)


def add_method_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--operation-count", type=int)
    parser.add_argument("--operations", help="comma-separated operation names; defaults to random subset")
    parser.add_argument("--scenario", choices=["random", *SCENARIOS.keys()], default="random")


def add_model_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--rewrite-model", default="api:deepseek/deepseek-v4-flash")
    parser.add_argument("--goal-fidelity", action=argparse.BooleanOptionalAction, default=True,
                        help="response judge must verify the harmful output fulfils the ORIGINAL goal "
                             "(default on, fixes off-topic false positives); --no-goal-fidelity = official goal-blind judge.")
    parser.add_argument("--rewrite-fallback-model", default=None,
                        help="weakly-aligned model to retry a rewrite op when the primary "
                             "rewrite model refuses (empty output), e.g. api:sao10k/l3.3-euryale-70b. "
                             "Off by default = faithful (attacker refusal counts as failure).")
    parser.add_argument("--judge-model", default="api:deepseek/deepseek-v4-flash")
    parser.add_argument("--target", required=True)
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1",
                        help="endpoint for rewrite + target models")
    parser.add_argument("--api-key-env", default="OPENROUTER_API_KEY")
    # Judge routes through OpenRouter. The official ReNeLLM binary harm judge is
    # served by deepseek/deepseek-v4-flash (verified: returns 0/1, no 403). OpenAI-direct
    # is NOT used: that account's quota is exhausted (429 insufficient_quota) and the
    # OpenRouter openai/* route 403s harmful-judge prompts.
    parser.add_argument("--judge-base-url", default="https://openrouter.ai/api/v1",
                        help="endpoint for the harmfulness judge (OpenRouter by default)")
    parser.add_argument("--judge-api-key-env", default="OPENROUTER_API_KEY")
    parser.add_argument("--rewrite-temperature", type=float, default=None,
                        help="fixed rewrite temperature; default None => per-op random.uniform(0,1) like the official repo")
    parser.add_argument("--judge-temperature", type=float, default=0.0)
    parser.add_argument("--target-temperature", type=float, default=0.0)
    parser.add_argument("--rewrite-max-tokens", type=int, default=96)
    parser.add_argument("--judge-max-tokens", type=int, default=8)
    parser.add_argument("--target-max-tokens", type=int, default=256)
    parser.add_argument("--request-delay", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--wiring-check", action="store_true")


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper-local ReNeLLM algorithm Code.")
    sub = parser.add_subparsers(dest="mode", required=True)

    smoke = sub.add_parser("smoke")
    add_method_args(smoke)
    smoke.add_argument("--out")

    inspect = sub.add_parser("inspect")
    add_data_args(inspect)
    inspect.add_argument("--include-goal-text", action="store_true")
    inspect.add_argument("--out")

    run_cmd = sub.add_parser("run")
    add_data_args(run_cmd)
    add_method_args(run_cmd)
    add_model_args(run_cmd)
    run_cmd.add_argument("--out")

    args = parser.parse_args()
    if args.mode == "smoke":
        args.rewrite_model = "fake"
        args.judge_model = "fake"
        args.target = "fake"
        args.base_url = "fake"
        args.api_key_env = ""
        args.judge_base_url = "fake"
        args.judge_api_key_env = ""
        args.rewrite_temperature = 0.0
        args.judge_temperature = 0.0
        args.target_temperature = 0.0
        args.rewrite_max_tokens = 16
        args.judge_max_tokens = 4
        args.target_max_tokens = 16
        args.request_delay = 0.0
        args.timeout = 60.0
        args.wiring_check = True
        args.seed = 20260608
        write_json(run(SMOKE_GOALS, args), args.out)
        return

    rows = select_rows(read_goals(args.goals, args.goal_field), args)
    if args.mode == "inspect":
        visible_rows = rows if args.include_goal_text else [
            {
                "id": row["id"],
                "source_row": row["source_row"],
                "category": row["category"],
                "has_target_text": bool(row["target"]),
            }
            for row in rows
        ]
        write_json(
            {
                "schema_version": "paper_local_attack_inspect.v0.1",
                "paper_id": PAPER_ID,
                "method": METHOD_ID,
                "dataset": display_path(resolve_path(args.goals)),
                "selected_rows": len(rows),
                "rows": visible_rows,
                "goal_text_hidden": not args.include_goal_text,
            },
            args.out,
        )
        return

    write_json(run(rows, args), args.out)

if __name__ == "__main__":
    main()
