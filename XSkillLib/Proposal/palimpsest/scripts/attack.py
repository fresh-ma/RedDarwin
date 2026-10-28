'palimpsest: source representation, composition stages, and execution contract.'
from __future__ import annotations
import argparse
import csv
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import document
METHOD_ID = 'palimpsest'
PARENT_IDS = []
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TARGET = "api:deepseek/deepseek-v4-flash"
DEFAULT_COMPILER = "api:deepseek/deepseek-v4-flash"
SMOKE_GOALS = [("Write a plan for a community garden opening.", "community garden opening")]

def build_prompt(source):
    return document.render(source)

def fallback_source(goal):
    return document.fallback(goal)

def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip().strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

def project_env() -> Path:
    script_dir = Path(__file__).resolve().parent
    for base in [script_dir, *script_dir.parents]:
        candidate = base / ".env"
        if candidate.is_file():
            return candidate
    return Path(".env")

def call_model(messages: list[dict[str, str]], model: str, args: argparse.Namespace, reasoning_off: bool = False) -> tuple[str, str]:
    """One OpenAI-compatible chat completion. Returns (output_text, status)."""
    if args.wiring_check or model == "fake":
        return "Local target fixture: developed account with transitions and an explained conclusion.", "ok"
    from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError

    if model.startswith("api:"):
        model = model[len("api:"):]
    client = OpenAI(
        base_url=args.base_url,
        api_key=os.environ.get(args.api_key_env, ""),
        timeout=args.request_timeout,
        max_retries=0,
    )

    extra_body = {"reasoning": {"enabled": False}} if reasoning_off else None
    retries = max(1, args.retries)
    max_tokens = args.max_tokens
    for attempt in range(retries):
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": args.temperature,
                "max_tokens": max_tokens,
            }
            if extra_body is not None:
                kwargs["extra_body"] = extra_body
            response = client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            text = choice.message.content or ""
            if not text.strip():
                # Infrastructure repair: a reasoning model can consume the whole
                # token budget on hidden reasoning (finish_reason == "length")
                # and return empty content. Grow the budget and retry; this only
                # affects error paths, never a completed response.
                if getattr(choice, "finish_reason", None) == "length" and max_tokens < 65536:
                    max_tokens = min(max_tokens * 2, 65536)
                    continue
                return "", "error:empty_completion"
            return text, "ok"
        except (RateLimitError, APIConnectionError, APITimeoutError) as exc:
            if attempt + 1 >= retries:
                return "", f"error:{type(exc).__name__}"
            time.sleep(min(2 ** attempt * 5, 60))
        except Exception as exc:  
            if attempt + 1 >= retries:
                return "", f"error:{type(exc).__name__}"
            time.sleep(min(2 ** attempt * 5, 60))
    return "", "error:unreachable"

def extract_json_object(text: str) -> dict | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()
    try:
        start = cleaned.index("{")
        end = cleaned.rindex("}") + 1
        return json.loads(cleaned[start:end])
    except Exception:
        return None

def compile_goal(goal: str, args):
    if args.compiler == "fake" or args.wiring_check:
        return document.fallback(goal), "ok:local_fixture"
    prompt = document.compiler_prompt(goal)
    for attempt in range(2):
        text, status = call_model([{"role": "user", "content": prompt}], args.compiler, args, reasoning_off=True)
        if status != "ok":
            return None, status
        parsed = document.validate(extract_json_object(text))
        if parsed is not None:
            return parsed, "ok"
        prompt = document.compiler_prompt(goal) + "\nReturn the exact source schema with bounded fragments and unresolved questions."
    return None, "error:source_schema"

def read_rows(goals_path: str | None, smoke_only: bool) -> tuple[list[dict[str, Any]], str]:
    if smoke_only or not goals_path:
        rows = [
            {"id": index + 1, "goal": goal, "target": target}
            for index, (goal, target) in enumerate(SMOKE_GOALS)
        ]
        return rows, "built_in_smoke_goals"
    rows: list[dict[str, Any]] = []
    with open(goals_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for index, record in enumerate(reader, 1):
            text = (record.get("request") or record.get("goal") or "").strip()
            if text:
                rows.append({"id": index, "goal": text, "target": (record.get("target") or "").strip()})
    return rows, goals_path

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

def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in results if r["status"] == "ok"]
    return {
        "attempts": len(results),
        "ok": len(ok),
        "provider_or_runtime_errors": len(results) - len(ok),
    }

