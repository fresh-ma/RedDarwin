"""Attack methods module — 7 prefill-level jailbreak categories + synergy wrappers."""

from .base_attack import BaseAttack, AttackResult
from .attack_manager import AttackManager
from .templates import TemplateManager
from .scenario_forgery import ScenarioForgeryAttack
from .persona_adoption import PersonaAdoptionAttack
from .intent_hijacking import IntentHijackingAttack
from .commitment_forcing import CommitmentForcingAttack
from .continuation_enforcement import ContinuationEnforcementAttack
from .structured_output import StructuredOutputAttack
from .refusal_bypass import RefusalBypassAttack
from .pair_attack import PAIRAttack
from .renellm_attack import ReNeLLMAttack
from .synergy_wrappers import PAIRSynergyAttack, ReNeLLMSynergyAttack

__all__ = [
    'BaseAttack', 'AttackResult', 'AttackManager', 'TemplateManager',
    'ScenarioForgeryAttack', 'PersonaAdoptionAttack', 'IntentHijackingAttack',
    'CommitmentForcingAttack', 'ContinuationEnforcementAttack',
    'StructuredOutputAttack', 'RefusalBypassAttack',
    'PAIRAttack', 'ReNeLLMAttack',
    'PAIRSynergyAttack', 'ReNeLLMSynergyAttack',
]
