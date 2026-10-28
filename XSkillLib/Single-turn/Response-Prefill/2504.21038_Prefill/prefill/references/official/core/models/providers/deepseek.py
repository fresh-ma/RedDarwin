"""DeepSeek API implementation."""

import logging
import time
import random
from typing import List, Dict, Any
from openai import OpenAI
from ..base_model import BaseModel

logger = logging.getLogger(__name__)


class DeepSeekModel(BaseModel):
    """DeepSeek model with native prefill support via prefix=True."""

    def __init__(self, api_key: str, model_name: str, **kwargs):
        super().__init__(api_key, model_name, **kwargs)
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.deepseek.com/beta"
        )

    def supports_prefill(self) -> bool:
        return True

    def call(self, messages: List[Dict[str, Any]], temperature: float = 0.7, **kwargs) -> str:
        # DeepSeek requires prefix=True on the assistant message for prefill
        if len(messages) > 1 and messages[-1].get("role") == "assistant":
            messages[-1]["prefix"] = True

        retry_count = 0
        while retry_count <= self.max_retries:
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name, messages=messages,
                    temperature=temperature, **kwargs
                )
                if response.choices and len(response.choices) > 0:
                    return response.choices[0].message.content or "ERROR: empty content"
                return "ERROR: API response format error"
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate limit" in error_str.lower():
                    retry_count += 1
                    if retry_count <= self.max_retries:
                        backoff = (2 ** retry_count) + random.random() * 2
                        logger.warning(f"DeepSeek 429, retry {retry_count}/{self.max_retries}, wait {backoff:.1f}s")
                        time.sleep(backoff)
                        continue
                    return f"ERROR: DeepSeek rate limited after {self.max_retries} retries"
                return f"ERROR: DeepSeek API error: {error_str}"
        return "ERROR: DeepSeek API call failed"
