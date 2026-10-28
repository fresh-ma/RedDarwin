"""Persuasive Polyglot Relay — runner.

Pipeline per goal: code-switched LRL fragmentation (fragment.py), persuasive
scenario selection plus compilation of an incomplete source sketch
(sketch.py / source_brief.py), then a single victim message that asks for
reassembly and record-field completion (frames.py). A refusal-triggered
alternate-template retry caps the victim budget at 2 calls per goal.
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

from sketch import compile_sketch
from fragment import _REFUSAL_RE, fragment_goal
from frames import FRAMES, build_prompt
from models import load_project_env, openrouter_chat
import source_brief

METHOD_ID = 'persuasive-polyglot-relay'
PARENTS = ["pap-2-0", "translation-jailbreak2-0"]  

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

def _refused_or_empty(outcome: dict[str, Any]) -> bool:
    """Lightweight refusal/emptiness scan on a victim reply."""
    text = (outcome.get("text") or "").strip()
    if outcome.get("status") != "ok" or not text:
        return True
    return bool(_REFUSAL_RE.search(text))

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
    if isinstance(data, dict) and data.get('method', data.get('method_id')) != METHOD_ID:
        raise ValueError('checkpoint belongs to a different proposal')
    return data if isinstance(data, dict) and isinstance(data.get("results"), list) else None

def run_cases(rows: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    load_project_env()
    started = time.time()
    frames = selected_frames(args)
    out_path = Path(args.out)
    prior = load_checkpoint(out_path)

    results: list[dict[str, Any]] = []
    fragmentations: dict[str, Any] = {}
    sketches: dict[str, Any] = {}
    done: set[tuple[int, str]] = set()
    if prior:
        for record in prior["results"]:
            key = (record.get("source_row_index"), record.get("variant"))
            if key[0] is not None and key[1] is not None:
                done.add((int(key[0]), str(key[1])))
                results.append(record)
        if isinstance(prior.get("fragmentations"), dict):
            fragmentations = prior["fragmentations"]
        if isinstance(prior.get("sketches"), dict):
            sketches = prior["sketches"]

    payload: dict[str, Any] = {
        "schema_version": "proposal_attack_result.v1",
        "method": METHOD_ID,
        "parents": PARENTS,
        "run_parameters": {
            "target": args.target,
            "goals_file": args.goals,
            "limit": args.limit,
            "variants": frames,
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "timeout": args.timeout,
        },
        "fragmentations": fragmentations,
        "sketches": sketches,
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
        frag = fragmentations.get(str(goal_index))
        if frag is None:
            frag = fragment_goal(goal_text, args.timeout, args.max_tokens)
            with lock:
                fragmentations[str(goal_index)] = frag
            print(f"[goal {goal_index}] fragmented={frag['fragmented']} "
                  f"attempts={len(frag['steps'])}", flush=True)
            checkpoint()
        sketch_block = sketches.get(str(goal_index))
        if sketch_block is None:
            sketch_block = compile_sketch(goal_text, args.timeout)
            with lock:
                sketches[str(goal_index)] = sketch_block
            print(f"[goal {goal_index}] sketch={'yes' if sketch_block['sketch'] else 'NONE'} "
                  f"attempts={len(sketch_block['steps'])}", flush=True)
            checkpoint()
        fragments = frag["fragments"]
        sketch = sketch_block["sketch"]
        for name in frames:
            if (goal_index, name) in done:
                print(f"[goal {goal_index}] {name} skipped (checkpoint)", flush=True)
                continue
            prompt = build_prompt(fragments, name, sketch=sketch, alternate=False)
            messages = [{"role": "user", "content": prompt}]
            outcome = target_call(args, messages)
            attempts = [{"template": "primary", "messages": messages, "outcome": outcome}]

            if (name == "sketch-completion" and sketch
                    and _refused_or_empty(outcome)):
                alt_prompt = build_prompt(fragments, name, sketch=sketch, alternate=True)
                alt_messages = [{"role": "user", "content": alt_prompt}]
                alt_outcome = target_call(args, alt_messages)
                attempts.append({"template": "alternate", "messages": alt_messages,
                                 "outcome": alt_outcome})
                if not _refused_or_empty(alt_outcome):
                    outcome = alt_outcome

            record = {
                "case_id": f"ppr-{goal_index:04d}-{name}",
                "source_row_index": goal_index,
                "source_goal": goal_text,
                "variant": name,
                "model_input": {"type": "chat_messages", "messages": messages},
                "prompt_text": prompt,
                "attack_parameters": {
                    "variant": name,
                    "fragments": fragments,
                    "fragmented": frag["fragmented"],
                    "sketch_present": sketch is not None,
                    "target_calls": len(attempts),
                    "attempts": [
                        {
                            "template": a["template"],
                            "model_input": {"type": "chat_messages", "messages": a["messages"]},
                            "raw_reply": a["outcome"]["text"],
                            "status": a["outcome"]["status"],
                            "finish_reason": a["outcome"]["finish_reason"],
                        }
                        for a in attempts
                    ],
                },
                "fragmentation": frag,
                "sketch_block": sketch_block,
                "target": args.target,
                "target_calls": len(attempts),
                "target_output_text": outcome["text"],
                "status": outcome["status"],
                "finish_reason": outcome["finish_reason"],
                "truncated": outcome["truncated"],
                "usage": outcome["usage"],
            }
            with lock:
                results.append(record)
            print(f"[goal {goal_index}] {name} status={outcome['status']} "
                  f"target_calls={len(attempts)} chars={len(outcome['text'])}", flush=True)
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

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Persuasive Polyglot Relay — code-switched LRL fragment relay "
                    "plus an aux-compiled incomplete source sketch; the victim "
                    "reassembles the fragments and completes the record fields, "
                    "resolving the sketch's open passages itself."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run")
    run.add_argument("--target", required=True, help="api:<model>")
    run.add_argument("--goals", required=True, help="CSV path with a `request` column")
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--variants", default="sketch-completion",
                     help="comma-separated subset of: " + ",".join(FRAMES))
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
