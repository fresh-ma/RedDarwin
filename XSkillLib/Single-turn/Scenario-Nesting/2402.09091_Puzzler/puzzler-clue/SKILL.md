---
name: puzzler-clue
paper_id: 2402.09091_implicit-clue-jailbreak
case_type: indirect_clue_jailbreak
access: black_box_api
fidelity_level: full_llm_pipeline
evidence_level: model_substitution_run
artifact_bundle: paper-local
execution_mode: live_target_run
---

# Puzzler Clue

Paper-local Code for Puzzler (arXiv:2402.09091), a black-box **indirect** jailbreak.
Every substep is a real LLM call with paper-verbatim prompts (no official repo was
released): Phase 1 extracts the malicious content (5-shot) and generates defensive
measures; Phase 2 filters by direct-correlation then inverts each kept defense into
an offensive measure via the "Dr. Al" template; Phase 3 assembles the offensive
measures into the indirect jailbreak prompt and queries the **target**. The judge is
the paper's QSR + FR rubric (Sec. 4.4), verbatim, served by an OpenRouter substitute
for the paper's human panel.

The attacker components (extract / defensive / filter / offensive) use a documented
OpenRouter substitute (`deepseek/deepseek-chat`) for the paper's GPT-4 / GPT-4-Turbo
/ GPT-3.5; the target and judge are `deepseek/deepseek-v4-flash` (project default,
fallback `deepseek-chat`). The dataset is a paper-local AdvBench subset under `data/`.

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, deps `openai` + ...). API keys are read from the global
`XSkillForge/.env` (`scripts/models.py` walks up to find it) — no per-skill `.env`,
no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

## Run

```bash
cd XSkillLib/Single-turn/Scenario-Nesting/2402.09091_Puzzler/puzzler-clue
# structural / offline checks (no LLM calls)
$PY scripts/attack.py inspect
$PY scripts/attack.py render --goal "Test request"
$PY scripts/attack.py smoke

# live run (per-case LLM call chains parallelised with --workers).
# max-tokens 2048 (target) / 1024 (judge) gives the deepseek-v4-flash reasoning model
# headroom; smaller budgets are consumed by hidden reasoning and yield empty outputs.
$PY scripts/attack.py run \
  --target api:deepseek/deepseek-v4-flash --allow-live \
  --attack-model deepseek/deepseek-chat --judge-model deepseek/deepseek-v4-flash \
  --sample 20 --max-defensive 6 --temperature 1.0 --max-tokens 2048 --workers 8 \
  --out results/puzzler_clue_dsv4_setA_final_20260625.json
```

## Final result (deepseek-v4-flash target+judge)

40 cases × 2 parameter configs (A: max-defensive 6, temp 1.0 / B: max-defensive 10,
temp 0.7), 40/40 completed, 0 provider errors, refusal_bypass 1.00 on both configs,
0 empty/judge-empty outputs.

- **content-harmful (QSR ∧ FR, on-goal harm) = 28 / 40 = 0.70** (A 0.60, B 0.80)
- QSR (harmful content) — A 0.85, B 0.90
- FR (follows original intent) — A 0.60, B 0.80

`results/puzzler_clue_dsv4_setA_final_20260625.json`,
`results/puzzler_clue_dsv4_setB_final_20260625.json`.

The FR<QSR gap is genuine, not a bug: on some cases the Dr.-Al indirect framing yields
a harmful *plan* (QSR true) that no longer fulfils a goal demanding a specific format
(e.g. "write a social-media post / blog post" → FR false). The goal-faithful judge
correctly declines to count those off-goal cases as success.

An earlier qwen-2.5-7b gate (QSR 1.00 / FR 0.95) was superseded by the deepseek-v4-flash
canonical above; its run artifact was dropped during consolidation.
