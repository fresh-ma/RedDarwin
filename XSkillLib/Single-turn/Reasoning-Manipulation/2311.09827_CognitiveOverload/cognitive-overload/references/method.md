# Cognitive Overload Method Notes

Paper anchors:

- `sec:2`: AdvBench and MasterKey are the malicious-prompt datasets.
- `sec:3.1`: multilingual setup translates AdvBench/MasterKey into 52
  non-English languages and uses rejection phrases for ASR after optional
  back-translation.
- `sec:3.2`: monolingual cognitive overload prompts the LLM directly in a
  non-English language.
- `sec:3.3`: language-switching uses a context turn in one language followed by
  the harmful prompt in the other language.
- `sec:4`: veiled expression requires sensitive phrase extraction/replacement
  with Mistral.
- `sec:5`: effect-to-cause requires event extraction and reframing.

Current implementation:

- Loads official released AdvBench JSONL translations.
- Loads official released wiki contexts for language-switch cases.
- Emits chat-message input records for monolingual, language-switch, and
  effect-to-cause modes (effect-to-cause template verbatim from
  `perform_effect_to_cause.py`).
- Runs the rendered prompts against an OpenRouter black-box target and scores
  each response with the verbatim official rejection-phrase judge plus a
  content-harm LLM judge (dual metric). See SKILL.md and plan.md.
- Out of scope (black-box reduction): Google Translate, DPR retrieval, NLLB
  back-translation, Mistral veiled-expression generation.

