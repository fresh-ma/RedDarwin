"""ReNeLLM (Rewriting the Nested LLM) attack implementation."""

from typing import Tuple, Dict
from .base_attack import BaseAttack
from ..utils.prompt_rewrite import PromptRewriter
from ..utils.scenario_nesting import ScenarioNester
from ..utils.attack_judge import AttackJudge


class ReNeLLMAttack(BaseAttack):
    def __init__(self):
        super().__init__("renellm", "ReNeLLM — prompt rewriting + scenario nesting attack")
        self.rewriter = PromptRewriter()
        self.nester = ScenarioNester()
        self.judge = AttackJudge()

    def generate_static_prefill(self, instruction: str, **kwargs) -> str:
        return ""

    def generate_prompt(self, instruction: str, **kwargs) -> str:
        model = kwargs.get('rewrite_model')
        if model is None:
            return instruction
        try:
            rewritten, _ = self.rewriter.rewrite_prompt(instruction, model)
            return self.nester.nest_prompt(rewritten)
        except Exception:
            return instruction

    def generate_adaptive_prefill(self, instruction, victim_model, attacker_model,
                                   max_iterations=10, **kwargs) -> Tuple[str, int]:
        judge_model = kwargs.get('judge_model', attacker_model)
        original = instruction

        for iteration in range(max_iterations):
            try:
                # Rewrite until it passes harmfulness check (looks benign)
                rewritten = None
                for _ in range(10):
                    temp, _ = self.rewriter.rewrite_prompt(instruction, attacker_model, temperature=0.8)
                    if not self.judge.judge_harmfulness_binary(temp, judge_model):
                        rewritten = temp
                        break
                if rewritten is None:
                    rewritten = instruction

                nested = self.nester.nest_prompt(rewritten)
                resp = victim_model.call(messages=[{"role": "user", "content": nested}], temperature=0.7)

                if not self.judge.quick_refusal_check(resp):
                    if self.judge.judge_harmfulness_binary(resp, judge_model):
                        return nested, iteration + 1

                instruction = original
            except Exception as e:
                self.logger.warning(f"ReNeLLM iteration {iteration+1} error: {e}")
                continue

        try:
            final, _ = self.rewriter.rewrite_prompt(original, attacker_model, temperature=0.5)
            return self.nester.nest_prompt(final), max_iterations
        except Exception:
            return original, max_iterations
