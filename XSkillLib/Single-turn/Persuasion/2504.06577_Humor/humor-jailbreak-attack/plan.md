# plan — humor jailbreak (2504.06577)

## Depth
Faithful from-paper reimplementation. No official repo (`code_repos=[]`); the attack is a
single fixed template, so full fidelity is reachable from the paper text alone (Figure 1 +
Sec 5 ablation + Sec 4 datasets/judge).

## Decisions
- **target**: OpenRouter `deepseek/deepseek-chat` (black-box). Paper used open weights
  Llama-3.3-70B / Llama-3.1-8B / Mixtral / Gemma-3-27B via local H100; substitute an
  OpenRouter open target (role preserved). Temp 0 (paper App. hyperparameters).
- **judge**: `deepseek/deepseek-v4-flash`, dual metric (refusal_bypass + content_harmful)
  as the canonical, PLUS the paper's binary "is-unsafe / did-jailbreak-happen" judge
  (Sec 4). content_harmful prompt is humor-shell aware (joke-only = not harmful). Paper's
  judge (Llama-3.3-70B) is swappable via `--judge`.
- **dataset**: paper uses JBB(100)/AdvBench(520)/HEx-PHI(300); all held full in `data/`,
  default AdvBench. Validation sample = 10 goals × 9 configs.
- **configs**: humor×{man,chicken,I,goat} + ablation×{...} + direct — reproduces the
  paper's core comparisons (humor vs direct-injection; humor vs no-humor ablation).
- **no GPU** — pure black-box API.

## Ask-first items (none triggered)
Target substitution (open→open) is policy-allowed and recorded; no gated data, no expensive
compute, no sensitive-storage decisions.

## Verify
- render matches Figure 1 verbatim + ablation removes exactly the 4 humor phrases ✓
- real run 0 provider errors, schema-aware empty scan (final_output) ✓
- recompute dual/paper ASR from raw verdicts == summary ✓
- audit content_harmful positives for genuine operational harm (independent GLM) ✓
