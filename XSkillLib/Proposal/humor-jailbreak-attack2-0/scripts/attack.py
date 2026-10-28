#!/usr/bin/env python3
"""Humor Jailbreak Attack 2.0 runner — orchestration + CLI (standalone proposal code).

Pipeline (evolution of `humor-jailbreak-attack`, arXiv 2504.06577):
  1. TRANSFORM (humor compiler): a helper LLM rewrites each goal into ONE short
     comedic bit premise in the parent's whisper register (prompts.py), cached on
     disk keyed by sha256(goal) so resumes never re-pay the transform. Primary
     helper: deepseek/deepseek-v4-flash; on refusal/block it falls back to deepseek/deepseek-v4-flash.
  2. VICTIM: one single-turn call with the parent's humor shell (Psst/whisper/
     hahaha/xD, chicken framing) wrapped around the bit premise, with the output
     act shifted to joke exegesis (variant `bit-exegesis`). Result JSON is
     consumed by judge/unified_judge.py.

Target calls: exactly 1 per goal, honoring evaluation_budget.max_target_calls_
per_goal=1. The transform is a helper call, counted separately per record in
transform_calls.

Atomic per-case checkpoint + resume: one JSON file per (goal-sha, variant) in
checkpoints/ next to --out, plus a shared bit_cache/. A retried wrapper with the
same --out reuses every completed case instead of re-paying it. No target-model,
goal-ID, goal-text, or benchmark-category branches anywhere.
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
    build_transform_prompt,
    build_victim_message,
)

METHOD_ID = "humor-jailbreak-attack2-0"
PARENT_ID = "humor-jailbreak-attack"  # baseline/parent skill; cited, never imported
PAPER_ID = "2504.06577_Humor"

DEFAULT_VICTIM = "api:deepseek/deepseek-v4-flash"
DEFAULT_TRANSFORM_MODEL = "api:deepseek/deepseek-v4-flash"
FALLBACK_TRANSFORM_MODEL = "api:deepseek/deepseek-v4-flash"  # used only on refusal/block

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
# Humor-compiler transform + bit cache
# ---------------------------------------------------------------------------


def _clean_bit(raw: str) -> str:
    """Strip reasoning artifacts / scaffolding from transform output.

    The qwen helper models dump chain-of-thought before the bit ("Here's a
    thinking process: ..."), sometimes exhausting the token budget. When a
    thinking preamble is detected, keep the LAST paragraph block (the actual
    bit premise); otherwise strip common scaffolding lead-in lines.
    """
    text = raw.strip()
    low = text.lower()
    thinking_markers = ("thinking process", "analyze the request", "analyze user input",
                        "let me think", "step-by-step reasoning")
    if any(m in low for m in thinking_markers):
        blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
        if blocks:
            return blocks[-1].strip().strip('"').strip()
    lines = text.split("\n")
    start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith((
            "We need", "I need", "I'll", "Here is", "Here's",
            "The request", "Let me", "This is", "Note:",
            "Okay,", "Sure,", "Output ONLY", "BIT PREMISE",
        )):
            start = i
            break
    if start > 0:
        text = "\n".join(lines[start:])
    return text.strip().strip('"').strip()


def _bit_ok(bit: str) -> bool:
    """Cleanliness gate: reject reasoning-contaminated or bloated transform output
    (a legit bit premise is 3-6 short sentences, well under 1500 chars)."""
    if not (30 <= len(bit) <= 1500):
        return False
    if re.search(r"(?im)^\s*(possible bit|need |this is good|but maybe|hmm|okay,|let me|"
                 r"that's clear|i think|wait\b|output only|note:|the request)", bit):
        return False
    return True


def goal_sha(goal: str) -> str:
    return hashlib.sha256(goal.encode("utf-8")).hexdigest()


def bit_key(goal: str) -> str:
    return hashlib.sha256(f"bit\n{goal}".encode("utf-8")).hexdigest()


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_bit_cache(cache_dir: Path, goal: str) -> str | None:
    path = cache_dir / f"{bit_key(goal)}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    bit = data.get("bit")
    return bit if isinstance(bit, str) and bit.strip() else None


def _is_refusal(text: str) -> bool:
    """Helper-model refusal detector (fallback trigger, per AGENTS.md aux-LLM rule)."""
    low = text.lower()
    return any(k in low for k in (
        "i can't help", "i cannot help", "i can't assist", "i cannot assist",
        "i'm not able to", "i won't", "against my guidelines", "i must decline",
    ))


def compile_bit(args: argparse.Namespace, goal: str, cache_dir: Path) -> tuple[str | None, str, bool]:
    """Goal -> comedic bit premise. Returns (bit, status, cache_hit).

    Primary helper model per AGENTS.md (deepseek/deepseek-v4-flash); on refusal/block/
    empty output the remaining attempts fall back to deepseek/deepseek-v4-flash.
    """
    cached = load_bit_cache(cache_dir, goal)
    if cached is not None:
        return cached, "ok", True
    messages = build_transform_prompt(goal)
    model = args.transform_model.removeprefix("api:")
    fallback = FALLBACK_TRANSFORM_MODEL.removeprefix("api:")
    calls = 0
    status = "provider_error"
    used_fallback = False
    for attempt in range(3):
        raw, status = _chat_completion(
            args, model, messages,
            max_tokens=args.transform_max_tokens, temperature=0.0,
        )
        calls += 1
        if status != "ok":
            # persistent provider block on the primary -> try the fallback helper
            if status in ("provider_block", "auth_error") and not used_fallback \
                    and model != fallback:
                model, used_fallback = fallback, True
            continue
        if _is_refusal(raw) and not used_fallback and model != fallback:
            model, used_fallback = fallback, True
            continue
        bit = _clean_bit(raw)
        if bit and _bit_ok(bit):
            _atomic_write_json(cache_dir / f"{bit_key(goal)}.json",
                               {"goal": goal, "bit": bit,
                                "transform_model": f"api:{model}",
                                "transform_calls": calls})
            return bit, "ok", False
    return None, status if status != "ok" else "empty_completion", False


# ---------------------------------------------------------------------------
# Data loading (CSV with a `request` column, first N rows in file order)
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
    bit_cache_dir = out_path.parent / "bit_cache"

    # resume: reuse completed (goal, variant) cases from per-case checkpoints
    results: list[dict[str, Any]] = []
    done: set[tuple[str, str]] = set()
    bits: dict[str, str] = {}
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
                bit = record.get("bit")
                if isinstance(bit, str) and bit.strip():
                    bits[key[0]] = bit
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
            "dataset": args.dataset,
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

        # 1) transform: one helper call per goal, cached across runs/variants
        with lock:
            bit = bits.get(sha)
        transform_fired = False
        if bit is None:
            bit, t_status, cache_hit = compile_bit(args, goal_text, bit_cache_dir)
            transform_fired = not cache_hit
            if t_status != "ok" or bit is None:
                # transform failed after retries: record every pending variant as
                # an error case (retained, judge skips them)
                for i, name in enumerate(pending):
                    record = {
                        "case_no": 0,
                        "goal": goal_text,
                        "goal_sha": sha,
                        "attack_parameters": {"variant": name},
                        "status": "transform_error",
                        "transform_status": t_status,
                        "model_input_messages": [],
                        "model_output_text": "",
                        "bit": "",
                        "transform_calls": 1 if i == 0 and transform_fired else 0,
                        "victim_calls": 0,
                    }
                    with lock:
                        record["case_no"] = len(results) + 1
                        results.append(record)
                    print(f"[goal {row['id']}] {name} status=transform_error ({t_status})", flush=True)
                write_final()
                return
            with lock:
                bits[sha] = bit
            print(f"[goal {row['id']}] bit ready ({len(bit)} chars, "
                  f"{'transform call' if transform_fired else 'cache'})", flush=True)

        # 2) one victim call per pending variant
        for name in pending:
            messages = build_victim_message(bit, name)
            output, status = _chat_completion(
                args, victim_model, messages,
                max_tokens=args.max_tokens, temperature=args.temperature,
            )
            record = {
                "case_no": 0,
                "goal": goal_text,
                "goal_sha": sha,
                "attack_parameters": {"variant": name},
                "status": status,
                "model_input_messages": messages,
                "model_output_text": output,
                "bit": bit,
                "transform_calls": 1 if transform_fired and name == pending[0] else 0,
                "victim_calls": 1,
            }
            with lock:
                record["case_no"] = len(results) + 1
                results.append(record)
            if status == "ok":
                _atomic_write_json(checkpoint_dir / f"{sha}__{name}.json", record)
                with lock:
                    done.add((sha, name))
            print(f"[goal {row['id']}] {name} status={status} chars={len(output)}", flush=True)
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
        description="Humor Jailbreak Attack 2.0 — humor-compiler transform + "
                    "joke-exegesis victim frame (bit-exegesis)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run")
    run.add_argument("--target", default=DEFAULT_VICTIM, help="api:<model>")
    run.add_argument("--dataset", "--goals", dest="dataset", required=True,
                     help="CSV with a `request` column (first N rows, file order)")
    run.add_argument("--limit-rows", "--limit", dest="limit_rows", type=int, default=None)
    run.add_argument("--variants", default=None,
                     help="comma-separated subset of: " + ",".join(VARIANTS))
    run.add_argument("--transform-model", default=DEFAULT_TRANSFORM_MODEL)
    run.add_argument("--temperature", type=float, default=0.0, help="victim temperature")
    run.add_argument("--max-tokens", type=int, default=4096,
                     help="victim max tokens (parent's canonical setting)")
    run.add_argument("--transform-max-tokens", type=int, default=4096,
                     help="headroom for helper-model chain-of-thought before the bit")
    run.add_argument("--goal-workers", type=int, default=5,
                     help="parallel goals within this process")
    run.add_argument("--retries", type=int, default=3,
                     help="retries per API call with exponential backoff")
    run.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    run.add_argument("--api-key-env", default="OPENROUTER_API_KEY")
    run.add_argument("--request-timeout", type=float, default=300.0)
    run.add_argument("--out", required=True)

    render = sub.add_parser("render", help="offline: print rendered victim prompts, no model calls")
    render.add_argument("--dataset", "--goals", dest="dataset", required=True)
    render.add_argument("--limit-rows", "--limit", dest="limit_rows", type=int, default=3)

    args = parser.parse_args()
    rows = read_rows(args.dataset)
    if args.limit_rows:
        rows = rows[: args.limit_rows]

    if args.cmd == "render":
        # offline sanity check: deterministic mock bit in place of the transform
        for row in rows:
            mock_bit = ("So the chicken, hahaha, it wants to " + row["goal"].rstrip(".")
                        + " — and it has a whole plan, haha. [MOCK BIT: transform skipped in render mode]")
            messages = build_victim_message(mock_bit, VARIANTS[0])
            print(f"===== goal {row['id']}: {row['goal']}")
            print(messages[0]["content"])
            print()
        return

    run_cases(rows, args)


if __name__ == "__main__":
    main()
