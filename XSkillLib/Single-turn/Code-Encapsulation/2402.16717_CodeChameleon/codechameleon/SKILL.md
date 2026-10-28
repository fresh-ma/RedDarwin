---
name: codechameleon
description: Paper-local Code for 2402.16717 CodeChameleon. Verbatim port of the official repo — encrypts raw goals with personalized rules, embeds the matching decryption function in a code-completion ProblemSolver prompt, runs an OpenRouter target, and scores with the paper's GPT-4 OpenAI-policy 1-5 judge.
metadata:
  paper: "2402.16717_personalized-encryption-jailbreak"
  fidelity_level: paper_algorithm_code
  access: black_box
  mechanism: personalized encryption + decryption-code code-completion prompt
  script: "scripts/attack.py"
  official_repo: "huizhang-L/CodeChameleon@16a19920"
---

# CodeChameleon

Paper: `2402.16717_personalized-encryption-jailbreak`
Method: `codechameleon`
Fidelity: `paper_algorithm_code` (verbatim port of `huizhang-L/CodeChameleon@16a19920`)

Implements the paper's personalized encryption framework:

- encrypt raw goals using `reverse`, `binary_tree`, `odd_even`, or `length` (byte-for-byte match to
  the official `encrypt.py`, incl. the `str()` serialization of dict/list-shaped encryptions);
- embed the matching Python decryption function (verbatim `decrypt.py` wrappers);
- wrap the encrypted query in the official code-completion `ProblemSolver` template (verbatim
  `template.py`) with the official jailbreak system prompt (`code_sys_helpful`);
- call a replaceable OpenAI-compatible target model (default OpenRouter);
- score with the official **GPT-4 OpenAI-policy 1-5 harmfulness judge** (Qi 2023, verbatim
  `gpt_evaluate.py` prompt) served by **OpenRouter `deepseek/deepseek-chat`** (scores the verbatim
  rubric fine; OpenRouter's `openai/*` route 403s the harmful-judge prompt, so use deepseek-chat —
  not OpenAI-direct);
- save inspectable input messages, model output, judge score, and a dual refusal proxy.

Reference evidence: `digest/sections/03.01-encryption.md`, `03.02-decryption.md`,
`07.03-complete-jailbreak-prompts.md`; official repo `huizhang-L/CodeChameleon`.

## Commands

Paths are relative to this method dir (`codechameleon/`).

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, deps `openai` + ...). API keys are read from the global
`XSkillForge/.env` (`scripts/cases.py` walks up to find it) — no per-skill `.env`,
no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter

# offline wiring check (no model calls)
$PY scripts/attack.py smoke --target fake --wiring-check --out /tmp/cc_smoke.json

# live run: target AND judge via OpenRouter (single key, from global XSkillForge/.env)
$PY scripts/attack.py run \
  --target api:deepseek/deepseek-v4-flash --judge-model deepseek/deepseek-v4-flash \
  --goals data/all_problem.csv --sample 16 --rules reverse,binary_tree \
  --judge --max-tokens 1024 \
  --out results/<run-id>.json

# fill ungraded judge gaps (re-scores only ungraded cases)
$PY scripts/attack.py rejudge \
  --infile <result> --judge-model deepseek/deepseek-v4-flash \
  --judge-base-url https://openrouter.ai/api/v1 --judge-api-key-env OPENROUTER_API_KEY --out <result>
```

Per-role swap: `--target` (victim) · `--judge-model` (Qi-2023 1–5 judge) · `--rules` (encryption) ·
`--template code|text` (scaffold) · `--goals`/`--sample` (data). Each role has its own model/base-url/key flags.

## Notes

- Black-box attack: no `local:` adapter needed, no GPU.
- Default judge is OpenRouter `deepseek/deepseek-chat` (verbatim Qi-2023 1-5 prompt). Do NOT route
  the judge to OpenAI-direct (`openai/*` 403s the harmful prompt; OpenAI-direct is quota-exhausted).
- Text-style prompt (`--template text`) is exposed for ablation; the main run uses `code`.

## Canonical result

- `results/RESULT_2026-06-26.md` + `results/codechameleon_v4flash_16x2_tokfix_20260626.json`
  + GLM audit `results/GLM_REVIEW_tokfix_20260626.md`.
- 16 official goals × 2 encryption rules (reverse, binary_tree); target = judge =
  `deepseek/deepseek-v4-flash` (documented substitution for the paper's GPT-4 — OpenRouter
  `openai/*` 403s the harmful judge prompt). Official Qi-2023 1–5 prompt verbatim.
- raw judge ASR_content_harmful = 1.0 (16/16); **GLM/Crush per-case audited = 0.75 (12/16)** —
  4 false positives are the usual judge over-credit (non-actionable / off-goal). Canonical = 0.75.
- Full 820-row dataset vendored at `data/all_problem.csv` (the 16 are the demo sample).
- Sibling multi-target runs (glm-4.6 / llama-3.3-70b / qwen-2.5-72b) under `results/` for provenance.
