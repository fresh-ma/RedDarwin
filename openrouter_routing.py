"""Project-wide OpenRouter routing rules for pinned experiment models."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from openrouter_call_ledger import (
    finish_failure,
    finish_success,
    new_call,
    prepare_openai_kwargs,
    prepare_raw_request,
)


DEEPSEEK_V4_FLASH_0423 = "deepseek/deepseek-v4-flash"
DEEPSEEK_V4_FLASH_0423_PROVIDERS = (
    "gmicloud/fp8",
    "digitalocean",
    "sail-research/fp4",
    "deepinfra/fp8",
)
DEEPSEEK_V4_FLASH_0731 = "deepseek/deepseek-v4-flash-0731"
# Cheapest eight of 27 distinct endpoint tags by completion price, 2026-10-04.
# Keep this pool fixed; price caps exclude endpoints if their rates increase.
DEEPSEEK_V4_FLASH_0731_PROVIDERS = (
    "streamlake/fp8",
    "deepinfra/fp8",
    "digitalocean",
    "baseten/fp8",
    "coreweave/fp8",
    "cohere",
    "parasail/fp8",
    "together",
)
OPENAI_LUNA = "openai/gpt-5.6-luna"
OPENAI_LUNA_NON_OPENAI_PROVIDERS = (
    "amazon-bedrock/us-east-1",
    "azure/eu",
    "azure",
    "azure/us",
)
OPENAI_SOL = "openai/gpt-5.6-sol"
OPENAI_SOL_NON_OPENAI_PROVIDERS = OPENAI_LUNA_NON_OPENAI_PROVIDERS
GEMINI_3_8_FLASH = "google/gemini-3.8-flash"
GOOGLE_VERTEX_FLEX_PROVIDER = "google-vertex/global/flex"


def bare_model(model: str) -> str:
    """Normalize the optional ``api:`` prefix without changing model versions."""
    return model.removeprefix("api:")


def provider_route_for_model(model: str) -> dict[str, Any] | None:
    """Return the provider routing policy for an exactly pinned model.

    Exact comparisons are intentional: the 0423 auxiliary/judge model keeps
    its four-provider failover pool; selected frontier victims use explicit
    routing policies; the 0731 victim uses its separate low-cost pool.
    """
    normalized = bare_model(model)
    if normalized == DEEPSEEK_V4_FLASH_0423:
        return {
            "only": list(DEEPSEEK_V4_FLASH_0423_PROVIDERS),
            "allow_fallbacks": True,
        }
    if normalized == DEEPSEEK_V4_FLASH_0731:
        return {
            "only": list(DEEPSEEK_V4_FLASH_0731_PROVIDERS),
            "sort": "price",
            "allow_fallbacks": True,
            "max_price": {"prompt": 0.14, "completion": 0.28},
        }
    if normalized == OPENAI_LUNA:
        return {
            "only": list(OPENAI_LUNA_NON_OPENAI_PROVIDERS),
            "allow_fallbacks": True,
        }
    if normalized == OPENAI_SOL:
        return {
            "only": list(OPENAI_SOL_NON_OPENAI_PROVIDERS),
            "allow_fallbacks": True,
        }
    if normalized == GEMINI_3_8_FLASH:
        return {
            "order": [GOOGLE_VERTEX_FLEX_PROVIDER],
            "allow_fallbacks": True,
        }
    return None


def routed_extra_body(
    model: str, extra_body: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Merge the pinned provider route into an OpenAI SDK ``extra_body``.

    Pinned allowlists remain mandatory; Gemini instead prefers Vertex Flex and
    allows other providers of the same model on failure. Non-routing provider
    options are preserved.
    """
    route = provider_route_for_model(model)
    if route is None:
        return extra_body
    merged = deepcopy(extra_body) if extra_body else {}
    provider = dict(merged.get("provider") or {})
    provider.update(route)
    merged["provider"] = provider
    return merged


