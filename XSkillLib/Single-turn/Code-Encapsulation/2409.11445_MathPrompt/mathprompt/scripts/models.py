#!/usr/bin/env python3
"""Model plumbing for MathPrompt — .env loader + OpenAI-compatible chat client.

MathPrompt reaches every model role (attacker / target / judge) through one OpenAI-compatible
OpenRouter client. Errors are classified (rate_limited / auth_error / provider_block / ...) so a run
records honest provider failures instead of scoring garbage. The `.env` loader resolves the
UNIT-local `.env` FIRST by walking UP from this method dir looking for a `.env` marker file — no
fragile `parents[N]` indexing.
"""
from __future__ import annotations

import os
from pathlib import Path

from openai import OpenAI

SCRIPT_DIR = Path(__file__).resolve().parent
METHOD_DIR = SCRIPT_DIR.parent


def _load_env_file(path: Path) -> bool:
    if not path.exists():
        return False
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip().strip("'\""))
    return True


def load_env() -> None:
    """Load the nearest `.env`, method-local first, walking UP to the repo root."""
    for directory in (METHOD_DIR, *METHOD_DIR.parents):
        if _load_env_file(directory / ".env"):
            return


def make_client() -> OpenAI:
    load_env()
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
        timeout=300.0,
        max_retries=4,
    )


def chat(client: OpenAI, model: str, messages: list[dict], max_tokens: int,
         temperature: float = 0.0) -> tuple[str, str]:
    """Greedy decoding (temperature=0) per the paper's setup. Returns (text, status).

    Reasoning is disabled on deepseek-v4-flash so the judge/attacker do not blow their token budget
    on hidden reasoning and return empty (the jailbreak eval only cares about the final answer).
    """
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body={"reasoning": {"enabled": False}} if "deepseek-v4-flash" in model else None,
        )
        return (resp.choices[0].message.content or ""), "ok"
    except KeyError:
        return "OPENROUTER_API_KEY is required", "auth_error"
    except Exception as exc:  # noqa: BLE001 - classify provider errors
        text = f"{type(exc).__name__}: {exc}"
        low = text.lower()
        if "429" in low or "rate" in low:
            return text, "rate_limited"
        if "401" in low or "unauthorized" in low:
            return text, "auth_error"
        if any(k in low for k in ("403", "moderation", "blocked", "forbidden", "policy")):
            return text, "provider_block"
        return text, "provider_error"
