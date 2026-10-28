#!/usr/bin/env python3
"""Mastermind knowledge repository + strategy-level grey-box fuzzing (sec 4.3).

This module is the pure (no-LLM) core of Phase-2:

  * Strategy repository S = {s_1..s_N} — atomic distilled strategies, each a bit in
    the genome. Loaded from data/strategies.json. An optional query->config history
    map (successful strategy vectors keyed by past objective) drives seed scheduling.
  * Genome x in {0,1}^N (sec 4.3 "Fuzzing Formulation"): x_k = 1 activates s_k.
  * Semantic Seed Scheduling (sec 4.3): retrieve the top-K historical objectives most
    similar to q_target and seed the initial population with their successful configs
    (falls back to activating the top-K most relevant strategies when no history).
  * Fuzzing engine operators (sec 4.3): tournament Selection, uniform Crossover
    (each bit inherited from either parent w.p. 0.5), bit-flip Mutation w.p. p_m.

Similarity uses a dependency-free lexical cosine (bag-of-words) so the unit runs
self-contained. The paper uses sentence embeddings; swap `text_similarity` for a
real embedder without touching the GA. Fitness F(x) is supplied by attack.py (it
requires live multi-turn model calls) — this module stays pure and testable.
"""

from __future__ import annotations

import json
import math
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

DEFAULT_STRATEGIES = Path(__file__).resolve().parent.parent / "data" / "strategies.json"

Genome = tuple[int, ...]


@dataclass(frozen=True)
class Strategy:
    name: str
    description: str


@dataclass(frozen=True)
class Repository:
    strategies: tuple[Strategy, ...]
    # optional history: past objective text -> successful genome (for seed scheduling)
    history: tuple[tuple[str, Genome], ...] = ()

    @property
    def size(self) -> int:
        return len(self.strategies)


def load_repository(path: Path | str | None = None) -> Repository:
    p = Path(path) if path else DEFAULT_STRATEGIES
    obj = json.loads(p.read_text(encoding="utf-8"))
    strategies = tuple(Strategy(name=s["name"], description=s["description"]) for s in obj["strategies"])
    n = len(strategies)
    history: list[tuple[str, Genome]] = []
    for h in obj.get("history", []):
        genome = _coerce_genome(h.get("config", []), n)
        history.append((str(h.get("query", "")), genome))
    return Repository(strategies=strategies, history=tuple(history))


def _coerce_genome(config: list[int], n: int) -> Genome:
    bits = [1 if b else 0 for b in config][:n]
    bits += [0] * (n - len(bits))
    return tuple(bits)


def render_active(repo: Repository, genome: Genome) -> str:
    """Render the active strategies of a genome as the S_ret block for the Planner."""
    lines = [
        f"- {s.name}: {s.description}"
        for s, bit in zip(repo.strategies, genome)
        if bit
    ]
    return "\n".join(lines)


def active_names(repo: Repository, genome: Genome) -> list[str]:
    return [s.name for s, bit in zip(repo.strategies, genome) if bit]


# ---------------------------------------------------------------------------
# Lexical similarity (dependency-free stand-in for sentence embeddings)
# ---------------------------------------------------------------------------
_TOKEN = re.compile(r"[a-z0-9]+")


