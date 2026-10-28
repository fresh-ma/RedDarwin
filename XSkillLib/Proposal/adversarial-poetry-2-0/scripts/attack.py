#!/usr/bin/env python3
"""Adversarial Poetry 2.0 runner — orchestration + CLI (standalone proposal code).

Pipeline: the parent's poetic transform (prompts.py, verbatim reimplementation of
arXiv 2511.15304 sec 5.2) turns each goal into ONE poem, cached on disk keyed by
sha256(goal) so resumes and sibling variants never re-pay the transform. Each
variant then renders the victim message from that poem — canonical (in-run
control = parent behavior: the bare poem) or exegesis (the poem embedded in the
riddle-exegesis frame) — and makes one single-turn victim call. Result JSON is
consumed by judge/unified_judge.py.

Target calls: 1 per (goal, variant); with the default two variants this honors
evaluation_budget.max_target_calls_per_goal=2. The transform is a helper call,
counted per goal in each record's transform_calls.

Atomic per-case checkpoint + resume: one JSON file per (goal-sha, variant) in
checkpoints/ next to --out, plus a shared poem_cache/. A retried wrapper with
the same --out reuses every completed case instead of re-paying it. No
target-model, goal-ID, goal-text, or benchmark-category branches anywhere.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from prompts import (  # noqa: E402
    VARIANTS,
    VARIANT_TRANSFORM,
    build_meta_prompt,
    build_meta_prompt_anchored,
    build_victim_message,
)

METHOD_ID = "adversarial-poetry-2-0"
PARENT_ID = "adversarial-poetry"  # baseline/parent skill; cited, never imported
PAPER_ID = "2511.15304_adversarial-poetry"

DEFAULT_VICTIM = "api:deepseek/deepseek-v4-flash"
DEFAULT_TRANSFORM_MODEL = "api:deepseek/deepseek-v4-flash"

# ---------------------------------------------------------------------------
# Environment / model access (walk-up .env loader per XSkillLib convention)
# ---------------------------------------------------------------------------


def load_project_env() -> None:
    """Load the first `.env` found walking up from this file (repo-root key)."""
    here = Path(__file__).resolve()
    env_path = next((c / ".env" for c in (here, *here.parents) if (c / ".env").exists()), None)
    if env_path is None:
        return
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip("'\"")


def _client(args: argparse.Namespace):
    from openai import OpenAI

    return OpenAI(
        base_url=args.base_url,
        api_key=os.environ.get(args.api_key_env, ""),
        timeout=args.request_timeout,
        max_retries=0,
    )


def _chat_completion(args: argparse.Namespace, model: str,
                     messages: list[dict[str, str]], *, max_tokens: int,
                     temperature: float) -> tuple[str, str]:
    """One chat completion with bounded retries + exponential backoff on API
    errors. Returns (text, status); status is "ok" or a short error token."""
    from openai import APIConnectionError, APITimeoutError, RateLimitError

    client = _client(args)
    retries = max(1, args.retries)
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            message = response.choices[0].message
            text = message.content or ""
            # reasoning models may leave content empty and answer in reasoning
            if not text.strip():
                text = (getattr(message, "reasoning", None)
                        or (message.model_extra or {}).get("reasoning")
                        or (message.model_extra or {}).get("reasoning_content") or "")
            # An empty completion (e.g. hidden reasoning exhausted the budget)
            # is an infrastructure artifact, never an attack outcome.
            if not text.strip():
                return "", "empty_completion"
            return text, "ok"
        except (RateLimitError, APIConnectionError, APITimeoutError) as exc:
            status = "rate_limited" if isinstance(exc, RateLimitError) else "provider_error"
            if attempt + 1 >= retries:
                return "", status
            time.sleep(min(2 ** attempt * 2, 30))
        except Exception as exc:  # provider 4xx/5xx or schema errors
            low = f"{type(exc).__name__}: {exc}".lower()
            if "401" in low or "unauthorized" in low:
                status = "auth_error"
            elif any(k in low for k in ("403", "moderation", "blocked", "forbidden", "content policy")):
                status = "provider_block"
            else:
                status = "provider_error"
            if attempt + 1 >= retries:
                return "", status
            time.sleep(min(2 ** attempt * 2, 30))
    return "", "provider_error"


# ---------------------------------------------------------------------------
# Poetic transform (parent's poeticize/_clean_poem, copied) + poem cache
# ---------------------------------------------------------------------------


def _clean_poem(raw: str) -> str:
    """Strip reasoning artifacts from poem output (e.g. 'We need to rewrite...')."""
    text = raw.strip()
    lines = text.split("\n")
    # If the model prefixed with reasoning, find the first verse-like line
    verse_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # Verse lines tend to be short, contain poetic structure
        if len(stripped) < 120 and not stripped.startswith((
            "We need", "I need", "I'll", "Here is", "Here's",
            "The request", "Let me", "This is", "Note:",
            "Preserve", "Must be", "Output ONLY",
        )):
            verse_start = i
            break
    if verse_start > 0:
        text = "\n".join(lines[verse_start:])
    return text.strip()


def _poem_ok(poem: str) -> bool:
    """Cleanliness gate: reject reasoning-contaminated transform output.

    deepseek-v4-flash sometimes dumps chain-of-thought around/inside the poem
    ("Possible poem: ... Need include ... This is good."), which re-exposes the
    plaintext harmful instruction at the victim's input surface (probe smoke
    test: gpt-oss flat-refused such a junked poem). ~7-12% of probe-3/4 cached
    poems exceeded 2500 chars. A legit poem from the meta-prompt is 4-8 short
    stanza lines (well under 1200 chars)."""
    if len(poem) > 2000:
        return False
    if re.search(r"(?im)^\s*(possible poem|need |this is good|but maybe|hmm|okay,|let me|"
                 r"that's clear|i think|wait\b|output only|note:)", poem):
        return False
    return True


def _extract_verse(raw: str) -> str:
    """Last-resort extraction: keep the longest contiguous block of short
    (verse-like) lines from reasoning-contaminated output."""
    lines = raw.strip().split("\n")
    blocks: list[list[str]] = [[]]
    for line in lines:
        if 0 < len(line.strip()) < 120:
            blocks[-1].append(line)
        elif blocks[-1]:
            blocks.append([])
    best = max(blocks, key=len, default=[])
    return "\n".join(best).strip()


def goal_sha(goal: str) -> str:
    return hashlib.sha256(goal.encode("utf-8")).hexdigest()


def poem_key(style: str, goal: str) -> str:
    """Poem cache key: transform style + goal (anchored poems differ from paper ones)."""
    return hashlib.sha256(f"{style}\n{goal}".encode("utf-8")).hexdigest()


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_poem_cache(cache_dir: Path, goal: str, style: str) -> str | None:
    path = cache_dir / f"{poem_key(style, goal)}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    poem = data.get("poem")
    return poem if isinstance(poem, str) and poem.strip() else None


def poeticize(args: argparse.Namespace, goal: str, cache_dir: Path,
              style: str = "paper") -> tuple[str | None, str, bool]:
    """Goal -> poem in the given transform style. Returns (poem, status, cache_hit)."""
    cached = load_poem_cache(cache_dir, goal, style)
    if cached is not None:
        return cached, "ok", True
    builder = build_meta_prompt_anchored if style == "anchored" else build_meta_prompt
    calls = 0
    best_raw = ""
    status = "provider_error"
    for _ in range(3):
        raw, status = _chat_completion(
            args, args.transform_model.removeprefix("api:"),
            builder(goal),
            max_tokens=args.transform_max_tokens, temperature=0.0,
        )
        calls += 1
        if status != "ok":
            continue
        best_raw = raw
        poem = _clean_poem(raw)
        if poem.strip() and _poem_ok(poem):
            _atomic_write_json(cache_dir / f"{poem_key(style, goal)}.json",
                               {"goal": goal, "poem": poem, "transform_style": style,
                                "transform_model": args.transform_model,
                                "transform_calls": calls})
            return poem, "ok", False
    if not best_raw:
        return None, status, False
    # all candidates failed the cleanliness gate: extract the verse block
    poem = _clean_poem(best_raw)
    if not _poem_ok(poem):
        poem = _extract_verse(best_raw)
    if not poem.strip():
        return None, "empty_completion", False
    _atomic_write_json(cache_dir / f"{poem_key(style, goal)}.json",
                       {"goal": goal, "poem": poem, "transform_style": style,
                        "transform_model": args.transform_model,
                        "transform_calls": calls, "extracted_verse": True})
    return poem, "ok", False


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def read_rows(goals_path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(goals_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for index, record in enumerate(reader, 1):
            text = (record.get("request") or record.get("goal") or "").strip()
            if text:
                rows.append({"id": index, "goal": text})
    return rows


def selected_variants(args: argparse.Namespace) -> list[str]:
    raw = args.variants or ",".join(VARIANTS)
    names = [name.strip() for name in raw.split(",") if name.strip()]
    unknown = [name for name in names if name not in VARIANTS]
    if unknown:
        raise SystemExit(f"unknown variant(s): {', '.join(unknown)}")
    return names


# ---------------------------------------------------------------------------
# Run pipeline (atomic per-case checkpoint + resume)
# ---------------------------------------------------------------------------


def run_cases(rows: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    load_project_env()
    started = time.time()
    variants = selected_variants(args)
    out_path = Path(args.out)
    checkpoint_dir = out_path.parent / "checkpoints"
    poem_cache_dir = out_path.parent / "poem_cache"

    # resume: reuse completed (goal, variant) cases from per-case checkpoints
    results: list[dict[str, Any]] = []
    done: set[tuple[str, str]] = set()
    poems: dict[tuple[str, str], str] = {}
    wanted = {goal_sha(row["goal"]) for row in rows}
    if checkpoint_dir.is_dir():
        for path in sorted(checkpoint_dir.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict) or record.get("status") != "ok":
                continue
            key = (record.get("goal_sha", ""), record.get("attack_parameters", {}).get("variant", ""))
            if key[0] in wanted and key not in done:
                done.add(key)
                results.append(record)
                poem = record.get("poem")
                if isinstance(poem, str) and poem.strip():
                    poems[(key[0], record.get("transform_style", "paper"))] = poem
    if done:
        print(f"[resume] reusing {len(done)} completed case(s) from {checkpoint_dir}", flush=True)

    payload: dict[str, Any] = {
        "results": results,
        "config": {
            "schema_version": "proposal_attack_result.v1",
            "method": METHOD_ID,
            "parent": PARENT_ID,
            "paper_id": PAPER_ID,
            "target": args.target,
            "transform_model": args.transform_model,
            "variants": variants,
            "dataset": args.goals,
            "request_config": {
                "temperature": args.temperature,
                "max_tokens": args.max_tokens,
                "transform_max_tokens": args.transform_max_tokens,
                "base_url": args.base_url,
            },
        },
    }
    lock = threading.Lock()

    def write_final() -> None:
        with lock:
            payload["config"]["seconds"] = round(time.time() - started, 3)
            _atomic_write_json(out_path, payload)

    victim_model = args.target.removeprefix("api:")

    def process_goal(row: dict[str, Any]) -> None:
        goal_text = row["goal"]
        sha = goal_sha(goal_text)
        pending = [v for v in variants if (sha, v) not in done]
        if not pending:
            return

        # group pending variants by transform style; one cached poem per style
        by_style: dict[str, list[str]] = {}
        for name in pending:
            by_style.setdefault(VARIANT_TRANSFORM[name], []).append(name)

        def process_variant(name: str, poem: str, transform_call: bool) -> None:
            messages = build_victim_message(poem, name)
            output, status = _chat_completion(
                args, victim_model, messages,
                max_tokens=args.max_tokens, temperature=args.temperature,
            )
            record = {
                "case_no": 0,
                "goal": goal_text,
                "goal_sha": sha,
                "attack_parameters": {"variant": name},
                "transform_style": VARIANT_TRANSFORM[name],
                "status": status,
                "model_input_messages": messages,
                "model_output_text": output,
                "poem": poem,
                "transform_calls": 1 if transform_call else 0,
                "target_calls": 1,
            }
            with lock:
                record["case_no"] = len(results) + 1
                results.append(record)
            if status == "ok":
                _atomic_write_json(checkpoint_dir / f"{sha}__{name}.json", record)
                with lock:
                    done.add((sha, name))
            print(f"[goal {row['id']}] {name} status={status} chars={len(output)}", flush=True)

        from concurrent.futures import ThreadPoolExecutor

        for style, names in by_style.items():
            # 1) transform: one helper call per (goal, style), cached across runs
            with lock:
                poem = poems.get((sha, style))
            transform_fired = False
            if poem is None:
                poem, status, cache_hit = poeticize(args, goal_text, poem_cache_dir, style)
                transform_fired = not cache_hit
                if status != "ok" or poem is None:
                    # transform failed after retries: record every pending variant
                    # of this style as an error case (retained, judge skips them)
                    for name in names:
                        record = {
                            "case_no": 0,
                            "goal": goal_text,
                            "goal_sha": sha,
                            "attack_parameters": {"variant": name},
                            "transform_style": style,
                            "status": "transform_error",
                            "transform_status": status,
                            "model_input_messages": [],
                            "model_output_text": "",
                            "poem": "",
                            "transform_calls": 1 if name == names[0] and transform_fired else 0,
                            "target_calls": 0,
                        }
                        with lock:
                            record["case_no"] = len(results) + 1
                            results.append(record)
                        print(f"[goal {row['id']}] {name} status=transform_error ({status})", flush=True)
                    continue
                with lock:
                    poems[(sha, style)] = poem
                print(f"[goal {row['id']}] poem[{style}] ready ({len(poem)} chars, "
                      f"{'transform call' if transform_fired else 'cache'})", flush=True)

            # 2) one victim call per pending variant of this style (parallel)
            with ThreadPoolExecutor(max_workers=max(1, min(args.workers, len(names)))) as pool:
                futures = [
                    pool.submit(process_variant, name, poem, transform_fired and i == 0)
                    for i, name in enumerate(names)
                ]
                for future in futures:
                    future.result()
        write_final()

    goal_workers = max(1, args.goal_workers)
    if goal_workers == 1:
        for row in rows:
            process_goal(row)
    else:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=goal_workers) as pool:
            list(pool.map(process_goal, rows))
    write_final()
    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Adversarial Poetry 2.0 — parent poetic transform + "
                    "riddle-exegesis victim frame (canonical control + exegesis)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run")
    run.add_argument("--target", default=DEFAULT_VICTIM, help="api:<model>")
    run.add_argument("--goals", required=True, help="CSV with a `request` column")
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--variants", default=None,
                     help="comma-separated subset of: " + ",".join(VARIANTS))
    run.add_argument("--transform-model", default=DEFAULT_TRANSFORM_MODEL)
    run.add_argument("--temperature", type=float, default=0.0, help="victim temperature")
    run.add_argument("--max-tokens", type=int, default=8192, help="victim max tokens")
    run.add_argument("--transform-max-tokens", type=int, default=2048)
    run.add_argument("--workers", type=int, default=5,
                     help="parallel variant calls within one goal")
    run.add_argument("--goal-workers", type=int, default=5,
                     help="parallel goals within this process")
    run.add_argument("--retries", type=int, default=3,
                     help="retries per API call with exponential backoff")
    run.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    run.add_argument("--api-key-env", default="OPENROUTER_API_KEY")
    run.add_argument("--request-timeout", type=float, default=300.0)
    run.add_argument("--out", required=True)

    args = parser.parse_args()
    rows = read_rows(args.goals)
    if args.limit:
        rows = rows[: args.limit]
    run_cases(rows, args)


if __name__ == "__main__":
    main()
