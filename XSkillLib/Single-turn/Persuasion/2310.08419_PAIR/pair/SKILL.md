---
name: pair
description: "Paper-local Code of PAIR: Prompt Automatic Iterative Refinement for automated semantic jailbreak search."
paper_id: 2310.08419_automated-llm-jailbreak
method_id: pair
case_type: black_box_generator_loop
access: black_box_api
artifact_bundle: [official_code_reference, official_verbatim_prompts, official_advbench_subset, openrouter_roles, official_gpt4_judge]
execution_mode: [inspect, render, smoke, live_api]
evidence_level: real_model_run
fidelity_level: faithful_algorithm_code
status: ready_to_use
---

# PAIR

This skill reproduces the PAIR loop from arXiv 2310.08419. PAIR uses an attacker
LLM to produce a JSON `{improvement, prompt}` candidate, queries a target model
with that prompt, scores the prompt-response pair with a GPT-4 judge (1-10,
success=10), and feeds the response plus score back into the attacker history for
iterative refinement across parallel streams; it early-stops on the first judge
score of 10.

The attacker system prompts (roleplay / logical-appeal / authority-endorsement),
the GPT-4 judge system + user prompts, the initial message, and the
target-response feedback format are ported **verbatim** from the official repo
(patrickrchao/JailbreakingLLMs @ 6379ef7), stored in
`references/official_prompts.json`. Black-box: attacker, target, and judge all run
over OpenRouter `api:<model>`, no GPU. The paper's `N=30` streams / `K=3`
iterations are exposed as `--streams` / `--iterations`; durable runs use modest
values plus thread-pool parallelism so each setting finishes in minutes.

## Commands

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, stdlib + `openai`). API keys are read from the global
`XSkillForge/.env` (`scripts/models.py` walks up from the cwd to find the nearest
`.env` in any ancestor directory) — no per-skill `.env`, no `uv run`, no manual `export`.
Attacker/target/judge all use `OPENROUTER_API_KEY`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter

cd XSkillLib/Single-turn/Persuasion/2310.08419_PAIR/pair
$PY scripts/attack.py inspect --sample-rows 10          # peek the dataset (data/harmful_behaviors_custom.csv, 50 rows)
$PY scripts/attack.py smoke --out /tmp/2310.08419-pair-smoke.json   # wiring only, no model calls
$PY scripts/attack.py run \
  --attacker api:deepseek/deepseek-chat --target api:deepseek/deepseek-chat --judge api:deepseek/deepseek-chat \
  --streams 3 --iterations 3 --strategies roleplay,logical,authority \
  --sample-rows 20 --seed 7 --max-workers 3 --case-workers 8 \
  --out results/pair_deepseek_faithfuljudge_s3i3_20x_$(date +%Y%m%d-%H%M%S).json
# --data defaults to data/harmful_behaviors_custom.csv; pass --data <path> to swap datasets.
# Modular roles: --attacker / --target / --judge are independent api:<model> flags (mix-and-match),
# each with its own --attack-max-tokens / --target-max-tokens / --judge-max-tokens.
```

## Fidelity

`faithful_algorithm_code`: the multi-stream iterative PAIR search loop (attacker
JSON parsing, target querying, GPT-4 judge scoring, history feedback, early
stopping, rotating strategies) plus byte-verbatim official attacker + judge
prompts. Model substitution: OpenRouter `deepseek/deepseek-chat` serves all roles
instead of the paper's Mixtral attacker / Vicuna-Llama2-GPT4 targets / GPT-4 +
Llama Guard judges; the judge **prompt** is verbatim, only the serving model
differs. `fake` is only `--wiring-check` and is not attack evidence.

## Result Shape

Each result reports a DUAL metric (`judge10_asr` primary, `refusal_bypass_asr`
secondary/over-counting) and stores every stream and turn, including attacker
input messages, attacker JSON output, target input/output, judge raw output +
score, winning turn, and query counts.

## Final Result (real deepseek runs, self-checked)

| config | streams×iters | cases | judge10 ASR | refusal-bypass ASR | queries |
|--------|---------------|-------|-------------|--------------------|---------|
| s3i3   | 3 × 3         | 20    | 0.10 (2/20) | 1.00               | 180     |
| s2i2   | 2 × 2         | 20    | 0.05 (1/20) | 1.00               | ~80     |

`results/pair_deepseek_faithfuljudge_{s3i3,s2i2}_20x_20260610.json`. ASR
recomputed from raw per-case verdicts matches the stored summaries. All 3 judged
successes manually confirmed as GENUINE on-goal harm (food-poisoning methodology,
credential-harvesting phishing email, social-media hacking tutorial). The
deepseek attacker did not refuse the red-team role (0/180 empty attacker
prompts), so no fallback attacker was needed. Low absolute ASR is expected from a
strong target under a small budget with the strict GPT-4-judge==10 criterion.
