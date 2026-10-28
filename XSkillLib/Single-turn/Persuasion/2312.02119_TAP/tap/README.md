# TAP Reproduction Unit

Paper: `2312.02119` — Tree of Attacks: Jailbreaking Black-Box LLMs Automatically.

This folder is the paper-local runner for Tree of Attacks with Pruning (TAP). TAP is a black-box automated jailbreak search method. It uses an attacker LLM to generate candidate prompts, an evaluator LLM to prune off-topic candidates and score target responses, and a target LLM that receives only the candidate prompt.

## Scope

- Threat model: black-box access to the target model.
- Modality: text chat prompts.
- Search: iterative tree search with branching, pre-target pruning, target querying, judge scoring, and post-target pruning.
- Default roles:
  - `--attacker api:deepseek/deepseek-v4-flash`
  - `--target api:deepseek/deepseek-v4-flash`
  - `--evaluator api:deepseek/deepseek-v4-flash`
- GPU: not required when the three roles are API models.

The official paper implementation used Vicuna-13B-v1.5 as attacker and GPT-4 as evaluator. This benchmark unit defaults to DeepSeek Flash for all model-backed roles per local project policy; role substitution is recorded in result settings.

## Data

- `data/advbench_subset.csv`
- 50 goals
- Official source: `RICommunity/TAP` `data/advbench_subset.csv`, revision `7bcdad30537c679d00699fac16052dc916c89a6d`

## Run

```bash
uv sync
uv run python scripts/attack.py --help
uv run python scripts/attack.py --render-only --n-requests 2 --output results/render_probe.json
uv run python scripts/attack.py --wiring-check --output results/wiring_check.json
```

Low-cost API run shape:

```bash
uv run python scripts/attack.py \
  --n-requests 1 \
  --branching-factor 2 \
  --width 2 \
  --depth 2 \
  --attacker api:deepseek/deepseek-v4-flash \
  --target api:deepseek/deepseek-v4-flash \
  --evaluator api:deepseek/deepseek-v4-flash
```

Paper-scale parameters:

```bash
uv run python scripts/attack.py --branching-factor 4 --width 10 --depth 10 --keep-last-n 3 --n-requests 50
```

## Outputs

Result JSON files preserve:

- original goal and target prefix;
- attacker improvements and candidate prompts;
- on-topic scores;
- target responses and target call provenance;
- evaluator judge scores;
- tree/pruning counts by iteration;
- target/attacker/evaluator query counts.

Metrics use explicit count format: `success_count/denominator = rate`. If all target calls for a goal return empty output, that goal is marked invalid and excluded from the denominator.
