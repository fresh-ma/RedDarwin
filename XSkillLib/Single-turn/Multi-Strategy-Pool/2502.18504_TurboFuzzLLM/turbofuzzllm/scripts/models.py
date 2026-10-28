#!/usr/bin/env python3
"""Model client + method-local .env loader + path/config constants for TurboFuzzLLM.

Every model role (target / judge / mutator) reaches OpenRouter through
`OpenRouterClient.chat`. `load_dotenv` walks up from the method dir through
every ancestor (incl. the global XSkillForge/.env) and loads each `.env` it
finds — first value wins, cwd `.env` last. `normalize_model` strips the `api:` prefix while
blocking commercial/GPT-family ids. The paper/method identifiers and result
paths live here too so `attack.py` and sibling scripts share one source.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PAPER_ID = "2502.18504_turbofuzzllm-jailbreak-templates"
METHOD_ID = "turbofuzzllm"
SCRIPT_DIR = Path(__file__).resolve().parent
METHOD_DIR = SCRIPT_DIR.parent
PAPER_DIR = METHOD_DIR.parent
DATA_DIR = SCRIPT_DIR / "data"
RESULT_DIR = METHOD_DIR / "results"

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



@dataclass
class ApiResult:
    text: str
    finish_reason: str | None
    error: str | None = None
    raw_model: str | None = None



def _loads_llm_json(text: str) -> Any:
    # Tolerant JSON parse: try the raw text, then strip ```json fences and grab
    # the outermost {...}/[...] block; re-raise the original error if both fail.
    try:
        return json.loads(text)
    except json.JSONDecodeError as original:
        unfenced = re.sub(r"```(?:json)?", "", text)
        match = re.search(r"\{.*\}|\[.*\]", unfenced, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        raise original



class OpenRouterClient:
    def __init__(
        self,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout: int,
        sleep_seconds: float,
    ) -> None:
        self.model = normalize_model(model)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.sleep_seconds = sleep_seconds
        self.api_key = os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required for api:* model runs")

    def chat(self, messages: list[dict[str, str]], comment: str) -> ApiResult:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://local.agentic-carlini.invalid",
                "X-Title": "AgenticCarlini TurboFuzzLLM reproduction",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = _loads_llm_json(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return ApiResult("", None, f"HTTP {exc.code} during {comment}: {body[:500]}")
        except Exception as exc:  # noqa: BLE001
            return ApiResult("", None, f"{type(exc).__name__} during {comment}: {exc}")
        if self.sleep_seconds > 0:
            time.sleep(self.sleep_seconds)

        choices = data.get("choices") or []
        if not choices:
            return ApiResult("", None, f"empty choices during {comment}", data.get("model"))
        choice = choices[0]
        content = choice.get("message", {}).get("content") or ""
        return ApiResult(content, choice.get("finish_reason"), None, data.get("model"))



def load_dotenv() -> None:
    # Walk up from the method dir (XSkillLib convention): load every .env found
    # in any ancestor (incl. the global XSkillForge/.env) plus the cwd .env.
    # First value wins, so the closest .env overrides higher-level ones.
    candidates = [parent / ".env" for parent in (METHOD_DIR, *METHOD_DIR.parents)]
    candidates.append(Path.cwd() / ".env")
    for path in candidates:
        if not path.exists():
            continue
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
            raise ValueError(f"blocked commercial/GPT-family model id: {model}")
    return model
