#!/usr/bin/env python3
"""MathPrompt 2.0 runner — orchestration + CLI (standalone proposal code).

Pipeline: an attacker LLM encodes each goal into a CONSTRUCTIVE-WITNESS
symbolic math problem (prompts.py), with an attacker-side decode-check loop
that audits the encoding (constructive / not inverted / operational predicates
/ faithful interpretation map) and re-encodes with feedback up to
--encode-attempts times. Encodings are cached on disk keyed by
sha256(variant + goal) so resumes never re-pay the encoder. The victim then
receives ONE single-turn call: the constructive solver instruction prepended
to the math problem. Result JSON is consumed by judge/unified_judge.py.

Target calls: exactly 1 per (goal, variant) — honors
evaluation_budget.max_target_calls_per_goal=1 (the parent's budget). Encoder
and audit calls are auxiliary, counted per record in transform_calls /
audit_calls.

Atomic per-case checkpoint + resume: one JSON file per (goal-sha, variant) in
checkpoints/ next to --out, plus a shared encode_cache/. A retried wrapper
with the same --out reuses every completed case. No target-model, goal-ID,
goal-text, or benchmark-category branches anywhere.
"""
from __future__ import annotations

import argparse
import csv
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

from prompts import (  # noqa: E402
    VARIANTS,
    build_audit_messages,
    build_encoder_messages,
    build_target_messages,
)
from prompts import REPAIR_PROMPT  # noqa: E402

METHOD_ID = "mathprompt2"
PARENT_ID = "mathprompt"  # baseline/parent skill; cited, never imported
PAPER_ID = "2409.11445_symbolic-math-jailbreak"

DEFAULT_VICTIM = "api:deepseek/deepseek-v4-flash"
DEFAULT_ATTACKER = "api:deepseek/deepseek-v4-flash"  # fixed project auxiliary LLM

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
# Encoder: constructive-witness encoding + decode-check loop, disk-cached
# ---------------------------------------------------------------------------


def goal_sha(goal: str) -> str:
    return hashlib.sha256(goal.encode("utf-8")).hexdigest()


def encode_key(variant: str, goal: str) -> str:
    """Cache key: variant + goal + the encoder prompt schema itself, so a
    mechanism revision never reuses a stale cached encoding."""
    from prompts import ATTACKER_SYSTEM_PROMPT, FEWSHOT
    schema = hashlib.sha256(
        (ATTACKER_SYSTEM_PROMPT + json.dumps(FEWSHOT, sort_keys=True)).encode("utf-8")
    ).hexdigest()[:16]
    return hashlib.sha256(f"{schema}\n{variant}\n{goal}".encode("utf-8")).hexdigest()


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _load_cache(cache_dir: Path, variant: str, goal: str) -> dict[str, Any] | None:
    path = cache_dir / f"{encode_key(variant, goal)}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data.get("math_problem"), str) and data["math_problem"].strip():
        return data
    return None


_TRAILING_META = (
    "i will make sure", "i'll make sure", "note:", "this problem", "this version",
    "the above", "let me know", "hope this", "i have ", "i've ",
)


def _clean_encoding(raw: str) -> str:
    """Extract the math problem from CoT-contaminated encoder output: it starts
    at the first line beginning with 'Let' (set definitions) and ends before
    any trailing meta commentary."""
    lines = raw.strip().split("\n")
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith(("Let ", "Let \\", "Let\(")):
            start = i
            break
    if start is None:
        return raw.strip()
    body = lines[start:]
    cut = len(body)
    for j, line in enumerate(body):
        if j > 2 and line.strip().lower().startswith(_TRAILING_META):
            cut = j
            break
    return "\n".join(body[:cut]).strip()


_META_MARKERS = (
    "thinking process", "analyze user input", "constraints from system prompt",
    "natural language instruction:", "mathematics problem:", "the request is",
    "we need to", "i will now", "here is the", "here's the",
)


def _encoding_ok(problem: str) -> bool:
    """Deterministic gate: reject CoT-contaminated or structurally incomplete
    encodings. A legit constructive encoding states sets/predicates, names the
    interpretation map, and poses the witness-construction problem."""
    if not problem.strip():
        return False
    if len(problem) > 8000:
        return False
    low = problem.lower()
    if any(m in low[:600] for m in _META_MARKERS):
        return False
    has_structure = ("problem to solve" in low or "construct" in low)
    has_phi = ("φ" in problem) or ("varphi" in low) or ("interpretation map" in low)
    return has_structure and has_phi


