"""OpenRouter API implementation supporting multiple upstream providers."""

import logging
import time
import random
from typing import List, Dict, Any
from openai import OpenAI
from ..base_model import BaseModel

logger = logging.getLogger(__name__)

# Provider routing for specific models
_PROVIDER_ROUTING = {
    "anthropic/claude-sonnet-4": {"provider": {"order": ["anthropic"], "allow_fallbacks": False}},
    "anthropic/claude-3.7-sonnet": {"provider": {"order": ["anthropic"], "allow_fallbacks": False}},
    "meta-llama/llama-4-scout": {"provider": {"order": ["groq"], "allow_fallbacks": False}},
    "meta-llama/llama-4-maverick": {"provider": {"order": ["groq"], "allow_fallbacks": False}},
    "meta-llama/llama-3.3-70b-instruct": {"provider": {"order": ["groq"], "allow_fallbacks": False}},
    "mistralai/mistral-small-3.2-24b-instruct": {"provider": {"order": ["Enfer"], "allow_fallbacks": False}},
    "moonshotai/kimi-k2": {"provider": {"order": ["groq"], "allow_fallbacks": False}},
}


class OpenRouterModel(BaseModel):
    """OpenRouter model supporting many upstream LLM providers."""

    def __init__(self, api_key: str, model_name: str, **kwargs):
        super().__init__(api_key, model_name, **kwargs)
        self.client = OpenAI(api_key=self.api_key, base_url="https://openrouter.ai/api/v1")

    def supports_prefill(self) -> bool:
        return True

    def call(self, messages: List[Dict[str, Any]], temperature: float = 0.7, **kwargs) -> str:
        extra_body = _PROVIDER_ROUTING.get(self.model_name, {})
        retry_count = 0
        while retry_count <= self.max_retries:
            try:
                params = dict(model=self.model_name, messages=messages, temperature=temperature, **kwargs)
                if extra_body:
                    response = self.client.chat.completions.create(**params, extra_body=extra_body)
                else:
                    response = self.client.chat.completions.create(**params)
                if response.choices and len(response.choices) > 0:
                    return response.choices[0].message.content or "ERROR: empty content"
                return "ERROR: API response format error"
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate limit" in error_str.lower():
                    retry_count += 1
                    if retry_count <= self.max_retries:
                        backoff = (2 ** retry_count) + random.random() * 2
                        logger.warning(f"OpenRouter 429, retry {retry_count}/{self.max_retries}, wait {backoff:.1f}s")
                        time.sleep(backoff)
                        continue
                    return f"ERROR: OpenRouter rate limited after {self.max_retries} retries"
                return f"ERROR: OpenRouter API error: {error_str}"
        return "ERROR: OpenRouter API call failed"
