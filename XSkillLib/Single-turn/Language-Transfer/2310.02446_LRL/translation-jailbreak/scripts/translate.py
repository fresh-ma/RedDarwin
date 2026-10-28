#!/usr/bin/env python3
"""Swappable machine-translation client — the paper's core attack transform.

The low-resource-language attack forward-translates an English harmful goal into a
target language, sends it to the victim, then back-translates the reply into English
for judging. This module is the MT role: a REAL MT provider (Google/DeepL/AWS/Azure
via `tools/translation_api.py`, `--translator project-api`), with `cache` /
`identity` / `api` / `tagged` alternatives selectable by `--translator`. Keeping the
translator as its own module (its own flag) means it stays swappable and is never
silently collapsed into an LLM translator.
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

from models import api_chat, api_model_name, display_path, project_root, read_csv_rows, resolve_path
from prompts import LANGUAGES


def load_translation_tool():
    method_tool = Path(__file__).resolve().parents[1] / "tools" / "translation_api.py"
    project_tool = project_root() / "tools" / "translation_api" / "translation_api.py"
    tool_path = method_tool if method_tool.exists() else project_tool
    spec = importlib.util.spec_from_file_location("agentic_carlini_translation_api", tool_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {display_path(tool_path)}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_translation_cache(path_value: str | None) -> dict[tuple[str, str, str], str]:
    path = resolve_path(path_value)
    if not path or not path.exists():
        return {}
    rows = read_csv_rows(path)
    cache: dict[tuple[str, str, str], str] = {}
    for row in rows:
        sample_id = row.get("id") or row.get("sample_id") or row.get("index") or row.get("source_row") or ""
        for key, value in row.items():
            if not value:
                continue
            if key.startswith("forward_"):
                cache[(sample_id, key.removeprefix("forward_"), "forward")] = value
            elif key.startswith("back_"):
                cache[(sample_id, key.removeprefix("back_"), "backward")] = value
            elif key in LANGUAGES:
                cache[(sample_id, key, "forward")] = value
    return cache


def translate_text(
    text: str,
    sample_id: str,
    language: str,
    direction: str,
    args: argparse.Namespace,
    cache: dict[tuple[str, str, str], str],
) -> tuple[str, str, str]:
    if language == "en":
        return text, "identity_en", "ok"
    cached = cache.get((sample_id, language, direction)) or cache.get((str(sample_id), language, direction))
    if cached:
        return cached, "cache", "ok"
    if args.translator == "identity":
        return text, "identity", "ok"
    if args.translator == "cache":
        return text, "cache_missing_identity_fallback", "cache_missing"
    if args.translator == "project-api":
        try:
            tool = load_translation_tool()
            if direction == "forward":
                translated, provider = tool.translate_text_via_provider(
                    args.translation_provider,
                    text,
                    "en",
                    language,
                    "text",
                    args.translation_model,
                )
            else:
                translated, provider = tool.translate_text_via_provider(
                    args.translation_provider,
                    text,
                    "auto",
                    "en",
                    "text",
                    args.translation_model,
                )
            return translated, f"project-api:{provider}", "ok"
        # SystemExit: translation_api.py signals CLI-style errors (missing credentials,
        # HTTP errors) via SystemExit, which `except Exception` would miss; without this
        # one provider failure kills the whole asyncio gather instead of one case.
        except (Exception, SystemExit) as exc:  # noqa: BLE001
            return text, f"project-api_error:{type(exc).__name__}:{str(exc)[:120]}", "provider_error"
    if args.translator == "api":
        model = api_model_name(args.translator_model or args.target)
        if not model or model == "fake":
            return text, "api_translator_missing_model", "provider_error"
        if direction == "forward":
            prompt = (
                f"Translate the following text into {LANGUAGES[language]['name']}. "
                "Return only the translation.\n\n"
                f"{text}"
            )
        else:
            prompt = "Translate the following text into English. Return only the translation.\n\n" + text
        output, status = api_chat(
            [{"role": "user", "content": prompt}],
            model,
            args,
            max_tokens=args.translation_max_tokens,
            temperature=0.0,
        )
        # Empty output (reasoning-token exhaustion or silent refusal) must not be
        # forwarded to the victim as the "translated" attack query — fail the case
        # honestly instead. (In-target-language refusals can't be detected cheaply
        # and remain a known fidelity risk of LLM translators.)
        if status == "ok" and not output.strip():
            return text, f"api:{model}_empty_translation", "provider_error"
        return output, f"api:{model}", status
    if direction == "forward":
        return f"[{LANGUAGES[language]['name']} translation via {args.translator}]\n{text}", args.translator, "ok"
    return f"[Back-translated from {LANGUAGES[language]['name']}]\n{text}", args.translator, "ok"