def _bow(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for tok in _TOKEN.findall(text.lower()):
        counts[tok] = counts.get(tok, 0) + 1
    return counts


def text_similarity(a: str, b: str) -> float:
    va, vb = _bow(a), _bow(b)
    if not va or not vb:
        return 0.0
    common = set(va) & set(vb)
    dot = sum(va[t] * vb[t] for t in common)
    na = math.sqrt(sum(v * v for v in va.values()))
    nb = math.sqrt(sum(v * v for v in vb.values()))
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------------------
# Seed scheduling (sec 4.3 "Seed Scheduling")
# ---------------------------------------------------------------------------
def seed_population(
    repo: Repository,
    q_target: str,
    pop_size: int,
    top_k: int,
    rng: random.Random,
    init_active: int = 3,
) -> list[Genome]:
    """Initial population from the top-K semantically nearest historical successes;
    fall back to activating the `init_active` strategies most relevant to q_target."""
    n = repo.size
    seeds: list[Genome] = []
    if repo.history:
        ranked = sorted(
            repo.history, key=lambda hc: text_similarity(q_target, hc[0]), reverse=True
        )
        seeds = [g for _, g in ranked[: max(1, top_k)] if any(g)]
    if not seeds:
        # relevance-ranked strategies: activate the top init_active most similar to q_target
        order = sorted(
            range(n),
            key=lambda i: text_similarity(q_target, repo.strategies[i].description),
            reverse=True,
        )
        base = [0] * n
        for i in order[: max(1, min(init_active, n))]:
            base[i] = 1
        seeds = [tuple(base)]

    population: list[Genome] = []
    while len(population) < pop_size:
        seed = list(rng.choice(seeds))
        # jitter each seed by a couple of random bit flips for diversity
        for _ in range(rng.randint(0, 2)):
            j = rng.randrange(n)
            seed[j] ^= 1
        if not any(seed):  # never an all-zero genome (Planner needs at least one strategy)
            seed[rng.randrange(n)] = 1
        population.append(tuple(seed))
    return population


# ---------------------------------------------------------------------------
# Fuzzing engine operators (sec 4.3 "Fuzzing Engine")
# ---------------------------------------------------------------------------
def tournament_select(
    scored: list[tuple[Genome, float]], k: int, rng: random.Random
) -> Genome:
    """Tournament selection: sample k, return the highest-fitness genome."""
    k = max(1, min(k, len(scored)))
    contenders = rng.sample(scored, k)
    return max(contenders, key=lambda gs: gs[1])[0]


def uniform_crossover(x_a: Genome, x_b: Genome, rng: random.Random) -> Genome:
    """Each bit inherited from either parent with equal probability (sec 4.3)."""
    return tuple(a if rng.random() < 0.5 else b for a, b in zip(x_a, x_b))


def bitflip_mutate(x: Genome, p_m: float, rng: random.Random) -> Genome:
    """Flip each strategy bit with probability p_m (sec 4.3)."""
    child = [b ^ 1 if rng.random() < p_m else b for b in x]
    if not any(child):  # keep at least one active strategy
        child[rng.randrange(len(child))] = 1
    return tuple(child)


def evolve_generation(
    scored: list[tuple[Genome, float]],
    pop_size: int,
    tournament_k: int,
    p_m: float,
    rng: random.Random,
    elitism: int = 1,
) -> list[Genome]:
    """Build the next generation: elitism + tournament-selected crossover+mutation."""
    ordered = sorted(scored, key=lambda gs: gs[1], reverse=True)
    nxt: list[Genome] = [g for g, _ in ordered[:elitism]]
    while len(nxt) < pop_size:
        parent_a = tournament_select(scored, tournament_k, rng)
        parent_b = tournament_select(scored, tournament_k, rng)
        child = uniform_crossover(parent_a, parent_b, rng)
        child = bitflip_mutate(child, p_m, rng)
        nxt.append(child)
    return nxt[:pop_size]


def run_fuzzing(
    repo: Repository,
    q_target: str,
    fitness: Callable[[Genome], tuple[float, dict]],
    *,
    pop_size: int,
    generations: int,
    top_k: int,
    tournament_k: int,
    p_m: float,
    success_score: float,
    rng: random.Random,
) -> dict:
    """Strategy-level grey-box fuzzing loop (sec 4.3). `fitness(genome)` returns
    (score, episode_record); the loop early-stops when score >= success_score.
    Memoizes genomes so re-evaluated survivors don't re-run the conversation."""
    cache: dict[Genome, tuple[float, dict]] = {}

    def evaluate(g: Genome) -> tuple[float, dict]:
        if g not in cache:
            cache[g] = fitness(g)
        return cache[g]

    population = seed_population(repo, q_target, pop_size, top_k, rng)
    best_genome: Genome | None = None
    best_score = -1.0
    best_episode: dict = {}
    generations_run = 0
    solved = False

    for gen in range(1, generations + 1):
        generations_run = gen
        scored: list[tuple[Genome, float]] = []
        for genome in population:
            score, episode = evaluate(genome)
            scored.append((genome, score))
            if score > best_score:
                best_score, best_genome, best_episode = score, genome, episode
            if score >= success_score:
                solved = True
                break
        if solved:
            break
        population = evolve_generation(scored, pop_size, tournament_k, p_m, rng)

    return {
        "best_genome": list(best_genome) if best_genome is not None else [],
        "best_active_strategies": active_names(repo, best_genome) if best_genome is not None else [],
        "best_score": best_score,
        "solved": solved,
        "generations_run": generations_run,
        "genomes_evaluated": len(cache),
        "best_episode": best_episode,
    }
