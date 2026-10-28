---
name: h4rm3l
description: >-
  h4rm3l (2408.04811, Stanford) — a RED-TEAMING FRAMEWORK for composable jailbreak
  attack synthesis. A human-readable DSL composes string-transform primitives
  (.then(...)); a bandit few-shot synthesizer uses an LLM proposer to auto-generate
  new high-ASR jailbreak programs against a black-box target. Reproduced fully on
  OpenRouter (deepseek-v4-flash as proposer+target+judge). This SKILL is a TUTORIAL for
  USING the framework: add attack atoms, synthesize new attacks, apply them to any target,
  and harvest the program corpus for training a red-team model.
metadata:
  paper: "2408.04811_composable-jailbreak-synthesis"
  category: red-teaming
  attack_family: composable_jailbreak_program_synthesis
  access: black_box
  target_default: deepseek/deepseek-v4-flash
  has_training_corpus: "yes"
  modules: [decorators.py, attack.py, synthesize.py]
  script: scripts/synthesize.py
---

# h4rm3l — composable jailbreak attack synthesis (a red-teaming framework)

h4rm3l is not one attack; it is a **language + a generator**. A jailbreak is a *program*
`p` composing parameterized string→string primitives via `.then(...)`. An illicit prompt
`x` becomes `p(x)`; the target's reply to `p(x)` is scored by the paper's verbatim G/B/U
judge. **ASR(p) = E_x[H(x, LM(p(x)))]** (eq. 1). The core finding: **composition + program
synthesis discover far stronger attacks than single primitives**.

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, deps `openai` + `numpy` + ...). API keys are read from the global
`XSkillForge/.env` (`scripts/attack.py:_load_env` walks up the ancestor directories to find
it) — no per-skill `.env`, no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

## Modules (a framework, not one script)

| module | role |
|---|---|
| `scripts/decorators.py` | the **DSL**: `PromptDecorator` + `.then()` + the primitive classes + an **open `@register` registry** + `compile_program()` + `primitives_spec()`. |
| `scripts/attack.py` | **benchmark/execution**: apply a program grid to illicit prompts, query a target, score with the verbatim judge, report ASR. |
| `scripts/synthesize.py` | the **bandit few-shot synthesizer**: an LLM proposer auto-generates new programs; Thompson-sampling by ASR; output = an ASR-labeled program pool. |

## Tutorial 1 — add a new attack atom (the extension interface)

Open `decorators.py`, subclass `PromptDecorator`, and `@register` it. That's all — the new
atom is then usable in any `.then(...)` program, compilable, AND automatically offered to the
synthesizer's proposer (which reads the registry). No edits to attack.py / synthesize.py.

```python
@register("ROT13Decorator", sig="ROT13Decorator()", desc="ROT13-encode the request.")
class ROT13Decorator(PromptDecorator):
    def __init__(self): super().__init__()
    def decorate(self, prompt): return codecs.encode(prompt, "rot13")
```

## Tutorial 2 — synthesize NEW jailbreak attacks against a target

```bash
cd XSkillLib/Single-turn/Multi-Strategy-Pool/2408.04811_h4rm3l/h4rm3l
$PY scripts/synthesize.py \
  --proposer api:deepseek/deepseek-v4-flash \
  --target   api:deepseek/deepseek-v4-flash \
  --judge    api:deepseek/deepseek-v4-flash \
  --iterations 4 --proposals-per-iteration 5 --harmful-sample-size 10 \
  --out results/synth_v4flash_<date>.json
```

The proposer (a normal LLM — it only writes DSL *programs*, not harmful content) proposes
compositions; each is scored; the bandit favours high-ASR programs as few-shot examples for
the next round. Output pool is sorted by ASR — the top programs are your synthesized attacks.

## Tutorial 3 — apply a program to any target (red-team a model)

```bash
cd XSkillLib/Single-turn/Multi-Strategy-Pool/2408.04811_h4rm3l/h4rm3l
$PY scripts/attack.py run \
  --sample 12 --target api:<model> --judge-model deepseek/deepseek-v4-flash \
  --max-tokens 1536 --out results/h4rm3l_<model>.json   # set max-tokens >= 1536 (avoid truncation)
```

Or compose/apply a single program inline via `decorators.compile_program("AIMDecorator().then(...)")`
then `attack.run_program(...)`.

## Tutorial 4 — harvest the program corpus (train a red-team model)

The released curated programs (`data/synthesized_corpus/h4rm3l_synthesized_programs.json`, 68
ASR-labeled DSL programs) plus your local `results/synth_*.json` pool are the SFT corpus:
`{harmful intent → composable jailbreak program → ASR}`. See `../red_team_capability.json`.

## Current result (v4-flash, GLM-audited)

`results/RESULT_2026-06-26.md`. The synthesizer reproduced the paper's signature: best seed
ASR(B) 0.78 → a synthesized `CharDropout(p=0.05).then(AIMDecorator())…` at ~1.0 (genuine
black-powder recipe, GLM-confirmed). Composition + synthesis >> single primitives. Judge
over-counts are removed by the GLM adversarial audit.

## Settings & boundaries
- target/proposer/judge default `deepseek/deepseek-v4-flash`; model-substitution (paper used
  GPT-4 proposer). All black-box, no GPU.
- Set target `--max-tokens >= 1536` so harmful payloads complete before judging (truncation
  otherwise both inflates and deflates ASR).
- Primitives ported verbatim from official `mdoumbouya/h4rm3l` (repo cache removed after audit; see provenance in `red_team_capability.json`).
