"""models — OpenRouter chat client + unit-local .env loader + judge cache.

Copy-reference plumbing (project rule: self-contained, no shared import). One sync
`chat()` entry point returning (text, status); status="ok" on success else an honest
tag. Target reasoning is OFF by default (jailbreak eval judges only the final answer;
reasoning balloons latency + causes the empty-output loop).
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

METHOD_DIR = Path(__file__).resolve().parents[1]


def load_env() -> None:
    """Load the UNIT-local .env first, then walk up as fallback. setdefault so a real
    shell env var always wins."""
    here = Path(__file__).resolve()
    seen: set[Path] = set()
    for parent in (METHOD_DIR, *here.parents):
        env_path = parent / ".env"
        if env_path in seen or not env_path.exists():
            continue
        seen.add(env_path)
        for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def chat(
    messages: list[dict[str, str]],
    model: str,
    *,
    max_tokens: int = 1024,
    temperature: float = 0.0,
    reasoning: bool = False,
    base_url: str = "https://openrouter.ai/api/v1",
    api_key_env: str = "OPENROUTER_API_KEY",
) -> tuple[str, str]:
    """Send chat messages to an OpenRouter model. Returns (text, status)."""
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("openai package is required (uv sync)") from exc
    api_key = os.environ.get(api_key_env)
    if not api_key:
        return f"{api_key_env} is required", "auth_error"
    # gpt-oss endpoints mandate reasoning (400 if disabled) -> leave it on.
    extra = None if (reasoning or "gpt-oss" in model.lower()) else {"reasoning": {"enabled": False}}
    try:
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=300, max_retries=4)
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra,
        )
        text = resp.choices[0].message.content or ""
        return text, ("ok" if text.strip() else "ok_but_empty")
    except Exception as exc:  # noqa: BLE001
        tag = f"{type(exc).__name__}: {exc}"
        low = tag.lower()
        if "429" in low or "rate limit" in low:
            return tag, "rate_limited"
        if "401" in low or "unauthorized" in low:
            return tag, "auth_error"
        if any(k in low for k in ("403", "moderation", "blocked", "forbidden", "content policy")):
            return tag, "provider_block"
        return tag, "provider_error"


def spec_model(spec: str) -> str:
    """Split an `api:<model>` spec into the bare model id (no other backends here)."""
    prefix, _, model = spec.partition(":")
    if prefix != "api" or not model:
        raise SystemExit(f"spec must be 'api:<openrouter-model-id>', got {spec!r}")
    return model


class JudgeCache:
    """Tiny thread-safe on-disk JSON cache for judge verdicts, keyed by a stable hash
    of (kind, judge_model, request, output)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._data = {}

    @staticmethod
    def key(kind: str, judge_model: str, request: str, output: str) -> str:
        blob = f"{kind}\x00{judge_model}\x00{request}\x00{output}".encode("utf-8", "replace")
        return hashlib.sha1(blob).hexdigest()

    def get(self, key: str) -> Any | None:
        with self._lock:
            return self._data.get(key)

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value

    def flush(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
