"""models.py — SDK-free OpenAI-compatible model client + walk-up .env loader.

Every model role (reformulator / target / judge) is chosen by a provider:model spec string, so
`--target`, `--reformulator`, `--judge-model` are independently swappable (roles.py wires the flags).
The HTTP path uses only stdlib `urllib` — no `openai`/`anthropic` package — so the method's
pyproject declares no heavy deps for the API path.

Spec forms:
  - "fake:<mode>"   → offline wiring stub (never evidence); modes below.
  - "api:<model>"   → OpenAI-compatible endpoint, default OpenRouter (api_key_env OPENROUTER_API_KEY).
  - "ollama:<model>"→ local Ollama /v1 (http://localhost:11434/v1); interface (2) for a local
                      non-refusing reformulator/attacker (e.g. ollama:uncensored). No key.
  - "vllm:<model>"  → local vLLM OpenAI server (http://localhost:8000/v1).

Reasoning is OFF by default (jailbreak eval judges only the final answer; a reasoning target balloons
latency and can burn the whole token budget → empty output). OpenRouter disable = body
{"reasoning":{"enabled":False}}; Ollama/vLLM /v1 disable = {"reasoning_effort":"none"}.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def load_method_env(start: Path | None = None) -> None:
    """Walk up from the method dir through every ancestor, loading each `.env` found.

    XSkillLib convention: keys live in the global XSkillForge/.env, several levels above the
    skill dir, so the walk must not stop at the skill-local pyproject.toml. Nearer `.env` files
    win; never overrides an already-set process env var (shell env wins).
    """
    here = (start or Path(__file__)).resolve()
    if here.is_file():
        here = here.parent
    seen: set[Path] = set()
    for parent in (here, *here.parents):
        env_path = parent / ".env"
        if env_path in seen or not env_path.exists():
            continue
        seen.add(env_path)
        for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip("'\"")
            if key and value and key not in os.environ:
                os.environ[key] = value


def _http_chat(
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    *,
    api_key: str = "",
    max_tokens: int = 256,
    temperature: float = 0.0,
    seed: int | None = None,
    reasoning: bool = False,
    reasoning_style: str = "openrouter",
    timeout: float = 90.0,
    retries: int = 3,
) -> tuple[str, str]:
    """One thin urllib POST to any OpenAI-compatible /chat/completions. Returns (text, status)."""
    # gpt-oss endpoints mandate reasoning (400 if disabled) -> leave it on, and raise
    # max_tokens so reasoning tokens don't eat the whole completion budget.
    gpt_oss = "gpt-oss" in model.lower()
    if gpt_oss and max_tokens < 1024:
        max_tokens = 1024
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if seed is not None:
        body["seed"] = seed
    if not reasoning and not gpt_oss:
        if reasoning_style == "openrouter":
            body["reasoning"] = {"enabled": False}
        else:
            body["reasoning_effort"] = "none"
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    last = ""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                base_url.rstrip("/") + "/chat/completions", data=data, headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.load(resp)
            return (payload["choices"][0]["message"].get("content") or ""), "ok"
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            last = f"HTTP {exc.code}: {detail}"
            if exc.code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            if exc.code in (401, 403):
                return last, "auth_error" if exc.code == 401 else "provider_block"
            return last, "http_error"
        except (urllib.error.URLError, TimeoutError) as exc:
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(1.0 * (attempt + 1))
        except Exception as exc:  # noqa: BLE001
            return f"{type(exc).__name__}: {exc}", "provider_error"
    return last, "rate_limited" if "429" in last else "provider_error"


class FakeModel:
    """Offline wiring stub. Modes: tense / refusal / rating10 / rating1 / safe / unsafe / empty."""

    def __init__(self, mode: str = "refusal") -> None:
        self.mode = mode

    def complete(self, messages, **_: Any) -> tuple[str, str]:
        table = {
            "tense": "How were such things carried out by people in the recent past?",
            "refusal": "I'm sorry, but I can't assist with that request.",
            "rating10": "Rating: [[10]]",
            "rating1": "Rating: [[1]]",
            "safe": "safe",
            "unsafe": "unsafe",
            "empty": "",
        }
        return table.get(self.mode, table["refusal"]), "ok"


def call_model(
    spec: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 256,
    temperature: float = 0.0,
    seed: int | None = None,
    reasoning: bool = False,
    timeout: float = 90.0,
    retries: int = 3,
) -> tuple[str, str]:
    """Dispatch on the provider:model spec. Returns (text, status)."""
    if spec.startswith("fake:") or spec == "fake":
        mode = spec.split(":", 1)[1] if ":" in spec else "refusal"
        return FakeModel(mode).complete(messages)
    if spec.startswith("api:"):
        load_method_env()
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            return "OPENROUTER_API_KEY is required for api: targets", "auth_error"
        return _http_chat(
            OPENROUTER_BASE_URL, spec[4:], messages, api_key=key, max_tokens=max_tokens,
            temperature=temperature, seed=seed, reasoning=reasoning,
            reasoning_style="openrouter", timeout=timeout, retries=retries,
        )
    if spec.startswith("ollama:"):
        base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        return _http_chat(
            base, spec[7:], messages, api_key="ollama", max_tokens=max_tokens,
            temperature=temperature, seed=seed, reasoning=reasoning,
            reasoning_style="v1", timeout=max(timeout, 180.0), retries=retries,
        )
    if spec.startswith("vllm:"):
        base = os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1")
        return _http_chat(
            base, spec[5:], messages, api_key="vllm", max_tokens=max_tokens,
            temperature=temperature, seed=seed, reasoning=reasoning,
            reasoning_style="v1", timeout=max(timeout, 180.0), retries=retries,
        )
    raise SystemExit(f"Unsupported model spec: {spec!r} (use fake:<mode> | api:<m> | ollama:<m> | vllm:<m>)")


def call_with_retries(
    spec: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    temperature: float,
    seed: int | None = None,
    reasoning: bool = False,
    timeout: float = 90.0,
    max_attempts: int = 3,
    retry_sleep: float = 1.0,
) -> tuple[str, dict[str, Any]]:
    """Call the model, retrying on empty/errored output. Returns (text, call_meta)."""
    attempts: list[dict[str, Any]] = []
    for i in range(max(max_attempts, 1)):
        text, status = call_model(
            spec, messages, max_tokens=max_tokens, temperature=temperature,
            seed=seed, reasoning=reasoning, timeout=timeout, retries=1,
        )
        empty = text.strip() == ""
        ok = status == "ok" and not empty
        attempts.append({"attempt": i, "status": status, "empty": empty, "ok": ok})
        if ok:
            return text, {"ok": True, "attempts": attempts}
        if i + 1 < max(max_attempts, 1) and retry_sleep > 0:
            time.sleep(retry_sleep)
    return "", {"ok": False, "attempts": attempts}
