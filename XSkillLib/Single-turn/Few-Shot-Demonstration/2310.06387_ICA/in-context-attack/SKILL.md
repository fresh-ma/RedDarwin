# In-Context Attack (ICA) — 2310.06387

## What
Black-box prompt-prefix jailbreak. ICA prepends `k` harmful query+compliant-answer
demonstrations before the target harmful request, biasing an aligned LLM toward
the harmful sub-distribution in a single forward pass. From *Jailbreak and Guard
Aligned Language Models With Only Few In-Context Demonstrations* (Wei et al.,
2310.06387). Implements the attack side (ICA); the dual ICD defense is out of
scope for this attack unit.

`P_attack = [x_1, y_1, ..., x_k, y_k, x]` rendered as a multi-turn chat prefix.

## Use
XSafeBench black-box jailbreak unit. Reuses the reference dual-metric judge so
results aggregate with other units. Swap target/judge/dataset/shot-grid freely.

## Run

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, dep `openai`). API keys are read from the global
`XSkillForge/.env` (`scripts/attack.py:load_env` walks up to find it) — no per-skill
`.env`, no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
cd in-context-attack
# Render cases only (no model calls)
$PY scripts/attack.py render --shots 1,3 --limit-rows 2

# Real run: 20 AdvBench behaviors x {1-shot, 3-shot} = 40 cases
$PY scripts/attack.py run \
  --shots 1,3 \
  --target api:deepseek/deepseek-chat \
  --judge api:deepseek/deepseek-chat \
  --out results/ica_deepseek_advbench20_1and3shot.json
```
`OPENROUTER_API_KEY` must be in the environment (or the global `XSkillForge/.env`).
Each `--shots` value is a distinct config; pass e.g. `--shots 1,3,5` for a grid.

## Test
`render --limit-rows 2 --shots 1,3` must yield 4 cases with 3 and 7 messages
(roles alternating user/assistant, ending in user). A real `run` is valid when
`summary.cases >= 10`, `summary.n_configs >= 2`, `summary.ok == cases`, and every
verdict carries `refused`/`harmful` booleans with computed `asr_refusal_bypass`
and `asr_content_harmful`. Saved result:
`results/ica_deepseek_advbench20_1and3shot.json`.

## Settings
- Target / judge: `api:<openrouter-model-id>` (defaults `deepseek/deepseek-chat`).
- Judge is dual-metric (refusal-bypass + content-harmful + combined success),
  reused verbatim from the `2305.13860` reference harness.
- Dataset: `data/advbench_harmful_behaviors.json` — the complete AdvBench
  harmful-behaviors set (520 rows, flat JSON `{id,goal,target}`; see
  `data/SOURCE.md`). Use `--limit-rows N` to subsample for cheap smoke runs.
- Demonstrations: `data/ica_demonstrations.json` (5 harmful query/compliant-answer
  pairs in the paper's documented appendix style; official repo `PKU-ML/adv-icl`
  is 404, so faithfully reconstructed). Demos are drawn from the AdvBench front;
  for a clean run, subsample target rows from the back (e.g. `--limit-rows`) to
  avoid overlap with the demo queries.
- `--shots` (config knob), `--temperature` (default 0.0), `--max-tokens`
  (default 1024), `--concurrency` (default 12).

## Result (recorded sample)
deepseek/deepseek-chat target + judge, 40 cases: `asr_refusal_bypass=0.025`,
`asr_content_harmful=0.025`. Per-config: 1-shot = 0.0, 3-shot = 0.05 — the
expected monotone shot trend. Low absolute ASR matches the paper's finding that
low-shot ICA barely moves strongly-aligned models (GPT-4 1-shot = 0%).
