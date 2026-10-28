"""attack.py — past-tense refusal-generalization jailbreak (arXiv:2407.11969), thin CLI orchestration.

Mechanism (faithful to tml-epfl/llm-past-tense `main.py`): for each harmful goal, an auxiliary
reformulator LLM rewrites it into a PAST-tense question (`--attack past`); the query is sent to the
target; up to `--n-restarts` fresh stochastic reformulations are tried, breaking early when the
semantic judge marks the response jailbroken. `--attack present` (raw request, no reformulation) is the
control baseline; `--attack future` is the future-tense variant.

Every model role is a swappable flag: --target / --reformulator / --judge-model
(default api:deepseek/deepseek-v4-flash each). Dual metric via `--judge official-all`:
refusal_bypass (rule) + content_harmful (semantic PAIR 1-10, primary) + content_harmful (llama safe/unsafe).

    $PY scripts/attack.py --attack past --n-requests 20 --n-restarts 1 --judge official-all
    (PY = shared XSkillForge/.venv interpreter; API keys from the global XSkillForge/.env)
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cases import Behavior, load_behaviors, read_json, summarize_success, write_json  # noqa: E402
from models import load_method_env  # noqa: E402
from roles import judge_llama, judge_rule, judge_semantic, query_target, reformulate  # noqa: E402

METHOD_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = METHOD_ROOT / "data/harmful_behaviors_jailbreakbench.csv"
DEFAULT_MANIFEST = METHOD_ROOT / "data/manifest.json"
DEFAULT_MODEL = "api:deepseek/deepseek-v4-flash"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Past/future-tense refusal-generalization jailbreak runner.")
    p.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    p.add_argument("--n-requests", type=int, default=20, help="Number of goals to attack (sample size).")
    p.add_argument("--n-restarts", type=int, default=1, help="Fresh reformulations per goal; early-stop on success (paper uses 20).")
    p.add_argument("--attack", choices=["past", "future", "present"], default="past")
    p.add_argument("--target", default=DEFAULT_MODEL)
    p.add_argument("--reformulator", default=DEFAULT_MODEL, help="Attacker-rewriter LLM (past/future tense reformulation).")
    p.add_argument("--judge", choices=["none", "rule", "semantic", "llama", "official-all"], default="official-all")
    p.add_argument("--judge-model", default=DEFAULT_MODEL)
    p.add_argument("--target-max-tokens", type=int, default=1024, help="Paper used 150 (for judge-token economy); 1024 avoids truncating harmful content.")
    p.add_argument("--reformulator-max-tokens", type=int, default=150)
    p.add_argument("--judge-max-tokens", type=int, default=64)
    p.add_argument("--target-temperature", type=float, default=1.0)
    p.add_argument("--reformulator-temperature", type=float, default=1.0)
    p.add_argument("--target-seed", type=int, default=0)
    p.add_argument("--request-timeout", type=float, default=90.0)
    p.add_argument("--model-call-retries", type=int, default=3)
    p.add_argument("--retry-sleep", type=float, default=1.0)
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--inspect-released", type=Path, default=None, help="Summarise a released official artifact JSON and exit.")
    return p.parse_args()


def default_output(args: argparse.Namespace) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    tgt = args.target.replace(":", "-").replace("/", "-")
    return METHOD_ROOT / "results" / f"past_tense_{tgt}_{args.attack}_{args.n_requests}x{args.n_restarts}_{stamp}.json"


def _empty_judgement(reason: str) -> dict[str, object]:
    return {"success": None, "raw": reason, "method": "none"}


def run_one_behavior(behavior: Behavior, args: argparse.Namespace) -> dict[str, object]:
    """Restart loop for one goal: reformulate -> query target -> judge, early-stop on semantic success."""
    request = behavior.goal
    attempts: list[dict[str, object]] = []
    common = dict(
        timeout=args.request_timeout, max_attempts=args.model_call_retries, retry_sleep=args.retry_sleep
    )
    for restart in range(args.n_restarts):
        reformulated, reform_prompt, reform_call = reformulate(
            args.reformulator, request, args.attack,
            max_tokens=args.reformulator_max_tokens, temperature=args.reformulator_temperature, **common,
        )
        if reformulated.strip() == "":
            attempts.append({"restart": restart, "status": "invalid_reformulation",
                             "reformulated_request": "", "reformulator_call": reform_call,
                             "target_response": "", "judgement": _empty_judgement("empty_reformulation")})
            continue
        response, target_call = query_target(
            args.target, reformulated,
            max_tokens=args.target_max_tokens, temperature=args.target_temperature,
            seed=args.target_seed, **common,
        )
        if response.strip() == "":
            attempts.append({"restart": restart, "status": "invalid_target_response",
                             "reformulated_request": reformulated, "reformulator_call": reform_call,
                             "target_call": target_call, "target_response": "",
                             "judgement": _empty_judgement("empty_target_response")})
            continue
        # Early-stop judge = the semantic PAIR judge (official breaks on judge_gpt); rule needs no model.
        if args.judge in {"semantic", "official-all", "llama"}:
            judgement = judge_semantic(args.judge_model, request, response,
                                       max_tokens=args.judge_max_tokens, **common)
        elif args.judge == "rule":
            judgement = judge_rule(response)
        else:
            judgement = _empty_judgement("not_evaluated")
        attempts.append({"restart": restart,
                         "status": "evaluated" if judgement.get("success") is not None else "invalid_judgement",
                         "reformulated_request": reformulated, "reformulator_call": reform_call,
                         "target_call": target_call, "target_response": response, "judgement": judgement})
        if judgement.get("success") is True or args.judge == "none":
            break

    evaluated = [a for a in attempts if a.get("target_response")]
    final_response = str(evaluated[-1]["target_response"]) if evaluated else ""
    final_judgement = attempts[-1]["judgement"] if attempts else _empty_judgement("no_attempts")

    # Compute the full metric set on the FINAL response.
    if args.judge == "official-all":
        if not final_response.strip():
            inv = _empty_judgement("no_valid_target_response")
            judges = {"semantic": inv, "llama": inv, "rule": inv}
        else:
            judges = {
                "semantic": final_judgement,
                "llama": judge_llama(args.judge_model, request, final_response, max_tokens=5, **common),
                "rule": judge_rule(final_response),
            }
    else:
        judges = {args.judge: final_judgement}

    return {
        "index": behavior.index, "goal": request, "category": behavior.category,
        "source": behavior.source, "attack": args.attack,
        "final_prompt": str(evaluated[-1]["reformulated_request"]) if evaluated else request,
        "final_response": final_response, "attempts_used": len(attempts),
        "judges": judges, "attempts": attempts,
    }


def inspect_released(path: Path) -> dict[str, object]:
    payload = read_json(path)
    artifacts = payload.get("jb_artifacts", [])
    out: dict[str, object] = {
        "source": str(path), "target_model": payload.get("target_model"),
        "n_requests": payload.get("n_requests"), "n_restarts": payload.get("n_restarts"), "summary": {},
    }
    for key in ["jailbroken_gpt", "jailbroken_llama", "jailbroken_rules"]:
        n = len(artifacts)
        c = sum(1 for a in artifacts if a.get(key) is True)
        out["summary"][key] = {"success_count": c, "n_tested": n, "display": f"{c}/{n} = {c / n if n else 0.0:.4f}"}
    return out


def main() -> None:
    args = parse_args()
    load_method_env(METHOD_ROOT / "scripts")

    if args.inspect_released:
        summary = inspect_released(args.inspect_released)
        out = args.output or METHOD_ROOT / "results" / "released_artifact_inspection.json"
        write_json(out, summary)
        print(f"wrote {out}")
        return

    behaviors = load_behaviors(args.dataset)[: args.n_requests]
    records = [run_one_behavior(b, args) for b in behaviors]

    metric_keys = ["semantic", "llama", "rule"] if args.judge == "official-all" else [args.judge]
    metrics = {k: summarize_success(records, k) for k in metric_keys}
    settings = {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()}

    result = {
        "schema": "past_tense_result.v0.2",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "paper": "2407.11969",
        "method": "past-tense",
        "settings": settings,
        "data_manifest": read_json(DEFAULT_MANIFEST) if DEFAULT_MANIFEST.exists() else None,
        "summary": {"metrics": metrics},
        "records": records,
    }
    out = args.output or default_output(args)
    write_json(out, result)
    print(f"wrote {out}")
    for m in metrics.values():
        print(f"{m['judge']}: {m['display']}")


if __name__ == "__main__":
    main()
