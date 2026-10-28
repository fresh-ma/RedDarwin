#!/usr/bin/env python3
"""OpenRouter chat client + .env loader for Cognitive Overload.

The black-box target, the in-tool paraphraser (veiled_expression), and the
content-harm over-count judge all reach their model through `openrouter_chat`.
Keys are read from the nearest `.env` found by walking up from the method dir
through every ancestor directory (XSkillLib convention: the global
XSkillForge/.env holds OPENROUTER_API_KEY) — no per-skill `.env`, no manual
`export`.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
METHOD_DIR = SCRIPT_PATH.parents[1]


def _find_env_file() -> Path | None:
    """Walk up from the method dir through every ancestor directory; return the
    first `.env` found (a method-local one still wins; otherwise the global
    XSkillForge/.env is found by walking up)."""
    for base in (METHOD_DIR, *SCRIPT_PATH.parents):
        cand = base / ".env"
        if cand.exists():
            return cand
    return None


def load_project_env() -> None:
    env_path = _find_env_file()
    if env_path is None or not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            os.environ[key] = value


def openrouter_chat(model: str, messages: list[dict[str, str]], timeout: int, max_tokens: int, temperature: float) -> dict[str, Any]:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required for api:<model> targets")
    payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    try:  # project-pinned provider routing (infra; identical for all goals/victims)
        from openrouter_routing import provider_route_for_model
        route = provider_route_for_model(model)
    except ImportError:
        route = None
    if route:
        payload["provider"] = route
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"OpenRouter HTTP {exc.code}: {body}") from exc
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("OpenRouter returned no choices")
    choice = choices[0]
    return {
        "content": str(((choice.get("message") or {}).get("content")) or ""),
        "finish_reason": choice.get("finish_reason"),
        "usage": data.get("usage"),
    }
