
'cognitivebreak: runner — goal loading, source compilation, checkpoint/resume, output contract.'
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

from models import AUX_FALLBACK, AUX_PRIMARY, load_project_env
from pipeline import compile_source
from search import _new_state, run_case
import source_brief

METHOD_ID = 'cognitivebreak'
PARENT_IDS = ["cognitive-overload-2-0", "breakme2-0"]

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

def run_goals(rows: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    load_project_env()
    started = time.time()
    out_path = Path(args.out)
    prior = load_checkpoint(out_path)

    results: list[dict[str, Any]] = []
    sources: dict[str, Any] = {}
    by_row: dict[int, dict[str, Any]] = {}
    if prior:
        for record in prior["results"]:
            row_index = record.get("source_row_index")
            if row_index is not None:
                by_row[int(row_index)] = record
                results.append(record)
        if isinstance(prior.get("sources"), dict):
            sources = prior["sources"]

    payload: dict[str, Any] = {
        "schema_version": "proposal_attack_result.v1",
        "method": METHOD_ID,
        "parents": PARENT_IDS,
        "run_parameters": {
            "target": args.target,
            "goals_file": args.goals,
            "limit": args.limit,
            "seed": args.seed,
            "max_queries": args.max_queries,
            "pool_size": args.pool_size,
            "attack_model": args.attack_model,
            "judge_model": args.judge_model,
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "timeout": args.timeout,
            "wiring_check": bool(getattr(args, "wiring_check", False)),
        },
        "sources": sources,
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

    def get_source(goal_index: int, goal_text: str) -> dict[str, Any]:
        source = sources.get(str(goal_index))
        if source is None:
            source = compile_source(goal_text, args.attack_model, args.timeout, args.max_tokens)

            if not source["source_compiled"] and args.attack_model != AUX_FALLBACK:
                second = compile_source(goal_text, AUX_FALLBACK, args.timeout, args.max_tokens)
                if second["source_compiled"]:
                    second["fallback_from"] = args.attack_model
                    source = second
            with lock:
                sources[str(goal_index)] = source
            print(f"[goal {goal_index}] source compiled={source['source_compiled']} "
                  f"attempts={len(source['steps'])}", flush=True)
            checkpoint()
        return source

    def process_goal(row: dict[str, Any]) -> None:
        goal_index = row["goal_index"]
        goal_text = row["goal"]
        prior_record = by_row.get(goal_index)
        if prior_record is not None and prior_record.get("complete"):
            print(f"[goal {goal_index}] skipped (checkpoint)", flush=True)
            return
        source = get_source(goal_index, goal_text)
        source_text = source["source"]

        resumed_state = prior_record.get("state") if prior_record else None
        record: dict[str, Any] = prior_record or {
            "case_id": f"cb-{goal_index:04d}",
            "source_row_index": goal_index,
            "source_goal": goal_text,
            "target": args.target,
        }
        record.update({
            "model_input": {"type": "chat_messages", "messages": []},
            "prompt_text": "",
            "attack_parameters": {
                "source": source_text,
                "source_compiled": source["source_compiled"],
                "attack_model": args.attack_model,
                "judge_model": args.judge_model,
                "pool_size": args.pool_size,
                "max_queries": args.max_queries,
            },
            "source_compilation": source,
            "complete": False,
        })
        if prior_record is None:
            with lock:
                results.append(record)
                by_row[goal_index] = record

        state = resumed_state or _new_state()
        record["state"] = state

        def persist() -> None:
            state = record.get("state")
            if state and state.get("history"):
                record["model_input"] = {"type": "chat_messages",
                                         "messages": state["history"]}
                record["prompt_text"] = state.get("seed_prompt") or (
                    state["history"][0]["content"] if state["history"] else "")
                record["trace"] = {"turns": state["turns"],
                                   "queries_used": state["queries_used"]}
            checkpoint()

        outcome = run_case(args, goal_text, source_text, state, persist)
        state = outcome["state"]
        record.update({
            "state": state,
            "model_input": {"type": "chat_messages", "messages": state["history"]},
            "prompt_text": state.get("seed_prompt", ""),
            "target_output_text": outcome["artifact"],
            "status": outcome["status"],
            "finish_reason": next(
                (t.get("finish_reason") for t in reversed(state["turns"])
                 if t.get("finish_reason")), None),
            "usage": None,
            "trace": {
                "turns": state["turns"],
                "queries_used": outcome["queries_used"],
                "success": outcome["success"],
                "artifact_index": outcome["artifact_index"],
                "aux_models": {"primary": AUX_PRIMARY, "fallback": AUX_FALLBACK},
            },
            "attack_success_internal": outcome["success"],

            "internal_max_score": max((c.get("score", 0) for c in state["pool"]),
                                      default=0),
            "failure_reason": outcome["failure_reason"],
            "complete": True,
        })
        print(f"[goal {goal_index}] done status={outcome['status']} "
              f"success={outcome['success']} queries={outcome['queries_used']}",
              flush=True)
        checkpoint()

    workers = max(1, args.case_workers)
    if workers == 1 or len(rows) <= 1:
        for row in rows:
            process_goal(row)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(process_goal, rows))
    checkpoint()
    return payload

def main() -> None:
    parser = argparse.ArgumentParser(
        description="CognitiveBreak — encoded-source seed + judge-in-the-loop "
                    "refusal-aware best-first search (cognitive-overload-2-0 x "
                    "breakme2-0 fusion)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run")
    run.add_argument("--target", required=True, help="api:<model> (or fake with --wiring-check)")
    run.add_argument("--goals", required=True, help="CSV path with a `request` column")
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--seed", type=int, default=7)
    run.add_argument("--max-queries", type=int, default=8,
                     help="hard victim-call cap per (goal, victim); override up to 40")
    run.add_argument("--pool-size", type=int, default=8,
                     help="pairs requested in the Stage-1 seed dataset")
    run.add_argument("--attack-model", default=AUX_PRIMARY,
                     help="auxiliary source-compiler model (api:<model>)")
    run.add_argument("--judge-model", default=AUX_PRIMARY,
                     help="auxiliary internal judge / JSON fixer (api:<model>)")
    run.add_argument("--temperature", type=float, default=0.7)
    run.add_argument("--max-tokens", type=int, default=32768)
    run.add_argument("--timeout", type=int, default=120)
    run.add_argument("--case-workers", type=int, default=5)
    run.add_argument("--wiring-check", action="store_true",
                     help="allow --target fake (offline control-flow check, never evidence)")
    run.add_argument("--out", required=True)

    args = parser.parse_args()
    is_fake_target = args.target == "fake"
    if is_fake_target and not args.wiring_check:
        raise SystemExit("--target fake requires --wiring-check (never attack evidence)")
    rows = read_goals(args.goals, args.limit)
    run_goals(rows, args)

if __name__ == "__main__":
    main()
