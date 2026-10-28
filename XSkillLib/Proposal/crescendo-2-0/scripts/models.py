#!/usr/bin/env python3
"""Provider-aware chat client + method-local .env loader + path roots for Crescendo.

Every role (attacker / target / judge) reaches its model through `chat`. Model
strings carry a provider scheme so the same call site works hosted and local:

  api:<model>     -> OpenRouter (`OPENROUTER_API_KEY`), OpenAI-compatible SDK call
  ollama:<model>  -> local Ollama daemon, no API key, native /api/chat
  <model>         -> treated as api:<model>

The attacker role defaults to a local uncensored model over Ollama (it won't
refuse the adversarial red-team role), but the unit stays distributable:
`ollama_available` lets `default_role_model` fall back to the hosted API model
when a recipient has no Ollama daemon. The target and judge stay hosted/neutral.
Keys load from the nearest `.env` found walking up from the paper dir through
all ancestors (XSkillLib convention: the global `XSkillForge/.env` is picked up
this way — no per-skill `.env`, no manual `export`). `METHOD_ROOT` / `PAPER_ROOT`
are the shared path anchors the other modules import.
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
# OpenRouter client
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

    load_env_from_nearest(PAPER_ROOT)
    try:
        api_key = os.environ[args.api_key_env]
    except KeyError as exc:
        raise SystemExit(f"{args.api_key_env} is required for api roles") from exc
    # Per-request timeout + bounded retries so one hung socket cannot stall the whole run.
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


def default_role_model() -> str:
    """Attacker/generator default: local uncensored over Ollama, else hosted API."""
    return "ollama:uncensored" if ollama_available("uncensored") else "api:deepseek/deepseek-v4-flash"


def _model_id(spec: str, role: str) -> str:
    """Validate a role's scheme-tagged model string, returning it unchanged.

    The scheme is preserved so `chat` can route to OpenRouter (api:) or the local
    Ollama daemon (ollama:); bare strings are accepted as api:<model>."""
    provider, model = split_model(spec)
    if provider not in {"api", "ollama"} or not model:
        raise SystemExit(f"{role} must be api:<model> or ollama:<model> (got {spec!r}); fake requires --wiring-check")
    return spec


def _ollama_chat(model: str, messages: list[dict[str, str]], temperature: float, max_tokens: int) -> tuple[str, str]:
    # A supergemma-class thinking model returns EMPTY content when token-capped, so a
    # local role is never hard-capped (uncensored-llm skill): num_predict=-1 runs to a
    # natural stop, and think=false keeps the final text clean.
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


def _retryable(exc: Exception) -> bool:
    """True for transient failures worth one more attempt: connection/timeout/5xx.

    4xx auth/permission (and other client) errors are NOT retried.
    """
    status = getattr(exc, "status_code", None)
    if status is not None:
        try:
            return int(status) >= 500
        except (TypeError, ValueError):
            return False
    try:
        from openai import APIConnectionError, APITimeoutError

        return isinstance(exc, (APIConnectionError, APITimeoutError, TimeoutError, ConnectionError))
    except ImportError:
        return isinstance(exc, (TimeoutError, ConnectionError))


def chat(client, model: str, messages: list[dict[str, str]], temperature: float, max_tokens: int) -> tuple[str, str]:
    provider, name = split_model(model)
    if provider == "ollama":
        return _ollama_chat(name, messages, temperature, max_tokens)
    # crescendo-2-0 reliability: up to 2 additional attempts (2s/5s backoff) when the
    # response has empty/missing choices or empty content, or on transient
    # connection/timeout/5xx errors. Applies to every role (attacker/target/judge).
    backoffs = (2.0, 5.0)
    for attempt in range(1 + len(backoffs)):
        try:
            response = client.chat.completions.create(
                model=name, messages=messages, temperature=temperature, max_tokens=max_tokens
            )
        except Exception as exc:  # provider/runtime error kept separate from refusal
            if attempt < len(backoffs) and _retryable(exc):
                time.sleep(backoffs[attempt])
                continue
            return "", f"provider_error:{type(exc).__name__}"
        # Some OpenRouter upstreams return a 200 with choices=None/[] (rate limit,
        # content filter, transient upstream error), or an empty content string
        # (e.g. token-capped or truncated upstream). Retry those too; after the
        # last attempt treat as a per-turn provider error instead of crashing the
        # whole multi-turn run on choices[0].
        choices = getattr(response, "choices", None)
        content = str(choices[0].message.content or "") if choices else ""
        if choices and content:
            return content, "ok"
        if attempt < len(backoffs):
            time.sleep(backoffs[attempt])
            continue
        return "", "provider_error:empty_choices" if not choices else "provider_error:empty_content"
    return "", "provider_error:unreachable"
