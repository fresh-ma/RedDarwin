#!/usr/bin/env python3
"""OpenRouter chat client + walk-up .env loader for Puzzler.

Every Puzzler role (extractor / defensive-gen / filter / offensive-gen / target /
judge) reaches its model through `chat`, an OpenRouter `POST /chat/completions`
call with bounded retries. Keys are read from the nearest `.env` found by walking
up from this file (XSkillLib convention: the global `XSkillForge/.env` is found
this way — no per-skill `.env`, no manual `export`).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PAPER_ROOT = Path(__file__).resolve().parents[2]


def _find_env_root(start: Path) -> Path:
    """Walk up from `start` to the first ancestor directory holding a `.env`."""
    for p in [start, *start.parents]:
        if (p / ".env").exists():
            return p
    return PAPER_ROOT


PROJECT_ROOT = _find_env_root(PAPER_ROOT)


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

def load_project_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip().strip("'\"")


def chat(model: str, prompt: str, *, max_tokens: int, temperature: float,
         retries: int = 3) -> dict[str, Any]:
    """One OpenRouter chat completion. Returns {content, finish_reason, usage}."""
    load_project_env()
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required (global XSkillForge/.env, found by walking up)")
    endpoint = os.environ.get("OPENROUTER_CHAT_URL", "https://openrouter.ai/api/v1/chat/completions")
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    last_err: Exception | None = None
    for attempt in range(retries):
        request = urllib.request.Request(
            endpoint, data=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
            choices = data.get("choices") or []
            if not choices:
                raise RuntimeError("OpenRouter returned no choices")
            choice = choices[0]
            return {
                "content": str(((choice.get("message") or {}).get("content")) or ""),
                "finish_reason": choice.get("finish_reason"),
                "usage": data.get("usage"),
            }
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            last_err = RuntimeError(f"HTTP {exc.code}: {body}")
            if exc.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise last_err from exc
        except OSError as exc:
            last_err = RuntimeError(str(exc))
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise last_err from exc
    raise last_err or RuntimeError("chat failed")
