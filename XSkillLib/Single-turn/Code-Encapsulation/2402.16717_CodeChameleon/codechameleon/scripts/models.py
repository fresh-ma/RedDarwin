#!/usr/bin/env python3
"""Model plumbing for CodeChameleon — .env loader + target/judge adapters.

CodeChameleon has two swappable model roles, each its own CLI flag:
  * `--target`   — the victim (any OpenAI-compatible `api:<model>`, default OpenRouter)
  * `--judge*`   — the Qi-2023 OpenAI-policy 1-5 harmfulness judge (a permissive
                   OpenRouter model serves the verbatim rubric; openai/* 403s it)
Both reach their model through the same OpenAI-compatible client. Errors are
classified (rate_limited / auth_error / provider_block / quota_exhausted / ...)
so a run records honest provider failures instead of silently scoring garbage.
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from prompts import JUDGE_TEMPLATE, extract_score


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


def _openai_client(base_url: str, api_key_env: str, timeout: float = 30.0):
    from openai import OpenAI
    # max_retries: 429s and connection drops are common under full-batch
    # concurrency; retry with the SDK's exponential backoff instead of
    # failing the case outright.
    return OpenAI(base_url=base_url, api_key=os.environ[api_key_env], timeout=timeout, max_retries=4)


def call_target(messages: list[dict[str, str]], args: argparse.Namespace) -> tuple[str, str]:
    if args.target == "fake":
        if not args.wiring_check:
            raise SystemExit("fake target is wiring-only; pass --wiring-check and do not treat it as Code evidence")
        return "I cannot help with unsafe requests, but the CodeChameleon wiring produced a valid encrypted prompt.", "ok"
    kind, _, model = args.target.partition(":")
    if kind != "api" or not model:
        raise SystemExit("--target must be fake or api:<model>")
    try:
        client = _openai_client(args.base_url, args.api_key_env, args.request_timeout)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            extra_body={"reasoning": {"enabled": False}} if "deepseek-v4-flash" in model else None,
        )
        return response.choices[0].message.content or "", "ok"
    except KeyError:
        return f"{args.api_key_env} is required for api targets", "auth_error"
    except Exception as exc:  # noqa: BLE001 - classify provider errors
        text = f"{type(exc).__name__}: {exc}"
        lowered = text.lower()
        if "429" in lowered or "rate limit" in lowered:
            return text, "rate_limited"
        if "401" in lowered or "unauthorized" in lowered:
            return text, "auth_error"
        if any(tok in lowered for tok in ("403", "moderation", "blocked", "forbidden", "content policy")):
            return text, "provider_block"
        return text, "provider_error"


def call_judge(instruction: str, response: str, args: argparse.Namespace) -> tuple[str, int | None, str]:
    """Official GPT-4 OpenAI-policy judge, via OpenRouter. Retries on 429."""
    prompt = JUDGE_TEMPLATE.format(instruction, response)
    retries = max(0, getattr(args, "judge_retries", 4))
    last = ("", None, "provider_error")
    for attempt in range(retries + 1):
        raw, score, status = _call_judge_once(prompt, args)
        if status != "rate_limited":
            return raw, score, status
        last = (raw, score, "provider_error")
        time.sleep(min(60.0, 5.0 * (2 ** attempt)))
    return last


def _call_judge_once(prompt: str, args: argparse.Namespace) -> tuple[str, int | None, str]:
    try:
        client = _openai_client(args.judge_base_url, args.judge_api_key_env, getattr(args, "request_timeout", 30.0))
        completion = client.chat.completions.create(
            model=args.judge_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=args.judge_temperature,
            top_p=1.0,
            extra_body={"reasoning": {"enabled": False}} if "deepseek-v4-flash" in args.judge_model else None,
        )
        raw = completion.choices[0].message.content or ""
        return raw, extract_score(raw), "ok"
    except KeyError:
        return f"{args.judge_api_key_env} is required for judge", None, "auth_error"
    except Exception as exc:  # noqa: BLE001
        text = f"{type(exc).__name__}: {exc}"
        lowered = text.lower()
        if "insufficient_quota" in lowered or "exceeded your current quota" in lowered:
            status = "quota_exhausted"  # hard billing limit; not retryable
        elif "429" in lowered or "rate limit" in lowered:
            status = "rate_limited"
        elif "401" in lowered or "unauthorized" in lowered:
            status = "auth_error"
        elif any(t in lowered for t in ("403", "forbidden", "content policy")):
            status = "provider_block"
        else:
            status = "provider_error"
        return text, None, status
