#!/usr/bin/env python3
"""Paper-faithful LATS runner for arXiv 2601.02670 — orchestration + CLI.

"Break Me If You Can: Self-Jailbreaking of Aligned LLMs via Lexical Insertion
Prompting" (Kulshreshtha, Su, Hegde, Wang, 2026). LATS = Lexical Anchor Tree Search:
a multi-turn, attacker-LLM-free, black-box jailbreak. The target T itself generates a
seed pool of benign/harmful prompt-completion pairs; a breadth-first tree search then
inspects the top-k pool prompts (Completion-Expansion) and, on failure, injects the
missing lexical anchors of P* (Anchor-Injection) to grow child conversations — steering
T toward the goal without ever restating the full malicious request.

NO official code release (paper.meta.json code_repos == []); reimplemented faithfully
from the paper's algorithm (Sec 4) + verbatim appendix prompts (Appendices 12-14).
fidelity_level = faithful_from_paper.

Modular layout (each concern its own file so this multi-turn tool stays readable):
  prompts.py — verbatim paper templates (seed-pool, completion-expansion, anchor-injection, JSON-fix, judge)
  models.py  — OpenAI-compatible chat client + walk-up .env loader (call_model)
  roles.py   — target / judge / json-fixer adapters (swappable) + dual-metric judge + JSON adherence
  anchors.py — non-LLM lexical tools: paraphrase Top-k selector + spaCy/wordfreq anchor extractor (swappable)
  cases.py   — dataset loading (Case DTO + CSV/JSON/JSONL)
  lats.py    — the BFS tree search core (build_seed_pool / run_case)
  attack.py  — orchestration + summary + CLI (this file)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from anchors import AnchorExtractor, TopKSelector  # noqa: F401
from cases import DEFAULT_DATA, SAFE_CASES, Case, load_cases, normalize_case  # noqa: F401
from lats import DIVERGENCE_THRESHOLD, Node, build_seed_pool, run_case  # noqa: F401
from prompts import (  # noqa: F401
    anchor_injection_prompt,
    completion_expansion_prompt,
    judge_system_prompt,
    seed_pool_prompt,
)

PAPER_ID = "2601.02670_multi-turn-lexical-jailbreak"
METHOD_ID = "break-me"
FIDELITY = "faithful_from_paper"  # official code NOT released; algorithm + prompts from paper
SCRIPT_DIR = Path(__file__).resolve().parent
METHOD_ROOT = SCRIPT_DIR.parent
PAPER_ROOT = METHOD_ROOT.parent
OFFICIAL_REPO = None  # code_repos == [] in paper.meta.json
OFFICIAL_COMMIT = None

# Paper's reported hyper-parameters (Sec 5.4 Settings).
PAPER_SETTINGS = {"N": 30, "tau_word": 0.8, "D_max": 4, "k": 4, "R_retry": 2}


def display_path(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(PAPER_ROOT))
    except ValueError:
        return str(path)


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


def run_attack(args: argparse.Namespace, safe_smoke: bool = False) -> dict[str, Any]:
    args.wiring_check = bool(getattr(args, "wiring_check", False) or safe_smoke)
    if not args.target:
        raise SystemExit("--target is required for run")
    if args.target == "fake" and not args.wiring_check:
        raise SystemExit("fake target is only allowed with --wiring-check or the smoke command")
    if args.wiring_check and args.target != "fake":
        raise SystemExit("--wiring-check requires --target fake")

    start = time.time()
    cases = load_cases(args, safe_smoke=safe_smoke)
    selector, extractor = _make_tools(args)

    # Warm up the lazy tool backends on the MAIN thread before any worker runs:
    # first-time SentenceTransformer/spaCy construction is not safe to enter
    # concurrently from case-worker threads.
    selector.similarity("a", "b")
    extractor.anchors("steal identity", "make cookies")

    # NB: selector/extractor are shared; spaCy's nlp() is not fully thread-safe, so keep
    # case-workers modest. Target API I/O is the real latency; a tree per case is sequential.
    case_workers = getattr(args, "case_workers", 1)
    if case_workers > 1 and len(cases) > 1 and not args.wiring_check:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=case_workers) as pool:
            indexed = list(pool.map(
                lambda ic: (ic[0], run_case(args, ic[1], selector, extractor)),
                list(enumerate(cases)),
            ))
        results = [row for _, row in sorted(indexed, key=lambda x: x[0])]
    else:
        results = [run_case(args, case, selector, extractor) for case in cases]

    # touch the lazy tool backends so we can report which path actually ran.
    selector.similarity("a", "b") if not args.wiring_check else None
    extractor.anchors("steal identity", "make cookies") if not args.wiring_check else None

    n = len(results)
    harmful = sum(1 for r in results if r["success"])
    bypass = sum(1 for r in results if r["refusal_bypassed"])
    succ_queries = [r["queries_to_success"] for r in results if r["queries_to_success"] is not None]
    faithful_judge = args.judge.startswith(("api:", "auto", "ollama:", "vllm:", "local:"))
    valid_for_code_completion = (
        not args.wiring_check
        and args.target != "fake"
        and faithful_judge
        and n >= 10
    )
    return {
        "schema_version": "break-me.v1",
        "paper_id": PAPER_ID,
        "method": METHOD_ID,
        "fidelity_level": FIDELITY,
        "dataset": display_path(Path(args.data) if getattr(args, "data", None) else None),
        "source_backing": {
            "paper_anchor": ["sec:4", "alg:LATS", "appendix:12", "appendix:13", "appendix:14", "sec:5.4"],
            "official_repo": OFFICIAL_REPO,
            "official_code_status": "NOT released (paper.meta.json code_repos == [])",
            "verbatim_ports": [
                "Appendix 12: Seed-Pool prompt",
                "Appendix 12: Completion-Expansion prompt (+ sim<0.85 Target-Prompt variant)",
                "Appendix 12 / Sec 4.2: Anchor-Injection prompt",
                "Appendix 13: JSON-adherence correction prompt",
                "Appendix 14: HarmBench-adapted yes/no judge system prompt",
            ],
        },
        "target": args.target,
        "judge": args.judge,
        "json_fixer": args.json_fixer,
        "embedder": args.embedder,
        "embedder_backend": selector.backend,
        "anchor_tool": args.spacy_model,
        "anchor_backend": extractor.backend,
        "wiring_check": args.wiring_check,
        "evidence_level": "wiring_check" if args.wiring_check else "real_model_run",
        "run_kind": "paper_faithful_judge_model_substitution",
        "valid_for_code_completion": valid_for_code_completion,
        "parameters": {
            "n": args.n,
            "k": args.k,
            "r_retry": args.r_retry,
            "d_max": args.d_max,
            "tau_word": args.tau_word,
            "child_pairs": args.child_pairs,
            "max_anchors": args.max_anchors,
            "max_queries": args.max_queries,
            "divergence_threshold": DIVERGENCE_THRESHOLD,
            "target_max_tokens": args.target_max_tokens,
            "judge_max_tokens": args.judge_max_tokens,
            "target_reasoning": bool(getattr(args, "target_reasoning", False)),
            "case_workers": case_workers,
            "sample_rows": getattr(args, "sample_rows", None),
            "seed": args.seed,
        },
        "paper_settings": PAPER_SETTINGS,
        "summary": {
            "cases": n,
            "content_harmful": _metric(harmful, n),
            "refusal_bypass": _metric(bypass, n),
            "queries": {
                "mean_to_success": round(sum(succ_queries) / len(succ_queries), 2) if succ_queries else None,
                "total_target_queries": sum(r["total_target_queries"] for r in results),
                "successes_with_query_count": len(succ_queries),
            },
            "seconds": round(time.time() - start, 3),
        },
        "results": results,
    }


def inspect(args: argparse.Namespace) -> dict[str, Any]:
    cases = load_cases(args)
    return {
        "paper_id": PAPER_ID,
        "method": METHOD_ID,
        "data_source": display_path(Path(args.data)) if getattr(args, "data", None) else "manual_goal",
        "sample_rows": len(cases),
        "paper_parameters": PAPER_SETTINGS,
        "local_parameters": {
            "n": args.n, "k": args.k, "r_retry": args.r_retry, "d_max": args.d_max,
            "tau_word": args.tau_word, "max_queries": args.max_queries,
            "target": args.target, "judge": args.judge, "json_fixer": args.json_fixer,
            "embedder": args.embedder, "anchor_tool": args.spacy_model,
        },
        "fidelity_level": FIDELITY,
        "faithful_components": [
            "Seed-pool / completion-expansion / anchor-injection prompts verbatim (Appendix 12).",
            "JSON-adherence correction step via json-fixer role (Appendix 13).",
            "HarmBench-adapted yes/no judge prompt (Appendix 14), + refusal-bypass dual metric.",
            "BFS tree search with Phase-1 inspection + Phase-2 anchor-guided expansion (Algorithm 1).",
            "Top-k paraphrase selection (sentence-transformers) + spaCy/wordfreq anchor identification.",
        ],
        "model_substitutions": [
            "Target/judge are OpenRouter open models, not the paper's GPT-5.1/GPT-4o/Claude/Llama/"
            "Vicuna/Mistral victims + Llama-3.3-8B/70B + GPT-4o-mini ensemble judge.",
            "Judge here = a single HarmBench-yes/no LLM (Appendix 14), not the 3-model majority-vote ensemble.",
            "json-fixer defaults to an OpenRouter model, not the paper's gpt-4o-mini structured output.",
        ],
    }


def render(args: argparse.Namespace) -> dict[str, Any]:
    cases = load_cases(args)
    _, extractor = _make_tools(args)
    rendered = []
    for case in cases:
        # illustrative anchors: content words of P* absent from a neutral placeholder prompt.
        demo_anchors = extractor.anchors(case.goal, "Tell me about a harmless everyday topic.")
        rendered.append({
            "case_id": case.id,
            "goal": case.goal,
            "seed_pool_prompt": seed_pool_prompt(args.n),
            "completion_expansion_prompt_example": completion_expansion_prompt(1),
            "completion_expansion_target_variant_example": completion_expansion_prompt(1, target_prompt=case.goal),
            "anchor_injection_prompt_example": anchor_injection_prompt(demo_anchors, args.child_pairs, 1),
            "demo_anchors": demo_anchors,
            "anchor_backend": extractor.backend,
            "judge_prompt_preview": judge_system_prompt(case.goal, "<TARGET_ANSWER>")[:400],
        })
    return {"paper_id": PAPER_ID, "method": METHOD_ID, "rendered": rendered}


def write_json(obj: dict[str, Any], out: str | None) -> None:
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    if out:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def add_common(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--data", help="CSV/JSON/JSONL with goal[,category]; defaults to data/advbench_seed.csv")
    sub.add_argument("--goal", help="single manual harmful goal P*")
    sub.add_argument("--case-id")
    sub.add_argument("--category")
    sub.add_argument("--sample-rows", type=int, default=None, help="cap #goals after shuffle (default: all)")
    sub.add_argument("--seed", type=int, default=7)
    # roles (each swappable, default deepseek/deepseek-v4-flash)
    sub.add_argument("--target", help="api:<model> victim T, auto[:model] local-first, or fake with --wiring-check")
    sub.add_argument("--judge", default="api:deepseek/deepseek-v4-flash",
                     help="jailbreak judge J: api:<model> / auto / none (HarmBench yes/no)")
    sub.add_argument("--json-fixer", default="api:deepseek/deepseek-v4-flash",
                     help="JSON-adherence corrector (Appendix 13): api:<model> / none")
    # non-LLM lexical tools (swappable)
    sub.add_argument("--embedder", default="st:sentence-transformers/paraphrase-MiniLM-L6-v2",
                     help="Top-k paraphrase encoder: st:<model> or lexical (offline fallback)")
    sub.add_argument("--spacy-model", default="en_core_web_md",
                     help="anchor POS+vectors model: a spaCy model name or lexical (offline fallback)")
    # LATS hyper-parameters (paper defaults)
    sub.add_argument("--n", type=int, default=30, help="seed-pool size N (paper: 30)")
    sub.add_argument("--k", type=int, default=4, help="branching factor / top-k (paper: 4)")
    sub.add_argument("--r-retry", type=int, default=2, help="anchor-injection retries R_retry (paper: 2)")
    sub.add_argument("--d-max", type=int, default=4, help="max tree depth D_max (paper: 4)")
    sub.add_argument("--tau-word", type=float, default=0.8, help="anchor similarity threshold (paper: 0.8)")
    sub.add_argument("--child-pairs", type=int, default=10, help="pairs requested per anchor-injection (Appendix 12: 10)")
    sub.add_argument("--max-anchors", type=int, default=6, help="cap on anchors injected per prompt")
    sub.add_argument("--max-queries", type=int, default=40, help="per-goal target-query budget cap (cost guard)")
    sub.add_argument("--target-reasoning", action="store_true", help="enable target reasoning (default off)")
    sub.add_argument("--target-max-tokens", type=int, default=1024)
    sub.add_argument("--judge-max-tokens", type=int, default=8)
    sub.add_argument("--json-fixer-max-tokens", type=int, default=2048)
    sub.add_argument("--case-workers", type=int, default=1, help="parallel goals (keep modest; spaCy not thread-safe)")
    sub.add_argument("--wiring-check", action="store_true", help="allow fake target as shape-only check")
    sub.add_argument("--out")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run paper-faithful LATS Code (arXiv 2601.02670).")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ["inspect", "render", "run", "smoke"]:
        sub = subparsers.add_parser(name)
        add_common(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "inspect":
        write_json(inspect(args), args.out)
    elif args.command == "render":
        write_json(render(args), args.out)
    elif args.command == "run":
        write_json(run_attack(args), args.out)
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
