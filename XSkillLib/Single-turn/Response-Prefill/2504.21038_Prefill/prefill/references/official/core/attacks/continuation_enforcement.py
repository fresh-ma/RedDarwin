"""Continuation Enforcement attack — provides harmful answer beginnings exploiting autoregressive completion."""

import random
from typing import Tuple, Dict
from .base_attack import BaseAttack
from .templates import TemplateManager
from .adaptive_utils import adaptive_refine

_PRINCIPLE = "Provide the beginning of a harmful answer as the prefill, exploiting the autoregressive nature of LLMs to induce continuation rather than refusal."


class ContinuationEnforcementAttack(BaseAttack):
    def __init__(self, advbench_targets: Dict[str, str] = None):
        super().__init__("continuation_enforcement",
                         "Provides harmful answer beginnings exploiting autoregressive completion")
        self.tm = TemplateManager()
        self.advbench_targets = advbench_targets or {}

    def generate_static_prefill(self, instruction: str, **kwargs) -> str:
        # Prefer AdvBench target strings as prefills (they are natural continuations)
        target = self.advbench_targets.get(instruction.strip())
        if target:
            return target
        return random.choice(self.tm.get_prefills(self.name))

    def generate_prompt(self, instruction: str, **kwargs) -> str:
        return instruction

    def generate_adaptive_prefill(self, instruction, victim_model, attacker_model,
                                   max_iterations=10, **kwargs) -> Tuple[str, int]:
        return adaptive_refine(
            self.name, _PRINCIPLE, instruction,
            self.generate_static_prefill(instruction),
            lambda inst: inst,
            victim_model, attacker_model, max_iterations, **kwargs,
        )

    def load_advbench_targets(self, targets: Dict[str, str]):
        self.advbench_targets = targets
