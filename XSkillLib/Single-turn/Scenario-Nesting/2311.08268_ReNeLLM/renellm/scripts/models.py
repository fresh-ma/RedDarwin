#!/usr/bin/env python3
"""OpenAI-compatible model client + .env / path plumbing for ReNeLLM.

Every model role (rewrite / target / judge) reaches its endpoint through
`api_chat`, an OpenAI-compatible `POST /chat/completions` with bounded retries.
Keys load from the shared global `.env`, found by walking up from this file
(XSkillLib convention: one `XSkillForge/.env`, no per-skill `.env`). Path
helpers resolve dataset/result paths relative to that root.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


def project_root() -> Path:
    # Walk up to the project root holding the shared `.env` (XSkillForge global
    # env). A method-local `.env` (if present) still wins since it is found
    # first. `.codex` kept for backward compatibility with the xsafebench layout.
    for parent in Path(__file__).resolve().parents:
        if (parent / ".env").exists() or ((parent / "data").exists() and (parent / ".codex").exists()):
            return parent
    return Path.cwd()


def display_path(path: Path) -> str:
    root = project_root()
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def resolve_path(path: Path) -> Path:
    path = Path(path).expanduser()
    if path.is_absolute() or path.exists():
        return path
    rooted = project_root() / path
    return rooted if rooted.exists() else path


def load_project_env() -> None:
    env_path = project_root() / ".env"
    if not env_path.exists():
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


def parse_api_model(model_spec: str) -> str:
    kind, sep, model = model_spec.partition(":")
    if kind == "fake" and not sep:
        return "fake"
    if kind == "api" and model:
        return model
    raise SystemExit(f"model spec must be fake or api:<model>, got: {model_spec}")


def model_is_fake(model_spec: str) -> bool:
    return parse_api_model(model_spec) == "fake"


def api_chat(
    model_spec: str,
    messages: list[dict[str, str]],
    *,
    base_url: str,
    api_key_env: str,
    temperature: float,
    max_tokens: int,
    wiring_check: bool,
    fake_text: str,
    timeout: float,
    max_retries: int = 4,
    backoff_base: float = 2.0,
) -> tuple[str, str]:
    model = parse_api_model(model_spec)
    if model == "fake":
        if not wiring_check:
            raise SystemExit("fake model calls require --wiring-check and are not Code evidence")
        return fake_text, "ok"
    load_project_env()
    api_key = os.environ.get(api_key_env)
    if not api_key:
        return f"{api_key_env} is required for api model calls", "auth_error"

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if "openrouter.ai" in base_url:
        headers["HTTP-Referer"] = "https://github.com/oscarwu/AgenticCarlini"
        headers["X-Title"] = "AgenticCarlini paper-local Code"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    # Retry transient failures (429 rate-limit, 5xx, timeouts, transport errors)
    # with exponential backoff so a single hiccup does not drop a whole case.
    # Hard auth/policy errors (401/403) and 4xx other than 429 are not retried.
    last_error: tuple[str, str] = ("no attempt made", "provider_error")
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            if exc.code in {401, 403}:
                return f"HTTP {exc.code}: {detail}", "auth_error"
            retriable = exc.code == 429 or 500 <= exc.code < 600
            last_error = (f"HTTP {exc.code}: {detail}", "provider_error")
            if not retriable or attempt == max_retries:
                return last_error
        except Exception as exc:  # transport/timeout errors are transient
            last_error = (f"{type(exc).__name__}: {exc}", "provider_error")
            if attempt == max_retries:
                return last_error
        else:
            try:
                return data["choices"][0]["message"].get("content") or "", "ok"
            except Exception:
                return json.dumps(data, ensure_ascii=False)[:500], "provider_error"
        time.sleep(backoff_base ** attempt)
    return last_error
