#!/usr/bin/env python3
"""OpenAI-compatible chat client + project .env loader for GPTFuzzer.

The target and the mutator LLM both reach their model through ``api_chat`` (an
OpenAI-compatible ``POST /chat/completions`` call, OpenRouter by default). Keys
are read from the project ``.env`` via ``load_project_env``. ``PAPER_ID`` lives
here because ``api_chat`` stamps it into the request headers.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

PAPER_ID = "2309.10253_auto-generated-llm-jailbreaks"


def project_root() -> Path:
    # XSkillLib convention: walk up from this script to the nearest ancestor
    # holding a `.env` (the global XSkillForge/.env); fall back to CWD.
    for parent in Path(__file__).resolve().parents:
        if (parent / ".env").exists():
            return parent
    return Path.cwd()


def _load_env_key(env_path: Path, env_name: str) -> bool:
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == env_name and value.strip():
            os.environ[env_name] = value.strip().strip("'\"")
            return True
    return False


def load_project_env(env_name: str) -> None:
    # Walk up through ALL ancestors and load the first .env that defines the key,
    # so a skill-local .env (if any) wins and the global XSkillForge/.env is the fallback.
    for parent in Path(__file__).resolve().parents:
        env_path = parent / ".env"
        if env_path.exists() and _load_env_key(env_path, env_name):
            return


def api_chat(
    messages: list[dict[str, str]],
    model: str,
    base_url: str,
    api_key_env: str,
    temperature: float,
    max_tokens: int,
    timeout: float,
) -> tuple[str, str]:
    try:
        load_project_env(api_key_env)
        api_key = os.environ[api_key_env]
        endpoint = base_url.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint = f"{endpoint}/chat/completions"
        payload = json.dumps(
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/oscarwu/AgenticCarlini",
                "X-Title": f"AgenticCarlini {PAPER_ID}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"].get("content") or "", "ok"
    except KeyError:
        return f"{api_key_env} is required for api targets", "auth_error"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        return f"HTTPError {exc.code}: {body}", "provider_error"
    except urllib.error.URLError as exc:
        return f"URLError: {exc.reason}", "provider_error"
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}", "provider_error"
