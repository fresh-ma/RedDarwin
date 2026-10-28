#!/usr/bin/env python3
"""Path/env plumbing + OpenAI-compatible target client for ArtPrompt.

The target (and the LLM masker / GPT-Judge, which reuse ``call_api``) reach their
model through this OpenAI-compatible client. The method-local ``.env`` is resolved
FIRST (walking up as fallback) so the unit runs self-contained without polluting a
shared repo-root env. All path constants (``METHOD_DIR``/``DEFAULT_DATASET``/...) are
computed once here and imported by the sibling modules.
"""
from __future__ import annotations

import os
from pathlib import Path


def _repo_root(start: Path) -> Path:
    # Walk up to the project root holding the shared `.env` (XSkillForge global env).
    # A method-local `.env` (if present) still wins; otherwise the global one is found
    # by walking up. `.codex` kept for backward compatibility with xsafebench layout.
    for p in [start, *start.parents]:
        if (p / ".codex").exists() or (p / ".env").exists():
            return p
    return start.parents[min(2, len(start.parents) - 1)]


ROOT = _repo_root(Path(__file__).resolve().parent)
METHOD_DIR = Path(__file__).resolve().parent.parent  # the artprompt/ method folder (self-contained, portable)
PAPER_DIR = METHOD_DIR.parent  # the paper unit folder, wherever it currently lives
CODE_DIR = METHOD_DIR  # legacy code/ was merged into the method folder at collect time
DEFAULT_DATASET = METHOD_DIR / "data" / "harmful_behaviors_custom.csv"
PROJECT_ENV = ROOT / ".env"


def repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            os.environ[key] = value


def call_fake(messages: list[dict[str, str]], max_tokens: int) -> tuple[str, str]:
    del messages, max_tokens
    return "I cannot help with unsafe requests, but I can discuss safety testing.", "ok"


def call_api(messages: list[dict[str, str]], model: str, max_tokens: int, base_url: str, api_key_env: str) -> tuple[str, str]:
    try:
        from openai import OpenAI

        load_env_file(PROJECT_ENV)
        client = OpenAI(base_url=base_url, api_key=os.environ[api_key_env])
        response = client.chat.completions.create(
            model=model, messages=messages, temperature=0, max_tokens=max_tokens,
        )
        return response.choices[0].message.content or "", "ok"
    except KeyError:
        return f"{api_key_env} is required for api targets", "auth_error"
    except Exception as exc:  # noqa: BLE001
        text = f"{type(exc).__name__}: {exc}"
        lowered = text.lower()
        if "429" in lowered or "rate limit" in lowered:
            return text, "rate_limited"
        if "401" in lowered or "unauthorized" in lowered:
            return text, "auth_error"
        if any(t in lowered for t in ("403", "moderation", "blocked", "forbidden", "content policy")):
            return text, "provider_block"
        return text, "provider_error"
