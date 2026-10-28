#!/usr/bin/env python3
"""Provider routing helpers for the Echo Chamber runner.

The attacker/generator role (objective rewrite, keyword extraction, path
selection, next-question generation, intermediate objective/answer evals) drives
the multi-turn ladder and must not refuse the adversarial persona. It therefore
defaults to a LOCAL uncensored model over Ollama (no API key); the target
(victim) and judge stay on the hosted OpenRouter API. Model strings carry a
provider scheme so the same call site works both hosted and local:

  api:<model>     -> OpenRouter (`OPENROUTER_API_KEY`), e.g. api:deepseek/deepseek-v4-flash
  ollama:<model>  -> local Ollama daemon, no API key, e.g. ollama:uncensored
  <model>         -> treated as api:<model>

`default_role_model` keeps the unit distributable: when no Ollama daemon has the
attacker model pulled, the attacker role falls back to the hosted API model, so
a recipient without Ollama still runs.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any


def split_model(model: str | None) -> tuple[str, str]:
    """Split a scheme-tagged model string into (provider, name)."""
    value = (model or "").strip()
    if value.startswith("ollama:"):
        return "ollama", value[len("ollama:"):].strip()
    if value.startswith("api:"):
        return "api", value[len("api:"):].strip()
    return "api", value


def ollama_base() -> str:
    return os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")


def ollama_available(model: str | None = None) -> bool:
    """True if a local Ollama daemon answers, and (if given) has `model` pulled."""
    try:
        with urllib.request.urlopen(f"{ollama_base()}/api/tags", timeout=3) as response:
            tags = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return False
    if not model:
        return True
    have = {str(m.get("name", "")).split(":")[0] for m in tags.get("models", [])}
    return model.split(":")[0] in have


def default_role_model(preferred: str, fallback: str = "api:deepseek/deepseek-v4-flash") -> str:
    """Resolve an attacker-role model string: keep `preferred` unless it names a
    local Ollama model that no daemon has, in which case use the hosted fallback."""
    provider, name = split_model(preferred)
    if provider == "ollama" and not ollama_available(name):
        return fallback
    return preferred


def ollama_chat(model: str, messages: list[dict[str, str]], *, max_tokens: int,
                temperature: float, top_p: float, json_mode: bool) -> dict[str, Any]:
    """Call a local Ollama model via native /api/chat, returning the same result
    shape as the runner's OpenAI-backed `chat`.

    A thinking-class uncensored model returns EMPTY content when token-capped, so
    a local role is never hard-capped (uncensored-llm skill): num_predict=-1 runs
    to a natural stop unless the caller asked for a genuinely large budget, and
    think=false keeps the final text clean.
    """
    started = time.time()
    num_predict = max_tokens if (max_tokens and max_tokens >= 1024) else -1
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": temperature, "top_p": top_p, "num_predict": num_predict},
    }
    if json_mode:
        payload["format"] = "json"
    request = urllib.request.Request(
        f"{ollama_base()}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "provider_error",
            "text": f"{type(exc).__name__}: {exc}",
            "finish_reason": None,
            "seconds": round(time.time() - started, 3),
        }
    message = data.get("message") or {}
    return {
        "status": "ok",
        "text": str(message.get("content") or ""),
        "finish_reason": data.get("done_reason"),
        "seconds": round(time.time() - started, 3),
    }
