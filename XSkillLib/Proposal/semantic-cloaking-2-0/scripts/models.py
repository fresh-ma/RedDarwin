#!/usr/bin/env python3
"""OpenAI-compatible chat client + walk-up .env loader for S2C.

Every S2C role (reframer / extractor / translator / target / judge) reaches its
model through `api_chat`, an OpenAI-compatible `POST /chat/completions` call with
bounded retries. Keys are read from the nearest `.env` found by walking up from
the cwd / script dir (the global XSkillForge/.env under the XSkillLib convention) —
no per-skill `.env` required.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


def _loads_llm_json(text: str):
    """Tolerant JSON parse: try raw, then strip ```json fences and extract the
    outermost {...} or [...] block; re-raise the original error if still failing."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as original:
        stripped = re.sub(r"```(?:json)?", "", text)
        match = re.search(r"\{.*\}|\[.*\]", stripped, flags=re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        raise original


def load_nearest_env(start: Path) -> Path | None:
    for directory in (start, *start.parents):
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


def api_chat(model: str, messages: list[dict[str, str]], temperature: float, max_tokens: int,
             reasoning: bool = False) -> str:
    load_nearest_env(Path.cwd())
    load_nearest_env(Path(__file__).resolve().parent)
    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENROUTER_BASE_URL")
    if not base_url:
        base_url = "https://openrouter.ai/api/v1" if os.environ.get("OPENROUTER_API_KEY") else "https://api.openai.com/v1"
    if "openrouter.ai" in base_url:
        api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    else:
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY or OPENROUTER_API_KEY is required for api:<model> adapters")
    api_key = api_key.strip()
    if api_key.lower().startswith("bearer "):
        api_key = api_key.split(None, 1)[1]
    base_url = base_url.rstrip("/")
    payload: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if not reasoning and "gpt-oss" not in model.lower():
        # Reasoning OFF (default): jailbreak eval judges only the final answer; a reasoning
        # target balloons latency + causes the empty-output loop. ~10x faster on OpenRouter.
        # gpt-oss endpoints mandate reasoning (400 if disabled) -> leave it on.
        payload["reasoning"] = {"enabled": False}
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/oscarwu/AgenticCarlini",
            "X-Title": "AgenticCarlini S2C Code",
        },
        method="POST",
    )
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                body = _loads_llm_json(response.read().decode("utf-8"))
            return body["choices"][0]["message"].get("content") or ""
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_err = RuntimeError(f"API error {exc.code}: {detail}")
            if exc.code in (429, 500, 502, 503, 520, 524) and attempt < 3:
                time.sleep(2 * (attempt + 1))
                continue
            raise last_err from exc
        except (urllib.error.URLError, TimeoutError, http.client.IncompleteRead) as exc:
            # IncompleteRead = provider closed a chunked response early (truncated body);
            # safe to retry like any other transient network error.
            last_err = RuntimeError(f"network error: {exc}")
            if attempt < 3:
                time.sleep(2 * (attempt + 1))
                continue
            raise last_err
    raise last_err if last_err else RuntimeError("api_chat failed")
