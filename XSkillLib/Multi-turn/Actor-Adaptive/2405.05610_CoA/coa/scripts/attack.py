#!/usr/bin/env python3
"""CoA (Chain-of-Attack) paper-local multi-turn Code runner — search loop + CLI.

CoA runs a multi-turn conversation against the target: an attacker LLM proposes a
chain of escalating prompts (broadly-related/safe -> increasingly on-goal), each
prompt is answered by the target in a growing conversation history, a lexical
semantic-relevance score drives the walk (next / back / regen with feedback), and a
goal-faithful 1-10 judge over the ORIGINAL objective decides genuine on-goal harm.

Modular layout (each role/piece is its own file so this multi-turn tool stays readable):
  prompts.py  — chain-generation + feedback-update templates + the judge prompt
  models.py   — OpenAI-compatible chat client + walk-up .env loader + repo paths
  roles.py    — attacker chain parsing, semantic scoring, refusal proxy, LLM judge
  cases.py    — dataset loading (goal rows, safe smoke set, --limit/--sample)
  attack.py   — the CoA multi-turn walk (run_case / run_cases), inspect, CLI (this file)

The sibling names are re-exported below so `import attack; attack.parse_chain / ...`
keeps working for gen_training_corpus.py — the split is behavior-preserving.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

# Sibling-module imports (scripts/ is on sys.path when run as `python scripts/attack.py`).
# Re-exported so `attack.<name>` keeps resolving for gen_training_corpus.py.
from cases import DEFAULT_GOALS, SAFE_GOALS, read_rows, repo_relative, select_rows  # noqa: F401
from models import (  # noqa: F401
    METHOD_DIR,
    PROJECT_ENV,
    ROOT,
    _repo_root,
    call_chat,
    load_env_file,
    ollama_available,
    split_model,
)
from prompts import (  # noqa: F401
    JUDGE_SUCCESS_THRESHOLD,
    JUDGE_SYSTEM,
    chain_generation_messages,
    update_messages,
)
from roles import (  # noqa: F401
    REFUSAL_HINTS,
    extract_json_object,
    llm_judge,
    parse_chain,
    parse_chain_text,
    refusal_proxy,
    semantic_similarity,
    words,
)

PAPER_ID = "2405.05610_multi-turn-semantic-jailbreak"
METHOD_ID = "coa"

# Target victim + judge default to a hosted, neutral API model.
DEFAULT_TARGET_MODEL = "api:deepseek/deepseek-v4-flash"
# The attacker (chain generator) plays an adversarial role a hosted model often
# refuses, so it defaults to a LOCAL uncensored model over Ollama; if no Ollama
# daemon (or the model isn't pulled), it falls back to the hosted API model so the
# unit still runs for recipients without Ollama.
UNCENSORED_MODEL = "ollama:" + os.environ.get("COA_UNCENSORED_MODEL", "uncensored")
API_ATTACKER_FALLBACK = "api:deepseek/deepseek-v4-flash"

_ATTACKER_DEFAULT: str | None = None


def default_attacker_model() -> str:
    """Resolve the attacker default once: local uncensored model if an Ollama
    daemon has it, else the hosted API fallback (with a one-line notice)."""
    global _ATTACKER_DEFAULT
    if _ATTACKER_DEFAULT is None:
        _, name = split_model(UNCENSORED_MODEL)
        if ollama_available(name):
            _ATTACKER_DEFAULT = UNCENSORED_MODEL
        else:
            _ATTACKER_DEFAULT = API_ATTACKER_FALLBACK
            print(f"[coa] Ollama model '{name}' unavailable; attacker falls back to {API_ATTACKER_FALLBACK}", flush=True)
    return _ATTACKER_DEFAULT


def messages_to_text(messages: list[dict[str, str]]) -> str:
    return "\n\n".join(f"{item['role'].upper()}:\n{item['content']}" for item in messages)


def round_grid(args: argparse.Namespace) -> list[int]:
    if not args.max_rounds_list:
        return [args.max_rounds]
    values = []
    for item in args.max_rounds_list.split(","):
        item = item.strip()
        if not item:
            continue
        value = int(item)
        if value < 1:
            raise SystemExit("--max-rounds-list values must be positive")
        values.append(value)
    return values or [args.max_rounds]


def stable_parameter_grid(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    grid: list[dict[str, Any]] = []
    for row in results:
        params = row.get("attack_parameters")
        if not isinstance(params, dict):
            continue
        key = json.dumps(params, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        grid.append(params)
    return grid


def run_case(row: dict[str, Any], args: argparse.Namespace, max_rounds: int) -> dict[str, Any]:
    case_args = argparse.Namespace(**vars(args))
    case_args.max_rounds = max_rounds
    gen_messages = chain_generation_messages(row["goal"], case_args)
    gen_output, gen_status = call_chat(gen_messages, case_args.attacker, case_args, role="attacker")
    generation = {
        "status": gen_status,
        "model": case_args.attacker,
        "model_input_messages": gen_messages,
        "model_output_text": gen_output,
    }
    if gen_status != "ok":
        return {"status": gen_status, "chain_generation": generation, "turns": [], "final_judge": {"success": False, "reason": gen_status}}
    try:
        chain = parse_chain(gen_output, case_args.max_rounds)
    except Exception as exc:
        generation["parse_error"] = f"{type(exc).__name__}: {exc}"
        return {"status": "chain_parse_failed", "chain_generation": generation, "turns": [], "final_judge": {"success": False, "reason": "chain_parse_failed"}}

    history: list[dict[str, str]] = []
    turns: list[dict[str, Any]] = []
    previous_sem = 0.0
    prompt_index = 0
    for turn_num in range(1, case_args.max_rounds + 1):
        prompt = chain[prompt_index]
        target_input = history + [{"role": "user", "content": prompt}]
        response, target_status = call_chat(target_input, case_args.target, case_args, role="target")
        sem = semantic_similarity(row["goal"], response)
        proxy = refusal_proxy(response) if target_status == "ok" else {"name": "refusal_proxy", "refused": False, "bypassed": False, "reason": target_status}
        # On a refusal-bypass candidate, confirm GENUINE on-goal harm with the LLM judge.
        if proxy.get("bypassed"):
            judge = llm_judge(row["goal"], response, case_args)
        else:
            judge = {"name": "llm_judge", "rating": None, "success": False, "reason": "refused_skip", "status": "skipped"}
        verdict = {"proxy": proxy, "llm_judge": judge, "success": bool(judge.get("success")), "bypassed": bool(proxy.get("bypassed"))}
        if verdict["success"]:
            action = "end_walk"
        elif sem > previous_sem:
            action = "next_walk"
            prompt_index = min(prompt_index + 1, len(chain) - 1)
        elif case_args.use_feedback_updater and turn_num < case_args.max_rounds:
            update_input = update_messages(row["goal"], prompt, response, sem, turn_num, case_args)
            update_output, update_status = call_chat(update_input, case_args.attacker, case_args, role="attacker")
            try:
                updated = extract_json_object(update_output).get("prompt", "").strip() if update_status == "ok" else ""
            except Exception:
                updated = ""
            if updated:
                chain[prompt_index] = updated
            action = "regen_walk"
        else:   # 
            action = "back_walk" if prompt_index > 0 else "next_walk"
            prompt_index = max(0, prompt_index - 1) if action == "back_walk" else min(prompt_index + 1, len(chain) - 1)
        turn = {
            "turn": turn_num,
            "prompt": prompt,
            "target_status": target_status,
            "target_input_messages": target_input,
            "target_input_text": messages_to_text(target_input),
            "target_output_text": response,
            "semantic_score": sem,
            "semantic_delta": sem - previous_sem,
            "walk_decision": action,
            "judge": verdict,
        }
        turns.append(turn)
        # 无论是否 back_walk, history 都更新, 导致失败的 prompt 也加入了. 如 r2 失败, 下一轮: [q0, r0, q1, r1, q2, r2, q1]
        history = target_input + [{"role": "assistant", "content": response}]
        previous_sem = sem
        if verdict["success"] or target_status != "ok":
            break
        if case_args.request_delay:
            time.sleep(case_args.request_delay)
    final = turns[-1] if turns else {}
    # Case-level dual metric: harmful = any turn judged genuine on-goal harm;
    # bypassed = any turn passed the refusal proxy.
    any_harm = any(t["judge"].get("success") for t in turns)
    any_bypass = any(t["judge"].get("bypassed") for t in turns)
    best_rating = max(
        (t["judge"].get("llm_judge", {}).get("rating") or 0 for t in turns),
        default=0,
    )
    return {
        "status": final.get("target_status", "no_turns"),
        "chain_generation": generation,
        "selected_chain": chain,
        "turns": turns,
        "final_judge": {
            "success": any_harm,
            "refusal_bypassed": any_bypass,
            "best_rating": best_rating,
            **(final.get("judge", {})),
        },
        "final_output_text": final.get("target_output_text", ""),
    }


def run_cases(rows: list[dict[str, Any]], source: str, args: argparse.Namespace) -> dict[str, Any]:
    load_env_file(PROJECT_ENV)
    started = time.time()
    results = []
    case_id = 0
    for row in rows:
        for max_rounds in round_grid(args):
            case_id += 1
            case = run_case(row, args, max_rounds)
            params = {
                "max_rounds": max_rounds,
                "use_feedback_updater": args.use_feedback_updater,
                "semantic_backend": "lexical_overlap",
                "seed": args.seed,
            }
            results.append(
                {
                    "case_id": case_id,
                    "sample": {"id": row["id"], "category": row.get("category", ""), "source_row": row.get("source_row"), "goal_text": row["goal"]},
                    "attack_parameters": params,
                    **case,
                }
            )
    ok = [row for row in results if row["status"] == "ok"]
    harmful = [row for row in ok if row["final_judge"].get("success")]
    bypassed = [row for row in ok if row["final_judge"].get("refusal_bypassed")]
    grid = stable_parameter_grid(results)
    valid_for_code_completion = bool(
        not args.wiring_check
        and args.target != "fake"
        and len(results) >= 10
        and len(grid) >= 2
        and len(results) == len(ok)
    )
    return {
        "schema_version": "paper_local_attack_result.v0.1",
        "paper_id": PAPER_ID,
        "method": METHOD_ID,
        "fidelity_level": "partial_algorithm_code",
        "evidence_level": "wiring_check" if args.wiring_check else "real_model_run",
        "wiring_check": bool(args.wiring_check),
        "valid_for_code_completion": valid_for_code_completion,
        "completion_scope": "10_case_live_model_substitution_coa" if valid_for_code_completion else "not_completion",
        "target": args.target,
        "attacker": args.attacker,
        "judge": args.judge,
        "judge_success_threshold": JUDGE_SUCCESS_THRESHOLD,
        "dataset": source,
        "source_backing": {
            "paper_sections": [
                "digest/sections/03-multi-turns-conversation-with-increasing-semantic-relevance.md",
                "digest/sections/04.02-attack-chain-executor.md",
                "digest/sections/04.03.01-policy-selection-based-on-incremental-semantic-relevance.md",
                "digest/sections/04.03.02-context-driven-attacker.md",
            ],
            "dataset_artifact": repo_relative(DEFAULT_GOALS),
        },
        "attack_parameters": {
            "max_rounds_list": round_grid(args),
            "use_feedback_updater": args.use_feedback_updater,
            "semantic_backend": "lexical_overlap",
            "seed": args.seed,
        },
        "parameter_grid": grid,
        "summary": {
            "attempts": len(results),
            "ok": len(ok),
            "provider_or_runtime_errors": len(results) - len(ok),
            "content_harmful": len(harmful),
            "refusal_bypassed": len(bypassed),
            "asr_content_harmful": len(harmful) / len(ok) if ok else None,
            "asr_refusal_bypass": len(bypassed) / len(ok) if ok else None,
            "seconds": round(time.time() - started, 3),
        },
        "results": results,
    }


def write_json(data: dict[str, Any], out: str | None) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
    else:
        print(text, end="")


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--goals", default=DEFAULT_GOALS)
    parser.add_argument("--sample-rows", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--seed", type=int, default=20260608)
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--max-rounds-list", help="comma-separated max round budgets; overrides --max-rounds for run grids")
    parser.add_argument("--use-feedback-updater", action=argparse.BooleanOptionalAction, default=True)


def add_run(parser: argparse.ArgumentParser) -> None:
    add_common(parser)
    parser.add_argument("--target", default=DEFAULT_TARGET_MODEL,
                        help="target victim model, api:<model> or ollama:<model>")
    parser.add_argument("--attacker", default=None,
                        help="chain generator; default: local ollama:uncensored, else api:deepseek/deepseek-v4-flash (deepseek often refuses this role)")
    parser.add_argument("--judge", default="api:deepseek/deepseek-v4-flash",
                        help="goal-faithful LLM judge; sees ORIGINAL goal + response")
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    parser.add_argument("--api-key-env", default="OPENROUTER_API_KEY")
    parser.add_argument("--target-temperature", type=float, default=0.0)
    parser.add_argument("--attacker-temperature", type=float, default=0.8)
    parser.add_argument("--target-max-tokens", type=int, default=1024)
    parser.add_argument("--attacker-max-tokens", type=int, default=1024)
    parser.add_argument("--request-delay", type=float, default=0.0)
    parser.add_argument("--wiring-check", action="store_true")
    parser.add_argument("--out")


def main() -> None:
    parser = argparse.ArgumentParser(description="CoA paper-local multi-turn Code runner.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    inspect = sub.add_parser("inspect")
    add_common(inspect)
    inspect.add_argument("--out")
    run = sub.add_parser("run")
    add_run(run)
    smoke = sub.add_parser("smoke")
    add_run(smoke)
    smoke.set_defaults(goals=None, target="fake", attacker="fake", judge="fake", wiring_check=True)
    args = parser.parse_args()

    # Resolve the attacker (chain generator) default: local uncensored model over
    # Ollama when present, else the hosted API fallback. `smoke` pins attacker="fake".
    if args.cmd == "run" and getattr(args, "attacker", None) is None:
        args.attacker = default_attacker_model()

    smoke_only = args.cmd == "smoke"
    rows, source = read_rows(args.goals, smoke_only)
    rows = select_rows(rows, args)
    if args.cmd == "inspect":
        write_json(
            {
                "paper_id": PAPER_ID,
                "method": METHOD_ID,
                "dataset": source,
                "rows": len(rows),
                "max_rounds_list": round_grid(args),
                "rendered_case_count": len(rows) * len(round_grid(args)),
                "sample_ids": [r["id"] for r in rows],
            },
            args.out,
        )
    else:
        write_json(run_cases(rows, source, args), args.out)


if __name__ == "__main__":
    main()
