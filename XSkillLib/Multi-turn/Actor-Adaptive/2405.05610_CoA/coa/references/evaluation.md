# Evaluation Notes

The durable result JSON stores:

- chain generation messages and attacker output;
- the selected chain;
- per-turn target input messages, target output, semantic score, semantic delta, walk decision, and refusal-proxy judge;
- run parameters and source references.

`fake` is only accepted with `--wiring-check`. It is not counted as Code evidence. A paper-faithful evaluation requires SIMCSE, the full query budget, and a stronger LLM judge.
