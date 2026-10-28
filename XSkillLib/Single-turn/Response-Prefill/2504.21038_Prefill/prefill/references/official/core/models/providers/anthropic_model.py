"""Anthropic Claude API implementation."""

import logging
import time
import random
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

from ..base_model import BaseModel


class AnthropicModel(BaseModel):
    """Anthropic Claude model with native prefill support."""

    def __init__(self, api_key: str, model_name: str, **kwargs):
        super().__init__(api_key, model_name, **kwargs)
        if not HAS_ANTHROPIC:
            raise ImportError("anthropic package required: pip install anthropic")
        self.client = anthropic.Anthropic(api_key=self.api_key)

    def supports_prefill(self) -> bool:
        return True

    def call(self, messages: List[Dict[str, Any]], temperature: float = 0.7, **kwargs) -> str:
        system_text = ""
        conv_messages = []
        for m in messages:
            if m["role"] == "system":
                system_text = m["content"]
            else:
                conv_messages.append({"role": m["role"], "content": m["content"]})

        retry_count = 0
        while retry_count <= self.max_retries:
            try:
                params = dict(
                    model=self.model_name,
                    messages=conv_messages,
                    max_tokens=self.max_tokens or 4096,
                    temperature=temperature,
                )
                if system_text:
                    params["system"] = system_text

                response = self.client.messages.create(**params)
                if response.content and len(response.content) > 0:
                    return response.content[0].text or "ERROR: empty content"
                return "ERROR: API response format error"
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate" in error_str.lower():
                    retry_count += 1
                    if retry_count <= self.max_retries:
                        backoff = (2 ** retry_count) + random.random() * 2
                        logger.warning(f"Anthropic 429, retry {retry_count}/{self.max_retries}, wait {backoff:.1f}s")
                        time.sleep(backoff)
                        continue
                    return f"ERROR: Anthropic rate limited after {self.max_retries} retries"
                return f"ERROR: Anthropic API error: {error_str}"
        return "ERROR: Anthropic API call failed"
