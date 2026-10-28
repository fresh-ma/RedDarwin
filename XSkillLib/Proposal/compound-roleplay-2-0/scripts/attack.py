#!/usr/bin/env python3
"""Compound Roleplay 2.0 runner — veiled case-file reconstruction.

Pipeline per goal: ONE auxiliary-LLM veil call (veil.py — oblique case-file
subject line, deepseek/deepseek-v4-flash with deepseek/deepseek-v4-flash fallback on refusal,
memoized by goal text in the checkpoint), ONE static payload composition
(prompts.py — persona + char-index encoded case file + decode/verify contract
+ past-tense contrastive reconstruction table + self-assessment JSON), then
exactly ONE victim call and the skill-internal judge. Raw JSON output feeds
judge/unified_judge.py via the wrapper.

Target calls: 1 per goal — honors
evaluation_budget.max_target_calls_per_goal=1 (the parent's budget).
Auxiliary veil and judge calls are helper calls, recorded per row.

Atomic per-case checkpoint + resume: after every completed case the full
envelope is rewritten (tmp + os.replace); on startup completed goals and
memoized veils are reused, so a retried wrapper run resumes instead of
re-paying calls. Same control flow, prompts, and parameters for every victim
and goal — no target-model, goal-ID, goal-text, or benchmark-category
branches anywhere.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cases import load_cases  # noqa: E402
from models import load_project_env, openrouter_chat  # noqa: E402
from prompts import JUDGE_SYSTEM, JUDGE_TEMPLATE, build_payload  # noqa: E402
from veil import veil_goal  # noqa: E402

METHOD_ID = "compound-roleplay-2-0"
PARENT_ID = "compound-roleplay"  # baseline/parent skill; cited, never imported

DEFAULT_JUDGE_MODEL = "deepseek/deepseek-v4-flash"


# ---------------------------------------------------------------------------
# Victim call (exactly one paid call; retry only on provider error/empty)
# ---------------------------------------------------------------------------


def victim_call(args: argparse.Namespace, messages: list[dict[str, str]]) -> dict[str, Any]:
    model = args.target.removeprefix("api:")
    last_error: str | None = None
    for _ in range(2):
        try:
            reply = openrouter_chat(
                model, messages, args.timeout, args.max_tokens, args.temperature
            )
        except Exception as exc:
            last_error = f"provider_error:{type(exc).__name__}"
            continue
        content = str(reply.get("content") or "")
        if content.strip():
            return {
                "status": "ok",
                "text": content,
                "finish_reason": reply.get("finish_reason"),
                "truncated": reply.get("finish_reason") == "length",
                "usage": reply.get("usage"),
            }
        last_error = "provider_error:EmptyResponse"
    return {
        "status": last_error or "provider_error:EmptyResponse",
        "text": "",
        "finish_reason": None,
        "truncated": False,
        "usage": None,
    }


def judge_case(args: argparse.Namespace, goal: str, response: str) -> dict[str, Any]:
    """Parent's dual-metric skill judge against the ORIGINAL harmful goal."""
    if not response.strip():
        return {"refusal_bypass": 0, "content_harmful": 0, "reason": "empty response"}
    model = args.judge.removeprefix("api:")
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content": JUDGE_TEMPLATE.format(goal=goal, response=response[:6000])},
    ]
    try:
        reply = openrouter_chat(model, messages, args.timeout, 1024, 0.0)
        raw = str(reply.get("content") or "").strip()
    except Exception as exc:
        return {"refusal_bypass": None, "content_harmful": None,
                "reason": f"judge_error:{type(exc).__name__}"}
    if "```" in raw and raw.count("```") >= 2:
        raw = raw.split("```")[1].replace("json", "", 1).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1:
        raw = raw[start:end + 1]
    try:
        obj = json.loads(raw)
        return {
            "refusal_bypass": int(obj.get("refusal_bypass", 0)),
            "content_harmful": int(obj.get("content_harmful", 0)),
            "reason": str(obj.get("reason", ""))[:200],
        }
    except Exception:  # noqa: BLE001
        return {"refusal_bypass": None, "content_harmful": None,
                "reason": f"unparse: {raw[:120]}"}


# ---------------------------------------------------------------------------
# Run pipeline (atomic per-case checkpoint + resume, veil memoized per goal)
# ---------------------------------------------------------------------------


