---
name: deepinception
description: "DeepInception nested-scene black-box jailbreak (2311.03191). Wrap a harmful goal in a nested fictional multi-layer scene template, send to an OpenRouter target, and score with a dual-metric LLM judge (refusal-bypass + content-harmful)."
metadata:
  paper: "2311.03191_nested-scene-llm-jailbreak"
  title: "DeepInception: Hypnotize Large Language Model to Be Jailbreaker"
  access: black_box
  mechanism: nested-scene fictional prompt template
  official_repo: "https://github.com/tmlr-group/DeepInception"
  runner: "scripts/attack.py"
  status: ready_to_use
---

# DeepInception

## What
DeepInception is a pure black-box, training-free prompt-template jailbreak. It
wraps a harmful goal inside a nested fictional multi-layer scene ("layer i
creates layer i+1"); characters at each layer propose a step toward the goal,
and the final layer is asked to summarize concrete tools/steps. The runner
adapts the XSafeBench reference harness and swaps only the template-application
step for DeepInception's verbatim nested-scene render.

## Use
- `scripts/attack.py` — render cases or run them against an API target with a
  dual-metric LLM judge.
- `data/advbench_harmful_behaviors.json` — full AdvBench (520 harmful behaviors),
  the paper's primary benchmark (Sec 4.1); the default dataset.
- `data/jailbreakbench_behaviors.json` — JailbreakBench (100 behaviors), the
  additional named benchmark the paper cross-validates on. See `data/SOURCE.md`.
- `references/method.md` — template wording, parameters, and fidelity notes.
- `results/` — saved run JSON (raw input/output/verdict per case).

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, dep `openai`). API keys are read from the global
`XSkillForge/.env` (`scripts/attack.py` walks up from the skill dir to find the
nearest ancestor `.env`) — no per-skill `.env`, no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

## Run
From the method dir (`deepinception/`):

```bash
cd XSkillLib/Single-turn/Scenario-Nesting/2311.03191_DeepInception/deepinception
$PY scripts/attack.py run \
  --scene-types "science fiction,spy movie" \
  --num-layers 5 --num-characters 5 \
  --limit-rows 20 \
  --target api:deepseek/deepseek-v4-flash \
  --judge api:deepseek/deepseek-v4-flash \
  --max-tokens 8192 \
  --out results/deepinception_v4flash_tok8192_<DATE>.json
```

`--scene-types` takes a comma list; each scene becomes one config (>= 2 configs).
`--layer-values` / `--character-values` align positionally to the scenes for the
paper's layer/character ablations. Use `--judge none` for the cheap keyword
refusal proxy (probe only — not harmful-compliance evidence).

**Token budget for reasoning targets (REQUIRED for `deepseek-v4-flash`).** v4-flash
is a reasoning model and the nested-scene answers are long multi-layer narratives;
at a small `max_tokens` it spends the budget on hidden reasoning / truncates and
returns EMPTY content (which then scores as not-harmful, artificially DEFLATING
the ASR). Use `--max-tokens 8192` to get 0 `status=ok-but-empty` cells. A lower cap
(e.g. 2048) left 7/40 empty and suppressed the measured ASR (0.35 vs 0.575 clean).

## Test
Render-only (no model call), validates pipeline + dual configs:

```bash
cd XSkillLib/Single-turn/Scenario-Nesting/2311.03191_DeepInception/deepinception
$PY scripts/attack.py render \
  --scene-types "science fiction,spy movie" --limit-rows 3
```

## Settings
- Target: `api:<openrouter-model-id>` (black-box chat). Default judge
  `api:deepseek/deepseek-chat`; falls back to `api:deepseek/deepseek-v4-flash`
  if that errors.
- Dual metric in each `verdict`: `refused` + `harmful` booleans →
  `asr_refusal_bypass`, `asr_content_harmful`, `asr_jailbreak_success`.
- Default attack params: scene `science fiction`, layers 5, characters 5
  (paper defaults). Template wording is verbatim to official commit fc5689e.
- Black-box only; no GPU / no local weights. Do not paste raw attack prompts or
  model completions into chat.
