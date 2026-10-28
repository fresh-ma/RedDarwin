#!/usr/bin/env python3
"""Bio-inspired (fruit-fly) optimization operators for CC-BOS.

Faithful port of the Fruit-Fly Optimization search over the eight-dimensional
strategy space (official gen.py): stratified init, smell (local step with decay),
vision (attraction to the best fly), and Cauchy mutation, plus the
unique-candidate acceptance loop.
"""

from __future__ import annotations

import math
import random

from prompts import DIMENSION_OPTIONS, DIM_KEYS

# Official constants (gen.py + digest §10.1 Parameter Settings).
DECAY_RATE = 0.95
CAUCHY_SCALE = 0.2
STAGNATION_THRESHOLD = 2
MAX_UNIQUE_ATTEMPTS = 5


def fly_key(fly: dict[str, int]) -> tuple[int, ...]:
    return tuple(fly[dim] for dim in DIM_KEYS)


def stratified_samples(values: list[int], population_size: int, rng: random.Random) -> list[int]:
    samples: list[int] = []
    while len(samples) < population_size:
        shuffled = values[:]
        rng.shuffle(shuffled)
        samples.extend(shuffled)
    return samples[:population_size]


def initialize_population(population_size: int, rng: random.Random) -> list[dict[str, int]]:
    dim_samples = {
        dim: stratified_samples(list(range(len(options))), population_size, rng)
        for dim, options in DIMENSION_OPTIONS.items()
    }
    return [{dim: dim_samples[dim][i] for dim in DIMENSION_OPTIONS} for i in range(population_size)]


def smell_search(fly: dict[str, int], iteration: int, rng: random.Random,
                 decay_rate: float = DECAY_RATE) -> dict[str, int]:
    decay = decay_rate**iteration
    mutated = fly.copy()
    for dim, value in fly.items():
        width = max(1, int(len(DIMENSION_OPTIONS[dim]) * 0.3 * decay))
        step = rng.randint(-width, width)
        mutated[dim] = (value + step) % len(DIMENSION_OPTIONS[dim])
    return mutated


def vision_search(fly: dict[str, int], best_fly: dict[str, int], iteration: int,
                  max_iter: int, rng: random.Random) -> dict[str, int]:
    attraction = 0.3 + 0.7 * (iteration / max(1, max_iter))
    return {
        dim: best_fly[dim] if rng.random() < attraction else fly[dim]
        for dim in fly
    }


def cauchy_mutation(fly: dict[str, int], rng: random.Random,
                    mutation_probability: float = 0.3, scale: float = CAUCHY_SCALE) -> dict[str, int]:
    mutated = fly.copy()
    for dim, value in fly.items():
        if rng.random() < mutation_probability:
            # standard Cauchy sample via inverse-CDF (tan(pi*(u-0.5))), scaled.
            perturb = int(math.tan(math.pi * (rng.random() - 0.5)) * scale)
            mutated[dim] = (value + perturb) % len(DIMENSION_OPTIONS[dim])
    return mutated


def unique_candidates(
    population: list[dict[str, int]],
    explored: set[tuple[int, ...]],
    operator,
    rng: random.Random,
    attempts: int = MAX_UNIQUE_ATTEMPTS,
) -> list[dict[str, int]]:
    new_population = []
    for fly in population:
        last = fly
        for _ in range(attempts):
            candidate = operator(fly)
            last = candidate
            key = fly_key(candidate)
            if key not in explored:
                explored.add(key)
                new_population.append(candidate)
                break
        else:
            explored.add(fly_key(last))
            new_population.append(last)
    return new_population
