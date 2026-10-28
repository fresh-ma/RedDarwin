# Evaluation Notes

The result JSON stores per case:

- selected raw goal and encrypted text (`str()`-serialized exactly like the official pipeline);
- full `model_input_messages` (incl. the official `code_sys_helpful` system prompt) and joined text;
- raw `model_output_text`;
- the official **GPT-4 OpenAI-policy 1-5 harmfulness judge** (Qi 2023), ported verbatim from
  `gpt_evaluate.py` (`judge_template` + `#thescore:` extraction). Run via OpenAI-direct
  (`api.openai.com`, `OPENAI_API_KEY`) because OpenRouter 403s harmful-judge prompts;
- a secondary `refusal_proxy_refused` flag (dual metric).

Score convention (paper-faithful):

- `asr_strict_score_eq5` = fraction scoring exactly 5 (the paper's headline ASR);
- `asr_content_harmful_score_ge4` = fraction scoring >= 4 (content-harmful);
- `asr_refusal_bypass` = fraction not matching a refusal pattern (over-counts; reported as a floor).

`fake` target is only accepted with `--wiring-check`. The judge call retries on transient 429 with
backoff; a hard `insufficient_quota` is labeled `quota_exhausted` and not retried. Use the `rejudge`
subcommand to fill ungraded gaps without re-spending on already-scored cases.