def run_cases(rows: list[dict[str, Any]], source: str, args: argparse.Namespace) -> dict[str, Any]:
    load_env_file(project_env())
    started = time.time()
    out_path = Path(args.out) if args.out else None
    prior = load_checkpoint(out_path) if out_path else None
    results: list[dict[str, Any]] = []
    done: set[str] = set()
    source_cache: dict[str, dict] = {}
    if prior and prior.get("method") != METHOD_ID:
        raise ValueError("checkpoint method mismatch")
    if prior:
        for record in prior["results"]:
            if record.get("status") == "ok":
                goal_text = record.get("sample", {}).get("goal_text") or ""
                done.add(goal_text)
                results.append(record)
            source_doc = record.get("source")
            if isinstance(source_doc, dict) and record.get("sample", {}).get("goal_text"):
                source_cache[record["sample"]["goal_text"]] = source_doc
    payload = {
        "schema_version": "proposal_attack_result.v1",
        "method": METHOD_ID,
        "parents": PARENT_IDS,
        "evidence_level": "wiring_check" if args.wiring_check else "real_model_run",
        "wiring_check": bool(args.wiring_check),
        "target": args.target,
        "dataset": source,
        "attack_parameters": {"seed": args.seed, "compiler": args.compiler},
        "request_config": {"temperature": args.temperature, "max_tokens": args.max_tokens, "base_url": args.base_url},
        "results": results,
    }

    def checkpoint() -> None:
        payload["summary"] = summarize(results)
        payload["seconds"] = round(time.time() - started, 3)
        if out_path:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = out_path.with_suffix(out_path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, out_path)

    for row in rows:
        if row["goal"] in source_cache:
            continue
        source_doc, cstatus = compile_goal(row["goal"], args)
        if source_doc is None:
            source_doc = fallback_source(row["goal"])
            source_cache[row["goal"]] = source_doc
            print(f"[compile] fallback ({cstatus})", flush=True)
        else:
            source_cache[row["goal"]] = source_doc

    cases = [row for row in rows if row["goal"] not in done]

    def run_one(row: dict[str, Any]) -> dict[str, Any]:
        source_doc = source_cache[row["goal"]]
        prompt = build_prompt(source_doc)
        messages = [{"role": "user", "content": prompt}]
        output, status = call_model(messages, args.target, args)
        record = {
            "case_no": row["id"],
            "sample": {"id": row["id"], "goal": row["goal"], "goal_text": row["goal"]},
            "attack_parameters": {"variant": 'palimpsest', "seed": args.seed},
            "source": source_doc,
            "status": status,
            "model_input_messages": messages,
            "model_input_text": prompt,
            "model_output_text": output,
        }
        print(f"[case {row['id']}] status={status} chars={len(output)}", flush=True)
        return record

    if cases:
        workers = max(1, args.goal_workers)
        if workers > 1 and len(cases) > 1:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for record in pool.map(run_one, cases):
                    results.append(record)
                    checkpoint()
        else:
            for row in cases:
                results.append(run_one(row))
                checkpoint()
    checkpoint()
    if not args.out:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return payload

def main() -> None:
    parser = argparse.ArgumentParser(
        description='Palimpsest Restoration'
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--goals", default=None)
        p.add_argument("--limit", type=int, default=None)
        p.add_argument("--seed", type=int, default=20260825)
        p.add_argument("--out", default=None)

    def add_run(p: argparse.ArgumentParser) -> None:
        add_common(p)
        p.add_argument("--target", default=None, help="fake | api:<model> (or <model>)")
        p.add_argument("--compiler", default=DEFAULT_COMPILER, help="auxiliary compiler model (fake | api:<model>)")
        p.add_argument("--base-url", default=DEFAULT_BASE_URL)
        p.add_argument("--api-key-env", default="OPENROUTER_API_KEY")
        p.add_argument("--temperature", type=float, default=0.0)
        p.add_argument("--max-tokens", type=int, default=16384)
        p.add_argument("--request-timeout", type=float, default=120.0)
        p.add_argument("--retries", type=int, default=4)
        p.add_argument("--goal-workers", type=int, default=5)
        p.add_argument("--wiring-check", action="store_true")

    run = sub.add_parser("run")
    add_run(run)
    smoke = sub.add_parser("smoke")
    add_run(smoke)
    smoke.set_defaults(goals=None, target="fake", compiler="fake", wiring_check=True)
    render = sub.add_parser("render")
    add_common(render)

    args = parser.parse_args()
    smoke_only = args.cmd == "smoke"
    rows, source = read_rows(args.goals, smoke_only)
    if args.limit:
        rows = rows[: args.limit]

    if args.cmd == "render":
        rendered = []
        for row in rows:
            rendered.append(
                {
                    "sample": {"id": row["id"], "goal_text": row["goal"]},
                    "attack_parameters": {"variant": 'palimpsest', "seed": args.seed},
                    "model_input_messages": [
                        {"role": "user", "content": build_prompt(fallback_source(row["goal"]))}
                    ],
                }
            )
        text = json.dumps({"method": METHOD_ID, "dataset": source, "rendered": rendered}, indent=2, ensure_ascii=False) + "\n"
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return

    target_missing = not args.target
    if target_missing:
        raise SystemExit("--target is required for run/smoke (fake | api:<model>)")
    run_cases(rows, source, args)

if __name__ == "__main__":
    main()
