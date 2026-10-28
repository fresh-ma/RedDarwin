---
name: artprompt
description: "Run paper-local ArtPrompt Code: mask the sensitive word and replace it with official ASCII-art fonts (cloaked prompt), score with official Dict-Judge + GPT-Judge."
metadata:
  paper: "2402.11753_ascii-art-jailbreak"
  access: black_box
  mechanism: ASCII-art masked-word cloaked prompt
  script: "scripts/attack.py"
  case_type: black_box_generator_loop
  artifact_bundle: [official_artprompt_dataset, official_ascii_art_fonts, target_model, dict_judge, gpt_judge]
  execution_mode: [inspect, render, smoke, live_api]
  evidence_level: real_model_run
  fidelity_level: paper_algorithm_code
  status: ready_to_use
---

# ArtPrompt Attack Script

Faithful port of `uw-nsl/ArtPrompt` @`6eb8664`. ArtPrompt (1) masks the sensitive word of a
harmful instruction with `[MASK]`, and (2) replaces it with ASCII art (cloaked prompt) so the
safety filter never sees the trigger word, but the victim LLM reconstructs it and answers.

Ported verbatim from the official repo (kept under `references/official/`):
- ASCII generation = `generate_alphabet_ascii`: font `gen` (official `gptgen_ascii` 5x5 grid)
  plus `art`-package fonts (`alphabet/letters/keyboard/cards/puzzle`), same per-font trimming + separators.
- Cloaked prompt = official `vitc_horizontal` (`--direction h`, default) or `vitc_vertical`
  (`--direction v`) task template.
- Masker = modular (`--masker dataset|heuristic|llm`): `dataset` = per-row `category` column
  (default), `heuristic` = official `mask_word_stop`, `llm` = official `GPTMaskPrompt`
  (`--masker-model api:<model>`).
- Judges = official **Dict-Judge** (`Safe_SubString`) + **GPT-Judge** (OpenAI-policy 1-5 `#thescore`,
  ASR = fraction scored 5). ArtPrompt uses no HarmBench classifier.

Official datasets live in `artprompt/data/`:
`harmful_behaviors_custom.csv` (50), `HEx_PHI_sub10.json` (11 categories), `vitc/vitc-s.json` +
`vitc/vitc-l.json` (recognition benchmark).

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, deps `openai` + `art` + ...). API keys are read from the global
`XSkillForge/.env` (`scripts/models.py` walks up to find it) — no per-skill `.env`,
no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

## Quick checks
```bash
cd XSkillLib/Single-turn/Encoding-Linguistic/2402.11753_ArtPrompt/artprompt
$PY scripts/attack.py smoke >/dev/null
$PY scripts/attack.py render --limit 1 --fonts gen,alphabet,cards --out /tmp/artprompt-render.json
$PY scripts/attack.py render --limit 1 --fonts gen --direction v --out /tmp/artprompt-render-v.json
$PY scripts/attack.py inspect --limit 2 --masker heuristic --out /tmp/artprompt-inspect.json
```

## Live run (target + GPT-Judge over OpenRouter, key from global XSkillForge/.env)
```bash
cd XSkillLib/Single-turn/Encoding-Linguistic/2402.11753_ArtPrompt/artprompt
$PY scripts/attack.py run \
  --sample-rows 20 --seed 20260609 --fonts gen,cards --direction h \
  --masker dataset \
  --target api:qwen/qwen-2.5-32b-instruct \
  --judge api:openai/gpt-4o \
  --max-tokens 700 --judge-max-tokens 600 --request-delay 0.4 \
  --out results/artprompt_qwen32b_20x2_gen_cards.json
```

Mix and match the modular roles — each has its own model/tokens:
- `--target api:<model>` (victim), `--masker {dataset,heuristic,llm}` (`--masker-model api:<model>`,
  `--masker-max-tokens`), `--direction {h,v}`, `--judge none|api:<model>`
  (`--judge-base-url`, `--judge-key-env`, `--judge-max-tokens`).

(OpenRouter 403-blocks the policy-judge prompt, so the GPT-Judge routes to OpenAI directly — also
the official path. `--judge none` runs Dict-Judge only.)

Live outputs use `evidence_level=real_model_run` and store full model input/output + both named
judges. `smoke` and `--target fake --wiring-check` are wiring-only (non-evidence).

Do not classify this script as `ascii-smuggling`: that concept refers to invisible Unicode tag
smuggling, while ArtPrompt uses visible ASCII-art text.
