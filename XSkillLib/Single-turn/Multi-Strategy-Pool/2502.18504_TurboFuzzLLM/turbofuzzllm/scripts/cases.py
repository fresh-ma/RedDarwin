#!/usr/bin/env python3
"""Dataset DTOs + loaders for TurboFuzzLLM — Behavior and Template.

`load_behaviors` reads a HarmBench-style CSV of target behaviors (shuffled by
seed, optional `--sample` slice); `load_templates` reads seed jailbreak templates
(rows must carry the QUESTION_PLACEHOLDER). The Template DTO also carries the
per-template fuzzing bookkeeping (visited count, responses, jailbroken set, ASR).
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass, field
from typing import Any

from prompts import QUESTION_PLACEHOLDER


@dataclass
class Behavior:
    idx: int
    text: str
    behavior_id: str
    row: dict[str, str]



@dataclass
class Template:
    name: str
    text: str
    parent: str | None = None
    root: str | None = None
    mutator: str = "ORIGINAL"
    level: int = 0
    initial_asr: float = 0.0
    visited: int = 0
    unexplored_mutations: list[str] = field(default_factory=list)
    responses: dict[int, dict[str, Any]] = field(default_factory=dict)
    jailbroken_questions: set[int] = field(default_factory=set)

    @property
    def num_attacks(self) -> int:
        return len(self.responses)

    @property
    def num_jailbreaks(self) -> int:
        return len(self.jailbroken_questions)

    @property
    def num_rejects(self) -> int:
        return self.num_attacks - self.num_jailbreaks

    @property
    def asr(self) -> float:
        if self.num_attacks == 0:
            return 0.0
        return self.num_jailbreaks / self.num_attacks



def load_behaviors(path: Path, sample: int, seed: int) -> list[Behavior]:
    rows: list[Behavior] = []
    with path.open(newline="", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        for idx, row in enumerate(reader):
            text = row.get("Behavior") or row.get("text") or row.get("prompt") or row.get("question")
            if not text:
                continue
            behavior_id = row.get("BehaviorID") or row.get("id") or f"behavior_{idx}"
            rows.append(Behavior(idx=idx, text=text, behavior_id=behavior_id, row=row))
    rng = random.Random(seed)
    rng.shuffle(rows)
    return rows[:sample] if sample > 0 else rows



def load_templates(path: Path, mutations: list[str]) -> list[Template]:
    templates: list[Template] = []
    with path.open(newline="", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            name = row.get("template") or row.get("id") or f"O{len(templates)}"
            if not name.startswith("O"):
                name = f"O{name}"
            text = row.get("text") or row.get("template_text") or ""
            if QUESTION_PLACEHOLDER not in text:
                continue
            templates.append(
                Template(
                    name=name,
                    text=text,
                    parent=name,
                    root=name,
                    mutator="ORIGINAL",
                    unexplored_mutations=list(mutations),
                )
            )
    return templates
