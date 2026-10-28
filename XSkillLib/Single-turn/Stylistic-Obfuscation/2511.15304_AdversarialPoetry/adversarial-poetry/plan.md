# Adversarial Poetry Code Plan

## Analysis Ledger

### paper-core

- Method: rewrite a harmful request into verse with a fixed LLM meta-prompt,
  then compare baseline versus poetic single-turn responses on the same target.
- Benchmark unit: run both arms on the same sampled dataset rows, store target
  input, target output, status, and 3-judge majority verdicts.
- Dataset entry: MLCommons AILuminate demo set staged in `code/data/`; runner
  accepts `--dataset` and `--sample`.
- Model substitution: no GPT, Gemini, or Claude roles. The current completed
  run uses Qwen 7B target, DeepSeek v4 flash transformer, and DeepSeek/Qwen/Mistral
  judges.

### official-repo/report parity

- Official repo: none released; this is a paper-algorithm Code reconstruction.
- Fidelity target: preserve the paper's two-arm baseline-vs-poetic design,
  single-turn text target, fixed rewrite prompt, and 3-judge 2-of-3 evaluation.
- Released poems are withheld by the paper; the local Code uses benign
  style-only exemplars as documented in the method skill.

### implementation-risk

- No GPU or external staging is required; OpenRouter serves all model roles.
- The completed result is a real model run, not smoke or replay: 10 sampled
  prompts, 20 target calls across baseline/poetic arms, and per-arm judge fields.
- Current result is a quick benchmark validation, not the paper's full sweep.

## Run Command

```bash
# run from the method dir: adversarial-poetry/
uv run python -u scripts/attack.py \
  --sample 10 \
  --seed 260622 \
  --target api:qwen/qwen-2.5-7b-instruct \
  --transform-model api:deepseek/deepseek-v4-flash \
  --judges deepseek/deepseek-v4-flash,qwen/qwen-2.5-72b-instruct,mistralai/mistral-small-3.2-24b-instruct \
  --out results/poetry_qwen7b_openjudges_n10_20260622.json
```

## Result Files

- Raw result: `results/poetry_qwen7b_openjudges_n10_20260622.json`
- Benchmark view: `results/poetry_qwen7b_openjudges_n10_benchmark_view_20260622.json`
