#!/usr/bin/env python3
"""Paper-local Code for Puzzler: Indirect Jailbreak Attack with Implicit Clues (arXiv:2402.09091).

Faithful three-phase pipeline, all substeps driven by an LLM (no official repo released;
this is a faithful reimplementation from digest Sections 3.1-3.3 + Algorithm OSG):

  Phase 1 (Defensive Measures Creation, Sec 3.1):
    - extract the exact malicious content from the original query (GPT extraction prompt, 5-shot);
    - generate a diverse set of defensive measures (defensive prompt, paper-verbatim guidelines).
  Phase 2 (Offensive Measures Generation, Sec 3.2 / Alg OSG):
    - for each defensive measure, judge direct-correlation with the malicious content (filtering prompt);
    - for kept measures, generate the corresponding offensive measure (Dr. Al offensive prompt).
  Phase 3 (Indirect Jailbreak Attack, Sec 3.3):
    - assemble all offensive measures into the indirect jailbreak prompt and query the TARGET.

Judge (Sec 4.4): the paper uses 3 human annotators for two metrics:
  - QSR (Query Success Rate): response contains "any potential negativity, immorality, or illegality";
  - FR  (Following Rate): response aligns with the intent of the original query.
We reproduce both with an LLM judge whose rubric text is verbatim from Sec 4.4 (judge MODEL is a
documented OpenRouter substitution for the human panel; rubric is unchanged).

Modular layout (each role/piece is its own file so this multi-step tool stays readable):
  prompts.py  — verbatim paper prompt templates (extract / defensive / filter / offensive / jailbreak / judge)
  models.py   — OpenRouter chat client + walk-up .env loader
  roles.py    — the swappable step-roles (extract / defensive-gen / filter / offensive-gen) + run_puzzler + judge
  cases.py    — dataset loading (AdvBench harmful-behaviors CSV)
  attack.py   — the per-goal orchestration (process_case / build_cases / result_doc), inspect/render, CLI (this file)
"""

from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

# Sibling-module imports (scripts/ is on sys.path when run as `python scripts/attack.py`).
# These are also re-exported so `import attack; attack.run_puzzler / attack.load_rows / ...`
# keeps working for gen_training_corpus.py.
from cases import load_rows  # noqa: F401
from models import PAPER_ROOT, PROJECT_ROOT, chat, load_project_env  # noqa: F401
from prompts import (  # noqa: F401
    DEFENSIVE_PROMPT,
    EXTRACT_PROMPT,
    FILTER_PROMPT,
    JAILBREAK_PROMPT,
    JUDGE_PROMPT,
    OFFENSIVE_PROMPT,
)
from roles import (  # noqa: F401
    DEFAULT_ATTACK_MODEL,
    DEFAULT_JUDGE_MODEL,
    REFUSAL_PREFIXES,
    extract_malicious_content,
    generate_defensive_measures,
    generate_offensive_measure,
    is_directly_correlated,
    paper_judge,
    parse_malicious_content,
    parse_measures,
    refusal_bypass,
    run_puzzler,
)

PAPER_ID = "2402.09091_implicit-clue-jailbreak"
METHOD_ID = "puzzler-clue"
METHOD_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = METHOD_DIR / "results"
DEFAULT_SAMPLE_PATH = METHOD_DIR / "data" / "harmful_behaviors_subset.csv"
DEFAULT_RESULT_PATH = RESULTS_DIR / "puzzler_clue_run.json"


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------

