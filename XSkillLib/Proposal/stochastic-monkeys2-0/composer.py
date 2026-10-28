"""composer.py — semantic augmentation operator for Stochastic Monkeys 2.0.

The parent skill drew k i.i.d. random ASCII perturbations.  SM2.0 keeps the
open-loop best-of-n search but replaces the perturbation operator with a
stochastic compositional generator over lightweight jailbreak primitives.
Each sampled composition is a coherent prompt, not noise.

No attacker LLM is used; composition is pure Python random sampling.  The
operator is goal-agnostic and victim-agnostic.
"""
from __future__ import annotations

import random
import string

from prompts import (
    ASCII_SAMPLE_SPACE,
    ENCODING_HINTS,
    INSTRUCTION_SUFFIXES,
    PERSONA_PREFIXES,
    PREFILL_SUFFIXES,
    SCENARIO_WRAPPERS,
)


# --- lightweight reversible transforms used as encoding primitives ---------------

def _reverse_words(text: str) -> str:
    return " ".join(word[::-1] for word in text.split())


def _drop_first_letters(text: str) -> str:
    return " ".join(word[1:] if len(word) > 1 else word for word in text.split())


def _caesar_plus_1(text: str) -> str:
    def shift(ch: str) -> str:
        if ch.isalpha():
            base = ord("a") if ch.islower() else ord("A")
            return chr(base + (ord(ch) - base + 1) % 26)
        return ch
    return "".join(shift(ch) for ch in text)


def _leet_simple(text: str) -> str:
    mapping = {"e": "3", "a": "4", "o": "0", "E": "3", "A": "4", "O": "0"}
    return "".join(mapping.get(ch, ch) for ch in text)


def _random_char_perturb(text: str, p: float) -> str:
    """Parent character_edit primitive, kept as one optional noise layer."""
    if not text:
        return text
    k = max(1, int(p * len(text)))
    indices = random.sample(range(len(text)), k=min(k, len(text)))
    chars = list(text)
    for idx in indices:
        chars[idx] = random.choice(ASCII_SAMPLE_SPACE)
    return "".join(chars)


_ENCODING_TRANSFORMS = {
    "reverse_words": _reverse_words,
    "drop_first": _drop_first_letters,
    "caesar1": _caesar_plus_1,
    "leet": _leet_simple,
}

_ENCODING_HINT_FOR_TRANSFORM = {
    "reverse_words": ENCODING_HINTS[0],
    "drop_first": ENCODING_HINTS[1],
    "caesar1": ENCODING_HINTS[2],
    "leet": ENCODING_HINTS[3],
}


class SemanticComposer:
    """Stochastic compositional generator for jailbreak prompts.

    For each call, it independently samples a subset of primitive categories
    (persona, scenario, instruction, prefill, encoding, noise) and chains them
    into one user message.  The sampling probabilities and primitive pools are
    fixed; no goal- or victim-specific logic is allowed.

    Parameters:
      variant: composition strategy.
          - "semantic" (default): only semantic primitives, no noise.
          - "semantic-noise": semantic primitives + light character perturbation.
          - "heavy": higher chance of stacking multiple primitives.
      p_noise: strength of the optional character perturbation (default 0.03).
      seed: optional; when None the global RNG is used.
    """

    VARIANTS = ("semantic", "semantic-noise", "heavy")

    def __init__(self, variant: str = "semantic", p_noise: float = 0.03, seed: int | None = None):
        if variant not in self.VARIANTS:
            raise ValueError(f"unknown variant {variant!r}; choose from {self.VARIANTS}")
        self.variant = variant
        self.p_noise = p_noise
        self._rng = random.Random(seed)

    def _sample(self, pool: list[str]) -> str:
        return self._rng.choice(pool)

    def _maybe(self, probability: float) -> bool:
        return self._rng.random() < probability

    def __call__(self, goal: str) -> str:
        rng = self._rng
        use_persona = self._maybe(0.25)
        use_scenario = self._maybe(0.65)
        use_instruction = self._maybe(0.70)
        use_prefill = self._maybe(0.40)
        use_encoding = self._maybe(0.12)
        use_noise = self.variant in ("semantic-noise", "heavy") and self._maybe(0.30)

        if self.variant == "heavy":
            # Bias toward richer stacks in the heavy variant.
            use_persona = use_persona or self._maybe(0.25)
            use_scenario = use_scenario or self._maybe(0.30)
            use_instruction = use_instruction or self._maybe(0.30)
            use_prefill = use_prefill or self._maybe(0.35)

        prompt = goal

        if use_persona:
            prompt = self._sample(PERSONA_PREFIXES).format(goal=prompt)
        if use_scenario:
            prompt = self._sample(SCENARIO_WRAPPERS).format(goal=prompt)
        if use_instruction:
            prompt = prompt + self._sample(INSTRUCTION_SUFFIXES)
        if use_prefill:
            prompt = prompt + self._sample(PREFILL_SUFFIXES)
        if use_encoding:
            transform_name = rng.choice(list(_ENCODING_TRANSFORMS.keys()))
            transformed = _ENCODING_TRANSFORMS[transform_name](goal if not (use_persona or use_scenario) else prompt)
            if transform_name in _ENCODING_HINT_FOR_TRANSFORM:
                # Use the hint template but replace the literal goal with the
                # transformed text so the inline instruction is consistent.
                hint = _ENCODING_HINT_FOR_TRANSFORM[transform_name]
                prompt = hint.format(goal=transformed)
            else:
                prompt = transformed
        if use_noise:
            prompt = _random_char_perturb(prompt, self.p_noise)

        # Ensure we never return the verbatim goal unchanged by forcing a thin
        # semantic wrapper if nothing was sampled.
        if not (use_persona or use_scenario or use_instruction or use_prefill or use_encoding or use_noise):
            prompt = prompt + self._sample(INSTRUCTION_SUFFIXES)

        return prompt


# --- Registry mirroring the parent's augmentation_map style ----------------------

def build_composer(variant: str = "semantic", p_noise: float = 0.03, seed: int | None = None) -> SemanticComposer:
    return SemanticComposer(variant=variant, p_noise=p_noise, seed=seed)
