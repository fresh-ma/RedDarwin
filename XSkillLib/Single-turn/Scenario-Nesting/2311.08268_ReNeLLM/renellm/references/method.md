# Method

ReNeLLM is a black-box, training-free jailbreak generator with two stages, ported
verbatim from the official `NJUNLP/ReNeLLM` repo (commit `a61c39e`).

## Stage 1 — Prompt Rewriting

An attacker/rewrite LLM applies a *random subset* (1–6, random order) of six
rewrite operations to the original AdvBench behavior. The operation prompts in
`attack.py` (`REWRITE_OPERATIONS`) are copied verbatim from
`utils/prompt_rewrite_utils.py`:

- `shortenSentence` — paraphrase in ≤6 words; the model returns 5 candidates and
  one is chosen at random (then its number prefix is stripped).
- `misrewriteSentence` — misspell sensitive/illegal words ("theft -> theift").
- `changeOrder` — permute word order without changing words.
- `addChar` — insert meaningless foreign words.
- `languageMix` — translate one or two words into Chinese (English/Chinese mix).
- `styleChange` — rewrite into slang/dialect.

Per the official code, each rewrite call uses a per-call `random.uniform(0,1)`
temperature (so a prompt that gets rewritten into a harmless form can be re-rolled).
After rewriting, the **binary harmfulness judge** checks the rewritten prompt still
carries harmful intent (label `1`); a `0` re-rolls the rewrite loop.

## Stage 2 — Scenario Nesting

The rewritten prompt is substituted (`scenario.replace("<>", behavior)`) into one
of three universal scenarios, verbatim from `utils/scenario_nest_utils.py`:
code completion, LaTeX table filling, text continuation (the "Bob's dream" story).
The nested prompt is sent to the target. The target output is screened by the
official refusal gate (`apologize`/`sorry` + `TEST_PREFIXES`); a non-refusing
output is scored by the binary harmfulness judge. Success ⇒ label `1`; otherwise
the loop restarts up to `iter_max` (paper default 20).

## Fidelity notes

- Rewrite + target route through OpenRouter `api:<model>`.
- The harmfulness judge routes through **OpenAI-direct** (`api.openai.com`) because
  OpenRouter's `openai/*` route returns HTTP 403 on harmful-judge prompts.
- The judge is the official **binary 0/1 GPT classifier**, *not* a 1-5 Qi-et-al.
  policy judge. ReNeLLM never used the Qi 1-5 rubric — its GPT-ASR is exactly this
  binary classifier (see `utils/harmful_classification_utils.py` + `check_gpt_asr.py`).
