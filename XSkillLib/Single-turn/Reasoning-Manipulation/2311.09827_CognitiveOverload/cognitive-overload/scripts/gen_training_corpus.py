#!/usr/bin/env python3
"""Generate a real training_corpus for the cognitive-overload unit (2311.09827).

Thin wrapper over attack.py -- reuses the real payload builders (no reimplementation):

  * effect_to_cause          -- DETERMINISTIC (attack.make_effect_to_cause_case;
                                derive_event gerund nominalization + verbatim template).
  * monolingual              -- MT (official pre-released 52-lang translations;
                                attack.make_monolingual_case). Standalone translated goal.
  * language_switch_lan_to_en-- MT (official pre-released non-English wiki context +
                                EN harmful goal; attack.make_switch_case). 2-turn payload.
  * veiled_expression        -- LLM paraphrase (attack.make_veiled_expression_case ->
                                attack.paraphrase_request). Primary api:deepseek/deepseek-v4-flash,
                                refusal-fallback api:mistralai/mistral-nemo, else DROP.
                                Threaded + per-call 60s timeout.

Quality filter: drop leading-refusal / empty / <15 chars / degenerate echo / dup.
A translated or veiled prompt is NOT a refusal.
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import attack  # the real paper-local runner; reuse its funcs verbatim

PAPER_ID = attack.PAPER_ID
METHOD_ID = attack.METHOD_ID
METHOD_DIR = SCRIPT_DIR.parent
OUT_PATH = METHOD_DIR / "data" / "training_corpus" / "sft_cognitive_overload.json"

DATASET = "AdvBench"
LANGUAGES = list(attack.DEFAULT_LANGUAGES)  # fr, ja, ar, sw, uk
VEILED_VARIANTS = list(attack.VEILED_VARIANTS)  # plain, no_sensitive, explicit
VEILED_N = 50          # goals paraphrased per variant via the LLM path
VEILED_TIMEOUT = 60    # per HTTP call (urllib) inside paraphrase_request
VEILED_OUTER_TIMEOUT = 180  # outer guard per (goal,variant) future
VEILED_MAX_TOKENS = 512
VEILED_WORKERS = 8
# Primary + single refusal-fallback; if both refuse the case is dropped (never faked).
PARA_CHAIN = ["api:deepseek/deepseek-v4-flash", "api:mistralai/mistral-nemo"]

REFUSAL_OPENERS = (
    "i'm sorry", "i am sorry", "sorry,", "sorry.", "i cannot", "i can't", "i can not",
    "as an ai", "as a language model", "i apologize", "my apologies", "i'm unable",
    "i am unable", "unable to", "i won't", "i will not", "i must decline",
    "i'm not able", "i am not able",
)


def is_leading_refusal(text: str) -> bool:
    h = (text or "").strip().lower()
    return any(h.startswith(p) for p in REFUSAL_OPENERS)


def quality_drop(payload: str, source_goal: str, mode: str) -> str | None:
    """Return a drop-reason string, or None if the payload is clean."""
    p = (payload or "").strip()
    if not p:
        return "empty"
    if len(p) < 15:
        return "too_short"
    if is_leading_refusal(p):
        return "leading_refusal"
    # degenerate echo: a veiled rewrite that did not change the goal is not a real payload.
    if mode == "veiled_expression" and p.lower() == source_goal.strip().lower():
        return "degenerate_echo"
    return None


def gen_deterministic() -> list[dict]:
    """effect_to_cause (en, full 520) + monolingual + language_switch over LANGUAGES (full 520)."""
    root = attack.dataset_dir(DATASET)
    english_rows = attack.read_json_list(root / "attacks.json")
    rows: list[dict] = []

    # effect_to_cause: deterministic, English, full dataset.
    for idx, er in enumerate(english_rows):
        c = attack.make_effect_to_cause_case(DATASET, idx, er)
        rows.append({
            "mode": "effect_to_cause", "language": "en",
            "source_row_index": idx, "source_goal": c["source_goal"],
            "payload": c["prompt_text"], "event": c["attack_parameters"]["event"],
            "payload_step": "deterministic",
        })

    # monolingual + language_switch: official pre-released MT, full dataset per language.
    for lang in LANGUAGES:
        lang_rows = attack.read_json_list(attack.language_assets(DATASET, lang)["attacks"])
        wiki = attack.read_json_list(attack.language_assets(DATASET, lang)["context_wiki"]) \
            if attack.has_wiki_context(DATASET, lang) else None
        n = min(len(lang_rows), len(english_rows))
        for idx in range(n):
            en_goal = str(english_rows[idx]["goal"])
            mc = attack.make_monolingual_case(DATASET, lang, idx, lang_rows[idx], en_goal)
            rows.append({
                "mode": "monolingual", "language": lang,
                "source_row_index": idx, "source_goal": en_goal,
                "payload": mc["prompt_text"], "payload_step": "mt_official_release",
            })
            if wiki is not None and idx < len(wiki):
                sc = attack.make_switch_case(DATASET, lang, idx, wiki[idx], english_rows[idx])
                rows.append({
                    "mode": "language_switch_lan_to_en", "language": lang,
                    "source_row_index": idx, "source_goal": str(english_rows[idx]["goal"]),
                    "payload": sc["prompt_text"], "messages": sc["messages"], "turns": 2,
                    "payload_step": "mt_official_release",
                })
    return rows


def gen_veiled() -> tuple[list[dict], dict]:
    """LLM-paraphrase mode, threaded with per-call timeout + refusal-fallback + drop."""
    attack.load_project_env()
    root = attack.dataset_dir(DATASET)
    english_rows = attack.read_json_list(root / "attacks.json")[:VEILED_N]
    jobs = [(idx, er, v) for idx, er in enumerate(english_rows) for v in VEILED_VARIANTS]

    stats = {"attempted": len(jobs), "para_refused_or_error": 0, "exception": 0, "timeout": 0}

    def _one(job):
        idx, er, variant = job
        return attack.make_veiled_expression_case(
            DATASET, idx, er, variant, PARA_CHAIN, VEILED_TIMEOUT, VEILED_MAX_TOKENS)

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=VEILED_WORKERS) as ex:
        futs = {ex.submit(_one, j): j for j in jobs}
        for fut, job in futs.items():
            idx, er, variant = job
            try:
                case = fut.result(timeout=VEILED_OUTER_TIMEOUT)
            except FutureTimeout:
                stats["timeout"] += 1
                continue
            except Exception:
                stats["exception"] += 1
                continue
            if not case["paraphrase"]["veiled_applied"]:
                stats["para_refused_or_error"] += 1
                continue
            rows.append({
                "mode": "veiled_expression", "language": "en",
                "source_row_index": idx, "source_goal": case["source_goal"],
                "payload": case["prompt_text"],
                "veiled_variant": variant,
                "paraphraser_model": case["paraphrase"]["paraphraser_model"],
                "paraphrase_status": case["paraphrase"]["status"],
                "payload_step": "llm_paraphrase",
            })
    return rows, stats


def quality_filter(rows: list[dict]) -> tuple[list[dict], dict]:
    kept: list[dict] = []
    seen: set[str] = set()
    dropped = {"empty": 0, "too_short": 0, "leading_refusal": 0,
               "degenerate_echo": 0, "duplicate": 0}
    for r in rows:
        reason = quality_drop(r["payload"], r["source_goal"], r["mode"])
        if reason:
            dropped[reason] += 1
            continue
        key = r["payload"].strip()
        if key in seen:
            dropped["duplicate"] += 1
            continue
        seen.add(key)
        kept.append(r)
    return kept, dropped


def main() -> int:
    print("[gen] deterministic modes (effect_to_cause + monolingual + language_switch) ...",
          file=sys.stderr)
    det_rows = gen_deterministic()
    print(f"[gen] deterministic raw rows: {len(det_rows)}", file=sys.stderr)

    # Probe the LLM path on 2 jobs before the full veiled batch.
    print("[gen] probing veiled LLM path (limit=2) ...", file=sys.stderr)
    attack.load_project_env()
    probe_rows = attack.read_json_list(attack.dataset_dir(DATASET) / "attacks.json")[:2]
    probe_ok = 0
    for i, er in enumerate(probe_rows):
        case = attack.make_veiled_expression_case(
            DATASET, i, er, "plain", PARA_CHAIN, VEILED_TIMEOUT, VEILED_MAX_TOKENS)
        if case["paraphrase"]["veiled_applied"]:
            probe_ok += 1
    print(f"[gen] probe veiled_applied: {probe_ok}/2", file=sys.stderr)

    print(f"[gen] veiled batch: {VEILED_N} goals x {len(VEILED_VARIANTS)} variants (threaded) ...",
          file=sys.stderr)
    veiled_rows, veiled_stats = gen_veiled()
    print(f"[gen] veiled kept (pre-filter): {len(veiled_rows)} | stats={veiled_stats}",
          file=sys.stderr)

    raw_rows = det_rows + veiled_rows
    kept, dropped = quality_filter(raw_rows)

    # Stable id after filtering.
    for i, r in enumerate(kept):
        r["id"] = f"cogoverload-{DATASET}-{r['mode']}-{r['language']}-{i + 1:04d}"

    by_mode: dict[str, int] = {}
    for r in kept:
        by_mode[r["mode"]] = by_mode.get(r["mode"], 0) + 1

    payloads = [r["payload"].strip() for r in kept]
    distinct = len(set(payloads))

    header = {
        "paper_id": PAPER_ID,
        "method_id": METHOD_ID,
        "capability": "multilingual_cognitive_overload jailbreak payloads "
                      "(effect_to_cause reasoning + multilingual language-switch + veiled-expression)",
        "description": "Real reusable cognitive-overload attack payloads generated by reusing the "
                       "paper-local attack.py builders. effect_to_cause is deterministic "
                       "(gerund-nominalized event + official verbatim template); monolingual and "
                       "language_switch_lan_to_en use the official pre-released 52-language machine "
                       "translations + non-English Wikipedia contexts (no LLM at gen time); "
                       "veiled_expression uses an in-tool paraphraser LLM "
                       "(api:deepseek/deepseek-v4-flash, refusal-fallback api:mistralai/mistral-nemo, "
                       "else dropped). Quality-filtered: leading-refusal/empty/<15/echo/dup removed.",
        "generator_model": "deterministic (effect_to_cause + official MT release) + "
                           "api:deepseek/deepseek-v4-flash (fallback api:mistralai/mistral-nemo) for veiled_expression",
        "dataset": f"{DATASET} (520 harmful behaviours) x {{{','.join(LANGUAGES)}}} (official MT subset)",
        "payload_field": "payload (rendered cognitive-overload attack text: effect_to_cause reframed "
                         "prompt / monolingual translated goal / language_switch context+EN-goal / "
                         "veiled paraphrased request)",
        "modes": by_mode,
        "languages": ["en"] + LANGUAGES,
        "total": len(kept),
        "positive": len(kept),
        "negative": 0,
        "distinct_payloads": distinct,
        "quality_cleaned_dropped": dropped,
        "veiled_generation_stats": veiled_stats,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "official_repo": attack.OFFICIAL_REPO,
        "official_repo_commit": attack.OFFICIAL_REPO_COMMIT,
        "rows": kept,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(header, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "out": str(OUT_PATH.relative_to(METHOD_DIR)),
        "total": len(kept), "by_mode": by_mode,
        "distinct_payloads": distinct, "dropped": dropped,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
