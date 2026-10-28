#!/usr/bin/env python3
"""Model client + method-local env loader for Adversarial Poetry.

Every role (poetic-transform / target / judge) reaches its OpenRouter model
through `call_api`. Keys are read from the nearest `.env` found by walking up
from this file through every ancestor directory (XSkillLib convention: the
shared XSkillForge repo-root `.env`), so the unit runs self-contained — no
per-skill `.env`, no manual `export`. NO GPU — OpenRouter only.
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# project env + repo root (XSkillLib convention: walk up to the global .env)
# ---------------------------------------------------------------------------


def project_root(start: Path | None = None) -> Path:
    """Nearest ancestor directory holding a `.env` (the shared XSkillForge root)."""
    here = (start or Path(__file__)).resolve()
    for c in (here, *here.parents):
        if (c / ".env").exists():
            return c
    return here.parent


def load_project_env(start: Path | None = None) -> None:
    """Load the first `.env` found walking up through all ancestor directories."""
    here = (start or Path(__file__)).resolve()
    env_path = next((c / ".env" for c in (here, *here.parents) if (c / ".env").exists()), None)
    if env_path is None:
        return
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip():
            os.environ[k.strip()] = v.strip().strip("'\"")


# ---------------------------------------------------------------------------
# model call (copy-reference: functions/call_model). NO GPU, OpenRouter only.
# ---------------------------------------------------------------------------
def call_api(messages: list[dict], model: str, max_tokens: int = 512,
             temperature: float = 0.0) -> tuple[str, str]:
    try:
        load_project_env()
        from openai import OpenAI
        client = OpenAI(base_url="https://openrouter.ai/api/v1",
                        api_key=os.environ["OPENROUTER_API_KEY"],
                        timeout=30,
                        max_retries=0)
        resp = client.chat.completions.create(
            model=model, messages=messages, temperature=temperature, max_tokens=max_tokens)
        msg = resp.choices[0].message
        text = msg.content or ""
        # reasoning models (gpt-oss, r1, kimi-thinking) may put answer in reasoning field
        if not text.strip():
            text = (getattr(msg, "reasoning", None)
                    or (msg.model_extra or {}).get("reasoning")
                    or (msg.model_extra or {}).get("reasoning_content") or "")
        return (text or ""), "ok"
    except KeyError:
        return "OPENROUTER_API_KEY required", "auth_error"
    except Exception as exc:  # noqa: BLE001
        t = f"{type(exc).__name__}: {exc}"
        low = t.lower()
        if "429" in low or "rate limit" in low:
            return t, "rate_limited"
        if "401" in low or "unauthorized" in low:
            return t, "auth_error"
        if any(k in low for k in ("403", "moderation", "blocked", "forbidden", "content policy")):
            return t, "provider_block"
        return t, "provider_error"
