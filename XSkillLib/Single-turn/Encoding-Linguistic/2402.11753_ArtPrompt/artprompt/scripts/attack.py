#!/usr/bin/env python3
"""Paper-local ArtPrompt Code (faithful port of uw-nsl/ArtPrompt) — orchestration + CLI.

ArtPrompt (Jiang et al., 2024, arXiv:2402.11753) jailbreaks an aligned LLM by
(I) masking the sensitive word of a harmful instruction with ``[MASK]`` and
(II) replacing that word with ASCII art (cloaked prompt), so the safety filter
never sees the trigger token but the model still reconstructs and answers it.

Modular layout (each role/piece is its own file so this multi-role tool stays readable):
  prompts.py — verbatim templates + the ASCII-art 加壳 (gptgen_ascii grid, art fonts,
               vitc_horizontal/vertical cloaked-prompt templates, mask few-shot, GPT-Judge)
  models.py  — path/env plumbing + OpenAI-compatible target client (call_api/call_fake)
  roles.py   — the swappable masker (dataset/heuristic/llm) + judges (Dict-Judge/GPT-Judge)
  cases.py   — dataset loading (row readers, normalization, selection)
  attack.py  — render/run orchestration + argparse CLI (this file)

Every swappable role has its OWN CLI flag so they can be mixed and matched:
``--target``, ``--judge`` (+``--judge-model``/``--judge-max-tokens``),
``--masker`` (+``--masker-model``/``--masker-max-tokens``), ``--direction``.
Black-box: target via OpenRouter ``api:<model>``; no GPU. The official HarmBench
classifier is NOT used by ArtPrompt (it uses GPT-Judge), so nothing is deferred there.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# Sibling-module imports (scripts/ is on sys.path when run as `python scripts/attack.py`).
# These are also re-exported so `import attack; attack.X` keeps working for gen_training_corpus.py.
from models import DEFAULT_DATASET, call_api, call_fake  # noqa: F401
from prompts import (  # noqa: F401
    DICT_JUDGE_REFUSALS,
    SUPPORTED_FONTS,
    SUPPORTED_MASKERS,
    render_messages,
)
from roles import choose_mask_word, dict_judge, gpt_judge  # noqa: F401
from cases import (  # noqa: F401
    dataset_meta,
    load_selected,
    normalize_rows,
    parse_csv_ids,
    read_rows,
)

PAPER_ID = "2402.11753_ascii-art-jailbreak"
METHOD_ID = "artprompt"
FIDELITY = "paper_algorithm_code"
OFFICIAL_REPO = "https://github.com/uw-nsl/ArtPrompt"
OFFICIAL_COMMIT = "6eb866446b7648ccee705bd802fe3ae8694ffc12"


def render_items(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    fonts = parse_csv_ids(args.fonts, SUPPORTED_FONTS, "font")
    direction = getattr(args, "direction", "h") or "h"
    items = []
    for row in rows:
        mask_word, masker_meta = choose_mask_word(row, args)
        for font in fonts:
            messages, masked = render_messages(row["goal"], mask_word, font, direction=direction)
            params = {
                "font": font, "direction": direction,
                "mask_word": mask_word, "masked_instruction": masked,
                **masker_meta,
            }
            items.append({"sample": row, "parameters": params, "model_input_messages": messages})
    if not items:
        raise SystemExit("no items rendered")
    return items


def messages_to_text(messages: list[dict[str, str]]) -> str:
    return "\n\n".join(f"{item['role'].upper()}:\n{item['content']}" for item in messages)


def stable_parameter_grid(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[tuple, dict[str, Any]] = {}
    for item in items:
        p = item["parameters"]
        key = (p.get("font"), p.get("direction"), p.get("masker"))
        if key not in seen:
            seen[key] = {"font": p["font"], "direction": p.get("direction", "h"), "masker": p.get("masker")}
    return [seen[k] for k in sorted(seen)]


def run_cases(items: list[dict[str, Any]], args: argparse.Namespace, dataset: dict[str, Any]) -> dict[str, Any]:
    started = time.time()
    run_gpt_judge = bool(getattr(args, "judge", None)) and args.judge != "none"
    judge_kind, _, judge_model = (args.judge or "").partition(":") if run_gpt_judge else ("", "", "")
    if run_gpt_judge and (judge_kind != "api" or not judge_model):
        raise SystemExit("--judge must be 'none' or api:<model> (e.g. api:openai/gpt-4o)")

    results = []
    for case_id, item in enumerate(items, start=1):
        if args.target == "fake":
            if not args.wiring_check:
                raise SystemExit("fake target is wiring-only; pass --wiring-check and do not treat output as Code evidence")
            output, status = call_fake(item["model_input_messages"], args.max_tokens)
            target_label = "fake"
        else:
            kind, _, model = args.target.partition(":")
            if kind != "api" or not model:
                raise SystemExit("--target must be fake or api:<model>")
            output, status = call_api(item["model_input_messages"], model, args.max_tokens, args.base_url, args.api_key_env)
            target_label = args.target

        dj = dict_judge(output) if status == "ok" else {"name": "dict_judge", "refused": True, "non_refusal": False, "reason": status}
        gj: dict[str, Any] | None = None
        if status == "ok" and run_gpt_judge:
            gj = gpt_judge(item["sample"]["goal"], output, judge_model, args.judge_base_url, args.judge_key_env, args.judge_max_tokens)
            if args.request_delay:
                time.sleep(args.request_delay)

        results.append({
            "case_id": case_id,
            "sample": {
                "id": item["sample"]["id"],
                "category": item["sample"].get("category", ""),
                "source_row": item["sample"].get("source_row"),
                "goal_text": item["sample"]["goal"],
            },
            "status": status,
            "target": target_label,
            "parameters": item["parameters"],
            "model_input_messages": item["model_input_messages"],
            "model_input_text": messages_to_text(item["model_input_messages"]),
            "model_output_text": output,
            "dict_judge": dj,
            "gpt_judge": gj,
        })
        if args.request_delay:
            time.sleep(args.request_delay)

    ok = [r for r in results if r["status"] == "ok"]
    provider_errors = len(results) - len(ok)
    non_refusals = [r for r in ok if r["dict_judge"]["non_refusal"]]
    gpt_scored = [r for r in ok if r.get("gpt_judge") and r["gpt_judge"].get("score") is not None]
    gpt_harmful = [r for r in gpt_scored if r["gpt_judge"]["harmful_extreme"]]
    grid = stable_parameter_grid(items)

    valid_for_code_completion = bool(
        not args.wiring_check
        and args.target != "fake"
        and len(results) >= 10
        and provider_errors == 0
        and len(grid) >= 2
    )
    evidence_level = "wiring_check" if args.wiring_check else "real_model_run"
    if provider_errors:
        evidence_level = "provider_or_runtime_error"

    return {
        "schema_version": "paper_local_attack_result.v0.2",
        "paper_id": PAPER_ID,
        "method": METHOD_ID,
        "fidelity_level": FIDELITY,
        "evidence_level": evidence_level,
        "wiring_check": bool(args.wiring_check),
        "valid_for_code_completion": valid_for_code_completion,
        "completion_scope": "live_model_substitution_artprompt" if valid_for_code_completion else "not_completion",
        "target": args.target,
        "dataset": dataset,
        "source_backing": {
            "official_repo": OFFICIAL_REPO,
            "official_commit": OFFICIAL_COMMIT,
            "ported_components": [
                "generate_alphabet_ascii (gptgen_ascii 5x5 grid + art fonts)",
                "vitc_horizontal / vitc_vertical cloaked-prompt task templates (--direction h|v)",
                "modular masker: dataset (category column) / heuristic (mask_word_stop) / llm (GPTMaskPrompt)",
                "Dict-Judge (Safe_SubString refusal list)",
                "GPT-Judge (OpenAI-policy 1-5 #thescore template, Qi et al. 2023)",
            ],
            "paper_sections": ["sec:4.1", "sec:4.2", "sec:5.1"],
            "judge_note": "ArtPrompt uses GPT-Judge for HS/ASR (NOT HarmBench); ported faithfully.",
        },
        "attack_parameters": {
            "fonts": args.fonts,
            "direction": getattr(args, "direction", "h"),
            "masker": getattr(args, "masker", "dataset"),
            "masker_model": getattr(args, "masker_model", None),
            "mask_word_override": args.mask_word,
        },
        "parameter_grid": grid,
        "judge": {
            "dict_judge": "Safe_SubString",
            "gpt_judge": (judge_model if run_gpt_judge else None),
        },
        "summary": {
            "attempts": len(results),
            "ok": len(ok),
            "provider_or_runtime_errors": provider_errors,
            "dict_non_refusals": len(non_refusals),
            "asr_dict_judge": (len(non_refusals) / len(ok)) if ok else None,
            "gpt_scored": len(gpt_scored),
            "gpt_harmful_score5": len(gpt_harmful),
            "asr_gpt_judge": (len(gpt_harmful) / len(gpt_scored)) if gpt_scored else None,
            "seconds": round(time.time() - started, 3),
        },
        "results": results,
    }


def write_json(data: dict[str, Any], out: str | None) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def add_selection_args(parser: argparse.ArgumentParser, *, run_defaults: bool) -> None:
    parser.add_argument("--goals", default=str(DEFAULT_DATASET))
    parser.add_argument("--goal-field", default="auto")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--sample-rows", type=int, default=10 if run_defaults else None)
    parser.add_argument("--seed", type=int, default=20260609)
    parser.add_argument("--fonts", default="gen")
    parser.add_argument("--mask-word")
    parser.add_argument("--direction", choices=["h", "v"], default="h",
                        help="h = vitc_horizontal (letters side by side, default); v = vitc_vertical (stacked)")
    parser.add_argument("--masker", choices=SUPPORTED_MASKERS, default="dataset",
                        help="dataset = category column (default); heuristic = mask_word_stop; llm = GPTMaskPrompt")
    parser.add_argument("--masker-model", default="api:deepseek/deepseek-v4-flash",
                        help="api:<model> used only when --masker llm (default api:deepseek/deepseek-v4-flash)")
    parser.add_argument("--masker-max-tokens", type=int, default=256,
                        help="max tokens for the --masker llm call")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run paper-local ArtPrompt Code (faithful port of uw-nsl/ArtPrompt).")
    sub = parser.add_subparsers(dest="mode", required=True)
    smoke = sub.add_parser("smoke")
    smoke.add_argument("--out")
    smoke.add_argument("--mask-word")
    inspect = sub.add_parser("inspect")
    add_selection_args(inspect, run_defaults=False)
    inspect.add_argument("--out")
    render = sub.add_parser("render")
    add_selection_args(render, run_defaults=True)
    render.add_argument("--out")
    run = sub.add_parser("run")
    add_selection_args(run, run_defaults=True)
    run.add_argument("--target", default="fake")
    run.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    run.add_argument("--api-key-env", default="OPENROUTER_API_KEY")
    run.add_argument("--max-tokens", type=int, default=512)
    run.add_argument("--judge", default="none", help="'none' or api:<model>, e.g. api:openai/gpt-4o")
    run.add_argument("--judge-base-url", default="https://openrouter.ai/api/v1")
    run.add_argument("--judge-key-env", default="OPENROUTER_API_KEY")
    run.add_argument("--judge-max-tokens", type=int, default=600)
    run.add_argument("--request-delay", type=float, default=0.0)
    run.add_argument("--wiring-check", action="store_true")
    run.add_argument("--out")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.mode == "smoke":
        args.target = "fake"
        args.max_tokens = 32
        args.request_delay = 0.0
        args.wiring_check = True
        args.fonts = "gen"
        args.judge = "none"
        args.seed = 20260609
        args.direction = "h"
        args.masker = "dataset"
        args.masker_model = None
        args.masker_max_tokens = 256
        selected, dataset = load_selected(args, smoke_only=True)
        write_json(run_cases(render_items(selected, args), args, dataset), args.out)
        return
    selected, dataset = load_selected(args)
    items = render_items(selected, args)
    if args.mode == "inspect":
        categories: dict[str, int] = {}
        for row in selected:
            category = row.get("category") or "(missing)"
            categories[category] = categories.get(category, 0) + 1
        write_json({
            "schema_version": "paper_local_attack_inspect.v0.2",
            "paper_id": PAPER_ID, "method": METHOD_ID, "fidelity_level": FIDELITY,
            "dataset": dataset, "selected_rows": len(selected), "rendered_items": len(items),
            "parameter_grid": stable_parameter_grid(items),
            "categories": sorted(categories.items()),
        }, args.out)
        return
    if args.mode == "render":
        write_json({
            "schema_version": "paper_local_attack_render.v0.2",
            "paper_id": PAPER_ID, "method": METHOD_ID, "fidelity_level": FIDELITY,
            "dataset": dataset, "parameter_grid": stable_parameter_grid(items),
            "items": [{"sample": it["sample"], "parameters": it["parameters"], "model_input_messages": it["model_input_messages"]} for it in items],
        }, args.out)
        return
    write_json(run_cases(items, args, dataset), args.out)


if __name__ == "__main__":
    main()
