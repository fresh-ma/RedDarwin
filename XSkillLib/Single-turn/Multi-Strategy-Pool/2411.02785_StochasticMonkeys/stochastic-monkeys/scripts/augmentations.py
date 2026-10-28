"""augmentations.py — the payload transform for Stochastic Monkeys (arXiv 2411.02785).

This IS the attack: a random augmentation a: X -> X applied to a harmful prompt x before it is sent
to the target g. All character positions and characters are chosen independently and uniformly at
random from the ASCII sample space, i.e. P_aug(.; A) = Unif(A) (paper sec 3.1.1).

Reproduced BYTE-IDENTICAL in logic from the official repo
(uiuc-focal-lab/stochastic-monkeys, `augmentation/`):
  - character.py       -> RandomEdit / RandomInsertion / RandomDeletion
  - string_insertion.py-> RandomSuffix / RandomPrefix / RandomAnywhere
  - none.py            -> NoAugmentation (identity)
  - deepinception.py   -> DeepInception (verbatim template in prompts.py)

Strength is PROPORTIONAL (paper sec 3.1.2): with proportion p and a prompt of length L, the number
of augmented character positions (character-level) or the inserted-string length (string insertion)
is int(p * L), rounded DOWN. The paper's default is p = 0.05.

Every constructor takes `percentage` (== p). String-insertion classes also accept `length` (fixed
strength) exactly as the official code, but the CLI drives the proportional path (paper default).
"""
from __future__ import annotations

import random

from prompts import ASCII_SAMPLE_SPACE, DEEPINCEPTION_SCENES, DEEPINCEPTION_TEMPLATE

PROMPT_STRING_JOIN_SEPARATOR = ""
RANDOM_STRING_JOIN_SEPARATOR = ""
PREFIX_AUGMENTED_PROMPT = "{prefix} {prompt}"
SUFFIX_AUGMENTED_PROMPT = "{prompt} {suffix}"


# --- Character-level augmentations (augmentation/character.py) --------------------------------
class RandomEdit:
    """Randomly edits a fixed percentage of character positions (Edit)."""

    def __init__(self, percentage: float):
        self.percentage = percentage
        self._sample_space = ASCII_SAMPLE_SPACE

    def __call__(self, prompt: str) -> str:
        edit_indices = random.sample(range(len(prompt)), k=int(self.percentage * len(prompt)))
        chars = list(prompt)
        for index in edit_indices:
            chars[index] = random.choice(self._sample_space)
        return PROMPT_STRING_JOIN_SEPARATOR.join(chars)


class RandomInsertion:
    """Inserts random characters at random positions (Insert)."""

    def __init__(self, percentage: float):
        self.percentage = percentage
        self._sample_space = ASCII_SAMPLE_SPACE

    def __call__(self, prompt: str) -> str:
        random_insertion = PROMPT_STRING_JOIN_SEPARATOR.join(
            random.choices(self._sample_space, k=int(len(prompt) * self.percentage))
        )
        indices = random.sample(range(len(prompt)), k=len(random_insertion))
        for i, index in enumerate(sorted(indices)):
            prompt = prompt[: index + i] + random_insertion[i] + prompt[index + i :]
        return prompt


class RandomDeletion:
    """Randomly deletes a fixed percentage of character positions (Delete)."""

    def __init__(self, percentage: float):
        self.percentage = percentage

    def __call__(self, prompt: str) -> str:
        delete_indices = random.sample(range(len(prompt)), k=int(self.percentage * len(prompt)))
        chars = [prompt[i] for i in range(len(prompt)) if i not in delete_indices]
        return PROMPT_STRING_JOIN_SEPARATOR.join(chars)


