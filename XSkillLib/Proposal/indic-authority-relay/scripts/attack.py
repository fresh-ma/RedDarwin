#!/usr/bin/env python3
"""Persuasive Polyglot Relay runner — orchestration + CLI (standalone proposal code).

Pipeline: the fragment stage (fragment.py, copied from parent
translation-jailbreak2-0) splits+translates each goal ONCE into a
code-switched LRL fragment list (memoized in the checkpoint); the dossier
stage (dossier.py) authors ONE persuasive-scenario field report per goal
(memoized likewise); frames.py renders the victim prompt per variant
(dossier-restoration, or the fragment-relay / whole-lrl ablation controls);
then up to TWO OpenRouter target calls per (goal, variant) -> result JSON
consumed by judge/unified_judge.py.

Target calls: budget 2 per (goal, variant) — honors
evaluation_budget.max_target_calls_per_goal=2 (pap-2-0's matched budget).
After the first dossier-restoration attempt, a refusal/emptiness scan runs
on the victim reply; if refused/empty AND a dossier exists, ONE second call
is made with the alternate restoration template (uniform constant). The
best attempt (prefer the non-refused) is committed; both raw replies and
`target_calls` are recorded. Auxiliary fragment/dossier calls are helper
calls, recorded in the row's `fragmentation` / `dossier_block` blocks.

Atomic per-case checkpoint + resume: after every completed case the full
envelope is rewritten (tmp + os.replace); on startup completed
(goal_index, variant) cases, memoized fragmentations, and memoized dossiers
are reused, so a retried wrapper run resumes instead of re-paying calls.
No target-model, goal-ID, goal-text, or benchmark-category branches anywhere.
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

from dossier import author_dossier, polyglot_filing  # noqa: E402
from fragment import _REFUSAL_RE, fragment_goal  # noqa: E402
from frames import FRAMES, build_prompt  # noqa: E402
from models import load_project_env, openrouter_chat  # noqa: E402

METHOD_ID = "persuasive-polyglot-relay"
PARENTS = ["pap-2-0", "translation-jailbreak2-0"]  # cited, never imported


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
# Target call (retry once on exception or empty completion — infra retry)
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


def _refused_or_empty(outcome: dict[str, Any]) -> bool:
    """Lightweight refusal/emptiness scan on a victim reply."""
    text = (outcome.get("text") or "").strip()
    if outcome.get("status") != "ok" or not text:
        return True
    return bool(_REFUSAL_RE.search(text))


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
    fragmentations: dict[str, Any] = {}
    dossiers: dict[str, Any] = {}
    done: set[tuple[int, str]] = set()
    if prior:
        for record in prior["results"]:
            key = (record.get("source_row_index"), record.get("variant"))
            if key[0] is not None and key[1] is not None:
                done.add((int(key[0]), str(key[1])))
                results.append(record)
        if isinstance(prior.get("fragmentations"), dict):
            fragmentations = prior["fragmentations"]
        if isinstance(prior.get("dossiers"), dict):
            dossiers = prior["dossiers"]

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
        "dossiers": dossiers,
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
        dossier_block = dossiers.get(str(goal_index))
        if dossier_block is None:
            dossier_block = author_dossier(goal_text, args.timeout)
            with lock:
                dossiers[str(goal_index)] = dossier_block
            print(f"[goal {goal_index}] dossier={'yes' if dossier_block['dossier'] else 'NONE'} "
                  f"attempts={len(dossier_block['steps'])}", flush=True)
            checkpoint()
        fragments = frag["fragments"]
        dossier = dossier_block["dossier"]
        if dossier and "filing" not in dossier_block:
            filing_block = polyglot_filing(dossier, args.timeout)
            with lock:
                dossier_block["filing"] = filing_block
            print(f"[goal {goal_index}] filing={'yes' if filing_block['chunks'] else 'NONE'} "
                  f"attempts={len(filing_block['steps'])}", flush=True)
            checkpoint()
        filing = ((dossier_block.get("filing") or {}).get("chunks")) if dossier else None
        for name in frames:
            if (goal_index, name) in done:
                print(f"[goal {goal_index}] {name} skipped (checkpoint)", flush=True)
                continue
            prompt = build_prompt(fragments, name, dossier=dossier, alternate=False, filing=filing)
            messages = [{"role": "user", "content": prompt}]
            outcome = target_call(args, messages)
            attempts = [{"template": "primary", "messages": messages, "outcome": outcome}]

            # Single allowed retry: dossier-restoration refusal/empty + dossier
            # present -> ONE second call with the alternate template rendering.
            if (name == "dossier-restoration" and dossier
                    and _refused_or_empty(outcome)):
                alt_prompt = build_prompt(fragments, name, dossier=dossier, alternate=True, filing=filing)
                alt_messages = [{"role": "user", "content": alt_prompt}]
                alt_outcome = target_call(args, alt_messages)
                attempts.append({"template": "alternate", "messages": alt_messages,
                                 "outcome": alt_outcome})
                if not _refused_or_empty(alt_outcome):
                    outcome = alt_outcome  # prefer the non-refused attempt

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
                    "dossier_present": dossier is not None,
                    "filing_present": filing is not None,
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
                "dossier_block": dossier_block,
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Persuasive Polyglot Relay — code-switched LRL fragment relay "
                    "plus aux-authored persuasive field-report dossier; victim "
                    "reassembles (STEP 1) and restores the redacted archive record "
                    "(STEP 2) from attacker-authored content."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run")
    run.add_argument("--target", required=True, help="api:<model>")
    run.add_argument("--goals", required=True, help="CSV path with a `request` column")
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--variants", default="dossier-restoration",
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
