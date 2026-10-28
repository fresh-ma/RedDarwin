"""Experiment entry point for prefill-level jailbreak attacks.

Usage:
    python main.py --config configs/default.yaml
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime
from dataclasses import asdict
from typing import Dict, List, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

from core.utils.config_manager import ConfigManager, ExperimentConfig
from core.utils.dataset_manager import DatasetManager
from core.utils.logger import setup_logging
from core.models.model_manager import ModelManager
from core.attacks.attack_manager import AttackManager
from core.evaluators.evaluator_manager import EvaluatorManager

logger = logging.getLogger(__name__)


class Experiment:
    """Runs the full prefill-level jailbreak experiment."""

    def __init__(self, config: ExperimentConfig):
        self.config = config
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.model_manager = ModelManager()
        self.dataset_manager = DatasetManager()
        self.evaluator_manager = EvaluatorManager()

        # Load dataset
        instructions, targets = self.dataset_manager.load_advbench(
            config.dataset_config.file_path)
        self.attack_manager = AttackManager(advbench_targets=targets)

        # Initialize models
        self.victim_models = []
        self.attacker_model = None
        self._init_models()
        self._init_evaluators()

    def _init_models(self):
        for mc in self.config.victim_models:
            model = self.model_manager.create_model(
                mc.provider, mc.model_name, mc.api_key,
                max_retries=mc.max_retries, max_tokens=mc.max_tokens)
            self.victim_models.append((mc, model))

        ac = self.config.attacker_model
        self.attacker_model = self.model_manager.create_model(
            ac.provider, ac.model_name, ac.api_key, max_retries=ac.max_retries)

    def _init_evaluators(self):
        if "model_judge" not in (self.config.evaluation_config.evaluators or []):
            return

        if self.config.judge_models and len(self.config.judge_models) > 1:
            judge_instances = []
            judge_names = []
            for jc in self.config.judge_models:
                model = self.model_manager.create_model(
                    jc.provider, jc.model_name, jc.api_key, max_retries=jc.max_retries)
                judge_instances.append(model)
                judge_names.append(f"{jc.provider}/{jc.model_name}")
            self.evaluator_manager.add_majority_vote_judge(
                judge_models=judge_instances, judge_names=judge_names)
            logger.info(f"Initialized majority vote judge with {len(judge_instances)} models: {judge_names}")
        elif self.config.judge_model:
            jc = self.config.judge_model
            judge = self.model_manager.create_model(
                jc.provider, jc.model_name, jc.api_key, max_retries=jc.max_retries)
            self.evaluator_manager.add_model_judge_evaluator(judge)
            logger.info(f"Initialized single model judge: {jc.provider}/{jc.model_name}")

    def run(self) -> Dict[str, Any]:
        logger.info("Starting experiment")
        instructions = self.dataset_manager.get_sample_instructions(
            dataset_name=self.config.dataset_config.name,
            num_samples=self.config.dataset_config.num_samples,
            random_seed=self.config.dataset_config.random_seed)

        all_results = {}
        for mc, victim_model in self.victim_models:
            model_name = f"{mc.provider}/{mc.model_name}"
            logger.info(f"Testing model: {model_name}")
            results = self._test_model(victim_model, mc, instructions)
            all_results[model_name] = results

        report = self._build_report(all_results, instructions)
        self._save(report)
        return report

    def _test_model(self, victim_model, model_config, instructions: List[str]) -> List[Dict]:
        methods = self.config.attack_config.attack_methods
        gen_method = self.config.attack_config.generation_method
        max_iter = self.config.attack_config.max_iterations
        pool_size = self.config.attack_config.prefix_pool_size
        workers = self.config.parallel_workers
        results = []

        tasks = [(inst, atk) for inst in instructions for atk in methods]
        total = len(tasks)

        def run_single(inst, atk):
            attack_result = self.attack_manager.execute_attack(
                attack_name=atk, instruction=inst, victim_model=victim_model,
                method=gen_method, attacker_model=self.attacker_model,
                max_iterations=max_iter, temperature=model_config.temperature,
                pool_size=pool_size)
            evals = {}
            for ev_name in self.config.evaluation_config.evaluators:
                ev = self.evaluator_manager.evaluate(inst, attack_result.victim_response, ev_name)
                evals[ev_name] = {"passed": ev.passed, "details": ev.details}
            return {
                "instruction": inst, "attack_method": atk,
                "attack_result": asdict(attack_result),
                "evaluations": evals,
                "any_eval_passed": any(e["passed"] for e in evals.values()),
            }

        with tqdm(total=total, desc=f"Attacking {model_config.model_name}") as pbar:
            if workers > 1:
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = {executor.submit(run_single, i, a): (i, a) for i, a in tasks}
                    for future in as_completed(futures):
                        try:
                            results.append(future.result())
                        except Exception as e:
                            inst, atk = futures[future]
                            logger.error(f"Task failed ({atk}): {e}")
                        pbar.update(1)
            else:
                for inst, atk in tasks:
                    results.append(run_single(inst, atk))
                    pbar.update(1)
        return results

    def _build_report(self, all_results, instructions) -> Dict[str, Any]:
        report = {
            "timestamp": self.timestamp,
            "config": {
                "generation_method": self.config.attack_config.generation_method,
                "max_iterations": self.config.attack_config.max_iterations,
                "attack_methods": self.config.attack_config.attack_methods,
                "num_instructions": len(instructions),
            },
            "model_results": {},
        }
        for model_name, results in all_results.items():
            total = len(results)
            sm_pass = sum(1 for r in results if r["evaluations"].get("string_match", {}).get("passed", False))
            mj_pass = sum(1 for r in results if r["evaluations"].get("model_judge", {}).get("passed", False))
            any_pass = sum(1 for r in results if r["any_eval_passed"])
            report["model_results"][model_name] = {
                "total_attacks": total,
                "string_match_asr": sm_pass / total if total else 0,
                "model_judge_asr": mj_pass / total if total else 0,
                "overall_asr": any_pass / total if total else 0,
                "detailed_results": results,
            }
            logger.info(f"[{model_name}] SM ASR: {sm_pass}/{total} = {sm_pass/total:.2%}, "
                        f"MJ ASR: {mj_pass}/{total} = {mj_pass/total:.2%}")
        return report

    def _save(self, report: Dict):
        os.makedirs(self.config.output_dir, exist_ok=True)
        path = os.path.join(self.config.output_dir, f"results_{self.timestamp}.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"Results saved to {path}")


def main():
    parser = argparse.ArgumentParser(description="Prefill-Level Jailbreak Attack Experiment")
    parser.add_argument("--config", type=str, default="configs/default.yaml", help="Config file path")
    args = parser.parse_args()

    setup_logging()
    cm = ConfigManager()
    config = cm.load_config(args.config)
    experiment = Experiment(config)
    experiment.run()


if __name__ == "__main__":
    main()