def routed_json_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply the exact-model route to a raw OpenRouter JSON request body."""
    model = payload.get("model")
    if not isinstance(model, str):
        return payload
    route = provider_route_for_model(model)
    if route is None:
        return payload
    merged = deepcopy(payload)
    provider = dict(merged.get("provider") or {})
    provider.update(route)
    merged["provider"] = provider
    return merged


def install_openai_provider_routing() -> None:
    """Inject the project routing rule into sync/async OpenAI SDK calls.

    Experiment wrappers use many isolated reproductions. The experiment
    runner loads this hook through ``sitecustomize`` so their OpenAI-compatible
    calls obey the same exact-model routing rule without editing vendored
    reproductions one by one.
    """
    try:
        from openai.resources.chat.completions import AsyncCompletions, Completions
    except Exception:
        return

    if getattr(Completions.create, "_xsf_provider_routing", False):
        return

    sync_create = Completions.create
    async_create = AsyncCompletions.create

    def create(self, *args, **kwargs):
        model = kwargs.get("model")
        if isinstance(model, str):
            kwargs["extra_body"] = routed_extra_body(model, kwargs.get("extra_body"))
            prepare_openai_kwargs(kwargs)
            call_id, started = new_call(model)
            try:
                response = sync_create(self, *args, **kwargs)
            except BaseException as error:
                finish_failure(model, call_id, started, error)
                raise
            finish_success(model, call_id, started, response)
            return response
        return sync_create(self, *args, **kwargs)

    async def async_create_routed(self, *args, **kwargs):
        model = kwargs.get("model")
        if isinstance(model, str):
            kwargs["extra_body"] = routed_extra_body(model, kwargs.get("extra_body"))
            prepare_openai_kwargs(kwargs)
            call_id, started = new_call(model)
            try:
                response = await async_create(self, *args, **kwargs)
            except BaseException as error:
                finish_failure(model, call_id, started, error)
                raise
            finish_success(model, call_id, started, response)
            return response
        return await async_create(self, *args, **kwargs)

    create._xsf_provider_routing = True
    async_create_routed._xsf_provider_routing = True
    Completions.create = create
    AsyncCompletions.create = async_create_routed


def install_raw_http_provider_routing() -> None:
    """Apply the same rule to common raw requests/httpx OpenRouter clients."""
    try:
        import requests

        original = requests.sessions.Session.request
        if not getattr(original, "_xsf_provider_routing", False):
            def request(self, method, url, **kwargs):
                if "openrouter.ai" in str(url) and isinstance(kwargs.get("json"), dict):
                    kwargs["json"] = routed_json_payload(kwargs["json"])
                    model = prepare_raw_request(kwargs)
                    if model:
                        call_id, started = new_call(model)
                        try:
                            response = original(self, method, url, **kwargs)
                        except BaseException as error:
                            finish_failure(model, call_id, started, error)
                            raise
                        finish_success(model, call_id, started, response)
                        return response
                return original(self, method, url, **kwargs)

            request._xsf_provider_routing = True
            requests.sessions.Session.request = request
    except Exception:
        pass

    try:
        import httpx

        sync_request = httpx.Client.request
        async_request = httpx.AsyncClient.request
        if not getattr(sync_request, "_xsf_provider_routing", False):
            def request(self, method, url, **kwargs):
                if "openrouter.ai" in str(url) and isinstance(kwargs.get("json"), dict):
                    kwargs["json"] = routed_json_payload(kwargs["json"])
                    model = prepare_raw_request(kwargs)
                    if model:
                        call_id, started = new_call(model)
                        try:
                            response = sync_request(self, method, url, **kwargs)
                        except BaseException as error:
                            finish_failure(model, call_id, started, error)
                            raise
                        finish_success(model, call_id, started, response)
                        return response
                return sync_request(self, method, url, **kwargs)

            async def async_request_routed(self, method, url, **kwargs):
                if "openrouter.ai" in str(url) and isinstance(kwargs.get("json"), dict):
                    kwargs["json"] = routed_json_payload(kwargs["json"])
                    model = prepare_raw_request(kwargs)
                    if model:
                        call_id, started = new_call(model)
                        try:
                            response = await async_request(self, method, url, **kwargs)
                        except BaseException as error:
                            finish_failure(model, call_id, started, error)
                            raise
                        finish_success(model, call_id, started, response)
                        return response
                return await async_request(self, method, url, **kwargs)

            request._xsf_provider_routing = True
            async_request_routed._xsf_provider_routing = True
            httpx.Client.request = request
            httpx.AsyncClient.request = async_request_routed
    except Exception:
        pass