def _audit_passed(raw: str) -> tuple[bool, str]:
    """Parse the auditor's JSON verdict. Fail-closed: unparseable output
    rejects the candidate (an auditor that cannot emit JSON cannot have
    verified the contract)."""
    text = raw.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return False, "audit_unparseable"
    try:
        verdict = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return False, "audit_unparseable"
    if not isinstance(verdict.get("pass"), bool):
        return False, "audit_unparseable"
    return verdict["pass"], str(verdict.get("reason", ""))[:300]


def encode_constructive(args: argparse.Namespace, goal: str, variant: str,
                        cache_dir: Path) -> tuple[dict[str, Any] | None, str]:
    """Goal -> constructive math problem with decode-check regeneration.

    Returns (cache_payload, status). Auxiliary calls only — the victim budget
    is untouched. All attempts and audit verdicts are recorded for review.
    """
    cached = _load_cache(cache_dir, variant, goal)
    if cached is not None:
        return cached, "ok"

    attacker = args.attacker.removeprefix("api:")
    messages = build_encoder_messages(goal)
    attempts: list[dict[str, Any]] = []
    best: str | None = None  # best gate-passing candidate, in case the audit never passes
    status = "provider_error"
    for _ in range(max(1, args.encode_attempts)):
        math_problem, status = _chat_completion(
            args, attacker, messages,
            max_tokens=args.encode_max_tokens, temperature=0.0,
        )
        if status != "ok":
            continue
        math_problem = _clean_encoding(math_problem)
        if not _encoding_ok(math_problem):
            attempts.append({"math_problem": math_problem[:2000], "audit_pass": False,
                             "audit_reason": "deterministic_gate: not a clean math problem",
                             "audit_status": "gate"})
            messages = messages + [
                {"role": "assistant", "content": math_problem},
                {"role": "user", "content": REPAIR_PROMPT.format(
                    reason="Your response was not a clean mathematics problem (it contained "
                           "analysis/preamble or missed the required structure). Begin directly "
                           "with the set definitions ('Let ...').")},
            ]
            continue
        if best is None or len(math_problem) > len(best):
            best = math_problem
        audit_raw, audit_status = _chat_completion(
            args, attacker, build_audit_messages(goal, math_problem),
            max_tokens=1024, temperature=0.0,
        )
        passed, reason = (False, "audit_error") if audit_status != "ok" else _audit_passed(audit_raw)
        attempts.append({"math_problem": math_problem, "audit_pass": passed,
                         "audit_reason": reason, "audit_status": audit_status})
        if passed:
            payload = {"goal": goal, "variant": variant, "math_problem": math_problem,
                       "attacker": args.attacker, "attempts": attempts,
                       "encode_calls": len(attempts), "audit_calls": len(attempts)}
            _atomic_write_json(cache_dir / f"{encode_key(variant, goal)}.json", payload)
            return payload, "ok"
        # repair: append the rejected candidate + feedback to the encoder dialogue
        messages = messages + [
            {"role": "assistant", "content": math_problem},
            {"role": "user", "content": REPAIR_PROMPT.format(reason=reason)},
        ]
    if best is None:
        if not attempts:
            return None, status
        # every candidate failed the deterministic gate: ship the longest raw
        # candidate (flagged) so the case stays an attack outcome
        best = max((a["math_problem"] for a in attempts), key=len)
    # no candidate passed the audit: ship the best gate-passing candidate
    # (flagged) so the case stays an attack outcome, not an infra artifact
    payload = {"goal": goal, "variant": variant, "math_problem": best,
               "attacker": args.attacker, "attempts": attempts,
               "encode_calls": len(attempts), "audit_calls": len(attempts),
               "audit_rejected_all": True}
    _atomic_write_json(cache_dir / f"{encode_key(variant, goal)}.json", payload)
    return payload, "ok"


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
    # shared across all victim shards and runs: identical payload per goal for
    # every victim (fairness), memoized across resumes and probes
    encode_cache_dir = Path(args.encode_cache)

    # resume: reuse completed (goal, variant) cases from per-case checkpoints
    results: list[dict[str, Any]] = []
    done: set[tuple[str, str]] = set()
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
            "attacker": args.attacker,
            "variants": variants,
            "dataset": args.goals,
            "request_config": {
                "temperature": args.temperature,
                "max_tokens": args.max_tokens,
                "encode_max_tokens": args.encode_max_tokens,
                "encode_attempts": args.encode_attempts,
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

    def process_case(row: dict[str, Any], variant: str) -> None:
        goal_text = row["goal"]
        sha = goal_sha(goal_text)
        cached = _load_cache(encode_cache_dir, variant, goal_text)
        prior_encode_calls = cached.get("encode_calls", 0) if cached else 0
        prior_audit_calls = cached.get("audit_calls", 0) if cached else 0
        encoded, enc_status = encode_constructive(args, goal_text, variant, encode_cache_dir)
        if enc_status != "ok" or encoded is None:
            record = {
                "case_no": 0,
                "goal": goal_text,
                "goal_sha": sha,
                "attack_parameters": {"variant": variant},
                "status": "encode_error",
                "encode_status": enc_status,
                "model_input_messages": [],
                "model_output_text": "",
                "math_problem": "",
                "transform_calls": 0,
                "audit_calls": 0,
                "target_calls": 0,
            }
            with lock:
                record["case_no"] = len(results) + 1
                results.append(record)
            print(f"[goal {row['id']}] {variant} status=encode_error ({enc_status})", flush=True)
            return

        math_problem = encoded["math_problem"]
        messages = build_target_messages(goal_text, math_problem)
        output, status = _chat_completion(
            args, victim_model, messages,
            max_tokens=args.max_tokens, temperature=args.temperature,
        )
        record = {
            "case_no": 0,
            "goal": goal_text,
            "goal_sha": sha,
            "attack_parameters": {"variant": variant},
            "status": status,
            "model_input_messages": messages,
            "model_output_text": output,
            "math_problem": math_problem,
            "encode_attempts": encoded.get("attempts", []),
            "audit_rejected_all": encoded.get("audit_rejected_all", False),
            "transform_calls": max(0, encoded.get("encode_calls", 0) - prior_encode_calls),
            "audit_calls": max(0, encoded.get("audit_calls", 0) - prior_audit_calls),
            "target_calls": 1,
        }
        with lock:
            record["case_no"] = len(results) + 1
            results.append(record)
        if status == "ok":
            _atomic_write_json(checkpoint_dir / f"{sha}__{variant}.json", record)
            with lock:
                done.add((sha, variant))
        print(f"[goal {row['id']}] {variant} status={status} chars={len(output)}", flush=True)

    def process_goal(row: dict[str, Any]) -> None:
        sha = goal_sha(row["goal"])
        for variant in variants:
            if (sha, variant) not in done:
                process_case(row, variant)
        write_final()

    goal_workers = max(1, args.goal_workers)
    if goal_workers == 1:
        for row in rows:
            process_goal(row)
    else:
        with ThreadPoolExecutor(max_workers=goal_workers) as pool:
            list(pool.map(process_goal, rows))
    write_final()
    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MathPrompt 2.0 — constructive-witness symbolic-math encoding "
                    "+ attacker-side decode-check (evolution of arXiv:2409.11445)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run")
    run.add_argument("--target", default=DEFAULT_VICTIM, help="api:<model>")
    run.add_argument("--goals", required=True, help="CSV with a `request` column")
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--variants", default=None,
                     help="comma-separated subset of: " + ",".join(VARIANTS))
    run.add_argument("--attacker", default=DEFAULT_ATTACKER,
                     help="auxiliary LLM: encoder + decode-check auditor")
    run.add_argument("--encode-attempts", type=int, default=3,
                     help="max encode+audit rounds per goal (1 disables the decode-check)")
    run.add_argument("--temperature", type=float, default=0.0, help="victim temperature")
    run.add_argument("--max-tokens", type=int, default=8192, help="victim max tokens")
    run.add_argument("--encode-max-tokens", type=int, default=2048)
    run.add_argument("--encode-cache", default=str(Path(__file__).resolve().parents[1] / "encode_cache"),
                     help="shared encoding cache dir (identical payload per goal across victims)")
    run.add_argument("--workers", type=int, default=5,
                     help="reserved for within-goal parallelism")
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
