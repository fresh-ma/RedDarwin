# CodeAttack

Paper-local method directory for arXiv `2403.07865`, "CodeAttack: Revealing Safety Generalization Challenges of Large Language Models via Code Completion".

This is a black-box, single-turn text attack. CodeAttack converts a harmful natural-language goal into a code-completion prompt with three parts: input encoding, task decoding, and output-list initialization. The target model is queried normally through chat/API access.

All model-backed local roles default to `api:deepseek/deepseek-v4-flash` per project policy. The paper and official repo use GPT-family model names for their original experiments; those names are retained only as provenance.

## Run

```bash
uv run python scripts/attack.py --help
uv run python scripts/attack.py --wiring-check
uv run python scripts/attack.py --render-only --n-requests 2 --output results/render_probe.json
uv run python scripts/attack.py \
  --dataset data/advbench_harmful_behaviors.csv \
  --prompt-type python_stack_plus \
  --n-requests 10 \
  --n-samples 1 \
  --target api:deepseek/deepseek-v4-flash \
  --target-max-tokens 512 \
  --judge policy \
  --judge-model api:deepseek/deepseek-v4-flash \
  --request-timeout 45 \
  --model-call-retries 3
```

`api:deepseek/deepseek-v4-flash` is routed to OpenRouter when no explicit `OPENAI_BASE_URL` is set, using `OPENROUTER_API_KEY` from the method-local `.env`.

## Data

- `data/advbench_harmful_behaviors.csv`: full 520-row AdvBench harmful behaviors file from the official CodeAttack repo.
- `data/templates/`: official CodeAttack templates for Python string/list/stack, plus variants, C++ string, and Go string.
- `data/manifest.json`: counts, checksums, and provenance.

## Source Provenance

- `references/official/`: official CodeAttack source files from `https://github.com/renqibing/CodeAttack` plus the OpenRT CodeAttack wrapper used as a secondary implementation reference.

## Notes

The local runner records the original goal, generated code-completion prompt, target response, postprocessed extracted output, judge output, and count-form ASR metrics. The policy judge uses the official 1-5 rubric with JSON response mode. Empty model outputs and request exceptions are retried; cases that remain empty or unparseable after retries are marked invalid and excluded from the ASR denominator.
