#!/usr/bin/env python3
"""OpenRouter chat client + unit-local .env loader for CC-BOS."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
METHOD_DIR = SCRIPT_DIR.parent

# GPT / commercial-family target ids are blocked (project policy: open targets only).
BLOCKED_MODEL_PATTERNS = (
    "openai/",
    "anthropic/",
    "google/",
    "gemini",
    "claude",
    "gpt-",
    "gpt_",
    "/gpt",
)

# Formal XSkillForge victim-panel exception.  The shell wrapper still pins all
# auxiliary roles (attacker/translator/judge) to Qwen; this exception only
# makes the benchmark's explicitly selected Luna target routable.
FORMAL_VICTIM_EXCEPTIONS = {"openai/gpt-5.6-luna"}


@dataclass
class ApiResult:
    text: str
    finish_reason: str | None
    error: str | None = None
    raw_model: str | None = None


def load_dotenv() -> None:
    """Resolve the unit-local `.env` FIRST, then walk UP as fallback (marker-based)."""
    seen: set[Path] = set()
    candidates: list[Path] = [METHOD_DIR / ".env"]
    cursor = METHOD_DIR
    for _ in range(8):  # walk up to a repo-root .env as fallback
        cursor = cursor.parent
        candidates.append(cursor / ".env")
    candidates.append(Path.cwd() / ".env")
    for path in candidates:
        try:
            path = path.resolve()
        except OSError:
            continue
        if path in seen or not path.exists():
            continue
        seen.add(path)
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def normalize_model(model: str) -> str:
    lowered = model.lower()
    if model.startswith("api:"):
        model = model[4:]
        lowered = model.lower()
    if lowered in FORMAL_VICTIM_EXCEPTIONS:
        return model
    for pattern in BLOCKED_MODEL_PATTERNS:
        if pattern in lowered:
            # gpt-oss is open-weights, only hosted under the openai/ namespace —
            # exempt it from the openai//gpt-family blocks (other families stay blocked).
            if "gpt-oss" in lowered and pattern in ("openai/", "gpt-", "gpt_", "/gpt"):
                continue
            raise ValueError(f"blocked commercial/GPT-family model id: {model}")
    return model


def slug_model(model: str) -> str:
    return normalize_model(model).replace("/", "-").replace(":", "-")


class OpenRouterClient:
    def __init__(self, model: str, temperature: float, max_tokens: int, timeout: int, sleep: float,
                 reasoning: bool = True) -> None:
        self.model = normalize_model(model)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.sleep = sleep
        # Judges/attacker/translator keep reasoning ON (their prompts want CoT); only the
        # target answer call turns it OFF for speed + to avoid empty-content reasoning loops.
        self.reasoning = reasoning
        self.api_key = os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required for api:* model runs")

    def chat(self, messages: list[dict[str, str]], comment: str) -> ApiResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if not self.reasoning and "gpt-oss" not in self.model.lower():
            payload["reasoning"] = {"enabled": False}
        elif "gpt-oss" in self.model.lower() and self.max_tokens < 1024:
            # gpt-oss mandates reasoning; its reasoning tokens share the max_tokens
            # budget, so guarantee headroom for the visible answer.
            payload["max_tokens"] = 1024
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://local.agentic-carlini.invalid",
                "X-Title": "AgenticCarlini CC-BOS reproduction",
            },
            method="POST",
        )
        # Resample on empty content (up to 3 total draws). v4-flash sometimes ignores
        # reasoning:{enabled:false} and burns the whole budget on hidden reasoning ->
        # empty content with finish_reason length/stop; a transient content_filter/error
        # can also blank a draw. A fresh draw usually returns real content, so we resample
        # instead of recording a degenerate empty (rubric: sufficient budget + resample).
        last: ApiResult | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last = ApiResult("", None, f"HTTP {exc.code} during {comment}: {body[:500]}")
                if exc.code in (429, 500, 502, 503, 520, 524) and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                return last
            except Exception as exc:  # noqa: BLE001
                last = ApiResult("", None, f"{type(exc).__name__} during {comment}: {exc}")
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                return last
            if self.sleep > 0:
                time.sleep(self.sleep)
            choices = data.get("choices") or []
            if not choices:
                last = ApiResult("", None, f"empty choices during {comment}", data.get("model"))
                if attempt < 2:
                    time.sleep(1.0)
                    continue
                return last
            choice = choices[0]
            content = choice.get("message", {}).get("content") or ""
            last = ApiResult(content, choice.get("finish_reason"), None, data.get("model"))
            if content.strip() or attempt == 2:
                return last
            time.sleep(1.0)  # empty content -> resample
        return last if last is not None else ApiResult("", None, f"no draw during {comment}")
