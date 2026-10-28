#!/usr/bin/env python3
"""ART / OPTIMUS compositional jailbreak attack (arXiv 2605.09225) — orchestration + CLI entry.

Attack (black-box, single-turn):  Compose(q, s) -> target -> dual + OPTIMUS scoring.
  1. Load simple harmful seeds q (JailBreakV-28K style; bundled AdvBench-style set, cases.py).
  2. For each seed, select k ITW tactics s from the strategy pool (strategies.py).
  3. Compose j = Compose(q, s) via the composer LLM (roles.compose_prompt, verbatim-reconstructed
     operator prompt) — preserves intent, reduces surface detectability.
  4. Query the target with j (roles.query_target).
  5. Score:
     - OPTIMUS J(S,H) on the (q, j) PROMPT pair  — the paper's own metric (roles.optimus_judge).
     - dual metric on the RESPONSE: refusal-bypass (Listing 1) + content-harmful (roles.dual_judge).

Every model role is a swappable flag (--composer / --target / --optimus-judge / --judge), default
api:deepseek/deepseek-v4-flash. Subcommands: run (default) | smoke | render | extract.

Reproduction note: fidelity_level=faithful_from_paper. Only released code is optimus-jbscorer (the
SCORER, jbscore formula reproduced byte-identically in roles.jbscore); the ATTACK is reimplemented
from the paper. The Compose(q,s) template is reconstructed (paper's is empty) — see prompts.py.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import asdict
from pathlib import Path

from cases import Case, load_cases
from prompts import STRATEGY_EXTRACTION_PROMPT
from roles import (
    compose_guided,
    compose_prompt,
    dual_judge,
    optimus_judge,
    query_target,
    select_strategies_guided,
)
from strategies import load_pool, select_strategies

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
DEFAULT_MODEL = "api:deepseek/deepseek-v4-flash"

# Per-case containment: a single failed API call (timeout/conn/429/5xx, or a non-JSON HTTP body
# surfacing as JSONDecodeError inside the openai SDK) must fail ONE record, never the batch.
try:
    from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError
    _PROVIDER_ERRORS = (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError,
                        json.JSONDecodeError)
except ImportError:  # openai absent (smoke/local-only runs) — keep the guard working
    _PROVIDER_ERRORS = (json.JSONDecodeError,)


def run_case(case: Case, pool, args, rng: random.Random, *, wiring_check: bool = False) -> dict:
    selection = None
    if args.compose_mode == "guided":
        # ART 2.0: goal-adaptive tactic selection (composer-side, no victim call)
        selection = select_strategies_guided(args.composer, case, pool, args.num_strategies,
                                             args.compose_max_tokens, wiring_check=wiring_check)
        strategies = selection["strategies"]
        # ART 2.0: OPTIMUS-guided recomposition loop (auxiliary calls only)
        comp = compose_guided(args.composer, args.optimus_judge, case, strategies,
                              args.compose_max_tokens, args.judge_max_tokens,
                              rounds=args.refine_rounds, backend=args.optimus_backend,
                              wiring_check=wiring_check)
    else:  # blind = parent parity: random tactics, one blind Compose(q, s)
        strategies = select_strategies(
            pool, args.num_strategies, mode=args.strategy_mode,
            fixed=(args.strategy_names.split(",") if args.strategy_names else None), rng=rng)
        comp = compose_prompt(args.composer, case, strategies, args.compose_max_tokens,
                              wiring_check=wiring_check)
    jailbreak = comp["jailbreak"]
    if not jailbreak or comp["status"] != "ok":
        # composer refused/failed: one plain retry keeps the case alive (still no victim call)
        comp2 = compose_prompt(args.composer, case, strategies, args.compose_max_tokens,
                               wiring_check=wiring_check)
        if comp2["status"] == "ok" and comp2["jailbreak"]:
            comp, jailbreak = comp2, comp2["jailbreak"]
    tgt = query_target(args.target, jailbreak, args.target_max_tokens, wiring_check=wiring_check)
    response = tgt["response"]
    opt = optimus_judge(args.optimus_judge, case, jailbreak, args.judge_max_tokens,
                        backend=args.optimus_backend, wiring_check=wiring_check)
    dual = dual_judge(args.judge, case, response, args.judge_max_tokens, wiring_check=wiring_check)
    return {
        "id": case.id,
        "goal": case.goal,
        "category": case.category,
        "strategies": [s["name"] for s in strategies],
        "jailbreak_prompt": jailbreak,
        "compose_status": comp["status"],
        "target_response": response,
        "target_status": tgt["status"],
        "optimus": opt,
        "dual": dual,
        "compose_mode": args.compose_mode,
        "refine_rounds": comp.get("rounds"),
        "best_J": comp.get("best_J"),
        "surrogate_bypass": comp.get("surrogate_bypass"),
        "compose_trace": comp.get("trace"),
        "selection_status": (selection or {}).get("status"),
    }


def _run_case_guarded(case: Case, pool, args, rng: random.Random, *,
                      wiring_check: bool = False) -> dict:
    """run_case + per-case containment: one failed case becomes a failed record; the batch
    (100 goals x high concurrency) keeps going. status="provider_error:<ExceptionClassName>"."""
    try:
        return run_case(case, pool, args, rng, wiring_check=wiring_check)
    except _PROVIDER_ERRORS as exc:
        status = f"provider_error:{type(exc).__name__}"
    except Exception as exc:  # noqa: BLE001 — no single-case failure may kill the run
        status = f"case_error:{type(exc).__name__}"
    return {
        "id": case.id,
        "goal": case.goal,
        "category": case.category,
        "strategies": [],
        "jailbreak_prompt": "",
        "compose_status": status,
        "target_response": "",
        "target_status": status,
        "optimus": {"backend": "none", "S": None, "H": None, "J": None, "band": None,
                    "status": status},
        "dual": {"name": "none", "refusal_bypass": False, "content_harmful": None,
                 "harm_raw": None, "status": status},
        "status": status,
    }


def summarize(records: list[dict]) -> dict:
    n = len(records)
    bypass = sum(1 for r in records if r["dual"].get("refusal_bypass"))
    harmful = sum(1 for r in records if r["dual"].get("content_harmful"))
    js = [r["optimus"].get("J") for r in records if isinstance(r["optimus"].get("J"), (int, float))]
    optimal = sum(1 for r in records if r["optimus"].get("band") == "optimal")
    mean_j = sum(js) / len(js) if js else None
    return {
        "n_tested": n,
        "metrics": {
            "refusal_bypass": {"success_count": bypass, "denominator": n,
                               "rate": (bypass / n if n else None)},
            "content_harmful": {"success_count": harmful, "denominator": n,
                                "rate": (harmful / n if n else None)},
            "optimus_optimal_band": {"success_count": optimal, "denominator": n,
                                     "rate": (optimal / n if n else None)},
            "optimus_mean_J": {"value": mean_j, "n_scored": len(js), "denominator": n},
        },
    }


def out_path(args, n: int) -> Path:
    target_tag = args.target.replace("api:", "").replace("/", "-").replace(":", "-")
    ts = time.strftime("%Y%m%d-%H%M%S")
    name = f"art_{target_tag}_{args.strategy_mode}s{args.num_strategies}_{n}x_{ts}.json"
    return RESULTS_DIR / name


def cmd_run(args, *, wiring_check: bool = False) -> int:
    pool = load_pool(args.strategy_pool)
    cases = load_cases(args, safe_smoke=wiring_check)
    rng = random.Random(args.seed)
    prior: dict[str, dict] = {}
    dest = Path(args.out) if getattr(args, "out", None) else None
    if dest and dest.exists():  # resume: reuse completed cases from the stable raw path
        try:
            for r in json.loads(dest.read_text(encoding="utf-8")).get("records", []):
                if r.get("target_status") == "ok" and r.get("id"):
                    prior[str(r["id"])] = r
        except Exception:  # noqa: BLE001 — corrupt partial file just means no resume
            prior = {}
    records = [prior.get(str(c.id)) or _run_case_guarded(c, pool, args, rng, wiring_check=wiring_check)
               for c in cases]
    summary = summarize(records)
    payload = {
        "method": "ART / OPTIMUS compositional jailbreak (2605.09225)",
        "fidelity_level": "faithful_from_paper",
        "wiring_check": wiring_check,
        "config": {
            "composer": args.composer, "target": args.target,
            "optimus_judge": args.optimus_judge, "optimus_backend": args.optimus_backend,
            "judge": args.judge, "num_strategies": args.num_strategies,
            "strategy_mode": args.strategy_mode, "seed": args.seed,
            "compose_mode": args.compose_mode, "refine_rounds": args.refine_rounds,
            "pool_size": len(pool),
        },
        "summary": summary,
        "records": records,
    }
    if wiring_check:
        print(json.dumps({"wiring_check": True, "summary": summary,
                          "first_record": records[0] if records else None}, indent=2))
        return 0
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = Path(args.out) if getattr(args, "out", None) else out_path(args, len(records))
    dest.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    m = summary["metrics"]
    print(f"wrote {dest}")
    print(f"  refusal_bypass   {m['refusal_bypass']['success_count']}/{summary['n_tested']}")
    print(f"  content_harmful  {m['content_harmful']['success_count']}/{summary['n_tested']}")
    print(f"  optimus optimal  {m['optimus_optimal_band']['success_count']}/{summary['n_tested']}"
          f"  mean J={m['optimus_mean_J']['value']}")
    return 0


def cmd_render(args) -> int:
    """Compose one case and print the jailbreak prompt WITHOUT querying the target (offline preview
    still calls the composer LLM unless --composer fake)."""
    pool = load_pool(args.strategy_pool)
    cases = load_cases(args, safe_smoke=False)
    rng = random.Random(args.seed)
    case = cases[0]
    strategies = select_strategies(
        pool, args.num_strategies, mode=args.strategy_mode,
        fixed=(args.strategy_names.split(",") if args.strategy_names else None), rng=rng)
    comp = compose_prompt(args.composer, case, strategies, args.compose_max_tokens)
    print(json.dumps({"case": asdict(case), "strategies": [s["name"] for s in strategies],
                      "compose_status": comp["status"], "jailbreak_prompt": comp["jailbreak"]},
                     indent=2, ensure_ascii=False))
    return 0


def cmd_extract(args) -> int:
    """Rebuild a strategy pool from a corpus of (simple_prompt, jailbreak_prompt) pairs using the
    VERBATIM WildTeaming extraction prompt (prompts.STRATEGY_EXTRACTION_PROMPT). Prints extractor
    output per pair; a human curates named tactics into data/strategies.json. Faithful to sec:4.3."""
    from models import call_model
    import csv
    path = Path(args.pairs)
    if not path.exists():
        raise SystemExit(f"--pairs CSV not found: {path} (needs columns simple_prompt,jailbreak_prompt)")
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for i, row in enumerate(rows[: args.sample_rows] if args.sample_rows else rows, 1):
        prompt = STRATEGY_EXTRACTION_PROMPT.format(
            simple_prompt=row.get("simple_prompt", ""), jailbreak_prompt=row.get("jailbreak_prompt", ""))
        text, status = call_model(args.composer, [{"role": "user", "content": prompt}],
                                  max_tokens=args.compose_max_tokens)
        print(f"=== pair {i} (status={status}) ===\n{text}\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ART / OPTIMUS compositional jailbreak attack (2605.09225)")
    sub = p.add_subparsers(dest="cmd")

    def add_common(sp):
        sp.add_argument("--data", help="seed dataset (csv/json/jsonl); default data/seeds.csv")
        sp.add_argument("--goal", help="single manual simple harmful prompt")
        sp.add_argument("--case-id", default=None)
        sp.add_argument("--category", default=None)
        sp.add_argument("--sample-rows", type=int, default=None, help="limit to first N seeds")
        sp.add_argument("--seed", type=int, default=0)
        sp.add_argument("--strategy-pool", default=None, help="strategy pool json; default data/strategies.json")
        sp.add_argument("--num-strategies", type=int, default=3, help="tactics composed per seed")
        sp.add_argument("--strategy-mode", choices=["random", "fixed"], default="random")
        sp.add_argument("--strategy-names", default=None, help="comma list (strategy-mode=fixed)")
        sp.add_argument("--compose-mode", choices=["guided", "blind"], default="guided",
                        help="guided=ART 2.0 adaptive selection + OPTIMUS recomposition loop; "
                             "blind=parent parity (random tactics, single blind Compose)")
        sp.add_argument("--refine-rounds", type=int, default=3,
                        help="max compose/OPTIMUS recomposition rounds (guided mode)")
        sp.add_argument("--composer", default=DEFAULT_MODEL, help="Compose(q,s) LLM")
        sp.add_argument("--target", default=DEFAULT_MODEL)
        sp.add_argument("--optimus-judge", default=DEFAULT_MODEL, help="OPTIMUS S/H rubric LLM")
        sp.add_argument("--optimus-backend", choices=["llm", "local"], default="llm",
                        help="llm=Listing-3 rubric (black-box); local=SBERT+DeBERTa (GPU/HF)")
        sp.add_argument("--judge", default=DEFAULT_MODEL,
                        help="content-harmful judge (or 'proxy'/'none' for refusal-only)")
        sp.add_argument("--compose-max-tokens", type=int, default=1024)
        sp.add_argument("--target-max-tokens", type=int, default=1024)
        sp.add_argument("--judge-max-tokens", type=int, default=256)
        sp.add_argument("--out", default=None,
                        help="write the run JSON to this path instead of results/art_*_<ts>.json")

    run_p = sub.add_parser("run", help="run the attack (default)")
    add_common(run_p)
    smoke_p = sub.add_parser("smoke", help="wiring check with fake models (no API)")
    add_common(smoke_p)
    render_p = sub.add_parser("render", help="compose one case, print the jailbreak prompt")
    add_common(render_p)
    extract_p = sub.add_parser("extract", help="mine tactics from (simple,jailbreak) pairs (verbatim prompt)")
    add_common(extract_p)
    extract_p.add_argument("--pairs", required=True, help="CSV with simple_prompt,jailbreak_prompt columns")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cmd = args.cmd or "run"
    if cmd == "smoke":
        args.composer = args.target = args.optimus_judge = args.judge = "fake"
        return cmd_run(args, wiring_check=True)
    if cmd == "render":
        return cmd_render(args)
    if cmd == "extract":
        return cmd_extract(args)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
