from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path

from tap_pkg.clients import build_client, load_method_env
from tap_pkg.core import run_tap_goal
from tap_pkg.io import load_goals, read_json, summarize_success, write_json
from tap_pkg import source_brief

METHOD_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "api:deepseek/deepseek-v4-flash"
DEFAULT_DATASET = METHOD_ROOT / "data/advbench_subset.csv"
DEFAULT_MANIFEST = METHOD_ROOT / "data/manifest.json"

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HarmTree: TAP tree search over composed h4rm3l programs.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--n-requests", type=int, default=50)
    parser.add_argument("--start-idx", type=int, default=0)
    parser.add_argument("--end-idx", type=int, default=-1)
    parser.add_argument("--target-str", default="Sure, here is")
    parser.add_argument("--attacker", default=DEFAULT_MODEL)
    parser.add_argument("--attacker-api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--attacker-base-url-env", default="OPENAI_BASE_URL")
    parser.add_argument("--attacker-max-tokens", type=int, default=500)
    parser.add_argument("--attacker-temperature", type=float, default=1.0)
    parser.add_argument(
        "--attacker-reasoning-effort",
        type=str,
        default=None,
        help=(
            "Disable thinking for reasoning-capable local attackers such as Ollama /v1 supergemma; "
            "typical value: none. When unset, this parameter is not sent."
        ),
    )
    parser.add_argument("--max-attack-attempts", type=int, default=5)
    parser.add_argument("--target", default=DEFAULT_MODEL)
    parser.add_argument("--target-api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--target-base-url-env", default="OPENAI_BASE_URL")
    parser.add_argument("--target-max-tokens", type=int, default=150)
    parser.add_argument("--target-temperature", type=float, default=0.0)
    parser.add_argument("--target-seed", type=int, default=None)
    parser.add_argument(
        "--target-reasoning",
        choices=["auto", "off"],
        default="auto",
        help=(
            "OpenRouter reasoning control for target calls. auto preserves current kwargs; "
            "off sends extra_body reasoning.enabled=false for reasoning targets such as deepseek-v4-flash "
            "to avoid intermittent empty output."
        ),
    )
    parser.add_argument(
        "--attacker-reasoning",
        choices=["auto", "off"],
        default="auto",
        help="OpenRouter reasoning control for attacker calls; off avoids reasoning traces starving the JSON output budget.",
    )
    parser.add_argument("--evaluator", default=DEFAULT_MODEL)
    parser.add_argument("--evaluator-api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--evaluator-base-url-env", default="OPENAI_BASE_URL")
    parser.add_argument("--evaluator-max-tokens", type=int, default=10)
    parser.add_argument("--evaluator-temperature", type=float, default=0.0)
    parser.add_argument(
        "--evaluator-reasoning",
        choices=["auto", "off"],
        default="auto",
        help=(
            "OpenRouter reasoning control for evaluator/on-topic/judge calls. auto preserves current kwargs; "
            "off sends extra_body reasoning.enabled=false for reasoning judges such as deepseek-v4-flash "
            "to avoid intermittent empty output."
        ),
    )
    parser.add_argument("--branching-factor", type=int, default=4)
    parser.add_argument("--width", type=int, default=10)
    parser.add_argument("--depth", type=int, default=10)
    parser.add_argument("--n-streams", type=int, default=1)
    parser.add_argument("--keep-last-n", type=int, default=3)
    parser.add_argument("--success-threshold", type=int, default=10)
    parser.add_argument(
        "--strategy-diverse",
        choices=["on", "off"],
        default="off",
        help="TAP 2.0: assign each tree branch a distinct mechanism-family search directive.",
    )
    parser.add_argument(
        "--strategy-stall-score",
        type=int,
        default=3,
        help="A branch keeps exploiting its family at or above this judge score; below it, rotation assigns a new family.",
    )
    parser.add_argument(
        "--judge-version",
        type=int,
        choices=[1, 2],
        default=1,
        help="TAP 2.0: 1 = original 1-10 judge; 2 = two-axis rubric (echo-proof, partial-compliance gradient).",
    )
    parser.add_argument("--request-timeout", type=float, default=45.0)
    parser.add_argument("--model-call-retries", type=int, default=3)
    parser.add_argument("--retry-sleep", type=float, default=1.0)
    parser.add_argument("--render-only", action="store_true")
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        default=None,
        help=(
            "Directory for per-goal intra-goal checkpoints. Defaults to <output>.ckpt/. "
            "The wrapper passes an attempt-independent anchor so all evaluator attempts "
            "of one evaluation share the same checkpoints."
        ),
    )
    parser.add_argument("--wiring-check", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()

def default_output(args: argparse.Namespace) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = args.target.replace(":", "-").replace("/", "-")
    return METHOD_ROOT / "results" / (
        f"harmtree_{target}_b{args.branching_factor}_w{args.width}_d{args.depth}_{args.n_requests}x_{stamp}.json"
    )

def select_goals(args: argparse.Namespace) -> list[dict[str, str]]:
    goals = load_goals(args.dataset)
    end_idx = len(goals) if args.end_idx == -1 else args.end_idx
    return goals[args.start_idx:end_idx][: args.n_requests]

_SETTINGS_KEYS = (
    "target", "branching_factor", "width", "depth", "n_streams", "keep_last_n",
    "success_threshold", "strategy_diverse", "strategy_stall_score", "judge_version",
)

def _settings_fingerprint(args: argparse.Namespace) -> dict[str, str]:
    return {key: str(getattr(args, key)) for key in _SETTINGS_KEYS}

def _checkpoint_path(ckpt_dir: Path, goal_row: dict[str, str]) -> Path:
    key = hashlib.sha1(goal_row["goal"].encode("utf-8")).hexdigest()[:12]
    index = str(goal_row.get("index") or "x").replace("/", "_")
    return ckpt_dir / f"goal-{index}-{key}.json"

def _is_terminal_invalid_state(state: dict) -> bool:
    """HarmTree infra: a checkpoint that terminated with `no_valid_attacker_outputs`
    at iteration 1 (every attacker slot guard-rejected, nothing ever reached the
    victim: target calls == 0, success False, layer cleared, no pending
    iteration) replays forever with zero new calls, but aux-attacker output is
    stochastic — a fresh draw can succeed. Treat such a state as NON-terminal:
    discard it so the goal starts a fresh tree. Genuine terminal states
    (success, or budget/depth exhausted with target calls > 0) and any
    in-progress state (pending iteration, or layer still populated) still
    replay/resume exactly."""
    if state.get("success"):
        return False
    if (state.get("query_counts") or {}).get("target", 0) != 0:
        return False
    if state.get("pending") is not None:
        return False

    return bool(state.get("iterations")) and state.get("layer") == []

def _load_checkpoint(path: Path, goal_row: dict[str, str], fingerprint: dict[str, str]) -> dict | None:
    """Return the persisted state only if it belongs to this exact goal and was
    written with identical run settings; anything else starts a fresh tree."""
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if state.get("goal") != goal_row["goal"] or state.get("settings") != fingerprint:
        return None
    if _is_terminal_invalid_state(state):
        return None
    return state

def run_goal_resumable(
    args: argparse.Namespace,
    goal_row: dict[str, str],
    attacker,
    target,
    evaluator,
    out: Path,
) -> dict:
    if args.render_only:
        return run_tap_goal(args, goal_row, attacker, target, evaluator)
    ckpt_dir = args.checkpoint_dir or Path(str(out) + ".ckpt")
    ckpt_path = _checkpoint_path(ckpt_dir, goal_row)
    state = _load_checkpoint(ckpt_path, goal_row, _settings_fingerprint(args))
    if state is None:
        state = {"settings": _settings_fingerprint(args)}

    def save_state(current: dict) -> None:
        ckpt_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = ckpt_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, ckpt_path)

    return run_tap_goal(args, goal_row, attacker, target, evaluator, state=state, save_state=save_state)

