---
name: mastermind
description: "Mastermind (arXiv 2601.05445) — knowledge-driven, hierarchical, strategy-level multi-turn jailbreak. Planner/Executor/Controller multi-turn episodes scored 1-10, wrapped in a grey-box genetic fuzzer over a binary strategy vector seeded from a distilled strategy repository."
metadata:
  paper_id: 2601.05445_autonomous-multi-turn-jailbreak
  family: multi-turn
  concept: multi-turn-jailbreak
  access: black_box
  fidelity_level: faithful_from_paper_no_official_code
  payload_contract:
    input_fields: [goal, active_strategy_subset]
    output_form: multi_turn_message_list
    retained_state: [dialogue_history, plan, controller_feedback]
    feedback_dependency: adaptive_controller_and_judge
    composition_status: not_composable
---

# Mastermind — Knowledge-Driven Multi-Turn Jailbreaking

## What
Mastermind (Li et al., arXiv 2601.05445) reformulates multi-turn jailbreaking as
**strategy-space combinatorial optimization**. Two phases:

- **Phase 1 — Knowledge Accumulation** (`scripts/gen_knowledge.py`, sec 4.2): explore an
  auxiliary harmful set on a safety-aligned **sandbox** model; the **Distiller** abstracts
  successful trajectories into atomic, model-agnostic **strategies**; cluster + consolidate
  them into a compact repository `S` (the genome alphabet).
- **Phase 2 — Knowledge-Driven Fuzzing** (`scripts/attack.py`, sec 4.3 + 4.1): for a new goal,
  **semantic seed scheduling** initializes a population of genomes `x ∈ {0,1}^N` (bit `k` =
  activate strategy `s_k`); a grey-box **genetic fuzzer** (tournament selection, uniform
  crossover p=0.5, bit-flip mutation `p_m`) evolves them. Each genome's **fitness `F(x)=max_t J_t`**
  comes from ONE full multi-turn episode:
  - **Planner** builds a step plan (each step + expected behavior) from the goal + active strategies.
  - Per turn: **Executor** writes the concrete user prompt `u_t` (the target-facing payload) →
    **Target** replies `r_t` → **Controller** decides **PROCEED / REFINE** (in-place rewrite of
    `u_t`) **/ ABORT** → **Judge** scores `r_t` 1-10. On ABORT the Planner **reflects** and replans once.

## Use / payload
The deliverable payload is the multi-turn conversation the Executor generates
(`prompts.executor_user`). Retained state = history + plan + controller feedback; the search is
adaptive (Controller + Judge feedback), so it is `not_composable` (cannot be frozen to a static prompt).

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`). API keys are read from the global `XSkillForge/.env`
(`scripts/models.py` walks up from the method dir to find the nearest `.env`) — no per-skill
`.env`, no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

## Run
```bash
cd XSkillLib/Single-turn/Multi-Strategy-Pool/2601.05445_Mastermind/mastermind
$PY scripts/attack.py --help
$PY scripts/attack.py inspect                 # repository + example plan prompt
$PY scripts/attack.py smoke                   # fake roles, shape-only (no API)

# real Phase-2 run (20-30 case sample; black-box, OpenRouter)
$PY scripts/attack.py run \
  --data data/harmbench_standard_200.csv --sample-rows 25 \
  --target api:deepseek/deepseek-v4-flash \
  --judge api:deepseek/deepseek-v4-flash \
  --pop-size 4 --generations 2 --max-turns 8 \
  --out results/mastermind_deepseek_hb_25x_$(date +%Y%m%d-%H%M%S).json

# StrongReject test set
$PY scripts/attack.py run --data data/strongreject_small_60.csv --sample-rows 25 ...

# Phase-1: grow the strategy repository from the auxiliary set
$PY scripts/gen_knowledge.py --limit 20 --sandbox api:meta-llama/llama-3.3-70b-instruct
```

## Test
`$PY scripts/attack.py smoke` runs fake roles end-to-end (GA + multi-turn loop) with
no network. Static acceptance: `... --help` and `inspect` work with the shared venv interpreter.

## Settings (each role a swappable flag, default `api:deepseek/deepseek-v4-flash`)
| Flag | Role |
|------|------|
| `--planner` | global strategist: builds + reflects the step plan (paper: DeepSeek-V3) |
| `--executor` | writes per-turn `u_t` — the target-facing payload (paper: Gemma-3-27B) |
| `--controller` | monitor: PROCEED/REFINE/ABORT + failure feedback |
| `--target` | victim model |
| `--judge-loop` | per-turn 1-10 judge, the fuzzing feedback signal (paper: GPT-4o) |
| `--judge` | final content-harm metric: `proxy` (keyword refusal-bypass), `none`, or `api:<model>` |
| `--strategies` | strategy repository JSON (default `data/strategies.json`) |
| fuzzing | `--pop-size --generations --seed-top-k --tournament-k --mutation-rate --success-score` |
| multi-turn | `--max-turns` (T_max, paper 10) `--max-refinements` `--no-reflection` |

## Fidelity / provenance
- **No official code, no prompt appendix.** Agent role templates (`prompts.py`) are a **faithful
  reimplementation** from the paper's prose (secs 4.1-4.2), each anchored in its docstring — NOT
  byte-verbatim official text. `fidelity_level: faithful_from_paper_no_official_code`.
- **Strategy repository** seeded from the paper's disclosed examples (Fig 1: authority persona,
  high-stakes crisis, risk-assessment masking, defensive frame, fictional crisis; sec 4.2 distilled
  logic). Growable via `gen_knowledge.py`.
- **Auxiliary set substituted** (paper's LLM-generated aux unreleased → AdvBench slice, Phase-1 only).
- **Datasets** full: HarmBench standard **200** + StrongReject small **60** held under `data/`.
- Similarity for seed scheduling / clustering uses a dependency-free lexical cosine (paper uses
  sentence embeddings) — swap `knowledge.text_similarity` for a real embedder without touching the GA.
