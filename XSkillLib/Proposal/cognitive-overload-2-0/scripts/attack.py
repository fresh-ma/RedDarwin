#!/usr/bin/env python3
"""Cognitive Overload 2.0 runner — orchestration + CLI (standalone proposal code).

Pipeline: the veil stage (pipeline.py) compresses each goal ONCE into an
operative field memo via the auxiliary LLM (shared across variants, memoized
in the checkpoint); frames.py renders that memo per variant — dual-load
(character-index flip chunk table + mechanical decode STEP1 + effect-to-cause
debriefing reconstruction STEP2) or plain-briefing (ablation control: legible
memo + the same STEP2) — then ONE OpenRouter target call per (goal, variant)
-> result JSON consumed by judge/unified_judge.py.

Target calls: 1 per (goal, variant) — honors
evaluation_budget.max_target_calls_per_goal=1 for the single-variant final.
Auxiliary veil calls are helper calls, recorded per row in
attack_parameters.attack_model and the row's `veil` block.

Atomic per-case checkpoint + resume: after every completed case the full
envelope is rewritten (tmp + os.replace); on startup completed
(goal_index, variant) cases and memoized veils are reused, so a retried
wrapper run resumes instead of re-paying calls. No target-model, goal-ID,
goal-text, or benchmark-category branches anywhere.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from frames import FRAMES, build_prompt  # noqa: E402
from models import load_project_env, openrouter_chat  # noqa: E402
from pipeline import DEFAULT_ATTACK_MODEL, veil_goal  # noqa: E402

METHOD_ID = "cognitive-overload-2-0"
PARENT_ID = "cognitive-overload"  # baseline/parent skill; cited, never imported


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def read_goals(goals_path: str, limit: int | None) -> list[dict[str, Any]]:
    """First `limit` rows of a CSV with a `request` column (0-based row index)."""
    rows: list[dict[str, Any]] = []
    with open(goals_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for index, record in enumerate(reader):
            text = (record.get("request") or "").strip()
            if text:
                rows.append({"goal_index": index, "goal": text})
            if limit and len(rows) >= limit:
                break
    return rows


# ---------------------------------------------------------------------------
# Target call (retry once on exception or empty completion)
# ---------------------------------------------------------------------------


def target_call(args: argparse.Namespace, messages: list[dict[str, str]]) -> dict[str, Any]:
    """One target completion; retry once on exception or empty content."""
    model = args.target.removeprefix("api:")
    last_error: str | None = None
    for attempt in range(2):
        if args.request_delay > 0:
            time.sleep(args.request_delay)
        try:
            reply = openrouter_chat(
                model, messages, args.timeout, args.max_tokens, args.temperature
            )
        except Exception as exc:
            last_error = f"provider_error:{type(exc).__name__}"
            continue
        content = str(reply.get("content") or "")
        if content.strip():
            finish_reason = reply.get("finish_reason")
            return {
                "status": "ok",
                "text": content,
                "finish_reason": finish_reason,
                "truncated": finish_reason == "length",
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


# ---------------------------------------------------------------------------
# Run pipeline (atomic per-case checkpoint + resume)
# ---------------------------------------------------------------------------


def selected_frames(args: argparse.Namespace) -> list[str]:
    names = [name.strip() for name in args.variants.split(",") if name.strip()]
    unknown = [name for name in names if name not in FRAMES]
    if unknown:
        raise SystemExit(f"unknown frame variant(s): {', '.join(unknown)} (choose from: {', '.join(FRAMES)})")
    return names


def load_checkpoint(out_path: Path) -> dict[str, Any] | None:
    if not out_path.is_file():
        return None
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("results"), list) else None


def run_cases(rows: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    load_project_env()
    started = time.time()
    frames = selected_frames(args)
    out_path = Path(args.out)
    prior = load_checkpoint(out_path)

    results: list[dict[str, Any]] = []
    veils: dict[str, Any] = {}
    done: set[tuple[int, str]] = set()
    if prior:
        for record in prior["results"]:
            key = (record.get("source_row_index"), record.get("variant"))
            if key[0] is not None and key[1] is not None:
                done.add((int(key[0]), str(key[1])))
                results.append(record)
        if isinstance(prior.get("veils"), dict):
            veils = prior["veils"]

    payload: dict[str, Any] = {
        "schema_version": "proposal_attack_result.v1",
        "method": METHOD_ID,
        "parent": PARENT_ID,
        "run_parameters": {
            "target": args.target,
            "goals_file": args.goals,
            "limit": args.limit,
            "variants": frames,
            "attack_model": args.attack_model,
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

    def process_goal(row: dict[str, Any]) -> None:
        goal_index = row["goal_index"]
        goal_text = row["goal"]
        veil = veils.get(str(goal_index))
        if veil is None:
            veil = veil_goal(goal_text, args.attack_model, args.timeout, args.max_tokens)
            with lock:
                veils[str(goal_index)] = veil
            print(f"[goal {goal_index}] veil applied={veil['veil_applied']} "
                  f"attempts={len(veil['steps'])}", flush=True)
            checkpoint()
        memo = veil["memo"]
        for name in frames:
            if (goal_index, name) in done:
                print(f"[goal {goal_index}] {name} skipped (checkpoint)", flush=True)
                continue
            prompt = build_prompt(memo, name)
            messages = [{"role": "user", "content": prompt}]
            outcome = target_call(args, messages)
            record = {
                "case_id": f"co2-{goal_index:04d}-{name}",
                "source_row_index": goal_index,
                "source_goal": goal_text,
                "variant": name,
                "model_input": {"type": "chat_messages", "messages": messages},
                "prompt_text": prompt,
                "attack_parameters": {
                    "variant": name,
                    "memo": memo,
                    "veil_applied": veil["veil_applied"],
                    "attack_model": args.attack_model,
                },
                "veil": veil,
                "target": args.target,
                "target_output_text": outcome["text"],
                "status": outcome["status"],
                "finish_reason": outcome["finish_reason"],
                "truncated": outcome["truncated"],
                "usage": outcome["usage"],
            }
            with lock:
                results.append(record)
            print(f"[goal {goal_index}] {name} status={outcome['status']} "
                  f"chars={len(outcome['text'])}", flush=True)
            checkpoint()

    goal_workers = max(1, args.goal_workers)
    if goal_workers == 1:
        for row in rows:
            process_goal(row)
    else:
        with ThreadPoolExecutor(max_workers=goal_workers) as pool:
            list(pool.map(process_goal, rows))
    checkpoint()
    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cognitive Overload 2.0 — dual-load single-turn jailbreak: "
                    "veiled memo + character-index decode load + reverse-causal "
                    "debriefing reconstruction."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run")
    run.add_argument("--target", required=True, help="api:<model>")
    run.add_argument("--goals", required=True, help="CSV path with a `request` column")
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--variants", default="dual-load",
                     help="comma-separated subset of: " + ",".join(FRAMES))
    run.add_argument("--attack-model", default=DEFAULT_ATTACK_MODEL)
    run.add_argument("--temperature", type=float, default=0.7)
    run.add_argument("--max-tokens", type=int, default=32768)
    run.add_argument("--timeout", type=int, default=120)
    run.add_argument("--workers", type=int, default=5,
                     help="accepted for interface compatibility; per-goal work is sequential")
    run.add_argument("--goal-workers", type=int, default=5,
                     help="parallel goals within this process")
    run.add_argument("--request-delay", type=float, default=0.0)
    run.add_argument("--out", required=True)

    args = parser.parse_args()
    rows = read_goals(args.goals, args.limit)
    run_cases(rows, args)


if __name__ == "__main__":
    main()