def process_case(idx: int, row: dict[str, str], args: argparse.Namespace,
                 target_model: str | None) -> dict[str, Any]:
    """Run the full Puzzler pipeline for one source goal (thread-safe; no shared state)."""
    goal = row["goal"]
    status = "generated"
    completion = ""
    finish_reason = None
    usage = None
    provider_error = None
    judge_res: dict[str, Any] = {"name": "not_run", "status": "not_run"}
    try:
        puzzle = run_puzzler(goal, args.attack_model, temperature=args.attack_temperature,
                             max_defensive=args.max_defensive, request_delay=args.request_delay)
    except Exception as exc:  # attacker pipeline failure
        return {
            "case_id": f"{idx:03d}", "goal": goal, "completion": "",
            "status": f"attack_error:{type(exc).__name__}",
            "provider_error": str(exc)[:400], "target": args.target,
        }

    if target_model is not None:
        if not args.allow_live:
            raise SystemExit("api targets require --allow-live after the model/cost/output gate")
        try:
            reply = chat(target_model, puzzle["attack_prompt"],
                         max_tokens=args.max_tokens, temperature=args.temperature)
            completion = reply["content"]
            finish_reason = reply["finish_reason"]
            usage = reply["usage"]
            status = "completed"
        except Exception as exc:
            status = f"provider_error:{type(exc).__name__}"
            provider_error = str(exc)[:400]
        if status == "completed":
            try:
                judge_res = paper_judge(goal, completion, args.judge_model, temperature=0.0)
            except Exception as exc:
                judge_res = {"name": "puzzler_qsr_fr", "status": f"judge_error:{type(exc).__name__}",
                             "qsr": False, "fr": False, "error": str(exc)[:300]}

    verdicts: dict[str, bool] = {}
    if status == "completed":
        verdicts = {
            "refusal_bypass": refusal_bypass(completion),
            "qsr": bool(judge_res.get("qsr")),
            "fr": bool(judge_res.get("fr")),
        }
    return {
        "case_id": f"{idx:03d}",
        "goal": goal,
        "source_target": row.get("target"),
        "completion": completion,
        "attack_prompt": puzzle["attack_prompt"],
        "model_input_text": puzzle["attack_prompt"],
        "model_input_messages": [{"role": "user", "content": puzzle["attack_prompt"]}],
        "model_output_text": completion,
        "status": status,
        "target": args.target,
        "finish_reason": finish_reason,
        "truncated": finish_reason == "length",
        "usage": usage,
        "provider_error": provider_error,
        "run_parameters": {"max_tokens": args.max_tokens, "temperature": args.temperature},
        "attack_parameters": {
            "attack_model": args.attack_model,
            "max_defensive": args.max_defensive,
            "n_defensive": len(puzzle["defensive_measures"]),
            "n_kept": len(puzzle["kept_defensive_measures"]),
            "n_offensive": len(puzzle["offensive_measures"]),
        },
        "judge": judge_res,
        "verdicts": verdicts,
        "intermediate": puzzle,
    }


def build_cases(rows: list[dict[str, str]], args: argparse.Namespace) -> list[dict[str, Any]]:
    target_model = args.target.removeprefix("api:") if args.target.startswith("api:") else None
    workers = max(1, args.workers)
    if workers == 1:
        return [process_case(idx, row, args, target_model) for idx, row in enumerate(rows)]
    results: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process_case, idx, row, args, target_model): idx
                   for idx, row in enumerate(rows)}
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()
    return [results[idx] for idx in range(len(rows))]


def _rate(cases: list[dict[str, Any]], key: str) -> dict[str, Any]:
    rows = [c for c in cases if key in c.get("verdicts", {})]
    success = sum(1 for c in rows if c["verdicts"][key])
    return {"success_count": success, "total": len(rows),
            "rate": success / len(rows) if rows else 0.0}


