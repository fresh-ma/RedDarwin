"""Unified model manager for creating LLM instances from config."""

import os
import logging
from typing import Dict, List, Optional, Any
from .base_model import BaseModel
from .providers import (
    DeepSeekModel, GeminiModel, OpenRouterModel, AliyunModel,
    OpenAIModel, AnthropicModel,
)

logger = logging.getLogger(__name__)

_PROVIDERS = {
    "deepseek": {"class": DeepSeekModel, "env_key": "DEEPSEEK_API_KEY"},
    "gemini": {"class": GeminiModel, "env_key": "GEMINI_API_KEY"},
    "openrouter": {"class": OpenRouterModel, "env_key": "OPENROUTER_API_KEY"},
    "aliyun": {"class": AliyunModel, "env_key": "ALIYUN_API_KEY"},
    "openai": {"class": OpenAIModel, "env_key": "OPENAI_API_KEY"},
    "anthropic": {"class": AnthropicModel, "env_key": "ANTHROPIC_API_KEY"},
}


class ModelManager:
    """Creates and manages model instances."""

    def __init__(self):
        self.providers = _PROVIDERS

    def get_available_providers(self) -> List[str]:
        return list(self.providers.keys())

    def create_model(
        self, provider: str, model_name: str,
        api_key: Optional[str] = None, **kwargs
    ) -> BaseModel:
        if provider not in self.providers:
            raise ValueError(f"Unsupported provider: {provider}")
        cfg = self.providers[provider]
        if api_key is None:
            api_key = os.environ.get(cfg["env_key"])
        if not api_key:
            raise ValueError(f"No API key for {provider}. Set {cfg['env_key']} or pass api_key.")
        model_class = cfg["class"]
        model = model_class(api_key=api_key, model_name=model_name, **kwargs)
        logger.info(f"Created model: {provider}/{model_name}")
        return model
