#!/usr/bin/env python3
"""OpenAI-compatible chat client + walk-up .env loader + repo-path plumbing for CoA.

Every CoA role (attacker / target / judge) reaches its model through `call_chat`,
an OpenAI-compatible chat completion with per-role temperature/max_tokens and honest
provider-error status codes. `_repo_root` walks up from this file to the ancestor
holding the shared `.env` (XSkillLib convention: the global XSkillForge/.env), and
`load_env_file` loads it — no per-skill `.env`, no manual `export`.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


def _repo_root(start: Path) -> Path:
    """Walk up to the project root holding the shared `.env` (XSkillLib convention:
    the global XSkillForge/.env is found from ANY ancestor directory). `.codex`
    kept for backward compatibility with the xsafebench layout. Never raises
    IndexError on a shallow path."""
    for p in [start, *start.parents]:
        if (p / ".codex").exists() or (p / ".env").exists():
            return p
    return start.parents[min(2, len(start.parents) - 1)]


ROOT = _repo_root(Path(__file__).resolve().parent)
METHOD_DIR = Path(__file__).resolve().parents[1]
PROJECT_ENV = ROOT / ".env"


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


# ---------------------------------------------------------------------------
# Provider routing: model strings carry a scheme so the same call site works
# both hosted and local.
#   api:<model>     -> OpenAI-compatible gateway (OpenRouter), needs an API key
#   ollama:<model>  -> local Ollama daemon, no API key, for the uncensored attacker
#   <model>         -> treated as api:<model>
# ---------------------------------------------------------------------------
def split_model(model: str | None) -> tuple[str, str]:
    value = (model or "").strip()
    if value.startswith("ollama:"):
        return "ollama", value[len("ollama:"):].strip()
    if value.startswith("api:"):
        return "api", value[len("api:"):].strip()
    return "api", value


def ollama_base() -> str:
    return os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")


def ollama_available(model: str | None = None) -> bool:
    """True if a local Ollama daemon answers, and (if given) has `model` pulled."""
    try:
        with urllib.request.urlopen(f"{ollama_base()}/api/tags", timeout=3) as response:
            tags = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return False
    if not model:
        return True
    have = {str(m.get("name", "")).split(":")[0] for m in tags.get("models", [])}
    return model.split(":")[0] in have


def _ollama_chat(model: str, messages: list[dict[str, str]], *, temperature: float, max_tokens: int) -> str:
    # A thinking-class uncensored model returns EMPTY content when token-capped, so a
    # local role is never hard-capped (uncensored-llm skill): num_predict=-1 runs to a
    # natural stop, and think=false keeps the final text clean.
    num_predict = max_tokens if (max_tokens and max_tokens >= 1024) else -1
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": temperature, "num_predict": num_predict},
    }
    request = urllib.request.Request(
        f"{ollama_base()}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                data = json.loads(response.read().decode("utf-8"))
                return str((data.get("message") or {}).get("content") or "")
        except (OSError, ValueError) as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    raise last_exc or RuntimeError("unreachable")


def _role_sampling(args: argparse.Namespace, role: str) -> tuple[float, int]:
    if role == "attacker":
        return args.attacker_temperature, args.attacker_max_tokens
    if role == "judge":
        return 0.0, 400
    return args.target_temperature, args.target_max_tokens


def successful_chat_result(content: str | None) -> tuple[str, str]:
    text = content or ""
    return (text, "ok") if text.strip() else ("", "empty_response")


def call_chat(messages: list[dict[str, str]], model_ref: str, args: argparse.Namespace, *, role: str) -> tuple[str, str]:
    if model_ref == "fake":
        if not args.wiring_check:
            raise SystemExit("fake model is wiring-only; pass --wiring-check and do not treat it as Code evidence")
        if role == "attacker":
            n = max(1, getattr(args, "max_rounds", 2))
            rounds = [{"prompt": f"Wiring-stub escalating prompt {i}: connect the broad background to the requested topic."} for i in range(1, n + 1)]
            return json.dumps({"rounds": rounds}), "ok"
        if role == "judge":
            return json.dumps({"Explanation": "wiring stub", "Rating": 1}), "ok"
        return "I cannot help with unsafe requests, but I can discuss evaluation methodology.", "ok"
    provider, model = split_model(model_ref)
    if not model:
        raise SystemExit("models must be fake, api:<model>, or ollama:<model>")
    if provider == "ollama":
        temperature, max_tokens = _role_sampling(args, role)
        try:
            content = _ollama_chat(model, messages, temperature=temperature, max_tokens=max_tokens)
            return successful_chat_result(content)
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}", "provider_error"
    try:
        from openai import OpenAI
        client = OpenAI(base_url=args.base_url, api_key=os.environ[args.api_key_env])
        temperature, max_tokens = _role_sampling(args, role)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return successful_chat_result(response.choices[0].message.content)
    except KeyError:
        return f"{args.api_key_env} is required for api targets", "auth_error"
    except Exception as exc:
        text = f"{type(exc).__name__}: {exc}"
        lowered = text.lower()
        if "429" in lowered or "rate limit" in lowered:
            return text, "rate_limited"
        if "401" in lowered or "unauthorized" in lowered:
            return text, "auth_error"
        if any(token in lowered for token in ("403", "moderation", "blocked", "forbidden", "content policy")):
            return text, "provider_block"
        return text, "provider_error"
