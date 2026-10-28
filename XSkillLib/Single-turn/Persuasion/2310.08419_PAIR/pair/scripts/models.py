#!/usr/bin/env python3
"""OpenAI-compatible chat client + walk-up .env loader for PAIR.

Every PAIR role (attacker / target / judge) reaches its model through `api_chat`,
an OpenAI-compatible `POST /chat/completions` call with bounded retries. Keys are
read from the nearest `.env` found by walking up ancestor directories — in the
XSkillLib layout this resolves to the global `XSkillForge/.env`; no per-skill
`.env` is needed.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


def _loads_llm_json(text: str):
    """Tolerant JSON parse for API/LLM text: raw, then code-fence/{...} extraction.

    On total failure the original JSONDecodeError is re-raised so the per-case
    containment in attack.py can record the case as provider_error:JSONDecodeError.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError as original:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.M)
        match = re.search(r"\{.*\}|\[.*\]", cleaned, flags=re.S)
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


def api_chat(model: str, messages: list[dict[str, str]], temperature: float, max_tokens: int) -> str:
    if load_nearest_env(Path.cwd()) is None:
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
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/oscarwu/AgenticCarlini",
            "X-Title": "AgenticCarlini PAIR Code",
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
        except (urllib.error.URLError, TimeoutError) as exc:
            last_err = RuntimeError(f"network error: {exc}")
            if attempt < 3:
                time.sleep(2 * (attempt + 1))
                continue
            raise last_err
    raise last_err if last_err else RuntimeError("api_chat failed")
