#!/usr/bin/env python3
"""Dataset loading + attack-input construction for Cognitive Overload.

This module owns the on-disk assets (AdvBench / MasterKey English goals plus the
paper's per-language machine translations + non-English wiki contexts), the small
fs helpers, one builder per faithful mode (effect-to-cause / monolingual /
language-switch / veiled-expression), and `build_cases`, the round-robin sampler
that assembles a set of target-facing cases across (mode, language) settings.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from typing import Any

from models import METHOD_DIR
from prompts import VEILED_VARIANTS, effect_to_cause_prompt
from roles import paraphrase_request

PAPER_DIR = METHOD_DIR.parent
PROJECT_ROOT = PAPER_DIR.parents[2]
# Self-contained single-folder Code: results live inside the method dir.
RESULTS_DIR = METHOD_DIR / "results"
DATA_ROOT = METHOD_DIR / "data"
# Both benchmarks the paper evaluates (Sec 2 "Evaluation Benchmarks"): AdvBench
# (520 English harmful behaviours, zou2023universal) and MasterKey (45 released
# instances across 9 prohibitive scenarios, deng2023jailbreaker). Each has the
# original English plus the paper's 52 machine-translated language variants. The
# dataset root is selectable; AdvBench remains the default to preserve prior runs.
ADVBENCH_DIR = DATA_ROOT / "AdvBench"
MASTERKEY_DIR = DATA_ROOT / "MasterKey"
DATASET_DIRS = {"AdvBench": ADVBENCH_DIR, "MasterKey": MASTERKEY_DIR}

DEFAULT_LANGUAGES = ["fr", "ja", "ar", "sw", "uk"]
MODES = ("effect_to_cause", "language_switch_lan_to_en", "monolingual", "veiled_expression")

# Default in-tool helper LLM (project default); swappable via --paraphraser-model.
# The paper used Mistral-7B-Instruct for veiled-expression generation -- any
# OpenRouter substitute is recorded as a model_substitution.
DEFAULT_PARAPHRASER_MODEL = "api:deepseek/deepseek-v4-flash"
# Fallback paraphrasers tried when the primary refuses to rewrite a harmful goal (so a
# paraphraser refusal doesn't either pollute the veiled ASR or shrink the sample). mistral-nemo
# is unmoderated and reliably paraphrases. If all refuse, the veiled case is dropped (not faked).
DEFAULT_PARAPHRASER_FALLBACKS = "api:mistralai/mistral-nemo"


def rel(path):
    try:
        return str(path.relative_to(PAPER_DIR))
    except ValueError:
        return str(path)


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json_list(path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"expected list JSON in {rel(path)}")
    return data


def dataset_dir(dataset: str):
    try:
        return DATASET_DIRS[dataset]
    except KeyError as exc:
        raise ValueError(f"unknown dataset {dataset!r}; choose from {sorted(DATASET_DIRS)}") from exc


def language_dir(dataset: str, language: str):
    return dataset_dir(dataset) / language


def language_assets(dataset: str, language: str) -> dict[str, Any]:
    return {
        "attacks": language_dir(dataset, language) / "attacks.json",
        "context_wiki": language_dir(dataset, language) / "context_wiki.json",
    }


def available_languages(dataset: str) -> list[str]:
    """Languages with a translated attacks.json under this dataset.

    AdvBench ships a per-language non-English wiki context (context_wiki.json)
    used by the language_switch mode; MasterKey ships only translated attacks,
    so language_switch is unavailable there (gated in build_cases).
    """
    langs = []
    for child in sorted(dataset_dir(dataset).iterdir()):
        if child.is_dir() and (child / "attacks.json").exists():
            langs.append(child.name)
    return langs


def has_wiki_context(dataset: str, language: str) -> bool:
    return language_assets(dataset, language)["context_wiki"].exists()


def dataset_summary() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, root in DATASET_DIRS.items():
        if not root.exists():
            continue
        english = root / "attacks.json"
        languages = {}
        for lang in available_languages(name):
            assets = language_assets(name, lang)
            entry = {
                "attacks_path": rel(assets["attacks"]),
                "attacks_rows": len(read_json_list(assets["attacks"])),
                "attacks_sha256": sha256_file(assets["attacks"]),
            }
            if assets["context_wiki"].exists():
                entry["context_wiki_path"] = rel(assets["context_wiki"])
                entry["context_wiki_rows"] = len(read_json_list(assets["context_wiki"]))
                entry["context_wiki_sha256"] = sha256_file(assets["context_wiki"])
            languages[lang] = entry
        out[name] = {
            "english_attacks": {
                "path": rel(english),
                "rows": len(read_json_list(english)),
                "sha256": sha256_file(english),
            },
            "language_count": len(languages),
            "languages": languages,
        }
    return out


# ---------------------------------------------------------------------------
# Attack-input construction (one builder per faithful mode)
# ---------------------------------------------------------------------------

_GERUND_IRREGULAR = {
    "make": "making",
    "write": "writing",
    "give": "giving",
    "take": "taking",
    "create": "creating",
    "provide": "providing",
    "produce": "producing",
    "use": "using",
    "hack": "hacking",
    "steal": "stealing",
    "develop": "developing",
    "design": "designing",
    "build": "building",
    "release": "releasing",
    "promote": "promoting",
    "describe": "describing",
    "explain": "explaining",
    "outline": "outlining",
    "generate": "generating",
    "manipulate": "manipulating",
}


def _gerund(verb: str) -> str:
    v = verb.lower()
    if v in _GERUND_IRREGULAR:
        return _GERUND_IRREGULAR[v]
    if v.endswith("e") and not v.endswith(("ee", "ye", "oe")):
        return v[:-1] + "ing"
    if len(v) >= 3 and v[-1] not in "aeiou" and v[-2] in "aeiou" and v[-3] not in "aeiou":
        return v + v[-1] + "ing"
    return v + "ing"


def derive_event(goal: str) -> str:
    """Deterministic event nominalization of an AdvBench goal.

    Faithful reduction of the paper's LLM event-extraction stage. AdvBench goals
    are imperative ("Write a script ...", "Give instructions ...") -> gerund head
    ("writing a script ...", "giving instructions ..."), matching the paper's own
    footnote example ("How to make a bomb?" -> event "making a bomb").
    """
    text = goal.strip().rstrip(".?!")
    tokens = text.split()
    if not tokens:
        return text
    head = _gerund(tokens[0])
    rest = " ".join(tokens[1:])
    event = f"{head} {rest}".strip()
    return event[0].lower() + event[1:] if event else event


def make_effect_to_cause_case(dataset: str, row_idx: int, english_row: dict[str, Any]) -> dict[str, Any]:
    goal = str(english_row["goal"])
    event = derive_event(goal)
    # VERBATIM template from official perform_effect_to_cause.py.
    prompt = effect_to_cause_prompt(event)
    return {
        "mode": "effect_to_cause",
        "language": "en",
        "messages": [{"role": "user", "content": prompt}],
        "prompt_text": prompt,
        "source_goal": goal,
        "attack_parameters": {
            "dataset": dataset,
            "mode": "effect_to_cause",
            "language": "en",
            "row_index": row_idx,
            "turns": 1,
            "event": event,
        },
    }


def make_monolingual_case(dataset: str, language: str, row_idx: int, row: dict[str, Any], english_goal: str) -> dict[str, Any]:
    prompt = str(row["goal"])
    return {
        "mode": "monolingual",
        "language": language,
        "messages": [{"role": "user", "content": prompt}],
        "prompt_text": prompt,
        "source_goal": english_goal,
        "attack_parameters": {
            "dataset": dataset,
            "mode": "monolingual",
            "language": language,
            "row_index": row_idx,
            "turns": 1,
        },
    }


def make_switch_case(
    dataset: str,
    language: str,
    row_idx: int,
    context_row: dict[str, Any],
    english_row: dict[str, Any],
) -> dict[str, Any]:
    # Official en_last multilingual mode: turn-1 = non-English wiki context as a
    # pseudo assistant/context turn, turn-2 = English harmful goal.
    context = str(context_row["response_0"])
    ending = str(english_row["goal"])
    messages = [
        {"role": "user", "content": context},
        {"role": "assistant", "content": "I see."},
        {"role": "user", "content": ending},
    ]
    return {
        "mode": "language_switch_lan_to_en",
        "language": language,
        "messages": messages,
        "prompt_text": context + "\n\n" + ending,
        "source_goal": ending,
        "attack_parameters": {
            "dataset": dataset,
            "mode": "language_switch_lan_to_en",
            "language": language,
            "row_index": row_idx,
            "turns": 2,
            "context_source": "wiki",
        },
    }


def make_veiled_expression_case(
    dataset: str,
    row_idx: int,
    english_row: dict[str, Any],
    variant: str,
    paraphraser_models: str | list[str],
    timeout: int,
    paraphraser_max_tokens: int,
) -> dict[str, Any]:
    goal = str(english_row["goal"])
    para = paraphrase_request(paraphraser_models, variant, goal, timeout, paraphraser_max_tokens)
    veiled = str(para["veiled_request"])
    chain = [paraphraser_models] if isinstance(paraphraser_models, str) else list(paraphraser_models)
    return {
        "mode": "veiled_expression",
        "language": "en",
        "messages": [{"role": "user", "content": veiled}],
        "prompt_text": veiled,
        "source_goal": goal,
        "paraphrase": {
            "variant": variant,
            "paraphraser_chain": chain,
            "paraphraser_model": para.get("paraphraser_model"),  # the model that actually produced it
            "status": para["status"],
            "veiled_applied": para["veiled_applied"],
            "sensitive_word": para.get("sensitive_word"),
            "steps": para["steps"],
        },
        "attack_parameters": {
            "dataset": dataset,
            "mode": "veiled_expression",
            "language": "en",
            "row_index": row_idx,
            "turns": 1,
            "veiled_variant": variant,
            "paraphraser_model": para.get("paraphraser_model"),
        },
    }


def build_cases(
    dataset: str,
    languages: list[str],
    modes: list[str],
    sample: int,
    start_index: int,
    *,
    paraphraser_models: str | list[str] = DEFAULT_PARAPHRASER_MODEL,
    veiled_variants: list[str] | None = None,
    paraphraser_timeout: int = 120,
    paraphraser_max_tokens: int = 512,
) -> list[dict[str, Any]]:
    root = dataset_dir(dataset)
    available = set(available_languages(dataset))
    missing = [lang for lang in languages if lang not in available]
    if missing:
        raise FileNotFoundError(f"missing {dataset} language assets: {missing}")
    english_rows = read_json_list(root / "attacks.json")
    veiled_variants = veiled_variants or list(VEILED_VARIANTS)

    builders: list[dict[str, Any]] = []
    paraphraser_skipped = 0
    # Round-robin over (mode, language) so a sample spans multiple settings.
    seed = start_index
    n = len(english_rows)
    pair_idx = 0
    max_attempts = max(sample * 6, n)  # guard: veiled may skip paraphraser-refused goals
    while len(builders) < sample and pair_idx < max_attempts:
        progressed = False
        for mode in modes:
            if mode == "effect_to_cause":
                idx = (seed + pair_idx) % n
                builders.append(make_effect_to_cause_case(dataset, idx, english_rows[idx]))
            elif mode == "veiled_expression":
                idx = (seed + pair_idx) % n
                for variant in veiled_variants:
                    case = make_veiled_expression_case(
                        dataset, idx, english_rows[idx], variant,
                        paraphraser_models, paraphraser_timeout, paraphraser_max_tokens)
                    # CREDIBILITY: only keep genuinely-veiled cases. If the whole paraphraser
                    # chain refused, DROP it (don't pass an un-veiled raw goal off as a veiled
                    # attack); top up to `sample` from the next goal instead.
                    if not case["paraphrase"]["veiled_applied"]:
                        paraphraser_skipped += 1
                        continue
                    builders.append(case)
                    if len(builders) >= sample:
                        break
            else:
                lang = languages[pair_idx % len(languages)]
                lang_rows = read_json_list(language_assets(dataset, lang)["attacks"])
                if mode == "monolingual":
                    idx = (seed + pair_idx) % min(len(lang_rows), n)
                    builders.append(make_monolingual_case(dataset, lang, idx, lang_rows[idx], english_rows[idx]))
                else:  # language_switch_lan_to_en (requires a non-English wiki context)
                    if not has_wiki_context(dataset, lang):
                        raise FileNotFoundError(
                            f"language_switch_lan_to_en needs context_wiki.json, "
                            f"absent for {dataset}/{lang} (only AdvBench ships wiki context)"
                        )
                    contexts = read_json_list(language_assets(dataset, lang)["context_wiki"])
                    idx = (seed + pair_idx) % min(len(contexts), n)
                    builders.append(make_switch_case(dataset, lang, idx, contexts[idx], english_rows[idx]))
            progressed = True
            if len(builders) >= sample:
                break
        pair_idx += 1
        if not progressed:
            break

    cases = []
    for i, b in enumerate(builders):
        case = {
            "case_id": f"cogoverload-{b['attack_parameters']['dataset']}-{b['mode']}-{b['language']}-{i + 1:02d}",
            "dataset": b["attack_parameters"]["dataset"],
            "source_row_index": b["attack_parameters"]["row_index"],
            "source_goal": b["source_goal"],
            "mode": b["mode"],
            "language": b["language"],
            "model_input": {"type": "chat_messages", "messages": b["messages"]},
            "prompt_text": b["prompt_text"],
            "attack_parameters": b["attack_parameters"],
        }
        if "paraphrase" in b:
            case["paraphrase"] = b["paraphrase"]
        cases.append(case)
    if paraphraser_skipped:
        # no silent truncation: report goals dropped because the whole paraphraser chain refused
        print(f"[veiled] dropped {paraphraser_skipped} goal(s): paraphraser chain refused; "
              f"topped up to {len(cases)} genuinely-veiled case(s)", file=sys.stderr)
    return cases
