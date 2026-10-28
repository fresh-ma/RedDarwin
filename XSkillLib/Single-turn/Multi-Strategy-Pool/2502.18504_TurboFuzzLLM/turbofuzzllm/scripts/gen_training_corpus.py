#!/usr/bin/env python3
"""Generate a TurboFuzzLLM red-team training corpus: {harmful goal -> jailbreak payload}.

Thin wrapper over attack.py. Reuses the paper's real mutation operators and the
real payload-assembly step (synthesis_message). TurboFuzzLLM fuzzes *templates*,
which are goal-agnostic: an evolved template wraps every behavior. So we evolve a
pool of genuine templates once -- LLM-driven mutations (generate_similar /
expand_before / expand_after / rephrase / shorten / crossover) via
api:deepseek/deepseek-v4-flash, plus the algorithmic static mutations (identity /
refusal_suppression / inject_prefix) -- then apply that pool across the FULL
HarmBench dataset, emitting one genuine payload per goal.

Quality-filtered: drops empty / too-short / genuine-leading-refusal /
degenerate-echo (template adds no scaffolding) / duplicate payloads.
"""

from __future__ import annotations

import json
import random
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import attack  # noqa: E402  (paper-local module; real mutation/template functions)

METHOD_DIR = SCRIPT_DIR.parent
DATASET = SCRIPT_DIR / "data" / "harmbench_behaviors_text_all.csv"
SEED_TEMPLATES = SCRIPT_DIR / "data" / "no_template.csv"
OUT_PATH = METHOD_DIR / "data" / "training_corpus" / "sft_turbofuzzllm.json"

GENERATOR_MODEL = "api:deepseek/deepseek-v4-flash"
SEED = 7
MIN_LEN = 15

# Mutation operators viable from a single seed (few_shots / transfer need
# previously-successful templates, so they are excluded from cold-start pooling).
STATIC_OPS = ["identity", "refusal_suppression", "inject_prefix"]
LLM_OPS_L1 = {
    "generate_similar": 3,
    "expand_before": 2,
    "expand_after": 2,
    "rephrase": 2,
    "shorten": 2,
    "crossover": 2,
}
# A second level deepens diversity: re-mutate level-1 LLM templates.
LLM_OPS_L2 = ["expand_after", "rephrase", "generate_similar"]

REFUSAL_PREFIXES = (
    "i'm sorry", "i am sorry", "i'm not able", "i am not able", "i cannot",
    "i can't", "i can not", "i apologize", "i apologise", "sorry, but",
    "as an ai", "i'm unable", "i am unable", "unfortunately, i",
    "i must decline", "i won't", "i will not",
)


def make_client() -> attack.OpenRouterClient:
    return attack.OpenRouterClient(GENERATOR_MODEL, 1.0, 600, 180, 0.0)


def scaffold_len(template_text: str) -> int:
    """Non-placeholder character count -- measures how much the template adds."""
    return len(template_text.replace(attack.QUESTION_PLACEHOLDER, "").strip())


def is_leading_refusal(payload: str) -> bool:
    head = payload.lstrip().lower()[:60]
    return any(head.startswith(p) for p in REFUSAL_PREFIXES)


def build_template_pool() -> list[attack.Template]:
    """Evolve a genuine template pool via the paper's real mutate() operators."""
    all_ops = STATIC_OPS + list(LLM_OPS_L1) + LLM_OPS_L2
    mutations = attack.parse_mutations(",".join(dict.fromkeys(all_ops)))
    seeds = attack.load_templates(SEED_TEMPLATES, mutations)
    if not seeds:
        raise RuntimeError("no seed templates loaded")
    seed = seeds[0]

    client = make_client()
    pool: list[attack.Template] = []
    lock = threading.Lock()
    gen_counter = {"n": 0}

    def add_template(text: str, mutator: str, parent: str) -> attack.Template | None:
        if attack.QUESTION_PLACEHOLDER not in text:
            return None
        with lock:
            gen_counter["n"] += 1
            name = f"G{gen_counter['n']}"
        t = attack.Template(
            name=name, text=text, parent=parent, root=seed.name,
            mutator=mutator, unexplored_mutations=list(mutations),
        )
        with lock:
            pool.append(t)
        return t

    # Static mutations (algorithmic, deterministic) -- always genuine payloads.
    for op in STATIC_OPS:
        text, _ = attack.mutate(seed, op, [seed], None, random.Random(SEED), set())
        add_template(text, op, seed.name)

    # Level-1 LLM mutations from the seed, sampled for diversity (threaded).
    def llm_l1(op: str, sample_idx: int) -> attack.Template | None:
        rng = random.Random(SEED + hash((op, sample_idx)) % 100000)
        try:
            text, trace = attack.mutate(seed, op, [seed] + pool, client, rng, set())
        except Exception:  # one failed mutation must not kill the pool build
            return None
        if trace.get("mutator_error") or not text:
            return None
        return add_template(text, op, seed.name)

    jobs_l1 = [(op, i) for op, n in LLM_OPS_L1.items() for i in range(n)]
    with ThreadPoolExecutor(max_workers=8) as ex:
        l1_results = list(ex.map(lambda a: llm_l1(*a), jobs_l1))
    l1_llm = [t for t in l1_results if t is not None]

    # Level-2 LLM mutations: deepen a few of the richest level-1 templates.
    parents_l2 = sorted(l1_llm, key=lambda t: len(t.text), reverse=True)[:3]

    def llm_l2(parent: attack.Template, op: str) -> attack.Template | None:
        rng = random.Random(SEED + hash((parent.name, op)) % 100000)
        try:
            text, trace = attack.mutate(parent, op, [seed] + pool, client, rng, set())
        except Exception:  # one failed mutation must not kill the pool build
            return None
        if trace.get("mutator_error") or not text:
            return None
        return add_template(text, op, parent.name)

    jobs_l2 = [(p, op) for p in parents_l2 for op in LLM_OPS_L2]
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda a: llm_l2(*a), jobs_l2))

    return pool


