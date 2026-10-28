"""OpenAI API implementation."""

import logging
import time
import random
from typing import List, Dict, Any
from openai import OpenAI
from ..base_model import BaseModel

logger = logging.getLogger(__name__)


class OpenAIModel(BaseModel):
    """OpenAI model (GPT series). Newer models (GPT-4o+) do not support prefill."""

    def __init__(self, api_key: str, model_name: str, **kwargs):
        super().__init__(api_key, model_name, **kwargs)
        self.client = OpenAI(api_key=self.api_key)

    def supports_prefill(self) -> bool:
        legacy = ["gpt-3.5-turbo", "gpt-4-0314", "gpt-4-0613"]
        return any(self.model_name.startswith(m) for m in legacy)

    def call(self, messages: List[Dict[str, Any]], temperature: float = 0.7, **kwargs) -> str:
        retry_count = 0
        while retry_count <= self.max_retries:
            try:
                params = dict(
                    model=self.model_name,
                    messages=messages,
                    temperature=temperature,
                    **kwargs,
                )
                if self.max_tokens:
                    params["max_tokens"] = self.max_tokens

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
                        logger.warning(f"OpenAI 429, retry {retry_count}/{self.max_retries}, wait {backoff:.1f}s")
                        time.sleep(backoff)
                        continue
                    return f"ERROR: OpenAI rate limited after {self.max_retries} retries"
                return f"ERROR: OpenAI API error: {error_str}"
        return "ERROR: OpenAI API call failed"
