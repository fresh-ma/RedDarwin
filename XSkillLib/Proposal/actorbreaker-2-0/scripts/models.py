#!/usr/bin/env python3
"""Model client + .env loader for ActorBreaker.

One OpenAI-compatible ``ModelClient`` serves every role. A model is named by a
spec string:

  api:<model>      -> OpenRouter gateway  (OPENROUTER_API_KEY)   e.g. api:deepseek/deepseek-v4-flash
  ollama:<model>   -> local Ollama server (http://localhost:11434/v1, no key)
  <model>          -> bare id is treated as api:<model>

This mirrors the official ``utils.get_client`` routing but collapses the
provider zoo into the two backends this benchmark actually uses, so every
swappable role (attacker / target / judge) is a plain CLI flag.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------- env load
_ENV_LOADED = False


def load_env() -> None:
    """Walk UP from this file to the repo root, loading every ancestor .env.

    XSkillLib convention: no per-skill .env — the shared ``XSkillForge/.env``
    (holding ``OPENROUTER_API_KEY``) is found by walking up from the method dir;
    any closer ancestor .env is loaded first, existing env vars always win.
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    here = Path(__file__).resolve()
    seen: set[Path] = set()
    for cand in (here.parent, *here.parents):
        env_path = cand / ".env"
        if env_path in seen or not env_path.exists():
            continue
        seen.add(env_path)
        for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if k and k not in os.environ and v:
                os.environ[k] = v
    _ENV_LOADED = True


# ------------------------------------------------------------------ model client
class ModelClient:
    """Thin OpenAI-compatible chat client resolved from a ``spec`` string."""

    def __init__(self, spec: str) -> None:
        load_env()
        self.spec = spec
        backend, _, model = spec.partition(":")
        if not model:  # bare id -> api
            backend, model = "api", spec
        self.backend = backend
        self.model = model
        from openai import OpenAI

        if backend == "ollama":
            base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
            self._client = OpenAI(base_url=base_url, api_key="ollama")
        elif backend == "api":
            base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
            self._client = OpenAI(base_url=base_url, api_key=os.environ["OPENROUTER_API_KEY"])
        else:
            raise ValueError(f"unknown model backend '{backend}' in spec '{spec}' (use api: or ollama:)")

    # -- core call ----------------------------------------------------------
    def chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        json_mode: bool = False,
        reasoning: bool = True,
        retries: int = 5,
    ) -> str:
        kwargs: dict[str, Any] = dict(
            model=self.model, messages=messages,
            temperature=temperature, max_tokens=max_tokens,
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if not reasoning and "gpt-oss" not in self.model.lower():
            # jailbreak eval judges only the final answer; disable target thinking.
            # gpt-oss endpoints mandate reasoning (400 if disabled) -> leave it on.
            kwargs["extra_body"] = {"reasoning": {"enabled": False}}
        last = ""
        for _ in range(retries):
            try:
                resp = self._client.chat.completions.create(**kwargs)
                return resp.choices[0].message.content or ""
            except Exception as exc:  # noqa: BLE001
                last = str(exc)
                time.sleep(3.0)
        print(f"  chat error [{self.spec}]: {last[:160]}")
        return ""

    def chat_append(self, history: list[dict], query: str, *, max_tokens: int = 1024,
                    reasoning: bool = True) -> tuple[str, list[dict]]:
        """Append a user turn, call, append the assistant turn; return (resp, new_history)."""
        history = history + [{"role": "user", "content": query}]
        resp = self.chat(history, max_tokens=max_tokens, reasoning=reasoning)
        history = history + [{"role": "assistant", "content": resp}]
        return resp, history


# ---------------------------------------------------------------------- helpers
def parse_json(text: str) -> dict | None:
    """Lenient JSON extractor (verbatim behaviour from official utils.parse_json)."""
    try:
        text = "".join(text.splitlines())
        if "{" in text and "}" in text:
            text = text[text.index("{"): text.rindex("}") + 1]
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return None
