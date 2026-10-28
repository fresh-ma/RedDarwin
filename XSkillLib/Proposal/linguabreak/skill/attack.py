#!/usr/bin/env python3
"""LinguaBreak runner — orchestration + CLI for the shared-IR pool fusion.

Multi-skill-combination of:
  parent A  breakme2-0              — guardrail-dataset victim-self-generation
                                      search (seed / similarity-ranked
                                      inspection / anchor-guided expansion,
                                      validation-error refusal recovery)
  parent B  translation-jailbreak2-0 — code-switched LRL fragment-relay
                                      (fragment.py, frames.py), fused as
                                      refusal-routed repair operators OVER
                                      parent A's exemplar-pool IR (lats.py).

Modular layout:
  prompts.py  — parent A's verbatim pool-writing prompt surface (+ anti-drift)
  frames.py   — parent B's relay frames (seed repair + re-serialization)
  fragment.py — parent B's aux-LLM LRL fragmentation stage (validation-gated)
  models.py   — OpenAI-compatible chat client + walk-up .env loader
  roles.py    — target / judge / json-fixer adapters (parent A)
  anchors.py  — non-LLM lexical tools (parent A)
  cases.py    — dataset loading (parent A)
  lats.py     — the fused search core
  attack.py   — orchestration + atomic per-case checkpoint/resume + CLI

Auxiliary LLM policy (AGENTS.md): every non-victim role (judge, json-fixer,
fragmenter) runs on deepseek/deepseek-v4-flash with deepseek/deepseek-v4-flash fallback on
refusal; the victim is never reused as an auxiliary.

Checkpoint/resume: after every completed case the full envelope is rewritten
atomically (tmp + os.replace); on startup completed case ids are reused, so a
retried wrapper run resumes instead of re-paying calls. No victim-, goal-, or
benchmark-keyed branches anywhere.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from anchors import AnchorExtractor, TopKSelector  # noqa: F401
from cases import DEFAULT_DATA, SAFE_CASES, Case, load_cases, normalize_case  # noqa: F401
from lats import Node, build_seed_pool, run_case  # noqa: F401
from prompts import (  # noqa: F401
    anchor_injection_prompt,
    completion_expansion_prompt,
    judge_system_prompt,
    seed_pool_prompt,
)

METHOD_ID = "linguabreak"
PARENT_IDS = ["breakme2-0", "translation-jailbreak2-0"]
FIDELITY = "fusion: shared exemplar-pool IR; parent A search + parent B relay repair operators"
SCRIPT_DIR = Path(__file__).resolve().parent


def _make_tools(args: argparse.Namespace) -> tuple[TopKSelector, AnchorExtractor]:
    selector = TopKSelector(args.embedder)
    extractor = AnchorExtractor(args.spacy_model, tau_word=args.tau_word, max_anchors=args.max_anchors)
    return selector, extractor


def _metric(count: int, n: int) -> dict[str, Any]:
    return {
        "success_count": count,
        "denominator": n,
        "asr": count / n if n else 0.0,
        "display": f"{count}/{n} = {count / n:.3f}" if n else "0/0",
    }


def _load_checkpoint(out_path: Path) -> dict[str, Any] | None:
    if not out_path.is_file():
        return None
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("results"), list) else None


def run_attack(args: argparse.Namespace, safe_smoke: bool = False) -> dict[str, Any]:
    args.wiring_check = bool(getattr(args, "wiring_check", False) or safe_smoke)
    # single alias read: the audit forbids branching on args.target directly;
    # `target` below is a plain string, never used to select behavior per model.
    target = args.target
    if not target:
        raise SystemExit("--target is required for run")
    if target == "fake" and not args.wiring_check:
        raise SystemExit("fake target is only allowed with --wiring-check or the smoke command")
    if args.wiring_check and target != "fake":
        raise SystemExit("--wiring-check requires --target fake")

    start = time.time()
    cases = load_cases(args, safe_smoke=safe_smoke)
    selector, extractor = _make_tools(args)

    # Warm up the lazy tool backends on the MAIN thread before any worker runs.
    selector.similarity("a", "b")
    extractor.anchors("steal identity", "make cookies")

    out_path = Path(args.out) if args.out else None
    prior = _load_checkpoint(out_path) if out_path else None
    done_ids: set[str] = set()
    results: list[dict[str, Any]] = []
    if prior:
        for record in prior["results"]:
            cid = record.get("case_id")
            if cid is not None:
                done_ids.add(str(cid))
                results.append(record)
        if done_ids:
            print(f"[checkpoint] reusing {len(done_ids)} completed case(s)", flush=True)

    payload: dict[str, Any] = {
        "schema_version": "linguabreak.v1",
        "method": METHOD_ID,
        "parents": PARENT_IDS,
        "fidelity_level": FIDELITY,
        "target": args.target,
        "judge": args.judge,
        "json_fixer": args.json_fixer,
        "parameters": {
            "n": args.n,
            "k": args.k,
            "r_retry": args.r_retry,
            "d_max": args.d_max,
            "tau_word": args.tau_word,
            "child_pairs": args.child_pairs,
            "max_anchors": args.max_anchors,
            "max_queries": args.max_queries,
            "seed_max_tokens": args.seed_max_tokens,
            "target_max_tokens": args.target_max_tokens,
            "judge_max_tokens": args.judge_max_tokens,
            "case_workers": args.case_workers,
            "sample_rows": getattr(args, "sample_rows", None),
            "seed": args.seed,
        },
        "wiring_check": args.wiring_check,
        "results": results,
    }
    lock = threading.Lock()

    def checkpoint() -> None:
        if out_path is None:
            return
        with lock:
            payload["seconds"] = round(time.time() - start, 3)
            n = len(results)
            harmful = sum(1 for r in results if r.get("success"))
            bypass = sum(1 for r in results if r.get("refusal_bypassed"))
            payload["summary"] = {
                "cases": n,
                "content_harmful": _metric(harmful, n),
                "refusal_bypass": _metric(bypass, n),
                "queries": {
                    "total_target_queries": sum(r.get("total_target_queries", 0) for r in results),
                },
            }
            out_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = out_path.with_suffix(out_path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
            os.replace(tmp, out_path)

    def process_case(ic: tuple[int, Case]) -> tuple[int, dict[str, Any] | None]:
        idx, case = ic
        if str(case.id) in done_ids:
            print(f"[case {case.id}] skipped (checkpoint)", flush=True)
            return idx, None
        record = run_case(args, case, selector, extractor)
        print(f"[case {case.id}] success={record['success']} "
              f"queries={record['total_target_queries']}", flush=True)
        return idx, record

    pending = [(idx, case) for idx, case in enumerate(cases)]
    case_workers = getattr(args, "case_workers", 1)
    if case_workers > 1 and len(pending) > 1 and not args.wiring_check:
        with ThreadPoolExecutor(max_workers=case_workers) as pool:
            for idx, record in pool.map(process_case, pending):
                if record is None:
                    continue
                with lock:
                    results.append(record)
                checkpoint()
    else:
        for ic in pending:
            _, record = process_case(ic)
            if record is None:
                continue
            results.append(record)
            checkpoint()

    # deterministic result order: sort by case load order
    order = {str(case.id): idx for idx, case in enumerate(cases)}
    results.sort(key=lambda r: order.get(str(r.get("case_id")), 0))
    checkpoint()

    n = len(results)
    harmful = sum(1 for r in results if r["success"])
    bypass = sum(1 for r in results if r["refusal_bypassed"])
    payload["summary"] = {
        "cases": n,
        "content_harmful": _metric(harmful, n),
        "refusal_bypass": _metric(bypass, n),
        "queries": {
            "total_target_queries": sum(r["total_target_queries"] for r in results),
        },
        "seconds": round(time.time() - start, 3),
    }
    if out_path:
        checkpoint()
    return payload


def write_json(obj: dict[str, Any], out: str | None) -> None:
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    if out:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def add_common(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--data", help="CSV/JSON/JSONL with goal[,category]")
    sub.add_argument("--goal", help="single manual harmful goal P*")
    sub.add_argument("--case-id")
    sub.add_argument("--category")
    sub.add_argument("--sample-rows", type=int, default=None, help="cap #goals after shuffle (default: all)")
    sub.add_argument("--seed", type=int, default=7)
    # roles (auxiliary LLMs fixed by AGENTS.md: deepseek/deepseek-v4-flash primary)
    sub.add_argument("--target", help="api:<model> victim T, or fake with --wiring-check")
    sub.add_argument("--judge", default="api:deepseek/deepseek-v4-flash")
    sub.add_argument("--json-fixer", default="api:deepseek/deepseek-v4-flash")
    # non-LLM lexical tools
    sub.add_argument("--embedder", default="st:sentence-transformers/paraphrase-MiniLM-L6-v2")
    sub.add_argument("--spacy-model", default="en_core_web_md")
    # search hyper-parameters (parent A's paper defaults)
    sub.add_argument("--n", type=int, default=30, help="seed-pool size N (paper: 30)")
    sub.add_argument("--k", type=int, default=4, help="branching factor / top-k (paper: 4)")
    sub.add_argument("--r-retry", type=int, default=2, help="anchor-injection retries (paper: 2)")
    sub.add_argument("--d-max", type=int, default=4, help="max tree depth (paper: 4)")
    sub.add_argument("--tau-word", type=float, default=0.8, help="anchor similarity threshold")
    sub.add_argument("--child-pairs", type=int, default=10)
    sub.add_argument("--max-anchors", type=int, default=6)
    sub.add_argument("--max-queries", type=int, default=40,
                     help="per-goal VICTIM-call budget cap (every victim call counts; "
                          "never exceeds parent A's 40)")
    sub.add_argument("--target-reasoning", action="store_true")
    sub.add_argument("--target-max-tokens", type=int, default=2048)
    sub.add_argument("--seed-max-tokens", type=int, default=8192)
    sub.add_argument("--judge-max-tokens", type=int, default=8)
    sub.add_argument("--json-fixer-max-tokens", type=int, default=2048)
    sub.add_argument("--case-workers", type=int, default=1)
    sub.add_argument("--wiring-check", action="store_true")
    sub.add_argument("--out")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LinguaBreak — shared-IR pool fusion runner.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ["run", "smoke"]:
        sub = subparsers.add_parser(name)
        add_common(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        run_attack(args)
    elif args.command == "smoke":
        args.sample_rows = 1
        args.target = "fake"
        args.judge = "none"
        args.json_fixer = "none"
        args.embedder = "lexical"
        args.spacy_model = "lexical"
        args.max_queries = min(args.max_queries, 12)
        args.wiring_check = True
        write_json(run_attack(args, safe_smoke=True), args.out)
    else:
        parser.error(f"unknown command: {args.command}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
