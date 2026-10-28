"""models.py — minimal model client + walk-up .env loader for Stochastic Monkeys 2.0.

Adapted from the parent skill; self-contained so the proposal wrapper needs no
external imports.
"""
from __future__ import annotations

import os
from pathlib import Path


def load_project_env(start: Path | None = None) -> None:
    """Walk up from this file through every ancestor directory, loading each .env
    found (nearest wins; pre-existing env vars are never overridden)."""
    here = (start or Path(__file__)).resolve()
    preexisting = set(os.environ)
    for parent in (here.parent, *here.parents):
        env_path = parent / ".env"
        if not env_path.exists():
            continue
        for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and value and key not in os.environ and key not in preexisting:
                os.environ[key] = value


def call_api(messages, model, max_tokens=256, *, reasoning=False,
             base_url="https://openrouter.ai/api/v1", api_key_env="OPENROUTER_API_KEY"):
    try:
        load_project_env()
        from openai import OpenAI
        client = OpenAI(base_url=base_url, api_key=os.environ[api_key_env])
        gpt_oss = "gpt-oss" in model.lower()
        if gpt_oss and max_tokens < 1024:
            max_tokens = 1024
        extra = None if (reasoning or gpt_oss) else {"reasoning": {"enabled": False}}
        resp = client.chat.completions.create(
            model=model, messages=messages, temperature=0, max_tokens=max_tokens, extra_body=extra)
        return resp.choices[0].message.content or "", "ok"
    except KeyError:
        return f"{api_key_env} is required for api targets", "auth_error"
    except Exception as exc:  # noqa: BLE001
        t = f"{type(exc).__name__}: {exc}"; low = t.lower()
        if "429" in low or "rate limit" in low:
            return t, "rate_limited"
        if "401" in low or "unauthorized" in low:
            return t, "auth_error"
        if any(k in low for k in ("403", "moderation", "blocked", "forbidden", "content policy")):
            return t, "provider_block"
        return t, "provider_error"


def call_model(target, messages, max_tokens=256, *, reasoning=False, wiring_check=False):
    if target == "fake":
        if not wiring_check:
            raise SystemExit("target 'fake' is only for --wiring-check / smoke (never evidence)")
        return "WIRING_CHECK_FAKE_OUTPUT", "smoke_only"
    if target.startswith("api:"):
        return call_api(messages, target[4:], max_tokens, reasoning=reasoning)
    raise SystemExit("target must be fake | api:<model>")
