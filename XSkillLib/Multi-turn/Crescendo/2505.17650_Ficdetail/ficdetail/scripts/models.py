#!/usr/bin/env python3
"""Provider-aware chat client + method-local .env loader + path roots for FicDetail.

Both roles (target / judge) reach their model through `chat`. Model strings carry
a provider scheme so the same call site works hosted and local:

  api:<model>     -> OpenRouter (`OPENROUTER_API_KEY`), OpenAI-compatible SDK call
  ollama:<model>  -> local Ollama daemon, no API key, native /api/chat
  <model>         -> treated as api:<model>

FicDetail has no attacker LLM (its three turns are fixed templates), so the only
swappable model roles are the target being attacked and the AHS/ASR judge; both
default to a hosted neutral model. Keys load from the nearest `.env` (this method
dir first, walking up as fallback) so the unit runs self-contained.
`METHOD_ROOT` / `PAPER_ROOT` are the shared path anchors the other modules import.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

METHOD_ROOT = Path(__file__).resolve().parents[1]
PAPER_ROOT = METHOD_ROOT.parent


# --------------------------------------------------------------------------- #
# .env loader
# --------------------------------------------------------------------------- #
def load_env_from_nearest(start: Path) -> None:
    for folder in [start, *start.parents]:
        env_path = folder / ".env"
        if not env_path.exists():
            continue
        for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value
        return


def _client(args: argparse.Namespace):
    from openai import OpenAI

    load_env_from_nearest(METHOD_ROOT)
    try:
        api_key = os.environ[args.api_key_env]
    except KeyError as exc:
        raise SystemExit(f"{args.api_key_env} is required for api roles") from exc
    return OpenAI(base_url=args.base_url, api_key=api_key, timeout=args.request_timeout, max_retries=2)


# --------------------------------------------------------------------------- #
# Provider routing
# --------------------------------------------------------------------------- #
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


def _model_id(spec: str, role: str) -> str:
    """Validate a role's scheme-tagged model string, returning it unchanged."""
    provider, model = split_model(spec)
    if provider not in {"api", "ollama"} or not model:
        raise SystemExit(f"{role} must be api:<model> or ollama:<model> (got {spec!r}); fake requires --wiring-check")
    return spec


def _ollama_chat(model: str, messages: list[dict[str, str]], temperature: float, max_tokens: int) -> tuple[str, str]:
    # num_predict=-1 lets a local reasoning model run to a natural stop (a capped
    # thinking model returns EMPTY content); think=false keeps the final text clean.
    num_predict = max_tokens if (max_tokens and max_tokens >= 1024) else -1
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": temperature, "num_predict": num_predict},
    }
    request = urllib.request.Request(
        f"{ollama_base()}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                data = json.loads(response.read().decode("utf-8"))
            return (str((data.get("message") or {}).get("content") or ""), "ok")
        except urllib.error.HTTPError as exc:
            if exc.code in (500, 502, 503) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            return "", f"provider_error:HTTP{exc.code}"
        except OSError as exc:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            return "", f"provider_error:{type(exc).__name__}"
    return "", "provider_error:unreachable"


def chat(client, model: str, messages: list[dict[str, str]], temperature: float, max_tokens: int) -> tuple[str, str]:
    provider, name = split_model(model)
    if provider == "ollama":
        return _ollama_chat(name, messages, temperature, max_tokens)
    try:
        # Target reasoning stays ON here — FicDetail's whole thesis is that CoT
        # reasoning enriches (not suppresses) harmful detail, so we judge the
        # model's natural reasoning-mode final answer.
        response = client.chat.completions.create(
            model=name, messages=messages, temperature=temperature, max_tokens=max_tokens
        )
    except Exception as exc:  # provider/runtime error kept separate from refusal
        return "", f"provider_error:{type(exc).__name__}"
    choices = getattr(response, "choices", None)
    if not choices:
        return "", "provider_error:empty_choices"
    return (choices[0].message.content or ""), "ok"