# --- String-insertion augmentations (augmentation/string_insertion.py) ------------------------
class RandomAnywhere:
    """Inserts a random string at a single random location (Anywhere)."""

    def __init__(self, percentage: float | None = None, length: int | None = None):
        _check_percentage_length(percentage, length)
        self.percentage = percentage
        self.length = length
        self._sample_space = ASCII_SAMPLE_SPACE

    def __call__(self, prompt: str) -> str:
        string_length = self.length if self.length is not None else int(self.percentage * len(prompt))
        random_insertion = RANDOM_STRING_JOIN_SEPARATOR.join(
            random.choices(self._sample_space, k=string_length)
        )
        index = random.randint(0, len(prompt))
        return prompt[:index] + random_insertion + prompt[index:]


class RandomPrefix:
    """Prepends a random string (Prefix)."""

    def __init__(self, percentage: float | None = None, length: int | None = None):
        _check_percentage_length(percentage, length)
        self.percentage = percentage
        self.length = length
        self._sample_space = ASCII_SAMPLE_SPACE

    def __call__(self, prompt: str) -> str:
        string_length = self.length if self.length is not None else int(self.percentage * len(prompt))
        random_prefix = RANDOM_STRING_JOIN_SEPARATOR.join(
            random.choices(self._sample_space, k=string_length)
        )
        return PREFIX_AUGMENTED_PROMPT.format(prompt=prompt, prefix=random_prefix)


class RandomSuffix:
    """Appends a random string (Suffix). The GCG-style random counterpart."""

    def __init__(self, percentage: float | None = None, length: int | None = None):
        _check_percentage_length(percentage, length)
        self.percentage = percentage
        self.length = length
        self._sample_space = ASCII_SAMPLE_SPACE

    def __call__(self, prompt: str) -> str:
        string_length = self.length if self.length is not None else int(self.percentage * len(prompt))
        random_suffix = RANDOM_STRING_JOIN_SEPARATOR.join(
            random.choices(self._sample_space, k=string_length)
        )
        return SUFFIX_AUGMENTED_PROMPT.format(prompt=prompt, suffix=random_suffix)


# --- Baselines --------------------------------------------------------------------------------
class NoAugmentation:
    """Identity (the no-augmentation baseline A_I)."""

    def __init__(self, **_kwargs):
        pass

    def __call__(self, prompt: str) -> str:
        return prompt


class DeepInception:
    """The DeepInception nested-scene template baseline (verbatim template in prompts.py)."""

    def __init__(self, max_characters: int = 5, max_layers: int = 5, **_kwargs):
        self._scene_options = DEEPINCEPTION_SCENES
        self.max_characters = max_characters
        self.max_layers = max_layers

    def __call__(self, prompt: str) -> str:
        scene = self._scene_options[random.randint(0, len(self._scene_options) - 1)]
        num_characters = random.randint(1, self.max_characters)
        num_layers = random.randint(1, self.max_layers)
        return DEEPINCEPTION_TEMPLATE.format(
            scene=scene, num_characters=num_characters, num_layers=num_layers, prompt=prompt
        )


def _check_percentage_length(percentage, length) -> None:
    if percentage is not None and length is not None:
        raise ValueError("Only one of `percentage` or `length` should be specified.")
    if percentage is None and length is None:
        raise ValueError("Either `percentage` or `length` should be specified.")


# Registry mirrors augmentation/augmentation_map.json (verbatim keys).
AUGMENTATIONS = {
    "none": NoAugmentation,
    "string_suffix": RandomSuffix,
    "string_prefix": RandomPrefix,
    "string_anywhere": RandomAnywhere,
    "character_edit": RandomEdit,
    "character_insertion": RandomInsertion,
    "character_deletion": RandomDeletion,
    "deepinception": DeepInception,
}


def build_augmentation(name: str, percentage: float):
    """Instantiate an augmentation by its map key with proportional strength p (paper default path).

    `none`/`deepinception` ignore `percentage`.
    """
    if name not in AUGMENTATIONS:
        raise SystemExit(f"unknown augmentation '{name}'; choose from {sorted(AUGMENTATIONS)}")
    cls = AUGMENTATIONS[name]
    if name in ("none", "deepinception"):
        return cls()
    return cls(percentage=percentage)
