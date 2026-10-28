#!/usr/bin/env python3
"""Model client + walk-up .env loader for Compound Role-Playing (XSkillLib convention).

Single-shot black-box attack: the only launched components are the target and the
judge, both OpenAI-compatible (OpenRouter by default). Model specs accept an
optional `api:` / `ollama:` prefix so any role is swappable:
  - "api:<model>" or "<model>"  -> OpenRouter (OpenAI-compatible)
  - "ollama:<model>"            -> local Ollama (http://localhost:11434/v1), e.g.
                                   an uncensored local model; no key needed.

API keys come from the global XSkillForge/.env: `load_project_env` walks up
ancestor directories and loads every `.env` it finds (nearest wins).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OLLAMA_BASE = "http://localhost:11434/v1"


def load_project_env(start: Path | None = None) -> None:
    """Walk up ancestor directories and load every .env found (nearest first).
    Never overrides a var already in the environment."""
    here = (start or Path(__file__)).resolve()
    preexisting = set(os.environ)
    seen: set[Path] = set()
    for parent in (here.parent, *here.parents):
        env_path = parent / ".env"
        if env_path in seen or not env_path.exists():
            seen.add(env_path)
            continue
        seen.add(env_path)
        for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip("'\"")
            if key and value and key not in preexisting:
                os.environ[key] = value


def _client_for(model: str):
    from openai import OpenAI

    if model.startswith("ollama:"):
        return OpenAI(api_key="ollama", base_url=OLLAMA_BASE), model[len("ollama:"):]
    name = model[len("api:"):] if model.startswith("api:") else model
    load_project_env()
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise EnvironmentError("OPENROUTER_API_KEY not set (expected in the global XSkillForge/.env).")
    return OpenAI(api_key=key, base_url=OPENROUTER_BASE), name


def call_model(
    model: str,
    messages: list[dict],
    max_tokens: int = 1024,
    temperature: float = 0.0,
    *,
    reasoning: bool = False,
    retries: int = 4,
) -> tuple[str | None, str]:
    """Return (text, status). text is None on hard failure. status in
    {ok, truncated, error: ...}. Target reasoning OFF by default (~10x faster,
    avoids the empty-output loop); judges only the final answer."""
    client, name = _client_for(model)
    # gpt-oss endpoints mandate reasoning (400 if disabled) -> leave it on.
    extra = None if (reasoning or "gpt-oss" in name.lower()) else {"reasoning": {"enabled": False}}
    last_err = ""
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=name,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                extra_body=extra,
            )
            choice = resp.choices[0]
            text = choice.message.content
            finish = getattr(choice, "finish_reason", "") or ""
            if text is None:
                last_err = f"null_content(finish={finish})"
                time.sleep(2 * (attempt + 1))
                continue
            return text, ("truncated" if finish == "length" else "ok")
        except Exception as e:  # noqa: BLE001 - transient provider errors
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(2 * (attempt + 1))
    return None, f"error: {last_err}"
