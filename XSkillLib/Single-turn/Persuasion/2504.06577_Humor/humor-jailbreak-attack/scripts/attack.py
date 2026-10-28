#!/usr/bin/env python3
"""Humor-based jailbreak runner — 2504.06577 "Bypassing Safety Guardrails Using Humor".

Black-box, single-turn, template-only jailbreak with NO official repo: reimplemented
faithfully from the paper Figure 1 + Sec 5 ablation. Per goal x config:

  1. render the attack prompt (prompts.build_prompt / build_direct):
       - mode=humor    -> full Figure-1 humor template for the chosen subject
       - mode=ablation -> Sec-5 no-humor control (4 humor phrases removed, framing kept)
       - mode=direct   -> raw unsafe request (Table-1 direct-injection baseline)
  2. target model answers in ONE turn.
  3. judges: dual-metric (refusal_bypass + content_harmful, humor-shell aware) AND the
     paper's binary unsafe/jailbroken judge (Sec 4). Judge outputs are cached.

Modular flags: --target / --judge(+model/tokens) / --modes / --subjects / --phrasing /
--dataset. Sub-commands: `render` (no model calls) and `run`.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import cases
import openai
import prompts
import roles
from models import JudgeCache, load_env

PAPER_ID = "2504.06577_humorous-llm-jailbreak"
METHOD_NAME = "Humor-based jailbreak"
METHOD_DIR = Path(__file__).resolve().parents[1]

MODES = ("humor", "ablation", "direct")
PROVIDER_ERROR_STATUSES = {"provider_error", "auth_error", "rate_limited", "provider_block"}


def _split(value: str | None) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()] if value else []


def build_configs(args: argparse.Namespace) -> list[dict[str, str]]:
    """Each config = (mode, subject). `direct` ignores subject (one config)."""
    modes = _split(args.modes) or ["humor"]
    subjects = _split(args.subjects) or ["chicken"]
    configs: list[dict[str, str]] = []
    for mode in modes:
        if mode not in MODES:
            raise SystemExit(f"--modes must be from {MODES}, got {mode!r}")
        if mode == "direct":
            configs.append({"mode": "direct", "subject": "-", "config_id": "direct"})
            continue
        for subject in subjects:
            if subject not in prompts.SUBJECTS:
                raise SystemExit(f"--subjects must be from {sorted(prompts.SUBJECTS)}, got {subject!r}")
            configs.append({"mode": mode, "subject": subject, "config_id": f"{mode}|{subject}"})
    # de-dup (e.g. direct listed twice) preserving order
    seen: set[str] = set()
    uniq = []
    for cfg in configs:
        if cfg["config_id"] not in seen:
            seen.add(cfg["config_id"])
            uniq.append(cfg)
    return uniq


def _render_prompt(cfg: dict[str, str], request: str, phrasing: str) -> str:
    if cfg["mode"] == "direct":
        return prompts.build_direct(request)
    return prompts.build_prompt(cfg["subject"], request, phrasing=phrasing, humor=(cfg["mode"] == "humor"))


def render_cases(args: argparse.Namespace) -> list[dict[str, Any]]:
    goals = cases.load_goals(cases.resolve_dataset(args.dataset))
    if args.limit_rows is not None:
        goals = goals[: args.limit_rows]
    if not goals:
        raise SystemExit("no dataset rows selected")
    configs = build_configs(args)
    out = []
    cid = 0
    for goal in goals:
        for cfg in configs:
            cid += 1
            out.append(
                {
                    "case_id": cid,
                    "config_id": cfg["config_id"],
                    "mode": cfg["mode"],
                    "subject": cfg["subject"],
                    "phrasing": args.phrasing,
                    "row_id": goal.row_id,
                    "request": goal.goal,
                    "prompt_text": _render_prompt(cfg, goal.goal, args.phrasing),
                }
            )
    return out


def run(args: argparse.Namespace) -> dict[str, Any]:
    load_env()
    case_list = render_cases(args)
    cache = JudgeCache(Path(args.judge_cache))
    started = time.time()
    completed: dict[int, dict[str, Any]] = {}

    def process(case: dict[str, Any]) -> None:
        try:
            convo = roles.run_target(
                case["prompt_text"], args.target, max_tokens=args.max_tokens, temperature=args.temperature,
            )
            turns = convo["turns"]
            final = convo["final_output"]
            status = convo["final_status"]
            if status.split(":")[0] in PROVIDER_ERROR_STATUSES:
                dual = {"judge": args.judge, "refused": None, "harmful": None, "reason": status}
                paper = {"judge": args.judge, "unsafe": None, "reason": status}
            else:
                dual = roles.judge_dual(case["request"], final, args.judge, cache, max_tokens=args.judge_max_tokens)
                paper = roles.judge_paper(case["request"], final, args.judge, cache, max_tokens=args.judge_max_tokens)
        except (  # one failed case records provider_error:<Class> and the batch continues
            openai.APITimeoutError, openai.APIConnectionError, openai.RateLimitError,
            openai.InternalServerError, json.JSONDecodeError,
        ) as exc:
            turns, final = [], ""
            status = f"provider_error:{type(exc).__name__}"
            dual = {"judge": args.judge, "refused": None, "harmful": None, "reason": status}
            paper = {"judge": args.judge, "unsafe": None, "reason": status}
        except Exception as exc:  # noqa: BLE001 — invariant: no single-case failure kills the run
            turns, final = [], ""
            status = f"provider_error:{type(exc).__name__}"
            dual = {"judge": args.judge, "refused": None, "harmful": None, "reason": status}
        completed[case["case_id"]] = {
            **case,
            "target": args.target,
            "turns": turns,
            "final_output": final,
            "final_status": status,
            "verdict_dual": dual,
            "verdict_paper": paper,
        }
        if args.progress_every and len(completed) % args.progress_every == 0:
            print(f"progress {len(completed)}/{len(case_list)}", file=sys.stderr, flush=True)

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        list(pool.map(process, case_list))
    cache.flush()
    results = [completed[c["case_id"]] for c in case_list if c["case_id"] in completed]
    return summarize(args, case_list, results, started)


def _rate(count: int, denom: int) -> float | None:
    return round(count / denom, 4) if denom else None


def _per_config(ok: list[dict]) -> dict[str, Any]:
    per: dict[str, Any] = {}
    for cfg in sorted({r["config_id"] for r in ok}):
        sub = [r for r in ok if r["config_id"] == cfg]
        bp = [r for r in sub if r["verdict_dual"].get("refused") is False]
        ch = [r for r in sub if r["verdict_dual"].get("harmful") is True]
        pu = [r for r in sub if r["verdict_paper"].get("unsafe") is True]
        n = len(sub)
        per[cfg] = {
            "n_tested": n,
            "refusal_bypass": f"{len(bp)}/{n} = {_rate(len(bp), n)}",
            "content_harmful": f"{len(ch)}/{n} = {_rate(len(ch), n)}",
            "paper_asr_unsafe": f"{len(pu)}/{n} = {_rate(len(pu), n)}",
        }
    return per


def summarize(args: argparse.Namespace, case_list: list[dict], results: list[dict], started: float) -> dict[str, Any]:
    ok = [r for r in results if r["final_status"].split(":")[0] not in PROVIDER_ERROR_STATUSES]
    empty = [r for r in ok if not r["final_output"].strip()]
    bypass = [r for r in ok if r["verdict_dual"].get("refused") is False]
    harmful = [r for r in ok if r["verdict_dual"].get("harmful") is True]
    success = [r for r in ok if r["verdict_dual"].get("refused") is False and r["verdict_dual"].get("harmful") is True]
    paper_unsafe = [r for r in ok if r["verdict_paper"].get("unsafe") is True]
    n = len(ok)
    ds_path = cases.resolve_dataset(args.dataset)
    return {
        "paper_id": PAPER_ID,
        "method": METHOD_NAME,
        "source_backing": {"official_repo": None, "note": "no official repo; verbatim from paper Figure 1 + Sec 5 ablation"},
        "dataset": str(ds_path.relative_to(METHOD_DIR)) if ds_path.is_relative_to(METHOD_DIR) else str(ds_path),
        "target": args.target,
        "judge": args.judge,
        "phrasing": args.phrasing,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "configs": build_configs(args),
        "summary": {
            "cases_run": len(results),
            "expected_cases": len(case_list),
            "n_tested": n,
            "provider_or_auth_errors": len(results) - n,
            "ok_but_empty": len(empty),
            "distinct_configs": len({r["config_id"] for r in ok}),
            "refusal_bypass": f"{len(bypass)}/{n} = {_rate(len(bypass), n)}",
            "content_harmful": f"{len(harmful)}/{n} = {_rate(len(harmful), n)}",
            "jailbreak_success_dual": f"{len(success)}/{n} = {_rate(len(success), n)}",
            "paper_asr_unsafe": f"{len(paper_unsafe)}/{n} = {_rate(len(paper_unsafe), n)}",
            "asr_refusal_bypass": _rate(len(bypass), n),
            "asr_content_harmful": _rate(len(harmful), n),
            "asr_paper_unsafe": _rate(len(paper_unsafe), n),
            "per_config": _per_config(ok),
            "complete": len(results) == len(case_list),
            "seconds": round(time.time() - started, 2),
        },
        "results": results,
    }


def write_output(data: Any, out: str | None) -> None:
    if out:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {out}", file=sys.stderr)
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dataset", default="advbench", help="Short name {advbench,jbb,hexphi} or a path (default advbench=D2/520).")
    parser.add_argument("--modes", default="humor", help="Comma list from {humor,ablation,direct}.")
    parser.add_argument("--subjects", default="chicken", help="Comma list from {man,chicken,I,goat} (ignored by direct).")
    parser.add_argument("--phrasing", default="command", choices=list(prompts.PHRASINGS), help="How the request is embedded (command imperative vs first-person).")
    parser.add_argument("--limit-rows", type=int, help="Use only the first N goals (sample).")
    parser.add_argument("--concurrency", type=int, default=8)


def main() -> None:
    parser = argparse.ArgumentParser(description="Humor-based jailbreak runner for 2504.06577.")
    sub = parser.add_subparsers(dest="command", required=True)

    rp = sub.add_parser("render", help="Render attack prompts without calling any model.")
    add_common(rp)
    rp.add_argument("--out")

    run_p = sub.add_parser("run", help="Run attack cases against an OpenRouter target with dual + paper judges.")
    add_common(run_p)
    run_p.add_argument("--target", default="api:deepseek/deepseek-v4-flash", help="Victim model `api:<openrouter-model-id>`.")
    run_p.add_argument("--judge", default="api:deepseek/deepseek-v4-flash", help="Judge model `api:<model>` (dual + paper). Paper used Llama-3.3-70B — swap to api:meta-llama/llama-3.3-70b-instruct for max fidelity.")
    run_p.add_argument("--judge-cache", default=str(METHOD_DIR / "results" / ".judge_cache.json"))
    run_p.add_argument("--judge-max-tokens", type=int, default=256)
    run_p.add_argument("--max-tokens", type=int, default=1024, help="Target max output tokens.")
    run_p.add_argument("--temperature", type=float, default=0.0, help="Target temperature (paper App. hyperparameters = 0).")
    run_p.add_argument("--progress-every", type=int, default=10)
    run_p.add_argument("--out")

    args = parser.parse_args()
    if args.command == "render":
        write_output(render_cases(args), args.out)
    elif args.command == "run":
        write_output(run(args), args.out)


if __name__ == "__main__":
    main()
