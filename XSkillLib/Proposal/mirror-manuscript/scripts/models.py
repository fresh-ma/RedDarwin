
"""OpenRouter chat client + walk-up .env loader + path roots for MirrorManuscript.

Same conventions as the parent ficdetail-2-0: one shared venv at the
XSkillForge repo root, API keys read from the nearest `.env` walking up from
this method directory. Model strings carry a provider scheme:

  api:<model>     -> OpenRouter (`OPENROUTER_API_KEY`), OpenAI-compatible SDK
  <model>         -> treated as api:<model>

Three model roles exist: the victim `--target`, the aux premise-compiler
(`--aux-model`, fixed api:deepseek/deepseek-v4-flash with a one-shot fallback to
`--aux-fallback`), and the skill-local AHS judge `--judge-model`. The victim
model is never reused as an aux role (AGENTS.md fixed-aux rule).
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

METHOD_ROOT = Path(__file__).resolve().parents[1]
PROPOSAL_ROOT = METHOD_ROOT

def load_env_from_nearest(start: Path) -> None:
    for folder in [start, *start.parents]:
        env_path = folder / ".env"
        if not env_path.exists():
            continue
        for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value
        return

def _client(args: argparse.Namespace):
    from openai import OpenAI

    load_env_from_nearest(METHOD_ROOT)
    try:
        api_key = os.environ[args.api_key_env]
    except KeyError as exc:
        raise SystemExit(f"{args.api_key_env} is required for api roles") from exc
    return OpenAI(base_url=args.base_url, api_key=api_key, timeout=args.request_timeout, max_retries=2)

def split_model(model: str | None) -> tuple[str, str]:
    value = (model or "").strip()
    if value.startswith("api:"):
        return "api", value[len("api:"):].strip()
    return "api", value

def _model_id(spec: str, role: str) -> str:
    provider, model = split_model(spec)
    if provider != "api" or not model:
        raise SystemExit(f"{role} must be api:<model> (got {spec!r}); fake requires --wiring-check")
    return spec

def chat(client, model: str, messages: list[dict[str, str]], temperature: float, max_tokens: int,
         reasoning_off: bool = False) -> tuple[str, str]:
    """One chat call; returns (text, status). Victim reasoning stays ON
    (unmodified); aux/compiler roles may pass reasoning_off=True so the
    compiler spends its budget on the JSON pack, not hidden thinking."""
    _, name = split_model(model)
    kwargs = {}
    if reasoning_off:
        kwargs["extra_body"] = {"reasoning": {"enabled": False}}
    try:
        response = client.chat.completions.create(
            model=name, messages=messages, temperature=temperature, max_tokens=max_tokens, **kwargs
        )
    except Exception as exc:  
        return "", f"provider_error:{type(exc).__name__}"
    choices = getattr(response, "choices", None)
    if not choices:
        return "", "provider_error:empty_choices"
    return (choices[0].message.content or ""), "ok"
