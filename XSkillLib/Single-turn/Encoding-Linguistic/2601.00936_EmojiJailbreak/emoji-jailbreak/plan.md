# Emoji Jailbreak Code Plan

## Plan Gate

This method is the template probe for the single-folder Code form. The plan was
settled before changing the package: keep one method folder, keep
`scripts/attack.py` as the runnable implementation, and make `SKILL.md` the
single ScaleMD README.

No batch migration follows from this file. Other papers wait for Oscar's review
of this template.

## Paper And Scope

- Paper: `2601.00936` — "Emoji-Based Jailbreaking of Large Language Models".
- Source status: no official repo found in local artifacts; this is a paperless
  reconstruction from `raw/source/main.tex`, `digest/`, and `reading/`.
- Reproduction scope: minimal faithful black-box method run, not full
  four-model Ollama table parity.

## Algorithm Core

Single-turn black-box prompt transformation:

- `direct`: no transformation baseline.
- `chaining`: replace matched concept words with emoji substitutions.
- `stuffing`: interleave emojis between words.
- Unicode NFC normalization is applied to generated prompts.

## Data, Target, Judge

- Data: `cache/advbench_subset_20.csv` plus `cache/emoji_map.json`.
- Target: `deepseek/deepseek-chat` through OpenRouter, labeled
  `model_substitution_run` for the paper's Ollama-local Mistral/Qwen/Gemma/Llama
  targets.
- Judge: triple judge in `scripts/attack.py`:
  1. dual rule-based refusal-bypass/content-harmful verdict,
  2. paper-style keyword classifier and keyword JSR,
  3. DeepSeek LLM dual judge.

## File Tree

```text
emoji-jailbreak/
├── SKILL.md
├── plan.md
├── scripts/attack.py
├── references/{method.md,evaluation.md}
├── cache/{advbench_subset_20.csv,emoji_map.json}
├── results/
├── check.json
└── artifacts.json
```

There is no separate `code/` record directory. Records sit next to the scripts
they describe.

## Run

Run from the method folder:

```bash
cd data/papers/2601.00936_direct-emoji-jailbreak/emoji-jailbreak
uv run python scripts/attack.py \
  --target-model deepseek/deepseek-chat \
  --judge-model deepseek/deepseek-chat \
  --out results/emoji_deepseekchat_20x3_20260623_singlefolder.json
```

Tiny live verification:

```bash
uv run python scripts/attack.py --sample 3 --modes direct,chaining --out /tmp/emoji_smoke.json
uv run python scripts/attack.py --rejudge /tmp/emoji_smoke.json --out /tmp/emoji_smoke_rejudged.json
```

## Expected Result

- Full run shape: 60 cases, `20 behaviors x 3 modes`.
- Result schema: `paper_local_attack_result.v0.1`.
- Expected signal: low keyword JSR around the paper's weak-attack range, not a
  high-ASR jailbreak.
