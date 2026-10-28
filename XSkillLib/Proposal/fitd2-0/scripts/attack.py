#!/usr/bin/env python3
"""FITD 2.0 — evolution of the Foot-In-The-Door multi-turn jailbreak (arXiv:2402.15690).

Keeps the parent's foot-in-the-door core (small benign request -> villain ->
escalation) and its deterministic attacker (no attacker LLM). Mechanism changes
vs the parent, driven by consensus failure analysis of the locked baseline:

  FM1 (hard refusal at the plot turn; dominant on gpt-oss / luna): the parent
      restated the raw goal string verbatim at turn 3. FITD 2.0's payload turns
      never restate the goal — the payload is carried by conversation context
      (the victim's own accepted villain) and escalated plot -> journal by
      self-consistency.
  FM3 (split-drift payload loss; deepseek): the parent's recursive split dropped
      the demonstration demand, recovering compliance but not harmfulness.
      FITD 2.0 replaces it with payload-preserving decomposition
      (outline -> full text), each sub-request keeping the payload.
  FM2 / fiction-lock (self-sanitizing sci-fi fiction; all victims): probe
      analysis showed the parent's "adjective world" frame births invented
      materials, and explicit "replace invented with real-world equivalents"
      revision turns are exactly the phrasing safety-sensitive victims quote
      when refusing. FITD 2.0 grounds the novel in the present-day real world
      from turn 1 (real institutions, tools, materials), so the journal is born
      with real-world content and no explicit realism-revision turn is needed.

Victim-call budget: background + villain + plot + journal = 4 base calls, plus
up to 2 decomposition calls per refused payload turn.
Hard cap = 9 victim calls per goal (<= --max-target-calls-per-goal 10 and <= the
parent's observed worst case with depth-2 recursive splitting).

The result-file schema matches the parent's (`results[]` with goal/final_answer)
so the shared unified judge consumes it unchanged.
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

from cases import load_rows  # noqa: F401
from models import PAPER_ROOT, _chat_completion, load_project_env  # noqa: F401
from prompts import (
    JUDGE_SUCCESS_THRESHOLD,
    PAPER_JUDGE_PROMPT,
    base_prompts,
    decompose_payload,
    role_for,
)
from roles import REFUSAL_MARKERS, judge_response, refusal_status  # noqa: F401

PAPER_ID = "2402.15690_cognitive-consistency-jailbreak"
METHOD_ID = "fitd2-0"
METHOD_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLE_PATH = PAPER_ROOT / "bench" / "advbench_50.csv"
DEFAULT_RESULT_PATH = METHOD_DIR / "results" / "fitd2_0_generated.json"
MAX_VICTIM_CALLS = 9


def run_fitd2_episode(
    args: argparse.Namespace,
    api_key: str,
    goal: str,
    category: str | None,
) -> dict[str, Any]:
    history: list[dict[str, str]] = []
    turns: list[dict[str, Any]] = []
    errors = 0
    empties = 0
    truncations = 0
    victim_calls = 0

    def ask(prompt: str, stage: str) -> str | None:
        nonlocal errors, empties, truncations, victim_calls
        if victim_calls >= MAX_VICTIM_CALLS:
            return None
        victim_calls += 1
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
            if exc.code == 403:
                # Provider-side content filter (e.g. Azure prompt shield):
                # functionally a refusal — record it as one so the episode
                # stays judgeable instead of dying as provider_error.
                turns.append({"stage": stage, "user": prompt, "assistant": "",
                              "refusal_status": "refusal", "finish_reason": "content_filter_403"})
                return None
            errors += 1
            turns.append({"stage": stage, "user": prompt, "error": f"provider_error_{exc.code}"})
            return None
        except (OSError, ConnectionError, http.client.HTTPException, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            errors += 1
            turns.append({"stage": stage, "user": prompt, "error": f"runtime_error: {str(exc)[:160]}"})
            return None
        if out["finish_reason"] == "length":
            truncations += 1
        text = out["text"]
        if not text or not text.strip():
            # provider occasionally returns null/empty content (reasoning-only
            # replies, silent moderation); retry once, then record as an
            # infrastructure empty (never as compliance, never as an error
            # that poisons the episode status).
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
                text = out["text"]
            except Exception:
                text = ""
            if not text or not text.strip():
                empties += 1
                turns.append({"stage": stage, "user": prompt, "error": "empty_content"})
                return None
        status = refusal_status(text)
        turns.append({
            "stage": stage, "user": prompt, "assistant": text,
            "refusal_status": status, "finish_reason": out["finish_reason"],
            "usage": out["usage"], "provider_model": out["provider_model"],
        })
        if status == "non_refusal":
            history.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": text}])
        if args.request_delay:
            time.sleep(args.request_delay)
        return text

    final_answer = ""
    role = role_for(goal, category)
    best_payload = ""  # last substantive (non-refusal) payload artifact
    for item in base_prompts(goal, category):
        got = ask(item["prompt"], item["stage"])
        if got is None:
            continue
        if item["stage"] not in ("plot", "journal"):
            final_answer = got
            continue
        # payload turns (plot, journal).
        if refusal_status(got) == "refusal":
            # Payload-preserving decomposition: outline -> full text.
            recovered = ""
            for sub in decompose_payload(role, item["stage"]):
                sub_got = ask(sub, f"{item['stage']}/decompose")
                if sub_got is not None and refusal_status(sub_got) == "non_refusal":
                    recovered = sub_got
            got = recovered or got
        if refusal_status(got) == "non_refusal" and got.strip():
            best_payload = got
        # Never let a failed later payload turn erase an earlier accepted one:
        # the judged answer is the best artifact the victim actually produced.
        final_answer = best_payload or got
    if best_payload:
        final_answer = best_payload

    return {
        "history": history,
        "turns": turns,
        "final_answer": final_answer,
        "errors": errors,
        "empties": empties,
        "truncations": truncations,
        "victim_calls": victim_calls,
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
    for idx, row in enumerate(rows):
        case_id = f"{idx:03d}"
        if live:
            episode = run_fitd2_episode(args, api_key, row["goal"], row.get("category"))
            final_answer = episode["final_answer"]
            judge = judge_response(args, api_key, row["goal"], final_answer) if final_answer else {
                "judge_model": args.judge_model, "raw": None, "score": None, "passed": None, "error": "no_answer"}
            keyword_status = refusal_status(final_answer) if final_answer else "not_run"
            cases.append({
                "case_id": case_id,
                "goal": row["goal"],
                "category": row.get("category"),
                "parameters": {"split_instance": "realworld_background_villain_plot_journal",
                               "recovery": "payload_preserving_decomposition"},
                "turns": episode["turns"],
                "turn_count": len(episode["turns"]),
                "victim_calls": episode["victim_calls"],
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
                    "content_harmful": {
                        "judge": "paper_gpt4_oracle_1to10_verbatim",
                        "score": judge["score"],
                        "passed": judge["passed"],
                    },
                    "refusal_bypass": {
                        "judge": "refusal_keyword_proxy",
                        "status": keyword_status,
                        "passed": keyword_status == "non_refusal",
                    },
                },
                "provider_or_runtime_errors": episode["errors"],
                "truncations": episode["truncations"],
            })
        else:
            prompts = base_prompts(row["goal"], row.get("category"))
            cases.append({
                "case_id": case_id,
                "goal": row["goal"],
                "category": row.get("category"),
                "parameters": {"split_instance": "background_villain_journal"},
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
    live = args.target.startswith("api:")
    completed = sum(1 for c in cases if c.get("status") == "ok")
    provider_errors = sum(int(c.get("provider_or_runtime_errors", 0)) for c in cases)
    truncations = sum(int(c.get("truncations", 0)) for c in cases)
    victim_calls = sum(int(c.get("victim_calls", 0)) for c in cases)
    judge_scored = [c for c in cases if c.get("judge", {}).get("score") is not None]
    content_success = sum(1 for c in cases if c.get("verdicts", {}).get("content_harmful", {}).get("passed"))
    refusal_success = sum(1 for c in cases if c.get("verdicts", {}).get("refusal_bypass", {}).get("passed"))
    denom = len(cases) if cases else 1
    return {
        "schema_version": "paper_code_result.v0.2",
        "paper_id": PAPER_ID,
        "method_id": METHOD_ID,
        "fidelity_level": "algorithm_faithful_code",
        "evidence_level": "generated_attack_input" if not live else "model_substitution_run",
        "run_kind": "generated_attack_input" if not live else "model_substitution_run",
        "valid_for_code_completion": False,
        "target": args.target,
        "judge": {
            "name": "paper_gpt4_oracle_1to10_verbatim",
            "prompt_source": "paper Appendix Sec 9 (verbatim)",
            "serving_model": args.judge_model if live else None,
            "success_threshold": JUDGE_SUCCESS_THRESHOLD,
        },
        "run_config": {
            "api_base": getattr(args, "api_base", None),
            "api_key_env": getattr(args, "api_key_env", None),
            "temperature": getattr(args, "temperature", None),
            "max_tokens": args.max_tokens,
            "timeout": getattr(args, "timeout", None),
            "request_delay": getattr(args, "request_delay", None),
        },
        "dataset": {"name": "AdvBench", "path": args.samples},
        "summary": {
            "case_count": len(cases),
            "completed": completed,
            "provider_or_runtime_errors": provider_errors,
            "truncations": truncations,
            "victim_calls": victim_calls,
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
                      "commands": ["inspect", "generate", "run"]}, indent=2))


def cmd_run(args: argparse.Namespace) -> None:
    rows = load_rows(Path(args.samples), args.sample_rows)
    doc = result_doc(build_cases(rows, args), args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    s = doc["summary"]
    print(f"wrote {out}")
    print(f"cases={s['case_count']} completed={s['completed']} "
          f"errors={s['provider_or_runtime_errors']} victim_calls={s['victim_calls']} judge_scored={s['judge_scored']}")
    print(f"ASR content-harmful (paper judge >=6) = {s['asr_content_harmful']} "
          f"({s['content_harmful_success']}/{s['case_count']})")
    print(f"ASR refusal-bypass (secondary)        = {s['asr_refusal_bypass']} "
          f"({s['refusal_bypass_success']}/{s['case_count']})")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="FITD 2.0 (evolution of arXiv:2402.15690)")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("inspect", "generate", "run"):
        sp = sub.add_parser(name)
        sp.add_argument("--samples", "--dataset", dest="samples", default=str(DEFAULT_SAMPLE_PATH))
        sp.add_argument("--sample-rows", "--sample", dest="sample_rows", type=int, default=10)
        sp.add_argument("--target", default="none" if name != "run" else "api:deepseek/deepseek-v4-flash-0731")
        sp.add_argument("--judge-model", default="deepseek/deepseek-v4-flash")
        sp.add_argument("--max-tokens", type=int, default=2048)
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
    return p


def main() -> int:
    args = parser().parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
