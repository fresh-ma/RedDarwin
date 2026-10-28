# Code Report: Contextual Interaction Attack (2402.09177)

## Status

`ready_to_use`. See `code/check.json` (v2 5-core, all dimensions pass).

The package runs the full faithful CIA pipeline end-to-end on a live target:
auxiliary-LLM decomposition (verbatim appendix §16 prompt) → multi-turn `[1,1]`
target run feeding the target's own `αᵢ` back as the context vector → dual judge
(prefix-matching refusal-bypass + verbatim PAIR GPT-4 ChatGPT-score rubric,
Rating==10).

## Implemented

- `cia-context/scripts/attack.py` — `inspect` (no network) + gated live `run`.
- Verbatim appendix §16 auxiliary-generation prompt (3 demonstrations).
- Verbatim PAIR / ChatGPT-score judge rubric (§9), Rating==10 convention.
- Sequential `[1,1]` target conversation carrying `αᵢ` forward.
- 10-row AdvBench subset cache; ≥2 target models enforced for ≥2 parameter sets.
- Per-turn transcripts, finish reason, usage, truncation, and provider-error
  metadata; incremental checkpointing.

## Result (20-case live run)

| Metric | Value |
|---|---|
| refusal-bypass ASR (prefix matching) | 0.95 |
| content-harmful ASR (PAIR GPT-4, Rating==10) | 0.00 |
| mean ChatGPT rating | 1.0 |
| auxiliary refusals (counted as failures, §4.1) | 1/20 |
| truncated at max_tokens | 12/20 |
| provider errors | 0 |

Deliverable: `results/archive/cia_context_run_20260611_ready.json`.

The 0.00 content-harmful ASR is an honest, expected alignment-dependent outcome:
on robust 2024 open models (Llama-3.1-8B, Qwen-2.5-7B) the disguised paraphrase
elicits a generic *ethical* artifact rather than the actual harmful goal, which
the strict PAIR judge correctly rates 1 (verified from per-case judge
justifications). The 0.95 vs 0.00 gap is exactly the prefix-matching
over-counting the paper notes in §9.

## Substitutions (documented)

- Auxiliary LLM: WizardLM-70B → `deepseek/deepseek-chat` (not served; verbatim
  prompt unchanged).
- Judge serving model: `deepseek/deepseek-chat` (openai/* 403s harmful judging;
  rubric byte-for-byte from §9).
- Targets: open/lab OpenRouter panel; never GPT/Claude/Gemini.
- The human judge (§9 headline) is the one paper judge left out as not
  reproducible offline.
