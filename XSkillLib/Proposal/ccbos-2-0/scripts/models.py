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


# Auxiliary-LLM policy (AGENTS.md): every non-victim role runs on
# deepseek/deepseek-v4-flash; if that model refuses the request, the same call is
# retried once on deepseek/deepseek-v4-flash. The victim (--target) never falls back.
AUX_PRIMARY_MODEL = "deepseek/deepseek-v4-flash"
AUX_FALLBACK_MODEL = "deepseek/deepseek-v4-flash"

# Markers that an auxiliary call was refused rather than answered. Covers
# English refusals and the Chinese refusals qwen emits against classical-Chinese
# attacker prompts. Kept deliberately short: only unambiguous refusal openers.
AUX_REFUSAL_MARKERS = (
    "i'm sorry", "i am sorry", "i cannot", "i can't", "cannot assist",
    "cannot help", "can't assist", "can't help", "cannot fulfill",
    "unable to comply", "i must refuse",
    "抱歉", "对不起", "无法完成", "不能帮助", "无法提供", "我无法",
)


def is_refusal(result: "ApiResult") -> bool:
    """True when an auxiliary call failed outright or the model refused."""
    if result.error is not None:
        return True
    text = result.text.strip()
    if not text:
        return True
    head = text[:400].lower()
    return any(marker in head for marker in AUX_REFUSAL_MARKERS)


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
    for pattern in BLOCKED_MODEL_PATTERNS:
        if pattern in lowered:
            # gpt-oss is open-weights, only hosted under the openai/ namespace —
            # exempt it from the openai//gpt-family blocks (other families stay blocked).
            if "gpt-oss" in lowered and pattern in ("openai/", "gpt-", "gpt_", "/gpt"):
                continue
            # gpt-5.6-luna is a fixed member of the XSkillForge victim panel; the
            # harness drives it through --target only, never through attacker/
            # translator/judge (pinned to the auxiliary deepseek/deepseek-v4-flash).
            if "gpt-5.6-luna" in lowered:
                continue
            raise ValueError(f"blocked commercial/GPT-family model id: {model}")
    return model


def slug_model(model: str) -> str:
    return normalize_model(model).replace("/", "-").replace(":", "-")


class OpenRouterClient:
    def __init__(self, model: str, temperature: float, max_tokens: int, timeout: int, sleep: float,
                 reasoning: bool = True, fallback_model: str | None = None) -> None:
        self.model = normalize_model(model)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.sleep = sleep
        # Judges/attacker/translator keep reasoning ON (their prompts want CoT); only the
        # target answer call turns it OFF for speed + to avoid empty-content reasoning loops.
        self.reasoning = reasoning
        # Auxiliary roles only: retry a refused call once on this model.
        self.fallback_model = normalize_model(fallback_model) if fallback_model else None
        self.api_key = os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required for api:* model runs")

    def chat(self, messages: list[dict[str, str]], comment: str) -> ApiResult:
        result = self._chat_with_model(self.model, messages, comment)
        if self.fallback_model and self.model == AUX_PRIMARY_MODEL and is_refusal(result):
            fallback = self._chat_with_model(self.fallback_model, messages, f"{comment}:fallback")
            if not is_refusal(fallback):
                return fallback
        return result

    def _chat_with_model(self, model: str, messages: list[dict[str, str]], comment: str) -> ApiResult:
        # Infra repair (2026-08-17): the urllib/HTTP-1.1 transport became
        # unusable against OpenRouter's edge mid-cycle — Cloudflare 403/1010 on
        # the default UA, then intermittent upstream 404s on any non-trivial
        # payload, while httpx-based clients (unified judge) and curl stayed
        # healthy. Route through the openai package (httpx, HTTP/2) with an
        # explicit provider-inference extra header disabled path unchanged:
        # same payload fields, same resample-on-empty policy.
        from openai import OpenAI  # local import: stdlib-only for inspect paths

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        extra: dict[str, Any] = {}
        if not self.reasoning and "gpt-oss" not in model.lower():
            payload["reasoning"] = {"enabled": False}
        elif "gpt-oss" in model.lower() and self.max_tokens < 1024:
            # gpt-oss mandates reasoning; its reasoning tokens share the max_tokens
            # budget, so guarantee headroom for the visible answer.
            payload["max_tokens"] = 1024
        reasoning_field = payload.pop("reasoning", None)
        if reasoning_field is not None:
            extra["reasoning"] = reasoning_field
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
            default_headers={
                "HTTP-Referer": "https://local.agentic-carlini.invalid",
                "X-Title": "AgenticCarlini CC-BOS reproduction",
            },
            timeout=self.timeout,
            max_retries=0,
        )
        last: ApiResult | None = None
        for attempt in range(3):
            try:
                msg = client.chat.completions.create(
                    extra_body=extra or None,
                    **payload,
                )
            except Exception as exc:  # noqa: BLE001
                last = ApiResult("", None, f"{type(exc).__name__} during {comment}: {exc}")
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                return last
            if self.sleep > 0:
                time.sleep(self.sleep)
            choices = getattr(msg, "choices", None) or []
            if not choices:
                last = ApiResult("", None, f"empty choices during {comment}", getattr(msg, "model", None))
                if attempt < 2:
                    time.sleep(1.0)
                    continue
                return last
            choice = choices[0]
            content = choice.message.content or ""
            last = ApiResult(content, choice.finish_reason, None, getattr(msg, "model", None))
            if content.strip() or attempt == 2:
                return last
            time.sleep(1.0)  # empty content -> resample
        return last if last is not None else ApiResult("", None, f"no draw during {comment}")
