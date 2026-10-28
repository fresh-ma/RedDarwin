"""Evaluator manager for running multiple evaluation methods."""

import logging
from typing import Dict, List, Optional
from .base_evaluator import BaseEvaluator, EvaluationResult
from .string_match_evaluator import StringMatchEvaluator
from .model_judge_evaluator import ModelJudgeEvaluator
from .majority_vote_judge import MajorityVoteJudgeEvaluator

logger = logging.getLogger(__name__)


class EvaluatorManager:
    def __init__(self):
        self.evaluators: Dict[str, BaseEvaluator] = {
            "string_match": StringMatchEvaluator()
        }

    def add_model_judge_evaluator(self, judge_model, name: str = "model_judge",
                                   judge_prompt: Optional[str] = None):
        self.evaluators[name] = ModelJudgeEvaluator(judge_model, judge_prompt)

    def add_majority_vote_judge(self, judge_models: List,
                                judge_names: Optional[List[str]] = None,
                                name: str = "model_judge"):
        self.evaluators[name] = MajorityVoteJudgeEvaluator(
            judge_models=judge_models, judge_names=judge_names
        )

    def evaluate(self, instruction: str, response: str,
                 evaluator_name: str = "string_match", **kwargs) -> EvaluationResult:
        if evaluator_name not in self.evaluators:
            raise ValueError(f"Unknown evaluator: {evaluator_name}")
        try:
            return self.evaluators[evaluator_name].evaluate(instruction, response, **kwargs)
        except Exception as e:
            logger.error(f"Evaluation error ({evaluator_name}): {e}")
            return EvaluationResult(passed=False, evaluation_method=evaluator_name,
                                    details={"error": str(e)})
