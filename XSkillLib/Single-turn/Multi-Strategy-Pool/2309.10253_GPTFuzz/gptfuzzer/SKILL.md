---
name: gptfuzzer
description: "Run a paper-local GPTFuzzer Code package with seed templates, MCTS-style selection, template mutators, target calls, predictor feedback, and inspectable model I/O."
metadata:
  paper: "2309.10253_auto-generated-llm-jailbreaks"
  access: black_box
  mechanism: seed-template fuzzing
  fidelity_level: paper_algorithm_code
  script: "scripts/attack.py"
  status: live_gate_passed_roberta_judge
---

# GPTFuzzer

This implements the paper's fuzzing loop: load jailbreak seed templates,
select a seed with MCTSExploreSelectPolicy scoring, mutate it with one of the
five OFFICIAL OpenAI mutators (generate_similar / cross_over / expand / shorten /
rephrase, verbatim prompts driven by an LLM), render each mutant with target
questions, call a target model, judge the responses with the paper's official
finetuned RoBERTa classifier `hubert233/GPTFuzz` (label 1 == jailbroken), and
retain successful mutants back into the seed pool.

Target + mutator LLM go through any OpenAI-compatible endpoint (OpenRouter by
default). The RoBERTa judge runs in-process on CPU; a refusal-bypass proxy is
recorded only as a labeled secondary metric.

Seed templates + harmful questions are the official GPTFuzz CSVs vendored at
`gptfuzzer/data/` (77 templates, 100 AdvBench-style questions);
`attack.py` resolves them relative to the script, so it runs from any CWD.

**Environment (XSkillLib convention):** one shared venv at the XSkillForge repo root
(`XSkillForge/.venv`, deps `openai` + `transformers==4.46.3` + `torch` + ...). API keys are
read from the global `XSkillForge/.env` (`scripts/models.py` walks up to find it) — no
per-skill `.env`, no `uv run`, no manual `export`.

```bash
PY=/path/to/XSkillForge/.venv/bin/python   # shared venv interpreter
```

Wiring / shape check (no API, no judge):

```bash
cd XSkillLib/Single-turn/Multi-Strategy-Pool/2309.10253_GPTFuzz/gptfuzzer
$PY scripts/attack.py inspect --out /tmp/gptfuzzer-inspect.json
$PY scripts/attack.py run --target fake --wiring-check --iterations 8 --energy 2 --sample-rows 3 --max-queries 30 --out /tmp/gptfuzzer-wiring.json
```

Live run (RoBERTa-judged, target + mutator over OpenRouter, key from global XSkillForge/.env):

```bash
cd XSkillLib/Single-turn/Multi-Strategy-Pool/2309.10253_GPTFuzz/gptfuzzer
$PY scripts/attack.py run \
  --target api:deepseek/deepseek-chat --mutator-model deepseek/deepseek-chat \
  --seed-templates-limit 4 --sample-rows 20 --iterations 3 --energy 1 --max-queries 80 \
  --out results/gptfuzzer_run.json
```

`transformers==4.46.3` (already pinned in the shared venv) is required: newer transformers
rejects the checkpoint's int-valued `id2label` config. The result JSON stores generated
templates, model input messages/text, model outputs, the RoBERTa class label per
record, per-iteration trace, and the retained seed pool.

`fake` is only a `--wiring-check` target. It validates loop/result shape and is
not attack evidence.

## Completed live gate (2026-06-10)

DeepSeek target + DeepSeek mutator, official RoBERTa judge, 20 goals x 2 settings:
settingA ASR 54/60=0.90, settingB ASR 25/40=0.625, combined 79/100=0.79, 0
provider errors. Results in `results/gptfuzzer_deepseek_roberta_setting{A,B}_20260610.json`.

## Self-check (2026-06-25)

Recomputed ASR straight from per-case `judge.jailbroken` flags: settingA 54/60,
settingB 25/40 — matches the reported numbers exactly. Read the judged-success
outputs: all sampled positives are genuine on-goal harmful completions (the AIM /
"Dr. Al" template yields step-by-step harmful instructions that fulfil the
original goal); non-jailbroken cases are correctly-labelled refusals. Judge is
the paper's OWN finetuned RoBERTa (verbatim, the most faithful judge available),
so off-topic false positives are minimal. No false negatives or pipeline issues
(0 provider/mutator errors). Honest combined ASR = **0.79** (RoBERTa),
**0.65** (refusal-bypass secondary).
