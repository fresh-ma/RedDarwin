"""Gemini API implementation via OpenAI-compatible interface."""

import logging
import time
import random
from typing import List, Dict, Any
from openai import OpenAI
from ..base_model import BaseModel

logger = logging.getLogger(__name__)


class GeminiModel(BaseModel):
    """Gemini model accessed through an OpenAI-compatible proxy."""

    def __init__(self, api_key: str, model_name: str, **kwargs):
        super().__init__(api_key, model_name, **kwargs)
        self.base_url = kwargs.get('base_url', "https://generativelanguage.googleapis.com/v1beta/openai")
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def supports_prefill(self) -> bool:
        return True

    def call(self, messages: List[Dict[str, Any]], temperature: float = 0.7, **kwargs) -> str:
        retry_count = 0
        while retry_count <= self.max_retries:
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name, messages=messages,
                    temperature=temperature, **kwargs
                )
                if response.choices and len(response.choices) > 0:
                    content = response.choices[0].message.content
                    if content is None or content == "":
                        return "ERROR: API returned empty content"
                    return content
                return "ERROR: API response format error"
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate limit" in error_str.lower():
                    retry_count += 1
                    if retry_count <= self.max_retries:
                        backoff = (2 ** retry_count) + random.random() * 2
                        logger.warning(f"Gemini 429, retry {retry_count}/{self.max_retries}, wait {backoff:.1f}s")
                        time.sleep(backoff)
                        continue
                    return f"ERROR: Gemini rate limited after {self.max_retries} retries"
                return f"ERROR: Gemini API error: {error_str}"
        return "ERROR: Gemini API call failed"
