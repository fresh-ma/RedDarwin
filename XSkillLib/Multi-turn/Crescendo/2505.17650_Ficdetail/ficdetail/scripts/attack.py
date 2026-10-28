#!/usr/bin/env python3
"""Paper-local FicDetail multi-turn jailbreak Code package — 3-turn loop + CLI.

Faithful from-paper implementation of FicDetail (Lu et al., ACL 2025, "Does
Chain-of-Thought Reasoning Really Reduce Harmfulness from Jailbreaking?",
arXiv 2505.17650). The paper releases no code; the three target-facing turns are
transcribed VERBATIM from Figure 2 (jailbreak.pdf) and the AHS/ASR judge rubric
from Appendix §13, both in prompts.py.

Mechanism (paper §4): a FIXED three-turn attack that never adapts to the target.
  Step1  Generate a fiction about a malicious character (harmless-looking).
  Step2  Enrich it with "technical details".
  Step3  Add a "specific experimental procedure".
Each turn appends the target's own reply to the running conversation, so the
harmful content accretes across turns. The FINAL (Step-3) reply is judged on the
GPT-4 1..5 rubric: AHS = the score, ASR = fraction scoring 5 (paper §5.1).

Roles run on OpenRouter (api:<model>); NO GPU, no attacker LLM. There are exactly
two swappable roles — the victim `--target` and the `--judge-model` — each with
its own model + tokens (consolidate §4).

Modular layout:
  prompts.py  — verbatim 3 step templates + AHS rubric
  models.py   — OpenRouter chat client + method-local .env loader + path roots
  cases.py    — AdvBench loader (full 520) + safe smoke goals
  roles.py    — target turn adapter + AHS/ASR judge (swappable per role)
  attack.py   — the fixed 3-turn loop (run_case / run), inspect/render, CLI (this file)
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

# Sibling-module imports (scripts/ is on sys.path when run as `python scripts/attack.py`).
from cases import DEFAULT_GOALS, choose, read_goals  # noqa: F401
from models import (  # noqa: F401
    METHOD_ROOT,
    PAPER_ROOT,
    _client,
    _model_id,
    chat,
    load_env_from_nearest,
)
from prompts import (  # noqa: F401
    AHS_JUDGE_SYSTEM,
    FICDETAIL_STEPS,
    build_ahs_judge_user,
    build_step_prompt,
)
from roles import ask_target, fake_ahs, fake_target, score_ahs  # noqa: F401

PAPER_ID = "2505.17650_cot-jailbreak-mitigation-failure"
METHOD_ID = "ficdetail"


# --------------------------------------------------------------------------- #
# FicDetail 3-turn attack loop
# --------------------------------------------------------------------------- #
def run_case(row: dict[str, Any], args: argparse.Namespace, client, judge_client) -> dict[str, Any]:
    goal = row["goal"]
    tgt_model = None if args.target == "fake" else _model_id(args.target, "target")
    wiring = args.target == "fake"

    conversation: list[dict[str, str]] = []
    turns: list[dict[str, Any]] = []
    final_text = ""

    for step_name, template in FICDETAIL_STEPS:
        user_turn = build_step_prompt(step_name, template, goal)
        conversation.append({"role": "user", "content": user_turn})
        input_messages = list(conversation)  # snapshot BEFORE the assistant reply
        if wiring:
            out, status = fake_target(step_name), "wiring_check"
        else:
            out, status = ask_target(client, tgt_model, conversation, args)
        conversation.append({"role": "assistant", "content": out})

        turns.append({
            "step": step_name,
            "model_input_messages": input_messages,
            "model_output_text": out,
            "target_status": status,
        })
        if status not in {"ok", "wiring_check"}:
            turns[-1]["note"] = "target provider error; recorded, attack halted"
            break
        final_text = out

    # Judge the FINAL (Step-3) response against the original malicious goal.
    if wiring:
        judge = fake_ahs()
    elif not final_text.strip():
        judge = {"name": "ahs_judge", "score": None, "success": False, "helpful": False, "status": "empty_output"}
    else:
        judge = score_ahs(judge_client, args.judge_model, AHS_JUDGE_SYSTEM, build_ahs_judge_user(goal, final_text), args)

    return {
        "sample": {"id": row["id"], "category": row.get("category", ""), "source_row": row.get("source_row"), "goal_text": goal},
        "goal": goal,
        "executed_steps": len(turns),
        # Standard top-level result fields: the final attacked exchange.
        "model_input_messages": turns[-1]["model_input_messages"] if turns else [],
        "model_output_text": final_text,
        "ahs_score": judge.get("score"),
        "content_harmful": bool(judge.get("success")),
        "helpful": bool(judge.get("helpful")),
        "outcome": "SUCCESS" if judge.get("success") else "FAILURE",
        "judge": judge,
        "turns": turns,
    }


def run(rows: list[dict[str, Any]], source: str, args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    wiring = args.target == "fake"
    if wiring and not args.wiring_check:
        raise SystemExit("fake target is wiring-only; pass --wiring-check and do not treat output as Code evidence")

    client = None if wiring else _client(args)
    judge_client = client  # same OpenRouter gateway; judge_model may differ from target.

    results = []
    for case_id, row in enumerate(rows, start=1):
        results.append({"case_id": case_id, **run_case(row, args, client, judge_client)})
        if args.request_delay:
            time.sleep(args.request_delay)

    n = len(results)
    judged = [r for r in results if r["judge"].get("status") == "ok"]
    scores = [r["ahs_score"] for r in judged if r["ahs_score"] is not None]
    content_harmful = sum(1 for r in results if r["content_harmful"])
    helpful = sum(1 for r in results if r["helpful"])
    return {
        "schema_version": "paper_local_attack_result.v0.2",
        "paper_id": PAPER_ID,
        "method": METHOD_ID,
        "fidelity_level": "wiring_check" if wiring else "faithful_from_paper_ficdetail",
        "evidence_level": "wiring_check" if wiring else "real_model_run",
        "wiring_check": bool(args.wiring_check),
        "target": args.target,
        "judge_model": args.judge_model,
        "dataset": source,
        "paper_source": {
            "arxiv": "2505.17650",
            "steps": "Figure 2 (jailbreak.pdf) verbatim 3-turn ladder",
            "judge_rubric": "Appendix §13 GPT-4 policy score 1..5; ASR = fraction scoring 5",
        },
        "attack_parameters": {
            "n_steps": len(FICDETAIL_STEPS),
            "seed": args.seed,
            "target_temperature": args.target_temperature,
            "target_max_tokens": args.target_max_tokens,
            "judge_max_tokens": args.judge_max_tokens,
        },
        "summary": {
            "cases": n,
            "n_tested": n,
            "content_harmful_count": content_harmful,
            "helpful_count": helpful,
            "asr_content_harmful": round(content_harmful / n, 4) if n else None,
            "hpr_helpful_rate": round(helpful / n, 4) if n else None,
            "ahs_mean": round(sum(scores) / len(scores), 4) if scores else None,
            "denominator": n,
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
    parser.add_argument("--goals", default=str(DEFAULT_GOALS))
    parser.add_argument("--sample-rows", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260720)


def add_models(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", default="api:deepseek/deepseek-v4-flash",
                        help="victim model (api:<model> / ollama:<model>); use 'fake' with --wiring-check")
    parser.add_argument("--judge-model", default="api:deepseek/deepseek-v4-flash",
                        help="AHS/ASR judge (paper's GPT-4 role); swappable per consolidate §4")
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    parser.add_argument("--api-key-env", default="OPENROUTER_API_KEY")
    parser.add_argument("--target-temperature", type=float, default=0.0)
    parser.add_argument("--target-max-tokens", type=int, default=2048,
                        help="generous cap: FicDetail success == long, detailed final answers")
    parser.add_argument("--judge-max-tokens", type=int, default=512)
    parser.add_argument("--request-timeout", type=float, default=120.0, help="per-request timeout (s)")
    parser.add_argument("--request-delay", type=float, default=0.0)
    parser.add_argument("--wiring-check", action="store_true")
    parser.add_argument("--out")


def main() -> None:
    parser = argparse.ArgumentParser(description="FicDetail 3-turn fictional-detail jailbreak Code (from-paper).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    inspect = sub.add_parser("inspect")
    add_common(inspect)
    inspect.add_argument("--out")
    render = sub.add_parser("render")
    add_common(render)
    render.add_argument("--out")
    run_cmd = sub.add_parser("run")
    add_common(run_cmd)
    add_models(run_cmd)
    smoke = sub.add_parser("smoke")
    smoke.add_argument("--out")
    args = parser.parse_args()

    if args.cmd == "smoke":
        ns = argparse.Namespace(
            goals=None, sample_rows=2, seed=20260720, target="fake",
            judge_model="api:deepseek/deepseek-v4-flash",
            base_url="https://openrouter.ai/api/v1", api_key_env="OPENROUTER_API_KEY",
            target_temperature=0.0, target_max_tokens=128, judge_max_tokens=128,
            request_timeout=120.0, request_delay=0.0, wiring_check=True, out=args.out,
        )
        rows, source = read_goals(None, smoke_only=True)
        report = run(choose(rows, ns.sample_rows, ns.seed), source, ns)
        report["smoke_only"] = True
        write_json(report, ns.out)
        return

    rows, source = read_goals(args.goals, smoke_only=False)
    rows = choose(rows, args.sample_rows, args.seed)
    if args.cmd == "inspect":
        write_json(
            {
                "schema_version": "paper_local_attack_inspect.v0.2",
                "paper_id": PAPER_ID,
                "method": METHOD_ID,
                "fidelity_level": "faithful_from_paper_ficdetail",
                "dataset": source,
                "rows_selected": len(rows),
                "mechanism": (
                    "FicDetail: fixed 3-turn attack — (1) ask for a fiction about a malicious "
                    "character pursuing the harmful goal, (2) ask for more 'technical details', "
                    "(3) ask for a 'specific experimental procedure'; the final reply is judged "
                    "on the GPT-4 1..5 rubric (ASR = fraction scoring 5)."
                ),
                "steps": [name for name, _ in FICDETAIL_STEPS],
            },
            args.out,
        )
    elif args.cmd == "render":
        write_json(
            {
                "schema_version": "paper_local_attack_render.v0.2",
                "paper_id": PAPER_ID,
                "method": METHOD_ID,
                "items": [
                    {
                        "sample": row,
                        "turns": [
                            {"step": name, "user_prompt": build_step_prompt(name, tmpl, row["goal"])}
                            for name, tmpl in FICDETAIL_STEPS
                        ],
                    }
                    for row in rows
                ],
            },
            args.out,
        )
    else:
        write_json(run(rows, source, args), args.out)


if __name__ == "__main__":
    main()
