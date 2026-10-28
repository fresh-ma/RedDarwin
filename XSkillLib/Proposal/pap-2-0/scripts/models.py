#!/usr/bin/env python3
"""OpenRouter chat client + .env walk-up loader + method-dir path anchors.

Every PAP role (paraphraser / target / judge) reaches its model through
`call_with_retry`, an OpenAI-compatible chat call with bounded retries on
transient failures. Keys are read from the global XSkillForge `.env` —
`load_project_env` walks up from the method dir through every ancestor and
loads each `.env` it finds (XSkillLib convention: no per-skill `.env`, no
manual `export`). The method-dir path anchors (DATA_DIR / RESULTS_DIR) live
here so the prompt / dataset modules can resolve their files off one source.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# Self-contained method dir: this script lives at <method-dir>/scripts/models.py,
# so data/ and results/ are siblings of scripts/ under the method dir.
# ---------------------------------------------------------------------------
METHOD_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = METHOD_DIR / "data"
RESULTS_DIR = METHOD_DIR / "results"


# ---------------------------------------------------------------------------
# Env loading (no external deps)
# ---------------------------------------------------------------------------


def load_project_env(start: Path | None = None) -> None:
    """Load env vars from the nearest .env walking up through every ancestor.

    XSkillLib convention: the global XSkillForge/.env is found by walking up
    from the method dir; a method-local .env (if present) also loads. Every
    ancestor .env is loaded, nearer ones win. Pre-existing env vars win.
    """
    here = (start or Path(__file__)).resolve()
    preexisting = set(os.environ)
    candidates: list[Path] = [METHOD_DIR / ".env"]
    for parent in (here.parent, *here.parents):
        env_path = parent / ".env"
        if env_path not in candidates:
            candidates.append(env_path)
    for env_path in candidates:
        if not env_path.exists():
            continue
        for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and value and key not in preexisting:
                os.environ[key] = value


# ---------------------------------------------------------------------------
# Model calling via OpenRouter (OpenAI-compatible)
# ---------------------------------------------------------------------------


def call_api(
    messages: list[dict[str, str]],
    model: str,
    max_tokens: int = 1024,
    temperature: float = 0.0,
    *,
    base_url: str = "https://openrouter.ai/api/v1",
    api_key_env: str = "OPENROUTER_API_KEY",
) -> tuple[str, str]:
    """Call OpenRouter and return (text, status)."""
    from openai import OpenAI
    client = OpenAI(base_url=base_url, api_key=os.environ[api_key_env],
                    timeout=60.0)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = resp.choices[0].message.content or ""
        served = None
        if hasattr(resp, "model"):
            served = resp.model
        return text, "ok"
    except Exception as exc:
        t = f"{type(exc).__name__}: {exc}"
        low = t.lower()
        if "429" in low or "rate limit" in low:
            return t, "rate_limited"
        if "401" in low or "unauthorized" in low:
            return t, "auth_error"
        if any(k in low for k in ("403", "moderation", "blocked", "forbidden")):
            return t, "provider_block"
        return t, "provider_error"


def call_with_retry(
    messages: list[dict[str, str]],
    model: str,
    max_tokens: int = 1024,
    temperature: float = 0.0,
    retries: int = 3,
    delay: float = 5.0,
    **kwargs: Any,
) -> tuple[str, str]:
    """Call API with retry on transient failures."""
    for attempt in range(retries):
        text, status = call_api(messages, model, max_tokens, temperature, **kwargs)
        if status == "ok":
            return text, status
        if status in ("auth_error", "provider_block"):
            return text, status
        if attempt < retries - 1:
            time.sleep(delay * (attempt + 1))
    return text, status
