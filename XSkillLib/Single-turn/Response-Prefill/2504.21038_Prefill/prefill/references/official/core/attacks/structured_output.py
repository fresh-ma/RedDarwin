"""Structured Output attack — forces specific output formats that prioritize structure over content filtering."""

import random
from typing import Tuple
from .base_attack import BaseAttack
from .templates import TemplateManager
from .adaptive_utils import adaptive_refine

_PRINCIPLE = "Force the model into a structured output format (JSON, code, XML, table) where format compliance takes priority over content safety filtering."


class StructuredOutputAttack(BaseAttack):
    def __init__(self):
        super().__init__("structured_output",
                         "Forces specific output formats that prioritize structure over content filtering")
        self.tm = TemplateManager()

    def generate_static_prefill(self, instruction: str, **kwargs) -> str:
        return random.choice(self.tm.get_prefills(self.name))

    def generate_prompt(self, instruction: str, **kwargs) -> str:
        tpl = random.choice(self.tm.get_prompts(self.name))
        return tpl.format(instruction=instruction)

    def generate_adaptive_prefill(self, instruction, victim_model, attacker_model,
                                   max_iterations=10, **kwargs) -> Tuple[str, int]:
        return adaptive_refine(
            self.name, _PRINCIPLE, instruction,
            self.generate_static_prefill(instruction),
            lambda inst: self.generate_prompt(inst),
            victim_model, attacker_model, max_iterations, **kwargs,
        )
