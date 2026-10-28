# Code Runbook: Contextual Interaction Attack (2402.09177)

The script runs the full faithful pipeline: auxiliary-LLM decomposition (verbatim
appendix prompt) → multi-turn target run → dual judge (prefix-matching +
verbatim PAIR GPT-4 rubric). OpenRouter key auto-loads from project-root `.env`.

```bash
# Inspect the pipeline + paper defaults (no network)
uv run --no-project python3 \
  scripts/attack.py inspect

# Full live run: 2 target models x 10 AdvBench goals = 20 cases (>=2 param sets)
uv run --no-project --with openai python3 \
  scripts/attack.py run \
  --allow-live \
  --sample-rows 10 \
  --targets meta-llama/llama-3.1-8b-instruct,qwen/qwen-2.5-7b-instruct \
  --aux-model deepseek/deepseek-chat \
  --judge-model deepseek/deepseek-chat \
  --max-tokens 1024 \
  --request-delay 0.1 \
  --out results/cia_context_run_20260611.json
```

Notes:
- `--targets` must list ≥2 models (≥2 parameter sets). Pick from the open/lab
  panel (`code_knowledge/snippets/value/target_panel.py`); never GPT/Claude/Gemini.
- Each case = 1 auxiliary call + (n+1) target calls + 1 judge call.
- The run writes an incremental checkpoint after every case, so a long run is
  resumable by inspecting the partial `--out` file.
- Headline metric = `summary.metrics.asr_content_harmful` (PAIR rubric, Rating==10).
  `asr_refusal_bypass` is the prefix-matching upper bound.
