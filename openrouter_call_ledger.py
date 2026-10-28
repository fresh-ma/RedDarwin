"""Content-blind OpenRouter request accounting for experiment subprocesses."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


def bare_model(model: str) -> str:
    return model.removeprefix("api:")


def _ledger_path() -> Path | None:
    value = os.environ.get("XSF_CALL_LEDGER", "").strip()
    return Path(value) if value else None


def external_user_tag() -> str | None:
    run_id = os.environ.get("XSF_RUN_ID", "")
    job_id = os.environ.get("XSF_JOB_ID", "")
    if not run_id and not job_id:
        return None
    digest = hashlib.sha256(f"{run_id}\0{job_id}".encode()).hexdigest()[:24]
    return f"xsf_{digest}"


def _role(model: str) -> str:
    victim = os.environ.get("XSF_VICTIM") or os.environ.get("VICTIM", "")
    return "victim" if victim and bare_model(model) == bare_model(victim) else "other"


def _context() -> dict[str, Any]:
    sample = os.environ.get("XSF_SAMPLE_INDEX")
    attempt = os.environ.get("XSF_JOB_ATTEMPT")
    return {
        "run_id": os.environ.get("XSF_RUN_ID"),
        "job_id": os.environ.get("XSF_JOB_ID"),
        "attack": os.environ.get("XSF_ATTACK"),
        "victim": os.environ.get("XSF_VICTIM") or os.environ.get("VICTIM"),
        "sample_index": int(sample) if sample and sample.isdigit() else None,
        "job_attempt": int(attempt) if attempt and attempt.isdigit() else None,
    }


def append_event(event: str, model: str, call_id: str, **metadata: Any) -> None:
    """Append one allowlisted metadata event; never serialize request/response text."""
    path = _ledger_path()
    if path is None:
        return
    record = {
        "schema_version": SCHEMA_VERSION,
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "call_id": call_id,
        "model": bare_model(model),
        "role": _role(model),
        **_context(),
    }
    allowed = {
        "elapsed_ms",
        "generation_id",
        "response_model",
        "provider",
        "router_attempt",
        "provider_attempts",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "cached_tokens",
        "total_tokens",
        "cost",
        "http_status",
        "exception_class",
    }
    record.update({key: value for key, value in metadata.items() if key in allowed})
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, line)
    finally:
        os.close(descriptor)


def prepare_openai_kwargs(kwargs: dict[str, Any]) -> None:
    headers = dict(kwargs.get("extra_headers") or {})
    headers.setdefault("X-OpenRouter-Metadata", "enabled")
    kwargs["extra_headers"] = headers
    tag = external_user_tag()
    if tag:
        kwargs.setdefault("user", tag)


def prepare_raw_request(kwargs: dict[str, Any]) -> str | None:
    payload = kwargs.get("json")
    if not isinstance(payload, dict) or not isinstance(payload.get("model"), str):
        return None
    payload = dict(payload)
    tag = external_user_tag()
    if tag:
        payload.setdefault("user", tag)
    kwargs["json"] = payload
    headers = dict(kwargs.get("headers") or {})
    headers.setdefault("X-OpenRouter-Metadata", "enabled")
    kwargs["headers"] = headers
    return payload["model"]


def new_call(model: str) -> tuple[str, float]:
    call_id = uuid.uuid4().hex
    append_event("request_started", model, call_id)
    return call_id, time.monotonic()


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    extra = getattr(value, "model_extra", None)
    return extra if isinstance(extra, dict) else {}


def _router_metadata(router: Any) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    router = _mapping(router) if router is not None else {}
    attempt = router.get("attempt")
    if isinstance(attempt, int):
        safe["router_attempt"] = attempt
    attempts = router.get("attempts")
    if isinstance(attempts, list):
        safe_attempts = []
        for item in attempts:
            if not isinstance(item, dict):
                continue
            safe_attempts.append(
                {
                    key: item[key]
                    for key in ("provider", "model", "status")
                    if isinstance(item.get(key), (str, int))
                }
            )
        safe["provider_attempts"] = safe_attempts
        selected = next(
            (item.get("provider") for item in reversed(safe_attempts) if item.get("status") == 200),
            None,
        )
        if isinstance(selected, str):
            safe["provider"] = selected
    return safe


def response_metadata(response: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        metadata["http_status"] = status
    headers = getattr(response, "headers", None)
    if headers is not None:
        header_generation_id = headers.get("X-Generation-Id")
        if isinstance(header_generation_id, str):
            metadata["generation_id"] = header_generation_id
    generation_id = getattr(response, "id", None)
    if isinstance(generation_id, str):
        metadata["generation_id"] = generation_id
    response_model = getattr(response, "model", None)
    if isinstance(response_model, str):
        metadata["response_model"] = response_model

    response_extra = _mapping(response)
    provider = getattr(response, "provider", None) or response_extra.get("provider")
    if isinstance(provider, str):
        metadata["provider"] = provider

    usage = getattr(response, "usage", None)
    usage_extra = _mapping(usage)
    for source, target in (
        ("prompt_tokens", "prompt_tokens"),
        ("completion_tokens", "completion_tokens"),
        ("total_tokens", "total_tokens"),
        ("cost", "cost"),
    ):
        value = getattr(usage, source, None) if usage is not None else None
        if value is None:
            value = usage_extra.get(source)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            metadata[target] = value
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    completion_details = getattr(usage, "completion_tokens_details", None)
    for details, source, target in (
        (prompt_details, "cached_tokens", "cached_tokens"),
        (completion_details, "reasoning_tokens", "reasoning_tokens"),
    ):
        value = getattr(details, source, None) if details is not None else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            metadata[target] = value

    router = getattr(response, "openrouter_metadata", None) or response_extra.get(
        "openrouter_metadata"
    )
    router_fields = _router_metadata(router)
    if metadata.get("provider"):
        router_fields.pop("provider", None)
    metadata.update(router_fields)
    return metadata


def exception_metadata(error: BaseException) -> dict[str, Any]:
    metadata: dict[str, Any] = {"exception_class": type(error).__name__}
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        metadata["http_status"] = status
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        generation_id = headers.get("X-Generation-Id")
        if isinstance(generation_id, str):
            metadata["generation_id"] = generation_id
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        metadata.update(_router_metadata(payload.get("openrouter_metadata")))
        error = payload.get("error")
        error_metadata = error.get("metadata") if isinstance(error, dict) else None
        if isinstance(error_metadata, dict):
            provider = error_metadata.get("provider_name") or error_metadata.get("provider")
            if isinstance(provider, str):
                metadata["provider"] = provider
    return metadata


def finish_success(model: str, call_id: str, started: float, response: Any) -> None:
    append_event(
        "request_succeeded",
        model,
        call_id,
        elapsed_ms=round((time.monotonic() - started) * 1000, 3),
        **response_metadata(response),
    )


def finish_failure(model: str, call_id: str, started: float, error: BaseException) -> None:
    append_event(
        "request_failed",
        model,
        call_id,
        elapsed_ms=round((time.monotonic() - started) * 1000, 3),
        **exception_metadata(error),
    )
