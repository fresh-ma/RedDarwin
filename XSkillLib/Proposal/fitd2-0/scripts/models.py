#!/usr/bin/env python3
"""OpenAI-compatible chat client + .env loader for FITD.

Every FITD model call (target turns and the judge) reaches its model through
`_chat_completion`, an OpenAI-compatible `POST /chat/completions` request. Keys
are read from the nearest ancestor `.env` via `load_project_env` (walks up to
the global XSkillForge `.env`), so the unit picks up the current key and
overrides any stale shell value.
"""

from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PAPER_ROOT = Path(__file__).resolve().parents[2]


def load_project_env() -> None:
    # Walk up from this skill to find the nearest ancestor `.env` (XSkillLib
    # convention: the shared XSkillForge repo-root `.env`; a method-local `.env`
    # still wins if present).
    env_path = None
    for parent in [PAPER_ROOT, *PAPER_ROOT.parents]:
        candidate = parent / ".env"
        if candidate.exists():
            env_path = candidate
            break
    if env_path is None:
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ[key] = value  # project .env overrides stale shell value


# --------------------------------------------------------------------------- #
# Target + judge model calls (OpenRouter, OpenAI-compatible).                  #
# --------------------------------------------------------------------------- #
def _chat_completion(
    *,
    api_base: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    timeout: int,
) -> dict[str, Any]:
    endpoint = api_base.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/oscarwu/AgenticCarlini",
            "X-Title": "AgenticCarlini paper-local FITD Code",
        },
        method="POST",
    )
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            if "choices" not in data or not data["choices"]:
                # HTTP 200 with an error/empty body (rate limit, provider
                # overload, content-filter block page): retry like a transport
                # error, then surface the body for diagnosis.
                raise urllib.error.URLError(f"no_choices: {json.dumps(data)[:200]}")
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as exc:
            last_exc = exc
            if attempt < 3:
                time.sleep(2 * (attempt + 1))
    else:
        raise last_exc  # type: ignore[misc]
    choice = data["choices"][0]
    content = choice["message"].get("content")
    return {
        "text": "" if content is None else str(content),
        "finish_reason": choice.get("finish_reason"),
        "usage": data.get("usage"),
        "provider_model": data.get("model"),
    }
