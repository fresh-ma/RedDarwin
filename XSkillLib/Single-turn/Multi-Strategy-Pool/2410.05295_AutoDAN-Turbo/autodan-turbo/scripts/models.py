#!/usr/bin/env python3
"""OpenAI-compatible chat client + walk-up .env loader (stdlib urllib, SDK-free).

Keys are read from the first `.env` found walking up from the script directory
(any ancestor, e.g. the global `XSkillForge/.env`). No per-skill `.env` needed.
Default gateway: OpenRouter. Reasoning OFF by default.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


def load_nearest_env(start: Path | None = None) -> Path | None:
    here = (start or Path(__file__)).resolve()
    for directory in (here, *here.parents):
        env_path = directory / ".env"
        if not env_path.exists():
            continue
        for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value:
                os.environ[key] = value
        return env_path
    return None


def _resolve_api() -> tuple[str, str]:
    load_nearest_env(Path(__file__).resolve().parent)
    base_url = (
        os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("OPENROUTER_BASE_URL")
        or "https://openrouter.ai/api/v1"
    )
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError('os.environ["OPENROUTER_API_KEY"] is required (global XSkillForge/.env)')
    api_key = api_key.strip()
    if api_key.lower().startswith("bearer "):
        api_key = api_key.split(None, 1)[1]
    return base_url.rstrip("/"), api_key


def api_chat(
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int = 1024,
    reasoning: bool = False,
    max_attempts: int = 5,
) -> tuple[str, str]:
    """POST /chat/completions. Returns (text, status) where status is ok|provider_error|..."""
    base_url, api_key = _resolve_api()
    payload: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    # gpt-oss endpoints mandate reasoning (400 if disabled) -> leave it on.
    if "openrouter.ai" in base_url and not reasoning and "gpt-oss" not in model.lower():
        payload["reasoning"] = {"enabled": False}
    elif not reasoning and "openrouter.ai" not in base_url:
        # local OpenAI-compatible servers (vLLM/Ollama /v1)
        payload["reasoning_effort"] = "none"

    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/oscarwu/AgenticCarlini",
        "X-Title": "AgenticCarlini AutoDAN-Turbo",
    }
    last = ""
    for attempt in range(max_attempts):
        try:
            req = urllib.request.Request(
                base_url + "/chat/completions",
                data=body,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            return text, "ok"
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last = f"HTTPError {exc.code}: {detail}"
            low = last.lower()
            if exc.code in (429, 500, 502, 503, 520, 524) and attempt < max_attempts - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            if "403" in low or "moderation" in low or "forbidden" in low or "policy" in low:
                return last, "provider_block"
            return last, "provider_error"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = f"{type(exc).__name__}: {exc}"
            if attempt < max_attempts - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            return last, "provider_error"
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
            if attempt < max_attempts - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            return last, "provider_error"
    return last, "provider_error"


def conditional_generate(
    model: str,
    condition: str,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
    max_attempts: int = 5,
) -> tuple[str, str]:
    """Replicate HF conditional_generate: prefill assistant with `condition`, return continuation."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": condition},
    ]
    out, status = api_chat(
        model, messages, temperature=temperature, max_tokens=max_tokens, max_attempts=max_attempts
    )
    if status != "ok":
        out2, status2 = api_chat(
            model,
            messages[:2],
            temperature=temperature,
            max_tokens=max_tokens,
            max_attempts=max_attempts,
        )
        return out2, status2
    return out, status
