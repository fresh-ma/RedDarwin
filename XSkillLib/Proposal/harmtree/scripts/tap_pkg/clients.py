from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from . import source_brief
import json

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

def load_method_env(start: Path) -> None:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        env_path = candidate / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
            if candidate == current:
                return
    load_dotenv(override=False)

@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str

    @classmethod
    def parse(cls, value: str) -> "ModelSpec":
        if ":" not in value:
            return cls("api", value)
        provider, model = value.split(":", 1)
        return cls(provider, model)

class ChatClient:
    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        seed: int | None = None,
        response_format: str | None = None,
        reasoning_effort: str | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> str:
        raise NotImplementedError

class OpenAICompatibleClient(ChatClient):
    def __init__(
        self,
        model: str,
        *,
        api_key_env: str,
        base_url_env: str | None = None,
        timeout: float = 45.0,
    ):
        api_key = os.getenv(api_key_env, "")
        base_url = os.getenv(base_url_env) if base_url_env else None
        if not base_url and "/" in model:
            base_url = OPENROUTER_BASE_URL
            api_key = os.getenv("OPENROUTER_API_KEY", api_key)
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        seed: int | None = None,
        response_format: str | None = None,
        reasoning_effort: str | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if seed is not None:
            kwargs["seed"] = seed
        if response_format is not None:
            kwargs["response_format"] = {"type": response_format}
        if reasoning_effort is not None and reasoning_effort != "":
            kwargs["reasoning_effort"] = reasoning_effort
        if extra_body is not None:
            kwargs["extra_body"] = extra_body
        response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

class MockClient(ChatClient):
    def __init__(self, mode: str):
        self.mode = mode

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        seed: int | None = None,
        response_format: str | None = None,
        reasoning_effort: str | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> str:
        joined = "\n".join(message["content"] for message in messages)
        if self.mode in ('tap_attacker','tap_attacker_plan','tap_attacker_repair'):
            return json.dumps({'improvement':'develop the next open section','prompt':source_brief.fallback('Plan a community garden opening.')})

        if self.mode == "empty":
            return ""
        if self.mode == "refusal":
            return "I'm sorry, but I can't assist with that request."
        if self.mode == "badbot":
            return "Sure, here is a direct answer to the requested objective."
        if self.mode == "tap_evaluator":
            if "Give a YES or NO response" in joined:
                return "Response: [[YES]]"
            return "Rating: [[1]]"
        if self.mode == "tap_evaluator10":
            if "Give a YES or NO response" in joined:
                return "Response: [[YES]]"
            return "Rating: [[10]]"
        return messages[-1]["content"][:max_tokens]

def build_client(
    spec_value: str,
    *,
    api_key_env: str = "OPENAI_API_KEY",
    base_url_env: str | None = "OPENAI_BASE_URL",
    timeout: float = 45.0,
) -> ChatClient:
    spec = ModelSpec.parse(spec_value)
    if spec.provider in {"api", "openai"}:
        return OpenAICompatibleClient(spec.model, api_key_env=api_key_env, base_url_env=base_url_env, timeout=timeout)
    if spec.provider == "mock":
        return MockClient(spec.model)
    raise ValueError(f"Unsupported model spec: {spec_value}")

def complete_with_retries(
    client: ChatClient,
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    temperature: float,
    seed: int | None = None,
    response_format: str | None = None,
    reasoning_effort: str | None = None,
    extra_body: dict[str, Any] | None = None,
    max_attempts: int = 3,
    retry_sleep: float = 1.0,
) -> tuple[str, dict[str, Any]]:
    attempts = []
    for attempt_index in range(max(max_attempts, 1)):
        try:
            if reasoning_effort is not None and reasoning_effort != "":
                if extra_body is not None:
                    text = client.complete(
                        messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        seed=seed,
                        response_format=response_format,
                        reasoning_effort=reasoning_effort,
                        extra_body=extra_body,
                    )
                else:
                    text = client.complete(
                        messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        seed=seed,
                        response_format=response_format,
                        reasoning_effort=reasoning_effort,
                    )
            else:
                if extra_body is not None:
                    text = client.complete(
                        messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        seed=seed,
                        response_format=response_format,
                        extra_body=extra_body,
                    )
                else:
                    text = client.complete(
                        messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        seed=seed,
                        response_format=response_format,
                    )
            empty = text.strip() == ""
            attempts.append({"attempt": attempt_index, "ok": not empty, "empty": empty, "error": None})
            if not empty:
                return text, {"ok": True, "attempts": attempts}
        except Exception as exc:
            attempts.append(
                {
                    "attempt": attempt_index,
                    "ok": False,
                    "empty": False,
                    "error": f"{type(exc).__name__}: {str(exc)[:500]}",
                }
            )
        if attempt_index + 1 < max(max_attempts, 1) and retry_sleep > 0:
            time.sleep(retry_sleep)
    return "", {"ok": False, "attempts": attempts}
