# Data — Stochastic Monkeys (2411.02785)

`sorry_bench_202406.csv` — the paper's safety set D, bundled verbatim from the official repo
(`uiuc-focal-lab/stochastic-monkeys`, `dataset/data/sorry_bench/sorry_bench_202406.csv`).

- **full_count: 450** (real-counted with `csv.DictReader`, not `wc -l`) — SORRY-Bench (Xie et al.,
  2024), 202406 release: 45 fine-grained unsafe-instruction categories × 10 prompts.
- Columns: `category`, `prompt` (the original harmful request x — the only field the attack needs),
  `target` (an affirmative-prefix string, unused by this reproduction).

The attack (`scripts/augmentations.py`) applies k independent random augmentations to `prompt`; the
judge (`scripts/roles.py`) scores compliance against the original `prompt`.