def main() -> None:
    attack.load_dotenv()
    rng = random.Random(SEED)

    behaviors = attack.load_behaviors(DATASET, sample=0, seed=SEED)  # FULL dataset
    total_attempted = len(behaviors)
    if not behaviors:
        raise RuntimeError("no behaviors loaded")

    pool = build_template_pool()
    if not pool:
        raise RuntimeError("template pool is empty")
    print(f"[pool] {len(pool)} templates: "
          + ", ".join(f"{t.name}:{t.mutator}" for t in pool))

    # Assign templates to goals (seeded round-robin over a shuffled pool).
    shuffled_pool = list(pool)
    rng.shuffle(shuffled_pool)

    rows: list[dict] = []
    seen_payloads: set[str] = set()
    drop_counts = {
        "empty": 0, "too_short": 0, "leading_refusal": 0,
        "degenerate_echo": 0, "duplicate": 0,
    }
    drop_examples: dict[str, str] = {}

    for i, behavior in enumerate(behaviors):
        template = shuffled_pool[i % len(shuffled_pool)]
        payload = attack.synthesis_message(behavior.text, template.text)

        if not payload.strip():
            drop_counts["empty"] += 1
            drop_examples.setdefault("empty", f"{behavior.behavior_id} -> <empty>")
            continue
        if len(payload.strip()) < MIN_LEN:
            drop_counts["too_short"] += 1
            drop_examples.setdefault("too_short", f"{behavior.behavior_id} -> {payload!r}")
            continue
        if is_leading_refusal(payload):
            drop_counts["leading_refusal"] += 1
            drop_examples.setdefault("leading_refusal", f"{behavior.behavior_id} -> {payload[:80]!r}")
            continue
        if scaffold_len(template.text) < MIN_LEN:
            drop_counts["degenerate_echo"] += 1
            drop_examples.setdefault(
                "degenerate_echo",
                f"{behavior.behavior_id} (template {template.name}:{template.mutator}) -> {payload[:80]!r}",
            )
            continue
        if payload in seen_payloads:
            drop_counts["duplicate"] += 1
            drop_examples.setdefault("duplicate", f"{behavior.behavior_id}")
            continue

        seen_payloads.add(payload)
        rows.append({
            "goal": behavior.text,
            "behavior_id": behavior.behavior_id,
            "payload": payload,
            "template_name": template.name,
            "template_mutator": template.mutator,
        })

    dropped = sum(drop_counts.values())
    distinct = len({r["payload"] for r in rows})

    out = {
        "paper_id": attack.PAPER_ID,
        "method": attack.METHOD_ID,
        "generator_model": GENERATOR_MODEL,
        "generator_note": (
            "Templates evolved by LLM-driven mutation (api:deepseek/deepseek-v4-flash) "
            "+ algorithmic static mutations (identity/refusal_suppression/inject_prefix); "
            "per-goal payload = algorithmic synthesis_message(goal, evolved_template). "
            "Templates are goal-agnostic per the paper's design."
        ),
        "payload_field": "payload",
        "count": len(rows),
        "dropped": dropped,
        "drop_counts": drop_counts,
        "total_attempted": total_attempted,
        "distinct_outputs": distinct,
        "template_pool_size": len(pool),
        "seed": SEED,
        "rows": rows,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({
        "out": str(OUT_PATH),
        "total_attempted": total_attempted,
        "kept": len(rows),
        "dropped": dropped,
        "drop_counts": drop_counts,
        "distinct_outputs": distinct,
        "drop_examples": drop_examples,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
