"""Configuration management for experiments."""

import os
import yaml
import json
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class ModelConfig:
    provider: str
    model_name: str
    api_key: Optional[str] = None
    max_retries: int = 3
    temperature: float = 0.7
    max_tokens: Optional[int] = None


@dataclass
class AttackConfig:
    attack_methods: List[str]
    generation_method: str = "static"  # "static" or "adaptive"
    max_iterations: int = 10
    prefix_pool_size: int = 5  # candidate pool size for adaptive prefix selection
    enable_all_attacks: bool = False


@dataclass
class DatasetConfig:
    name: str = "advbench"
    file_path: Optional[str] = None
    num_samples: Optional[int] = None
    random_seed: Optional[int] = None


@dataclass
class EvaluationConfig:
    evaluators: List[str] = None
    def __post_init__(self):
        if self.evaluators is None:
            self.evaluators = ["string_match"]


@dataclass
class ExperimentConfig:
    victim_models: List[ModelConfig]
    attacker_model: ModelConfig
    judge_model: Optional[ModelConfig] = None
    judge_models: Optional[List[ModelConfig]] = None
    attack_config: AttackConfig = None
    dataset_config: DatasetConfig = None
    evaluation_config: EvaluationConfig = None
    output_dir: str = "results"
    parallel_workers: int = 1
    model_parallel_workers: int = 1
    save_format: str = "json"

    def __post_init__(self):
        if self.attack_config is None:
            self.attack_config = AttackConfig(attack_methods=["commitment_forcing"])
        if self.dataset_config is None:
            self.dataset_config = DatasetConfig()
        if self.evaluation_config is None:
            self.evaluation_config = EvaluationConfig()


class ConfigManager:
    """Load and manage experiment configurations."""

    def __init__(self, config_dir: str = "configs"):
        self.config_dir = config_dir
        self.current_config: Optional[ExperimentConfig] = None

    def load_config(self, config_file: str) -> ExperimentConfig:
        with open(config_file, 'r', encoding='utf-8') as f:
            if config_file.endswith(('.yaml', '.yml')):
                data = yaml.safe_load(f)
            else:
                data = json.load(f)
        config = self._dict_to_config(data)
        self.current_config = config
        return config

    def _dict_to_config(self, d: Dict[str, Any]) -> ExperimentConfig:
        victim_models = [ModelConfig(**m) for m in d.get("victim_models", [])]
        attacker_model = ModelConfig(**d["attacker_model"])
        judge_model = ModelConfig(**d["judge_model"]) if "judge_model" in d else None
        judge_models = (
            [ModelConfig(**m) for m in d["judge_models"]]
            if "judge_models" in d else None
        )
        attack_config = AttackConfig(**d["attack_config"]) if "attack_config" in d else None
        dataset_config = DatasetConfig(**d["dataset_config"]) if "dataset_config" in d else None
        eval_config = EvaluationConfig(**d["evaluation_config"]) if "evaluation_config" in d else None
        return ExperimentConfig(
            victim_models=victim_models,
            attacker_model=attacker_model,
            judge_model=judge_model,
            judge_models=judge_models,
            attack_config=attack_config,
            dataset_config=dataset_config,
            evaluation_config=eval_config,
            output_dir=d.get("output_dir", "results"),
            parallel_workers=d.get("parallel_workers", 1),
            model_parallel_workers=d.get("model_parallel_workers", 1),
            save_format=d.get("save_format", "json"),
        )