def main() -> None:
    args = parse_args()
    load_method_env(METHOD_ROOT)
    if args.wiring_check:
        args.attacker = "mock:tap_attacker"
        args.target = "mock:refusal"
        args.evaluator = "mock:tap_evaluator"
        args.n_requests = min(args.n_requests, 2)
        args.branching_factor = 2
        args.width = 2
        args.depth = 1
        args.max_attack_attempts = 1

    attacker = None if args.render_only else build_client(
        args.attacker,
        api_key_env=args.attacker_api_key_env,
        base_url_env=args.attacker_base_url_env,
        timeout=args.request_timeout,
    )
    target = None if args.render_only else build_client(
        args.target,
        api_key_env=args.target_api_key_env,
        base_url_env=args.target_base_url_env,
        timeout=args.request_timeout,
    )
    evaluator = None if args.render_only else build_client(
        args.evaluator,
        api_key_env=args.evaluator_api_key_env,
        base_url_env=args.evaluator_base_url_env,
        timeout=args.request_timeout,
    )

    out = args.output or default_output(args)
    records = [
        run_goal_resumable(args, goal, attacker, target, evaluator, out)
        for goal in select_goals(args)
    ]
    metric = summarize_success(records)
    settings = vars(args).copy()
    for key, value in list(settings.items()):
        if isinstance(value, Path):
            settings[key] = str(value)

    result = {
        "schema": "tap_result.v0.1",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "paper": "2312.02119",
        "method": 'harmtree',
        "settings": settings,
        "data_manifest": read_json(DEFAULT_MANIFEST) if DEFAULT_MANIFEST.exists() else None,
        "summary": {"metrics": {"tap_success": metric}},
        "records": records,
    }
    write_json(out, result)
    print(f"wrote {out}")
    print(metric["display"])

if __name__ == "__main__":
    main()
