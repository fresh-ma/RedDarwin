# MathPrompt Code Plan

## Analysis Ledger

### paper-core

- Method: use an attacker LLM to rewrite a harmful natural-language request into
  a symbolic mathematics problem, then ask the target to solve it and provide a
  real-world example.
- Benchmark unit: run direct baseline and MathPrompt attack settings against
  replaceable chat targets, storing encoded math problem, target input/output,
  setting parameters, refusal-bypass verdict, and HarmBench-style content
  verdict.
- Dataset entry: paper-local AdvBench cache at
  `data/advbench/harmful_behaviors.csv`.
- Target panel: Qwen 2.5 7B and Mistral Nemo have completion results; DeepSeek
  Chat is used as attacker/judge substitute. DeepSeek-V4 Flash and DeepSeek
  Chat can be added as target IDs in a follow-up run.

### official-repo/report parity

- Official repo: none recorded; implementation is a paper-algorithm Code package
  from appendix prompts and digest evidence.
- Implemented mechanics: verbatim attacker system prompt, two few-shot examples,
  prepended solver instruction, direct baseline, MathPrompt attack setting,
  greedy decoding, and HarmBench classifier prompt served by an open/lab judge.
- Full paper-scale target sweep is not reproduced; the current artifact is a
  compact benchmark-unit validation over two open/lab targets.

### implementation-risk

- `no_external_staging_required`: no GPU/HPC/full-run staging is required for
  the current black-box benchmark unit; OpenRouter serves attacker, target, and
  judge roles.
- Durable completion evidence is the combined 80-case benchmark view generated
  from two real target runs.
- The official HarmBench-Llama classifier is GPU-only, so the benchmark uses the
  verbatim HarmBench prompt on an open/lab judge and records that substitution.

## Result Files

- Combined view:
  `results/mathprompt_qwen_mistral_combined_benchmark_view_20260622.json`
- Source runs:
  `results/mathprompt_qwen-2_5-7b-instruct.json`,
  `results/mathprompt_mistral-nemo.json`
