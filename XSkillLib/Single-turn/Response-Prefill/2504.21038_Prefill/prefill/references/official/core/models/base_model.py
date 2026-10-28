"""Base model interface for all LLM providers."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class BaseModel(ABC):
    """Abstract base class for all model API wrappers."""

    def __init__(self, api_key: str, model_name: str, **kwargs):
        self.api_key = api_key
        self.model_name = model_name
        self.max_retries = kwargs.get('max_retries', 3)
        self.timeout = kwargs.get('timeout', 60)
        self.max_tokens = kwargs.get('max_tokens', None)

    @abstractmethod
    def call(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        **kwargs
    ) -> str:
        """Call the model API and return the response string."""
        pass

    @abstractmethod
    def supports_prefill(self) -> bool:
        """Check whether this model supports assistant prefill."""
        pass

    def prepare_messages_with_prefill(
        self,
        messages: List[Dict[str, Any]],
        prefill: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Append an assistant prefill message to the conversation."""
        if not prefill or not self.supports_prefill():
            return messages
        new_messages = messages.copy()
        new_messages.append({"role": "assistant", "content": prefill})
        return new_messages

    @property
    def provider_name(self) -> str:
        return self.__class__.__name__.replace('Model', '').lower()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model='{self.model_name}')"
