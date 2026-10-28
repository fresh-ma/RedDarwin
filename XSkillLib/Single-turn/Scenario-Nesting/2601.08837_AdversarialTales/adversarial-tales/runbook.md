# Runbook

From the method directory, `uv run python scripts/attack.py --inspect` verifies
the local data and prompt assembly without a network request. A live run uses
API-only transformer, target, and judge calls and may run locally. Request
Deakin only for a future local-model or GPU variant.

The default data is the packaged historical N=20 AILuminate substitution sample.
Use `--dataset` to supply another CSV, JSON, or JSONL file with a goal-like
field. Results are written to `results/` with the chosen configuration.

The package rejects GPT, Claude, and Gemini model routes. Historical results
retain their original model IDs; they are evidence, not defaults for future
executions.
