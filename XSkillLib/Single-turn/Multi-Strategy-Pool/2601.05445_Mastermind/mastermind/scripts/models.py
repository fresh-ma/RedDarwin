#!/usr/bin/env python3
"""OpenAI-compatible chat client + walk-up .env loader for Mastermind.

Every Mastermind role (planner / executor / controller / distiller / target /
judge / embedder) reaches its model through `api_chat`, an OpenAI-compatible
`POST /chat/completions` call with bounded retries. Keys are read from the nearest
`.env` found by walking up from this method dir (XSkillLib convention: the global
`XSkillForge/.env` at the repo root) — no per-skill `.env` needed.

Mastermind (arXiv 2601.05445) is a black-box multi-turn attack — all agents are
chat calls, so a single client serves them. Ported from the X-Teaming Code
(2504.13203) models.py, the closest sibling multi-agent multi-turn unit.
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
    """Tolerant json.loads: try raw text, then strip ```json/``` fences and
    regex-extract the outermost {...} or [...] block; re-raise the original
    JSONDecodeError if every attempt fails."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as original:
        stripped = re.sub(r"```(?:json)?|```", "", text)
        for opener, closer in (("{", "}"), ("[", "]")):
            start = stripped.find(opener)
            end = stripped.rfind(closer) + 1
            if start == -1 or end <= start:
                continue
            try:
                return json.loads(stripped[start:end])
            except json.JSONDecodeError:
                continue
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
                os.environ.setdefault(key, value)
        return env_path
    return None


def api_chat(
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    response_format: dict | None = None,
    *,
    reasoning: bool = False,
) -> str:
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
    if response_format:
        payload["response_format"] = response_format
    # Reasoning OFF by default: the planner/executor/controller/distiller emit their
    # result as message content, and the judge returns a short JSON score; the
    # reasoning channel is pure latency. Roles that want CoT pass reasoning=True.
    # gpt-oss endpoints mandate reasoning (400 if disabled) -> leave it on.
    if "openrouter.ai" in base_url and not reasoning and "gpt-oss" not in model.lower():
        payload["reasoning"] = {"enabled": False}
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/oscarwu/AgenticCarlini",
            "X-Title": "AgenticCarlini Mastermind Code",
        },
        method="POST",
    )
    last_err: Exception | None = None
    max_attempts = 6
    for attempt in range(max_attempts):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                body = _loads_llm_json(response.read().decode("utf-8"))
            choices = body.get("choices")
            if choices:
                return choices[0].get("message", {}).get("content") or ""
            # HTTP 200 but no choices: OpenRouter often returns a rate-limit / provider
            # error (e.g. {"error": {"code": 429, ...}}) or an empty body with a 200
            # status. Treat it as a retryable hiccup instead of crashing the whole run.
            err = body.get("error")
            detail = json.dumps(err)[:300] if err else json.dumps(body)[:300]
            last_err = RuntimeError(f"API returned no choices: {detail}")
            if attempt < max_attempts - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise last_err
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_err = RuntimeError(f"API error {exc.code}: {detail}")
            if exc.code in (429, 500, 502, 503, 520, 524) and attempt < max_attempts - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise last_err from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as exc:
            last_err = RuntimeError(f"network error: {exc}")
            if attempt < max_attempts - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise last_err
    raise last_err if last_err else RuntimeError("api_chat failed")
