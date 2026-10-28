---
name: virtual-context
description: "Paper-local Code for 2406.19845 Virtual Context. Inserts virtual special-token separators and affirmative suffixes into target prompts."
metadata:
  paper: "2406.19845_VirtualContext"
  case_type: black_box_special_token_injection
  access: black_box_api
  artifact_bundle: [paper_algorithm, chat_templates, advbench_full, api_target, dual_judge]
  execution_mode: [run, wiring-check]
  evidence_level: real_model_run
  fidelity_level: paper_algorithm_code
  script: "scripts/attack.py"
  status: self_contained_code_ready
  payload_contract:
    composition: direct
    input_fields: [goal, template, separator, affirmative_suffix]
    output_form: one target-facing prompt
    retained_state: [template, separator, affirmative_suffix]
    feedback_dependency: none
---

# Virtual Context

Zhou et al., arXiv 2406.19845. Inserts a *virtual special token* (`<SEP>` / model chat separator) between the malicious goal and an affirmative suffix `O_x` so the target may treat `O_x` as its own prior generation and continue inside that affirmative context.

No official code repo — paper-derived from Sec 4 + Appendix tables. See `references/SOURCE_STATUS.md`.

## Modules

| file | role |
| --- | --- |
| `scripts/prompts.py` | attack templates + paper refusal vocab + HarmScore prompt (verbatim) + dual yes/no judge prompts |
| `scripts/models.py` | SDK-free OpenAI-compatible client (stdlib urllib), `.env` loader |
| `scripts/roles.py` | render Virtual Context, target query, dual yes/no + paper metrics |
| `scripts/cases.py` | AdvBench CSV loader + dual-metric ASR summariser |
| `scripts/attack.py` | thin CLI |

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`; this script needs only the stdlib). API keys are read from the global
`XSkillForge/.env` (`scripts/models.py` walks up to find it) — no per-skill `.env`,
no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

## Run

```bash
cd XSkillLib/Single-turn/Response-Prefill/2406.19845_VirtualContext/virtual-context
$PY scripts/attack.py \
  --target api:deepseek/deepseek-v4-flash \
  --judge api:deepseek/deepseek-v4-flash \
  --sample 20 \
  --template plain --separator sep \
  --target-max-tokens 1024
```

Wiring only (not evidence):

```bash
$PY scripts/attack.py --wiring-check --sample 2 --out /tmp/vc-wire.json
```

## Metrics

Primary (project dual): `refusal_bypass` + `content_harmful` via independent yes/no LLM judges.
Paper-side: Matching, ASR-vocabulary bypass (37 phrases, Sec 13), HarmScore 1–5 (threshold ≥ 3).

## Caveat

OpenRouter chat-completions delivers `<SEP>` as literal user text, not a raw tokenizer-level control token. Paper still evaluates GPT-3.5/4 via black-box chat; treat API runs as the paper's Direct+VC surface form, with the token-level fidelity caveat in `CONSOLIDATE_BLOCKER.md` at the unit root.
