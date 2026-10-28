#!/usr/bin/env python3
"""OpenAI-compatible chat client + method-local .env / path plumbing.

Every model role (target, judge, and the api-translator path) reaches its model
through `api_chat`, an OpenAI-compatible `POST /chat/completions` call with bounded
retries. Keys are read from the nearest `.env` (this method dir first, walking up
as fallback), so the unit runs self-contained. Also holds the small path/CSV
helpers shared across the sibling modules.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


def project_root() -> Path:
    # Walk up to the nearest ancestor holding a `.env` (XSkillLib convention:
    # one shared venv + one global XSkillForge/.env, no per-skill env). The
    # `.codex` marker is kept for backward compatibility with the xsafebench
    # layout; `.env` alone is enough, so the skill works anywhere under the
    # XSkillForge checkout.
    for parent in Path(__file__).resolve().parents:
        if (parent / ".env").exists() or (parent / ".codex").exists():
            return parent
    return Path.cwd()


def display_path(path: Path) -> str:
    root = project_root()
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def load_project_env() -> None:
    preexisting = set(os.environ)
    candidates = [
        project_root() / ".env",
        Path(__file__).resolve().parents[1] / ".env",
    ]
    for env_path in candidates:
        if not env_path.exists():
            continue
        for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and value and key not in preexisting:
                os.environ[key] = value


def resolve_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if path.is_absolute() or path.exists():
        return path
    rooted = project_root() / path
    return rooted if rooted.exists() else path


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        return list(csv.DictReader(handle))


def api_model_name(value: str) -> str:
    kind, _, model = value.partition(":")
    return model if kind == "api" and model else value


def api_chat(
    messages: list[dict[str, str]],
    model: str,
    args: argparse.Namespace,
    *,
    base_url: str | None = None,
    api_key_env: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> tuple[str, str]:
    load_project_env()
    key_env = api_key_env or args.api_key_env
    url = base_url or args.base_url
    api_key = os.environ.get(key_env)
    if not api_key:
        return f"{key_env} is required for api targets", "auth_error"

    payload = {
        "model": model,
        "messages": messages,
        "temperature": args.temperature if temperature is None else temperature,
        "top_p": args.top_p,
        "max_tokens": args.max_tokens if max_tokens is None else max_tokens,
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if "openrouter.ai" in url:
        headers["HTTP-Referer"] = "https://github.com/oscarwu/AgenticCarlini"
        headers["X-Title"] = "AgenticCarlini paper-local Code"
    retries = getattr(args, "max_retries", 4)
    last_err = "provider_error"
    last_detail = ""
    for attempt in range(retries + 1):
        request = urllib.request.Request(
            f"{url.rstrip('/')}/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=args.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            if exc.code in {401, 403}:
                return f"HTTP {exc.code}: {detail}", "auth_error"
            # 429 (rate limit) and 5xx are transient upstream errors -> backoff + retry.
            last_err, last_detail = "provider_error", f"HTTP {exc.code}: {detail}"
            if exc.code in {429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(min(2.0 * (2 ** attempt), 30.0))
                continue
            return last_detail, "provider_error"
        except Exception as exc:
            last_err, last_detail = "provider_error", f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(min(2.0 * (2 ** attempt), 30.0))
                continue
            return last_detail, "provider_error"
    else:
        return last_detail or "exhausted_retries", last_err
    try:
        return data["choices"][0]["message"].get("content") or "", "ok"
    except Exception:
        return json.dumps(data, ensure_ascii=False)[:500], "provider_error"


def chat_messages(text: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": text}]


def text_messages(messages: list[dict[str, str]]) -> str:
    return "\n\n".join(f"{m['role'].upper()}:\n{m['content']}" for m in messages)
