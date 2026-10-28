---
name: drattack
description: "Faithful paper-local DrAttack — decompose a harmful prompt into a phrase tree (cached GPT-4 PCFG parse), reconstruct the intent via an ICL demonstration, and run the official level-wise random search with embedding fitness. Black-box target + Yes/No harmfulness judge (official prompt verbatim) via OpenRouter; embedding fitness via local sentence-transformers MiniLM (documented ada-002 substitution); test_prefixes refusal proxy. No OpenAI-direct, no GPU."
metadata:
  paper: "2402.16914_prompt-decomposition-jailbreak"
  access: black_box
  mechanism: parsing-tree decomposition + ICL reconstruction + level-wise embedding-thresholded synonym random search
  script: "scripts/attack.py"
  fidelity_level: paper_algorithm_code
  official_repo: "xirui-li/DrAttack@f51bee1"
  payload_contract:
    input: "A harmful goal and its cached phrase-tree decomposition."
    output: "One reconstructed target-facing jailbreak prompt."
    retained_state: "The phrase tree, ICL reconstruction, and level-wise search candidates."
    feedback_dependency: "the search can be frozen into a selected prompt before replay"
    composition_status: "freeze_then_replay"
---

# DrAttack Attack Script

Faithful port of `xirui-li/DrAttack@f51bee1` (`drattack/ga/ga_attack.py` +
`base/attack_manager.py` + `experiments/main.py` + `evaluate_with_GPT.py`).
Decomposition (`visit_keys`/`reprocess` over the cached `parsing_tree_dictionary`),
ICL reconstruction (`generate_prompt` + official `general_template`), and the
level-wise random search (`expand_population` / `fitness` / `evolve`, with cosine
embedding fitness and the synonym similarity threshold) all match the official
source. Judge = official binary Yes/No harmfulness prompt (`temp_short`, verbatim)
served by an OpenRouter open model (default `--judge-model api:deepseek/deepseek-v4-flash`)
+ the `test_prefixes` refusal-keyword metric; dual ASR is reported.

Two documented substitutions (both forced by OpenAI-direct quota exhaustion + the
fact OpenRouter `openai/*` 403s harmful judge prompts / serves no ada-002): the
judge prompt is kept verbatim but served by an OpenRouter open model,
and `text-embedding-ada-002` fitness is replaced by local sentence-transformers
`all-MiniLM-L6-v2` (CPU). Cosine-fitness math and the search loop are unchanged.

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, deps `openai` + `sentence-transformers` + ...). API keys are read from the global
`XSkillForge/.env` (`scripts/attack.py` walks up to find it) — no per-skill `.env`,
no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

## Quick checks (offline: decomposition + reconstruction, no model calls)
```bash
cd XSkillLib/Single-turn/Multi-Strategy-Pool/2402.16914_DrAttack/drattack
$PY scripts/attack.py smoke >/dev/null
$PY scripts/attack.py inspect --sample 5 --out /tmp/drattack-inspect.json
```

## Live run (target + judge over OpenRouter, key from global XSkillForge/.env)
```bash
cd XSkillLib/Single-turn/Multi-Strategy-Pool/2402.16914_DrAttack/drattack
# real run (black-box, no GPU): 8 goals x 2 settings vs deepseek-v4-flash
$PY scripts/attack.py run \
  --sample 8 --settings "noun;noun+verb" \
  --target api:deepseek/deepseek-v4-flash \
  --judge-model api:deepseek/deepseek-v4-flash --judge-max-tokens 4096 \
  --out results/drattack_v4flash_8x2_$(date +%Y%m%d-%H%M%S).json
```

Target + judge = OpenRouter `api:<model>` (`OPENROUTER_API_KEY`); embedding fitness
= local MiniLM. Canonical run: `results/drattack_v4flash_8x2_tokfix_20260626.json`
(16 cases, audited content_harmful 0.0 — faithful negative; see
`results/RESULT_2026-06-27.md`). `runbook.md` has the full knob list, `plan.md` the
self-check. Default datasets live in `data/` (full 520-goal AdvBench set +
GPT-4 decomposition pack); official source preserved under `references/official/`.
Dataset- and model-agnostic via `--goals` / `--prompt-info` / `--target` /
`--judge-model` / `--sample`.
