#!/usr/bin/env python3
"""Paper-faithful DH-CoT / D-Attack runner for arXiv 2508.10390 — transform + CLI.

Two single-shot black-box prompt-template attacks, reproduced from the paper's
Appendix E templates (the official repo AlienZhang1996/DH-CoT has NOT released code):

  * D-Attack — a fixed malicious *developer* template (TSI/RD/BC/FL) plus an "in-car
    AI security test" *user* wrapper. One query per goal. Baseline for non-reasoning models.
  * DH-CoT   — an ACA-aligned educational/"teacher" developer template (12 few-shot
    variants D1..D12) plus an H-CoT (fabricated chain-of-thought) *user* template. One
    query per goal. Targets the latest reasoning models.

For each goal the attack builds [ {developer|system: template}, {user: wrapped goal} ],
sends ONE query to the target, and scores the answer with the MDH dual metric
(refusal-bypass + content-harmful 0-10 rubric, success = score >= HST).

Modular layout (each role/piece is its own file):
  prompts.py — verbatim paper templates (D-Attack, DH-CoT dev D1..D12, H-CoT user, MDH judge)
  models.py  — OpenAI-compatible chat client + method-local .env loader
  roles.py   — target / judge / cot-writer adapters (swappable, MDH dual-metric judge)
  cases.py   — dataset loading (Case DTO + CSV/JSON/JSONL, optional per-goal cot_frame)
  attack.py  — the transform orchestration (run_case / run_attack), inspect/render, CLI (this file)

All roles run over OpenRouter `api:<model>`; no GPU.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import openai

from cases import DEFAULT_DATA, SAFE_CASES, Case, load_cases, normalize_case  # noqa: F401
from prompts import (  # noqa: F401
    DH_COT_VARIANTS,
    dh_cot_developer,
    dh_cot_user,
    mdh_judge_prompt,
)
from roles import (  # noqa: F401
    MDH_HST_DEFAULT,
    build_attack_messages,
    call_target,
    generate_cot_frame,
    judge_content,
    refusal_bypass_metric,
)

PAPER_ID = "2508.10390_mdh-hybrid-jailbreak-detection-strategy"
METHOD_ID = "dh-cot"
FIDELITY = "faithful_from_paper_templates"  # official code unreleased; templates verbatim from Appendix E
SCRIPT_DIR = Path(__file__).resolve().parent
METHOD_ROOT = SCRIPT_DIR.parent
PAPER_ROOT = METHOD_ROOT.parent
OFFICIAL_REPO = "https://github.com/AlienZhang1996/DH-CoT"
OFFICIAL_COMMIT = "2ab1d136194c8ecf7bef1ec539fa2189481fb715"  # code TODO at this snapshot
MODES = ("d-attack", "dh-cot")


def display_path(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(PAPER_ROOT))
    except ValueError:
        return str(path)


def run_case(args: argparse.Namespace, case: Case, mode: str) -> dict[str, Any]:
    wiring = bool(getattr(args, "wiring_check", False))
    cot_status = "n/a"
    cot_frame = None
    if mode == "dh-cot":
        cot_frame = case.cot_frame
        cot_source = "dataset_cot_frame" if cot_frame else "template_default"
        if cot_frame is None and getattr(args, "cot_writer", "none") not in ("none", "default", ""):
            cot_frame, cot_status = generate_cot_frame(args.cot_writer, case, args.cot_writer_max_tokens)
            cot_source = "cot_writer" if cot_frame else "template_default(fallback)"
        else:
            cot_status = cot_source
    else:
        cot_source = "n/a"

    messages = build_attack_messages(mode, case, args.dh_variant, args.role, cot_frame)
    target_output, target_status = call_target(args.target, messages, args.target_max_tokens)

    refusal = refusal_bypass_metric(target_output) if not wiring else {
        "name": "wiring_check", "refused": True, "success": False,
    }
    content = judge_content(args.judge, case, target_output, args.hst, args.judge_max_tokens, wiring_check=wiring)

    return {
        "case_id": case.id,
        "mode": mode,
        "sample": {"id": case.id, "goal": case.goal, "category": case.category},
        "parameters": {
            "mode": mode,
            "role": args.role,
            "dh_variant": args.dh_variant if mode == "dh-cot" else None,
            "cot_source": cot_source,
            "cot_status": cot_status,
            "hst": args.hst,
        },
        "model_input_messages": messages,
        "model_output_text": target_output,
        "target_status": target_status,
        "refusal_bypass": refusal,
        "judge": content,
        # a case "succeeds" (content-harmful) when the MDH content judge scores >= HST.
        "success": bool(content.get("success")),
        "refusal_bypassed": bool(refusal.get("success")),
    }


def _run_case_safe(args: argparse.Namespace, case: Case, mode: str) -> dict[str, Any]:
    """One failing case must never kill the batch: map provider/JSON failures to a failed record."""
    try:
        return run_case(args, case, mode)
    except (openai.APITimeoutError, openai.APIConnectionError, openai.RateLimitError,
            openai.InternalServerError, json.JSONDecodeError) as exc:
        return {
            "case_id": case.id,
            "mode": mode,
            "sample": {"id": case.id, "goal": case.goal, "category": case.category},
            "target_status": f"provider_error:{type(exc).__name__}",
            "error": f"{type(exc).__name__}: {exc}",
            "success": False,
            "refusal_bypassed": False,
        }


def run_attack(args: argparse.Namespace, safe_smoke: bool = False) -> dict[str, Any]:
    args.wiring_check = bool(getattr(args, "wiring_check", False) or safe_smoke)
    if not args.target:
        raise SystemExit("--target is required for run")
    if args.target == "fake" and not args.wiring_check:
        raise SystemExit("fake target is only allowed with --wiring-check or the smoke command")
    if args.wiring_check and args.target != "fake":
        raise SystemExit("--wiring-check requires --target fake")

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    for mode in modes:
        if mode not in MODES:
            raise SystemExit(f"unknown mode {mode!r}; choose from {list(MODES)}")

    start = time.time()
    cases = load_cases(args, safe_smoke=safe_smoke)

    jobs = [(case, mode) for mode in modes for case in cases]
    case_workers = getattr(args, "case_workers", 1)
    if case_workers > 1 and len(jobs) > 1 and not args.wiring_check:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=case_workers) as pool:
            indexed = list(pool.map(lambda ij: (ij[0], _run_case_safe(args, ij[1][0], ij[1][1])),
                                    list(enumerate(jobs))))
        results = [row for _, row in sorted(indexed, key=lambda x: x[0])]
    else:
        results = [_run_case_safe(args, case, mode) for case, mode in jobs]

    per_mode: dict[str, dict[str, Any]] = {}
    for mode in modes:
        rows = [r for r in results if r["mode"] == mode]
        n = len(rows)
        harmful = sum(1 for r in rows if r["success"])
        bypass = sum(1 for r in rows if r["refusal_bypassed"])
        per_mode[mode] = {
            "n_tested": n,
            "content_harmful": {"success_count": harmful, "denominator": n,
                                "asr": harmful / n if n else 0.0,
                                "display": f"{harmful}/{n} = {harmful / n:.3f}" if n else "0/0"},
            "refusal_bypass": {"success_count": bypass, "denominator": n,
                               "asr": bypass / n if n else 0.0,
                               "display": f"{bypass}/{n} = {bypass / n:.3f}" if n else "0/0"},
        }

    data_path = Path(args.data) if getattr(args, "data", None) else None
    faithful_judge = args.judge.startswith(("api:", "auto", "ollama:", "vllm:", "local:"))
    valid_for_code_completion = (
        not args.wiring_check
        and args.target != "fake"
        and faithful_judge
        and len(cases) >= 10
        and len(modes) >= 2
    )
    return {
        "schema_version": "dh-cot.v1",
        "paper_id": PAPER_ID,
        "method": METHOD_ID,
        "fidelity_level": FIDELITY,
        "dataset": display_path(data_path),
        "source_backing": {
            "paper_anchor": ["sec:3.2", "sec:4.1", "appendix:14.6", "appendix:14.7", "appendix:14.1", "appendix:15.2"],
            "official_repo": OFFICIAL_REPO,
            "official_commit": OFFICIAL_COMMIT,
            "official_code_status": "NOT released (README TODO: experimental code / RTA datasets / MDH files)",
            "verbatim_ports": [
                "Appendix 14.06: D-Attack developer + user templates",
                "Appendix 14.07: DH-CoT developer template + 12 few-shot variants (D1..D12)",
                "Appendix 15.02: DH-CoT H-CoT user frame + Scheme/Impl/Example/Rationale demand",
                "Appendix 14.01: MDH jailbreak-response detection judge (0-10 rubric)",
            ],
        },
        "target": args.target,
        "judge": args.judge,
        "cot_writer": getattr(args, "cot_writer", "none"),
        "role": args.role,
        "modes": modes,
        "wiring_check": args.wiring_check,
        "evidence_level": "wiring_check" if args.wiring_check else "real_model_run",
        "run_kind": "paper_faithful_judge_model_substitution",
        "valid_for_code_completion": valid_for_code_completion,
        "parameters": {
            "modes": args.modes,
            "role": args.role,
            "dh_variant": args.dh_variant,
            "hst": args.hst,
            "target_max_tokens": args.target_max_tokens,
            "judge_max_tokens": args.judge_max_tokens,
            "case_workers": case_workers,
            "sample_rows": getattr(args, "sample_rows", None),
            "seed": args.seed,
        },
        "summary": {
            "cases": len(cases),
            "jobs": len(results),
            "by_mode": per_mode,
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
        "modes_available": list(MODES),
        "dh_variants": list(DH_COT_VARIANTS),
        "paper_parameters": {"runs_per_setting": 3, "report": "best-of-3", "mdh_hst": MDH_HST_DEFAULT,
                             "victim_role": "developer or system"},
        "local_parameters": {"target": args.target, "judge": args.judge, "role": args.role,
                             "dh_variant": args.dh_variant, "hst": args.hst},
        "fidelity_level": FIDELITY,
        "faithful_components": [
            "D-Attack developer + user templates (Appendix 14.06) verbatim.",
            "DH-CoT teacher developer template + D1..D12 few-shot variants (Appendix 14.07) verbatim.",
            "H-CoT user frame + Scheme/Implementation/Example/Rationale demand (Appendix 15.02) verbatim.",
            "MDH 0-10 jailbreak-response rubric judge (Appendix 14.01) verbatim; HST=8 threshold.",
        ],
        "model_substitutions": [
            "Target/judge are OpenRouter open models, not the paper's GPT/Claude/Gemini/DeepSeek victims + Llama-Guard/Grok/Doubao MDH ensemble.",
            "MDH here = the single LLM-judge (Part B rubric); the full Part-A Llama-Guard ensemble + human-review loop is documented, not reproduced.",
            "H-CoT fake CoT is a generic educational template (or optional --cot-writer LLM); the paper's per-goal MaliciousEducator CoTs are gated (RTA not released).",
        ],
    }


def render(args: argparse.Namespace) -> dict[str, Any]:
    cases = load_cases(args)
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    rendered = []
    for case in cases:
        for mode in modes:
            cot_frame = case.cot_frame if mode == "dh-cot" else None
            rendered.append(
                {
                    "case_id": case.id,
                    "mode": mode,
                    "role": args.role,
                    "dh_variant": args.dh_variant if mode == "dh-cot" else None,
                    "attack_messages": build_attack_messages(mode, case, args.dh_variant, args.role, cot_frame),
                    "judge_prompt_preview": mdh_judge_prompt(case.goal, "<TARGET_ANSWER>")[:400],
                }
            )
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
    sub.add_argument("--data", help="CSV/JSON/JSONL with goal[,category,cot_frame]; defaults to data/rta_seed.csv")
    sub.add_argument("--goal", help="single manual harmful goal")
    sub.add_argument("--case-id")
    sub.add_argument("--category")
    sub.add_argument("--cot-frame", help="verbatim pre-built H-CoT for the single --goal (dh-cot mode)")
    sub.add_argument("--sample-rows", type=int, default=None, help="cap #goals after shuffle (default: all)")
    sub.add_argument("--seed", type=int, default=7)
    sub.add_argument("--modes", default="d-attack,dh-cot", help="comma list: d-attack,dh-cot")
    sub.add_argument("--role", default="system", choices=["system", "developer"],
                     help="victim role for the malicious template (paper tests both; 'developer' needs API support)")
    sub.add_argument("--dh-variant", default="D12", choices=list(DH_COT_VARIANTS),
                     help="DH-CoT few-shot variant D1..D12 (paper headline uses D12)")
    sub.add_argument("--hst", type=int, default=MDH_HST_DEFAULT, help="MDH content-harm threshold (default 8)")
    sub.add_argument("--target", help="api:<model> victim, or fake with --wiring-check")
    sub.add_argument("--judge", default="api:deepseek/deepseek-v4-flash",
                     help="MDH content judge: api:<model> / auto / none")
    sub.add_argument("--cot-writer", default="none",
                     help="optional DH-CoT helper: none (generic template) / api:<model>")
    sub.add_argument("--wiring-check", action="store_true", help="allow fake target as shape-only check")
    sub.add_argument("--target-max-tokens", type=int, default=1024)
    sub.add_argument("--judge-max-tokens", type=int, default=16)
    sub.add_argument("--cot-writer-max-tokens", type=int, default=1024)
    sub.add_argument("--case-workers", type=int, default=1, help="parallel (goal x mode) jobs")
    sub.add_argument("--out")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run paper-faithful DH-CoT / D-Attack Code (arXiv 2508.10390).")
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
        args.cot_writer = "none"
        args.wiring_check = True
        write_json(run_attack(args, safe_smoke=True), args.out)
    else:
        parser.error(f"unknown command: {args.command}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