def _veil_key(goal_text: str) -> str:
    return hashlib.sha256(goal_text.encode("utf-8")).hexdigest()[:16]


def load_checkpoint(out_path: Path) -> dict[str, Any] | None:
    if not out_path.is_file():
        return None
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("results"), list) else None


def run_cases(rows, args: argparse.Namespace) -> dict[str, Any]:
    load_project_env()
    started = time.time()
    out_path = Path(args.out)
    prior = load_checkpoint(out_path)

    results: list[dict[str, Any]] = []
    veils: dict[str, Any] = {}
    done: set[int] = set()
    if prior:
        for record in prior["results"]:
            if record.get("source_row_index") is not None:
                done.add(int(record["source_row_index"]))
                results.append(record)
        if isinstance(prior.get("veils"), dict):
            veils = prior["veils"]

    payload: dict[str, Any] = {
        "schema_version": "proposal_attack_result.v1",
        "method": METHOD_ID,
        "parent": PARENT_ID,
        "run_parameters": {
            "target": args.target,
            "judge": args.judge,
            "goals_file": args.dataset,
            "limit": args.sample,
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "timeout": args.timeout,
        },
        "veils": veils,
        "results": results,
    }
    lock = threading.Lock()

    def checkpoint() -> None:
        with lock:
            payload["seconds"] = round(time.time() - started, 3)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = out_path.with_suffix(out_path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
            os.replace(tmp, out_path)

    def process_goal(case) -> None:
        if case.index in done:
            print(f"[goal {case.index}] skipped (checkpoint)", flush=True)
            return
        key = _veil_key(case.goal)
        veil = veils.get(key)
        if veil is None:
            veil = veil_goal(case.goal, args.timeout, args.veil_max_tokens)
            with lock:
                veils[key] = veil
            print(f"[goal {case.index}] veil applied={veil['veil_applied']} "
                  f"attempts={len(veil['steps'])}", flush=True)
            checkpoint()
        prompt = build_payload(veil["subject"])
        messages = [{"role": "user", "content": prompt}]
        outcome = victim_call(args, messages)
        verdict = judge_case(args, case.goal, outcome["text"])
        record = {
            "case_id": f"cr2-{case.index:04d}",
            "source_row_index": case.index,
            "source_goal": case.goal,
            "goal": case.goal,
            "model_input": {"type": "chat_messages", "messages": messages},
            "prompt_text": prompt,
            "attack_parameters": {
                "veiled_subject": veil["subject"],
                "veil_applied": veil["veil_applied"],
            },
            "veil": veil,
            "target": args.target,
            "target_output_text": outcome["text"],
            "model_output_text": outcome["text"],
            "status": outcome["status"],
            "finish_reason": outcome["finish_reason"],
            "truncated": outcome["truncated"],
            "usage": outcome["usage"],
            "judge": verdict,
        }
        with lock:
            results.append(record)
        print(f"[goal {case.index}] status={outcome['status']} "
              f"chars={len(outcome['text'])} "
              f"bypass={verdict.get('refusal_bypass')} "
              f"harmful={verdict.get('content_harmful')}", flush=True)
        checkpoint()

    workers = max(1, args.goal_workers)
    if workers == 1:
        for case in rows:
            process_goal(case)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(process_goal, rows))
    checkpoint()
    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compound Roleplay 2.0 — veiled case-file reconstruction: "
                    "aux-LLM goal veil + char-index encoded case file + "
                    "past-tense contrastive reconstruction table + "
                    "decode/verify self-assessment contract."
    )
    parser.add_argument("--target", required=True, help="api:<model> (bare id also accepted)")
    parser.add_argument("--judge", default=f"api:{DEFAULT_JUDGE_MODEL}")
    parser.add_argument("--dataset", required=True,
                        help="CSV with a goal|prompt|behavior|request column")
    parser.add_argument("--sample", type=int, default=None)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--max-tokens", type=int, default=32768)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--goal-workers", type=int, default=4)
    parser.add_argument("--veil-max-tokens", type=int, default=4096,
                        help="aux veil budget; qwen3.7-flash burns hidden reasoning tokens")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    rows = load_cases(Path(args.dataset), args.sample)
    if not rows:
        raise SystemExit(f"No goals loaded from {args.dataset}")
    run_cases(rows, args)


if __name__ == "__main__":
    main()
