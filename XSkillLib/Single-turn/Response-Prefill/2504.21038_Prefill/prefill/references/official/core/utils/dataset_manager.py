"""Dataset loading and management."""

import os
import csv
import random
import logging
from typing import Dict, List, Tuple, Optional, Any

logger = logging.getLogger(__name__)


class DatasetManager:
    """Manages loading and sampling from attack datasets."""

    def __init__(self, datasets_dir: str = "dataset"):
        self.datasets_dir = datasets_dir
        self.datasets: Dict[str, Dict[str, Any]] = {}

    def load_advbench(
        self, file_path: Optional[str] = None
    ) -> Tuple[List[str], Dict[str, str]]:
        """Load AdvBench harmful behaviors dataset.
        Supports both CSV (with goal/target columns) and plain text (one instruction per line).
        Returns (instructions_list, {instruction: target} dict).
        """
        if file_path is None:
            file_path = os.path.join(self.datasets_dir, "advbench.txt")

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Dataset not found: {file_path}")

        instructions, targets = [], {}

        if file_path.endswith('.csv'):
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    goal = row.get("goal", "").strip()
                    target = row.get("target", "").strip()
                    if goal:
                        instructions.append(goal)
                        if target:
                            targets[goal] = target
        else:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        instructions.append(line)

        self.datasets["advbench"] = {
            "instructions": instructions,
            "targets": targets,
            "file_path": file_path,
        }
        logger.info(f"Loaded AdvBench: {len(instructions)} instructions")
        return instructions, targets

    def get_sample_instructions(
        self, dataset_name: str = "advbench",
        num_samples: Optional[int] = None,
        random_seed: Optional[int] = None,
    ) -> List[str]:
        if dataset_name not in self.datasets:
            self.load_advbench()
        instructions = self.datasets[dataset_name]["instructions"]
        if num_samples is None or num_samples >= len(instructions):
            return instructions
        if random_seed is not None:
            rng = random.Random(random_seed)
            return rng.sample(instructions, num_samples)
        return random.sample(instructions, num_samples)

    def get_targets_dict(self, dataset_name: str = "advbench") -> Dict[str, str]:
        if dataset_name not in self.datasets:
            self.load_advbench()
        return self.datasets[dataset_name].get("targets", {})
