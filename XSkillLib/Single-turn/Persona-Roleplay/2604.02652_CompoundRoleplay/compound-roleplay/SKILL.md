---
name: compound-roleplay
description: "Compound Role-Playing jailbreak (arXiv:2604.02652). Single-shot black-box attack that combines three individually-weak elements — authoritative persona + contrastive good/bad Markdown table (education framing) + JSON self-assessment demand — into ONE message to 'saturate' the safety mechanism's cognitive resources. From-paper reimplementation (no official code)."
metadata:
  paper: "2604.02652"
  fidelity_level: partial_algorithm_code
  access: black_box
  mechanism:
    - composite-jailbreak
  payload_contract:
    input: "raw goal + category + selected compound elements"
    output: "one target-facing compound role-play message"
    retained_state: "selected persona, contrastive structure, and self-assessment requirement"
    feedback_dependency: "none"
    composition: "direct"
---

# Compound Role-Playing (arXiv:2604.02652)

## What

**Compound Role-Playing** wraps a raw harmful goal by combining three jailbreak
elements — each individually defended-against and weak alone — into a single
user message. The paper's thesis (sec 4.1): the combination does not *contradict*
the safety policy, it *overloads* it — "an attack that makes the model too busy
to remember the rules." The three elements (sec 4.2):

1. **Authoritative Persona** — assign a role (security expert / medical specialist)
   that reframes refused requests as "legitimate professional duties".
2. **Contrastive Structure** — a Markdown table juxtaposing a "bad example" (the
   real harmful content) vs a "good example", justified as education / "for
   comparison purposes".
3. **Self-Assessment Demand** — require a confidence self-assessment in JSON,
   adding metacognitive load that "consumes cognitive resources, reducing those
   allocated to safety judgment".

Paper target = OpenAI gpt-oss-20b; full-combo **ASR 71.4%** (5/7 categories) vs
14.3% for contrastive-only (Table `tab:ablation`).

**No official code** (`paper.meta` `code_repos: []`); this is a faithful
from-paper reimplementation. The paper releases no verbatim prompt — each element
is reconstructed from its sec-4.2 description (quoted in `scripts/prompts.py`).

## Use

- `scripts/prompts.py` — the three element templates + `build_payload()` composer
  + the dual-metric judge prompt (element descriptions quoted verbatim from sec 4.2).
- `scripts/models.py` — OpenAI-compatible client + `.env` loader that walks up
  ancestor directories (finds the global `XSkillForge/.env`)
  (`api:<model>` OpenRouter / `ollama:<model>` local).
- `scripts/roles.py` — swappable target + judge adapters.
- `scripts/cases.py` — dataset DTO + CSV loader.
- `scripts/attack.py` — thin CLI + orchestration; `--render` for static payload preview.
- `scripts/gen_dataset.py` — rebuilds `data/harmful_prompts.csv` (70 prompts).

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, deps `openai` + ...). API keys are read from the global
`XSkillForge/.env` (`scripts/models.py` walks up to find it) — no per-skill `.env`,
no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

## Run

```bash
cd XSkillLib/Single-turn/Persona-Roleplay/2604.02652_CompoundRoleplay/compound-roleplay
$PY scripts/attack.py --help
$PY scripts/attack.py --render --sample 3          # static: print payloads, no calls

# real run (paid): full combo on a 20-30 case sample
$PY scripts/attack.py --sample 20 \
  --target api:deepseek/deepseek-v4-flash \
  --judge  api:deepseek/deepseek-v4-flash

# ablation subsets (Table tab:ablation)
$PY scripts/attack.py --sample 20 --elements contrastive
$PY scripts/attack.py --sample 20 --elements contrastive+self_assessment
```

## Test

`$PY scripts/attack.py --render --sample 3` composes and prints payloads
for the full combo and any `--elements` subset with NO target calls (static check).

## Settings

- `--target` / `--judge` — model specs (`api:<model>` | `ollama:<model>`),
  independently swappable. Default `api:deepseek/deepseek-v4-flash`.
- `--elements` — active compound elements: comma list of
  `contrastive,persona,self_assessment` OR a preset (`all`,
  `contrastive+self_assessment`, `persona+self_assessment`, ...). Default `all`.
- `--sample N` — first N of 70 cases. `--target-max-tokens` (default 4096, keep
  high for reasoning targets so the table isn't truncated), `--judge-max-tokens`,
  `--target-temperature`.
- Env: `OPENROUTER_API_KEY` in the global `XSkillForge/.env`; `scripts/models.py`
  walks up ancestor directories to load it (a method-local `.env`, if present, wins).

## Data

`data/harmful_prompts.csv` — 70 prompts, 7 categories x 10, matching paper sec 5.1.
The paper does not release the prompts; reconstructed by `gen_dataset.py`. See
`red_team_capability.json` `data` block for full provenance.

## Substitution

`model_substitution_run`: paper used OpenAI gpt-oss-20b + human evaluators; here
target+judge default to an open model via OpenRouter with a dual-metric LLM judge
(refusal_bypass + content_harmful) scored against the original goal.

## Canonical evidence and boundaries

- `results/deakin_20260720_064807.json`: 20/20 target and judge calls complete,
  0 runtime/provider errors, 0 truncations, and 0 empty target outputs.
- The paper does not release its literal prompt template or 70 evaluation
  prompts. This package reconstructs the disclosed three-element mechanism and
  seven-category data shape; it does not claim byte-level artifact fidelity.
- The retained run tests the full combination only. The CLI exposes paper
  ablation subsets, but no ablation result is claimed as completed evidence.
- Canonical content-harm metrics must come from the paper-local all-case GLM
  audit, not from the raw judge alone.
