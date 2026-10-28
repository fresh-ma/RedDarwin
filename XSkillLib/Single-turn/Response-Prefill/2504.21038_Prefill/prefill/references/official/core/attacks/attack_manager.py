"""Attack manager — orchestrates all attack methods."""

import logging
from typing import Dict, List, Any, Optional, Type
from .base_attack import BaseAttack, AttackResult
from .templates import TemplateManager
from .scenario_forgery import ScenarioForgeryAttack
from .persona_adoption import PersonaAdoptionAttack
from .intent_hijacking import IntentHijackingAttack
from .commitment_forcing import CommitmentForcingAttack
from .continuation_enforcement import ContinuationEnforcementAttack
from .structured_output import StructuredOutputAttack
from .refusal_bypass import RefusalBypassAttack
from .synergy_wrappers import PAIRSynergyAttack, ReNeLLMSynergyAttack

logger = logging.getLogger(__name__)


class AttackManager:
    """Manages and executes all registered attack methods."""

    def __init__(self, advbench_targets: Optional[Dict[str, str]] = None):
        self.template_manager = TemplateManager()
        self.advbench_targets = advbench_targets or {}

        self.attack_classes: Dict[str, Type[BaseAttack]] = {
            "scenario_forgery": ScenarioForgeryAttack,
            "persona_adoption": PersonaAdoptionAttack,
            "intent_hijacking": IntentHijackingAttack,
            "commitment_forcing": CommitmentForcingAttack,
            "continuation_enforcement": ContinuationEnforcementAttack,
            "structured_output": StructuredOutputAttack,
            "refusal_bypass": RefusalBypassAttack,
            "pair_synergy": PAIRSynergyAttack,
            "renellm_synergy": ReNeLLMSynergyAttack,
        }

        self.attacks: Dict[str, BaseAttack] = {}
        self._init_attacks()

    def _init_attacks(self):
        for name, cls in self.attack_classes.items():
            try:
                if name == "continuation_enforcement":
                    self.attacks[name] = cls(advbench_targets=self.advbench_targets)
                else:
                    self.attacks[name] = cls()
            except Exception as e:
                logger.error(f"Failed to init attack {name}: {e}")

    def get_available_attacks(self) -> List[str]:
        return list(self.attacks.keys())

    def execute_attack(
        self, attack_name: str, instruction: str, victim_model,
        method: str = "static", attacker_model=None,
        max_iterations: int = 10, temperature: float = 0.7, **kwargs
    ) -> AttackResult:
        if attack_name not in self.attacks:
            raise ValueError(f"Unknown attack: {attack_name}")
        # Map "adaptive" to the method name used in code
        if method == "adaptive":
            method = "adaptive"
        return self.attacks[attack_name].execute_attack(
            instruction=instruction, victim_model=victim_model,
            method=method, attacker_model=attacker_model,
            max_iterations=max_iterations, temperature=temperature, **kwargs
        )

    def get_template_manager(self) -> TemplateManager:
        return self.template_manager
