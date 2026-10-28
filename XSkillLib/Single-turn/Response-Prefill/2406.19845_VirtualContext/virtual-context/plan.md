# Virtual Context Plan and Runbook

## Paper Route

Method name: **Virtual Context** (Zhou et al., arXiv 2406.19845).
Black-box special-token injection: `I = x ∘ <SEP> ∘ O_x` where `O_x` is an affirmative response.
No official repo → paper-derived from Sec 4 + Appendix tables (refusal vocab, HarmScore prompt, model templates).

## Data

Full AdvBench-compatible set held at `data/advbench/harmful_behaviors_custom.csv` (520 rows).
Validation run = sample 20.

## Real Evaluation

```bash
cd virtual-context
uv run python scripts/attack.py \
  --target api:deepseek/deepseek-v4-flash \
  --judge api:deepseek/deepseek-v4-flash \
  --sample 20 --template plain --separator sep \
  --target-max-tokens 1024
```

Dual metrics: refusal_bypass + content_harmful (yes/no judges).
Also records paper Matching / refusal-vocab ASR / HarmScore.

## Naming

Unit folder: `2406.19845_VirtualContext` (paper method name, correct).
Method dir: `virtual-context/`.
