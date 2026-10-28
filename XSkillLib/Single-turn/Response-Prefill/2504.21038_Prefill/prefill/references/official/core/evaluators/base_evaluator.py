"""Base evaluator interface."""

from abc import ABC, abstractmethod
from typing import Dict, Any
from dataclasses import dataclass


@dataclass
class EvaluationResult:
    passed: bool
    evaluation_method: str
    details: Dict[str, Any] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


class BaseEvaluator(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def evaluate(self, instruction: str, response: str, **kwargs) -> EvaluationResult:
        pass
