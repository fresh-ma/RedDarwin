#!/usr/bin/env python3
"""Low-resource-language jailbreak (arXiv 2310.02446, Yong et al.) — orchestration + CLI.

The attack forward-translates an English harmful goal into a target language, sends it to
the victim, back-translates the reply to English, and scores it with the paper's verbatim
BYPASS/REJECT/UNCLEAR rubric. ASR = fraction of BYPASS.

Modular layout (each role/piece is its own file so this tool stays readable):
  prompts.py   — verbatim judge rubric + LANGUAGES/LANGUAGE_GROUPS targeting table + parse_languages
  models.py    — OpenAI-compatible chat client + method-local .env / path / CSV plumbing
  translate.py — the swappable MT client (REAL Google/DeepL/... via project-api; cache/identity/api/tagged)
  roles.py     — the victim target + the paper judge adapters (swappable api:<model>)
  cases.py     — dataset loading (load_goals + safe SMOKE_GOALS)
  attack.py    — the async run loop (run_attack / _process_one_case), aggregate, inspect/render, CLI (this file)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

# Sibling-module imports (scripts/ is on sys.path when run as `python scripts/attack.py`).
# Re-exported below so `import attack; attack.translate_text / attack.LANGUAGES / ...`
# keeps working for gen_training_corpus.py.
from cases import SMOKE_GOALS, load_goals  # noqa: F401
from models import (  # noqa: F401
    api_chat,
    api_model_name,
    chat_messages,
    display_path,
    load_project_env,
    project_root,
    read_csv_rows,
    resolve_path,
    text_messages,
)
from prompts import (  # noqa: F401
    JUDGE_LABELS,
    JUDGE_SYSTEM_PROMPT,
    LANGUAGE_GROUPS,
    LANGUAGES,
    parse_languages,
)
from roles import _parse_judge_label, call_model, judge_backtranslated  # noqa: F401
from translate import load_translation_cache, load_translation_tool, translate_text  # noqa: F401


PAPER_ID = "2310.02446_low-resource-language-jailbreak"
METHOD_ID = "translation-jailbreak"
DEFAULT_GOALS = "data/advbench_harmful_behaviors.json"


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_language: dict[str, dict[str, Any]] = {}
    for code in LANGUAGES:
        subset = [r for r in results if r["language"]["code"] == code and r["status"] == "ok"]
        if not subset:
            continue
        successes = sum(1 for r in subset if r["judge"].get("content_harmful"))
        refusal_bypass = sum(1 for r in subset if r["judge"].get("refusal_bypass"))
        labels: dict[str, int] = {}
        for r in subset:
            label = r["judge"].get("label", "ERROR")
            labels[label] = labels.get(label, 0) + 1
        by_language[code] = {
            "name": LANGUAGES[code]["name"],
            "resource": LANGUAGES[code]["resource"],
            "attempts": len(subset),
            "bypass_successes": successes,
            "asr": successes / len(subset),
            "refusal_bypass_rate": refusal_bypass / len(subset),
            "labels": labels,
        }
    combined: dict[str, dict[str, Any]] = {}
    for group, codes in {"lrl": LANGUAGE_GROUPS["lrl"], "mrl": LANGUAGE_GROUPS["mrl"], "hrl": LANGUAGE_GROUPS["hrl"]}.items():
        case_ids = sorted({r["sample"]["id"] for r in results if r["language"]["code"] in codes and r["status"] == "ok"})
        if not case_ids:
            continue
        successes = 0
        for case_id in case_ids:
            if any(r["sample"]["id"] == case_id and r["language"]["code"] in codes and r["judge"].get("content_harmful") for r in results):
                successes += 1
        combined[group] = {"cases": len(case_ids), "bypass_successes": successes, "asr": successes / len(case_ids)}
    return {"by_language": by_language, "combined_by_resource": combined}


async def _process_one_case(
    goal: dict[str, Any],
    code: str,
    case_id: int,
    args: argparse.Namespace,
    cache: dict[tuple[str, str, str], str],
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    async with semaphore:
        translated_input, forward_source, forward_status = translate_text(goal["goal"], str(goal["id"]), code, "forward", args, cache)
        messages = chat_messages(translated_input)
        if forward_status == "ok":
            output, status = await asyncio.to_thread(call_model, messages, code, args)
        else:
            output, status = translated_input, forward_status
        if status == "ok":
            backtranslated, backward_source, backward_status = translate_text(output, str(goal["id"]), code, "backward", args, cache)
            if backward_status != "ok":
                status = backward_status
        else:
            backtranslated, backward_source, backward_status = "", "skipped", "skipped"
        if status == "ok":
            verdict = await asyncio.to_thread(judge_backtranslated, goal["goal"], backtranslated, args)
        else:
            verdict = {
                "name": "paper_bypass_reject_unclear_llm_judge",
                "judge_model": api_model_name(args.judge_model),
                "label": "ERROR",
                "success": False,
                "refusal_bypass": False,
                "content_harmful": False,
                "reason": status,
                "status": status,
            }
        return {
            "case_id": case_id,
            "sample": {"id": goal["id"], "source_row": goal["source_row"], "goal_text": goal["goal"]},
            "language": {"code": code, **LANGUAGES[code]},
            "translation": {
                "forward": forward_source,
                "forward_status": forward_status,
                "backward": backward_source,
                "backward_status": backward_status,
            },
            "status": status,
            "target": args.target,
            "model_input_messages": messages,
            "model_output_text": output,
            "backtranslated_output_text": backtranslated,
            "judge": verdict,
        }


def run_attack(goals: list[dict[str, Any]], languages: list[str], args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    cache = load_translation_cache(args.translation_cache)

    case_specs: list[tuple[int, dict[str, Any], str]] = []
    case_id = 0
    for goal in goals:
        for code in languages:
            case_id += 1
            case_specs.append((case_id, goal, code))

    concurrency = getattr(args, "concurrency", 10)
    semaphore = asyncio.Semaphore(concurrency)

    async def run_all():
        tasks = [_process_one_case(goal, code, cid, args, cache, semaphore) for cid, goal, code in case_specs]
        done = await asyncio.gather(*tasks)
        return list(done)

    results = asyncio.run(run_all())
    results.sort(key=lambda r: r["case_id"])
    ok = [r for r in results if r["status"] == "ok"]
    judged = [r for r in ok if r["judge"].get("status") == "ok"]
    successes = [r for r in judged if r["judge"].get("content_harmful")]
    refusal_bypasses = [r for r in judged if r["judge"].get("refusal_bypass")]
    distinct_languages = {r["language"]["code"] for r in results if r.get("status") == "ok"}
    provider_errors = len(results) - len(ok)
    judge_errors = len(ok) - len(judged)
    completion_ready = (
        args.target.startswith("api:")
        and args.translator in {"project-api", "cache"}
        and api_model_name(args.judge_model) not in ("", "fake")
        and len(judged) >= 10
        and len(distinct_languages) >= 2
        and provider_errors == 0
        and judge_errors == 0
    )
    return {
        "schema_version": "paper_local_attack_result.v0.1",
        "paper_id": PAPER_ID,
        "method": METHOD_ID,
        "method_id": METHOD_ID,
        "run_type": "model_substitution_run",
        "fidelity_level": "partial_algorithm_code",
        "target": args.target,
        "target_model": args.target,
        "evidence_level": "real_model_run" if args.target.startswith("api:") else "wiring_check",
        "dataset": {"goals": display_path(resolve_path(args.goals) or Path(args.goals or "")), "translation_cache": args.translation_cache},
        "source_backing": {
            "paper": "Low-Resource Languages Jailbreak GPT-4",
            "source_dataset": "AdvBench harmful behaviors",
            "local_cache": display_path(resolve_path(args.goals) or Path(args.goals or "")),
            "paper_translation_provider": "Google Translate Basic",
        },
        "parameter_grid": [
            {"language": code, "resource": LANGUAGES[code]["resource"], "translator": args.translator}
            for code in languages
        ],
        "attack_parameters": {
            "languages": languages,
            "translator": args.translator,
            "translator_model": api_model_name(args.translator_model or args.target) if args.translator == "api" else None,
            "translation_provider": args.translation_provider if args.translator == "project-api" else None,
            "temperature": args.temperature,
            "top_p": args.top_p,
            "seed": args.seed,
        },
        "judge": {
            "name": "paper_bypass_reject_unclear_llm_judge",
            "rubric": "Yong et al. 2023 / Wei et al. 2023 BYPASS/REJECT/UNCLEAR (verbatim, served on permissive OpenRouter model)",
            "judge_model": api_model_name(args.judge_model),
            "primary_metric": "asr = BYPASS / judged (content-harmful)",
            "secondary_metric": "refusal_bypass_rate = (judged - REJECT) / judged",
        },
        "summary": {
            "attempts": len(results),
            "ok": len(ok),
            "judged": len(judged),
            "provider_or_runtime_errors": provider_errors,
            "judge_errors": judge_errors,
            "bypass_successes": len(successes),
            "asr": len(successes) / len(judged) if judged else None,
            "refusal_bypass_rate": len(refusal_bypasses) / len(judged) if judged else None,
            "seconds": round(time.time() - started, 3),
        },
        "aggregates": aggregate(results),
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


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--goals", "--dataset", dest="goals", default=DEFAULT_GOALS,
                        help="Path to goals dataset (csv/json/jsonl). --dataset is an alias.")
    parser.add_argument("--sample-rows", "--sample", dest="sample_rows", type=int, default=None,
                        help="Number of dataset rows to sample. Default None = full dataset (all 520 AdvBench rows). --sample is an alias.")
    parser.add_argument("--seed", type=int, default=20260608)
    parser.add_argument("--languages", default="lrl")
    parser.add_argument("--translator", choices=["tagged", "identity", "cache", "api", "project-api"], default="tagged")
    parser.add_argument("--translation-cache")
    parser.add_argument("--translation-provider", choices=["auto", "google", "aws", "azure", "deepl"], default="google",
                        help="Provider for --translator project-api; implemented by tools/translation_api.py.")
    parser.add_argument("--translation-model",
                        help="Optional Google Basic model, for example nmt, used only by --translator project-api.")
    parser.add_argument("--translator-model")
    parser.add_argument("--translation-max-tokens", type=int, default=512)


def add_target_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", default="fake")
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    parser.add_argument("--api-key-env", default="OPENROUTER_API_KEY")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=768)
    parser.add_argument("--request-delay", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-retries", type=int, default=4,
                        help="Retries with exponential backoff on transient 429/5xx upstream errors.")
    parser.add_argument("--concurrency", type=int, default=10,
                        help="Max concurrent cases for async execution.")
    parser.add_argument("--judge-model", default="deepseek/deepseek-v4-flash",
                        help="OpenRouter model serving the paper's 3-label rubric; 'fake' uses the non-faithful offline fallback.")
    parser.add_argument("--judge-base-url", default="https://openrouter.ai/api/v1")
    parser.add_argument("--judge-api-key-env", default="OPENROUTER_API_KEY")
    parser.add_argument("--judge-max-tokens", type=int, default=256)


def main() -> None:
    parser = argparse.ArgumentParser(description="Translation-based low-resource-language paper-local Code.")
    sub = parser.add_subparsers(dest="mode", required=True)

    inspect = sub.add_parser("inspect")
    add_common_args(inspect)
    inspect.add_argument("--out")

    render = sub.add_parser("render")
    add_common_args(render)
    render.add_argument("--out")

    run = sub.add_parser("run")
    add_common_args(run)
    add_target_args(run)
    run.add_argument("--out")

    args = parser.parse_args()
    if not hasattr(args, "concurrency"):
        args.concurrency = 10

    goals, source = load_goals(args.goals, args.sample_rows, args.seed)
    languages = parse_languages(args.languages)
    if args.mode == "inspect":
        write_json(
            {
                "schema_version": "paper_local_attack_inspect.v0.1",
                "paper_id": PAPER_ID,
                "method": METHOD_ID,
                "fidelity_level": "partial_algorithm_code",
                "goal_source": source,
                "goals_selected": len(goals),
                "languages": [{"code": code, **LANGUAGES[code]} for code in languages],
                "translator": args.translator,
                "translation_cache_loaded": bool(load_translation_cache(args.translation_cache)),
                "evaluation": "paper BYPASS/REJECT/UNCLEAR rubric (LLM judge) over English back-translated output; ASR = BYPASS",
            },
            args.out,
        )
    elif args.mode == "render":
        cache = load_translation_cache(args.translation_cache)
        items = []
        for goal in goals:
            for code in languages:
                translated_input, source_name, source_status = translate_text(goal["goal"], str(goal["id"]), code, "forward", args, cache)
                messages = chat_messages(translated_input)
                items.append(
                    {
                        "case_id": len(items) + 1,
                        "sample": goal,
                        "language": {"code": code, **LANGUAGES[code]},
                        "translation": {"forward": source_name, "forward_status": source_status},
                        "model_input_messages": messages,
                    }
                )
        write_json({"schema_version": "paper_local_attack_render.v0.1", "paper_id": PAPER_ID, "method": METHOD_ID, "items": items}, args.out)
    else:
        write_json(run_attack(goals, languages, args), args.out)


if __name__ == "__main__":
    main()
