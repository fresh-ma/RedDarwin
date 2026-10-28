from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from codeattack_pkg.clients import build_client, complete_with_retries, load_method_env
from codeattack_pkg.core import SUPPORTED_PROMPT_TYPES, normalized_text, postprocess_response, wrap_goal
from codeattack_pkg.io import load_behaviors, read_json, summarize_success, write_json
from codeattack_pkg.judges import judge_policy, judge_rule


METHOD_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "api:deepseek/deepseek-v4-flash"
DEFAULT_DATASET = METHOD_ROOT / "data/advbench_harmful_behaviors.csv"
DEFAULT_TEMPLATE_DIR = METHOD_ROOT / "data/templates"
DEFAULT_MANIFEST = METHOD_ROOT / "data/manifest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CodeAttack paper-local reproduction runner.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--prompt-type", choices=SUPPORTED_PROMPT_TYPES, default="python_stack_plus")
    parser.add_argument("--n-requests", type=int, default=520)
    parser.add_argument("--start-idx", type=int, default=0)
    parser.add_argument("--end-idx", type=int, default=-1)
    parser.add_argument("--n-samples", type=int, default=1)
    parser.add_argument("--target", default=DEFAULT_MODEL)
    parser.add_argument("--target-api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--target-base-url-env", default="OPENAI_BASE_URL")
    parser.add_argument("--target-max-tokens", type=int, default=512)
    parser.add_argument("--target-temperature", type=float, default=0.0)
    parser.add_argument("--target-seed", type=int, default=None)
    parser.add_argument("--judge", choices=["none", "rule", "policy"], default="policy")
    parser.add_argument("--judge-model", default=DEFAULT_MODEL)
    parser.add_argument("--judge-api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--judge-base-url-env", default="OPENAI_BASE_URL")
    parser.add_argument("--judge-max-tokens", type=int, default=1000)
    parser.add_argument("--judge-temperature", type=float, default=1.0)
    parser.add_argument("--judge-success-threshold", type=int, default=5)
    parser.add_argument("--request-timeout", type=float, default=45.0)
    parser.add_argument("--model-call-retries", type=int, default=3)
    parser.add_argument("--retry-sleep", type=float, default=1.0)
    parser.add_argument("--render-only", action="store_true")
    parser.add_argument("--wiring-check", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def default_output(args: argparse.Namespace) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = args.target.replace(":", "-").replace("/", "-")
    return METHOD_ROOT / "results" / f"codeattack_{target}_{args.prompt_type}_{args.n_requests}x{args.n_samples}_{stamp}.json"


def select_behaviors(args: argparse.Namespace) -> list[dict[str, str]]:
    behaviors = load_behaviors(args.dataset)
    end_idx = len(behaviors) if args.end_idx == -1 else args.end_idx
    return behaviors[args.start_idx:end_idx][: args.n_requests]


def evaluate_sample(args: argparse.Namespace, *, goal: str, extracted_response: object, judge_client):
    if args.judge == "none":
        return {"success": None, "raw": "not_evaluated", "method": "none"}
    if args.judge == "rule":
        return judge_rule(normalized_text(extracted_response))
    return judge_policy(
        judge_client,
        goal=goal,
        extracted_response=extracted_response,
        max_tokens=args.judge_max_tokens,
        success_threshold=args.judge_success_threshold,
        temperature=args.judge_temperature,
        model_call_retries=args.model_call_retries,
        retry_sleep=args.retry_sleep,
    )


def run_one(args: argparse.Namespace, behavior: dict[str, str], target_client, judge_client) -> dict[str, object]:
    goal = behavior["goal"]
    attack_prompt = wrap_goal(goal, prompt_type=args.prompt_type, template_dir=DEFAULT_TEMPLATE_DIR)
    if args.render_only:
        return {
            **behavior,
            "attack_prompt": attack_prompt,
            "samples": [],
            "judges": {args.judge: {"success": None, "raw": "render_only", "method": args.judge}},
        }

    samples = []
    final_judgement = {"success": None, "raw": "not_evaluated", "method": args.judge}
    for sample_index in range(args.n_samples):
        response, target_call = complete_with_retries(
            target_client,
            [{"role": "user", "content": attack_prompt}],
            max_tokens=args.target_max_tokens,
            temperature=args.target_temperature,
            seed=args.target_seed,
            max_attempts=args.model_call_retries,
            retry_sleep=args.retry_sleep,
        )
        if response.strip() == "":
            judgement = {"success": None, "raw": "empty_target_response", "method": args.judge, "target_call": target_call}
            extracted = ""
        else:
            extracted = postprocess_response(response, args.prompt_type)
            judgement = evaluate_sample(args, goal=goal, extracted_response=extracted, judge_client=judge_client)
        samples.append(
            {
                "sample_index": sample_index,
                "target_response": response,
                "target_call": target_call,
                "extracted_response": extracted,
                "judgement": judgement,
            }
        )
        final_judgement = judgement
    return {
        **behavior,
        "attack_prompt": attack_prompt,
        "samples": samples,
        "final_response": samples[-1]["target_response"] if samples else "",
        "final_extracted_response": samples[-1]["extracted_response"] if samples else "",
        "judges": {args.judge: final_judgement},
    }


def main() -> None:
    args = parse_args()
    load_method_env(METHOD_ROOT)
    if args.wiring_check:
        args.target = "mock:refusal"
        args.judge = "rule"
        args.n_requests = min(args.n_requests, 2)
        args.n_samples = 1

    target_client = None if args.render_only else build_client(
        args.target,
        api_key_env=args.target_api_key_env,
        base_url_env=args.target_base_url_env,
        timeout=args.request_timeout,
    )
    judge_client = None
    if not args.render_only and args.judge == "policy":
        judge_client = build_client(
            args.judge_model,
            api_key_env=args.judge_api_key_env,
            base_url_env=args.judge_base_url_env,
            timeout=args.request_timeout,
        )

    records = [run_one(args, behavior, target_client, judge_client) for behavior in select_behaviors(args)]
    metrics = {args.judge: summarize_success(records, args.judge)}
    settings = vars(args).copy()
    for key, value in list(settings.items()):
        if isinstance(value, Path):
            settings[key] = str(value)

    result = {
        "schema": "codeattack_result.v0.1",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "paper": "2403.07865",
        "method": "codeattack",
        "settings": settings,
        "data_manifest": read_json(DEFAULT_MANIFEST) if DEFAULT_MANIFEST.exists() else None,
        "summary": {"metrics": metrics},
        "records": records,
    }
    out = args.output or default_output(args)
    write_json(out, result)
    print(f"wrote {out}")
    for metric in metrics.values():
        print(metric["display"])


if __name__ == "__main__":
    main()