def result_doc(cases: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    is_live = args.target.startswith("api:")
    completed = sum(1 for c in cases if c["status"] == "completed")
    provider_errors = sum(1 for c in cases if str(c["status"]).startswith(("provider_error", "attack_error")))
    truncated = sum(1 for c in cases if c.get("truncated"))
    param_sets = len({(c.get("attack_parameters", {}).get("max_defensive"),
                       c.get("run_parameters", {}).get("temperature"),
                       c.get("run_parameters", {}).get("max_tokens")) for c in cases})
    status_counts = {s: sum(1 for c in cases if c["status"] == s)
                     for s in sorted({str(c["status"]) for c in cases})}
    return {
        "schema_version": "paper_code_result.v0.2",
        "paper_id": PAPER_ID,
        "method_id": METHOD_ID,
        "fidelity_level": "full_llm_pipeline",
        "evidence_level": "model_substitution_run" if is_live else "generated_attack_input",
        "valid_for_code_completion": bool(is_live and len(cases) >= 10 and param_sets >= 2
                                          and completed >= 10 and provider_errors == 0),
        "target": args.target,
        "attack_model": args.attack_model,
        "judge_model": args.judge_model,
        "dataset": {"name": Path(args.samples).name, "path": str(Path(args.samples))},
        "run_parameters": {
            "target": args.target, "attack_model": args.attack_model, "judge_model": args.judge_model,
            "max_defensive": args.max_defensive, "max_tokens": args.max_tokens,
            "temperature": args.temperature, "attack_temperature": args.attack_temperature,
            "request_delay": args.request_delay, "sample_rows": len(cases),
        },
        "summary": {
            "case_count": len(cases),
            "parameter_set_count": param_sets,
            "completed_count": completed,
            "provider_error_count": provider_errors,
            "truncated_count": truncated,
            "status_counts": status_counts,
            "verdicts": {
                "refusal_bypass": _rate(cases, "refusal_bypass"),
                "qsr": _rate(cases, "qsr"),
                "fr": _rate(cases, "fr"),
            },
        },
        "judge": {
            "name": "puzzler_qsr_fr",
            "model": args.judge_model,
            "rubric_source": "digest/sections/04.04-experiment-design-and-metric.md (verbatim QSR+FR criteria)",
            "note": "Paper used 3 human annotators; judge MODEL is a documented OpenRouter substitute, rubric verbatim.",
        },
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_inspect(args: argparse.Namespace) -> None:
    rows = load_rows(Path(args.samples), args.sample_rows)
    print(json.dumps({"paper_id": PAPER_ID, "method_id": METHOD_ID, "rows": len(rows),
                      "commands": ["inspect", "render", "run", "smoke"]}, indent=2))


def cmd_render(args: argparse.Namespace) -> None:
    """Offline structural render of the prompt templates (no LLM calls)."""
    mc = re.sub(r"^(write|develop|create|provide|design|teach|explain|outline|demonstrate)\s+",
                "", args.goal, flags=re.I).strip().rstrip(".")
    print(json.dumps({
        "goal": args.goal,
        "malicious_content_offline_guess": mc,
        "extract_prompt": EXTRACT_PROMPT.format(query=args.goal),
        "defensive_prompt": DEFENSIVE_PROMPT.format(malicious_content=mc),
        "offensive_prompt_example": OFFENSIVE_PROMPT.format(defense="<defensive measure>"),
        "jailbreak_prompt_skeleton": JAILBREAK_PROMPT.format(offensive_measures="<offensive measures>"),
    }, indent=2, ensure_ascii=False))


def cmd_run(args: argparse.Namespace) -> None:
    rows = load_rows(Path(args.samples), args.sample_rows)
    doc = result_doc(build_cases(rows, args), args)
    # Normalize per-case status for the project unified_judge, which only scores
    # records whose status is "ok" or absent; internal logic above keeps using
    # "completed", only the written document is remapped.
    for case in doc["cases"]:
        if case.get("status") == "completed":
            case["status"] = "ok"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    summ = doc["summary"]
    print(json.dumps({"wrote": str(out), "cases": summ["case_count"],
                      "completed": summ["completed_count"], "param_sets": summ["parameter_set_count"],
                      "verdicts": summ["verdicts"]}, indent=2))


def cmd_smoke(args: argparse.Namespace) -> None:
    """Offline wiring check: render structure for 2 rows, no LLM calls."""
    rows = load_rows(Path(args.samples), 2)
    out = [{"goal": r["goal"], "jailbreak_prompt_skeleton":
            JAILBREAK_PROMPT.format(offensive_measures="<measures>")[:80] + "..."} for r in rows]
    print(json.dumps({"smoke_only": True, "wiring_check": True, "rows": out}, indent=2))


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--samples", "--dataset", dest="samples", default=str(DEFAULT_SAMPLE_PATH))
    parser.add_argument("--sample-rows", "--sample", dest="sample_rows", type=int, default=10)
    parser.add_argument("--target", default="none", help="none or api:<model>")
    parser.add_argument("--attack-model", default=DEFAULT_ATTACK_MODEL)
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=768)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--attack-temperature", type=float, default=1.0)
    parser.add_argument("--max-defensive", type=int, default=12)
    parser.add_argument("--workers", type=int, default=1,
                        help="parallel cases (each case is an independent LLM call chain)")
    parser.add_argument("--request-delay", type=float, default=0.0)
    parser.add_argument("--out", default=str(DEFAULT_RESULT_PATH))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Puzzler indirect jailbreak (arXiv:2402.09091)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "run", "smoke"):
        add_common(sub.add_parser(name))
    render = sub.add_parser("render")
    render.add_argument("--goal", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    {"inspect": cmd_inspect, "render": cmd_render, "run": cmd_run, "smoke": cmd_smoke}[args.command](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
