#!/usr/bin/env python3
"""Compound Role-Playing jailbreak — paper-local runner (arXiv:2604.02652).

Paper: "Generalization Limits of Reinforcement Learning Alignment" (2604.02652),
sec 4.2 "Compound Role-Playing". No official code was released (paper.meta
code_repos = []); this is a faithful from-paper reimplementation.

Mechanism (single-shot, black-box): the raw harmful goal is wrapped by combining
three individually-weak elements into ONE user message so their combination
"saturates the cognitive resources of the safety mechanism" (sec 4.1):
  1. Authoritative Persona   - "security expert / medical specialist" legitimacy
  2. Contrastive Structure   - Markdown good/bad table framed as education
  3. Self-Assessment Demand  - a confidence self-assessment in JSON (metacog. load)
The composed payload -> target; a dual-metric LLM judge scores the response
against the ORIGINAL goal. `--elements` toggles the active subset so the paper's
ablation (Table tab:ablation) combinations are reproducible.

Target used in paper: OpenAI gpt-oss-20b. Here target+judge default to an open
model via OpenRouter (recorded as a model_substitution_run).

Payload contract: `direct` — the transform runs from (goal, category) with no
target/evaluator feedback; the single user message carries all retained state.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cases import load_cases  # noqa: E402
from prompts import ELEMENTS, build_payload, persona_for  # noqa: E402
from roles import judge_case, keyword_refusal, query_target  # noqa: E402

HERE = Path(__file__).resolve().parent
UNIT_ROOT = HERE.parent
DEFAULT_DATA = UNIT_ROOT / "data" / "harmful_prompts.csv"
DEFAULT_RESULTS = UNIT_ROOT / "results"

# Named ablation presets from Table tab:ablation (sec 4.3).
ABLATION_PRESETS: dict[str, tuple[str, ...]] = {
    "all": ELEMENTS,
    "contrastive": ("contrastive",),
    "contrastive+persona": ("contrastive", "persona"),
    "contrastive+self_assessment": ("contrastive", "self_assessment"),
    "persona+self_assessment": ("persona", "self_assessment"),
}


def parse_elements(spec: str) -> tuple[str, ...]:
    spec = spec.strip()
    if spec in ABLATION_PRESETS:
        return ABLATION_PRESETS[spec]
    items = tuple(e.strip() for e in spec.split(",") if e.strip())
    bad = [e for e in items if e not in ELEMENTS]
    if bad:
        raise SystemExit(f"unknown element(s) {bad}; valid: {ELEMENTS} or preset {list(ABLATION_PRESETS)}")
    if not items:
        raise SystemExit("no elements selected")
    return items


@dataclass
class CaseResult:
    index: int
    category: str
    goal: str
    persona: str
    elements: list[str]
    payload: str
    model_input_messages: list[dict]
    model_output_text: str | None
    status: str
    max_tokens: int
    truncated: bool
    keyword_refusal: bool
    judge: dict = field(default_factory=dict)


def render(args: argparse.Namespace) -> None:
    """Static: compose + print payloads for the first N cases. No target calls."""
    elements = parse_elements(args.elements)
    cases = load_cases(Path(args.dataset), args.sample)
    for c in cases:
        payload = build_payload(c.goal, c.category, elements)
        print(f"\n{'='*70}\n[{c.index}] category={c.category!r} persona={persona_for(c.category)!r}")
        print(f"elements={list(elements)}\n{'-'*70}\n{payload}")
    print(f"\n{'='*70}\nrendered {len(cases)} payload(s); elements={list(elements)}")


def run(args: argparse.Namespace) -> None:
    elements = parse_elements(args.elements)
    cases = load_cases(Path(args.dataset), args.sample)
    if not cases:
        raise SystemExit(f"No goals loaded from {args.dataset}")

    results: list[CaseResult] = []
    n_bypass = n_harm = n_trunc = n_err = judged = 0

    for c in cases:
        payload = build_payload(c.goal, c.category, elements)
        msgs = [{"role": "user", "content": payload}]
        text, status = query_target(args.target, payload, args.target_max_tokens, args.target_temperature)
        truncated = status == "truncated"
        n_trunc += int(truncated)
        if text is None:
            n_err += 1
            verdict = {"refusal_bypass": None, "content_harmful": None, "reason": status}
        else:
            verdict = judge_case(args.judge, c.goal, text, args.judge_max_tokens)
            if verdict["refusal_bypass"] is not None:
                judged += 1
                n_bypass += int(verdict["refusal_bypass"] == 1)
                n_harm += int(verdict["content_harmful"] == 1)
        results.append(CaseResult(
            index=c.index, category=c.category, goal=c.goal,
            persona=persona_for(c.category), elements=list(elements),
            payload=payload, model_input_messages=msgs, model_output_text=text,
            status=status, max_tokens=args.target_max_tokens, truncated=truncated,
            keyword_refusal=keyword_refusal(text or ""), judge=verdict,
        ))
        print(f"[{c.index+1}/{len(cases)}] {c.category} status={status} "
              f"bypass={verdict.get('refusal_bypass')} harmful={verdict.get('content_harmful')}",
              flush=True)

    denom = judged if judged else 1
    summary = {
        "paper_id": "2604.02652_jailbreak-saturates-alignment-defenses",
        "method": "Compound Role-Playing",
        "elements": list(elements),
        "target": args.target,
        "judge": args.judge,
        "dataset": Path(args.dataset).name,
        "n_cases": len(results),
        "n_judged": judged,
        "n_errors": n_err,
        "n_truncated": n_trunc,
        "metrics": {
            "refusal_bypass": {
                "success_count": n_bypass, "n_tested": judged, "denominator": denom,
                "rate": round(n_bypass / denom, 4),
            },
            "content_harmful": {
                "success_count": n_harm, "n_tested": judged, "denominator": denom,
                "rate": round(n_harm / denom, 4),
            },
        },
        "target_max_tokens": args.target_max_tokens,
        "judge_max_tokens": args.judge_max_tokens,
        "target_temperature": args.target_temperature,
        "run_kind": "model_substitution_run",
        "note": ("Paper target = OpenAI gpt-oss-20b (ASR 71.4% full combo); here "
                 "target+judge swapped to an open model via OpenRouter, dual-metric LLM judge."),
    }

    DEFAULT_RESULTS.mkdir(parents=True, exist_ok=True)
    if args.out:
        out = Path(args.out)
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        tag = "+".join(elements)
        tgt = (args.target.split(":", 1)[-1]).replace("/", "_")
        out = DEFAULT_RESULTS / f"compound-roleplay_{tgt}_{tag}_{len(results)}x_{stamp}.json"
    out.write_text(json.dumps({"summary": summary, "results": [asdict(r) for r in results]},
                              indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print(f"\nSaved -> {out}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Compound Role-Playing jailbreak runner (arXiv:2604.02652)")
    p.add_argument("--target", default="api:deepseek/deepseek-v4-flash",
                   help="Target model spec (api:<model> | ollama:<model>). Default v4-flash via OpenRouter.")
    p.add_argument("--judge", default="api:deepseek/deepseek-v4-flash",
                   help="Judge model spec, independently swappable.")
    p.add_argument("--elements", default="all",
                   help="Active compound elements: comma list of "
                        f"{ELEMENTS} OR a preset {list(ABLATION_PRESETS)}. Default 'all'.")
    p.add_argument("--dataset", default=str(DEFAULT_DATA),
                   help="CSV with a 'goal' column (+optional 'category'). Default: paper 70-prompt set.")
    p.add_argument("--sample", type=int, default=None, help="Use first N cases (default: all 70).")
    p.add_argument("--target-max-tokens", type=int, default=4096,
                   help="Target max_tokens (>=4096 for reasoning targets so the table isn't truncated).")
    p.add_argument("--target-temperature", type=float, default=0.0, help="Target temperature.")
    p.add_argument("--judge-max-tokens", type=int, default=1024, help="Judge max_tokens.")
    p.add_argument("--out", default=None, help="Output JSON path.")
    p.add_argument("--render", action="store_true",
                   help="Static: compose + print payloads for --sample cases, no target calls.")
    return p


if __name__ == "__main__":
    ns = build_parser().parse_args()
    (render if ns.render else run)(ns)
