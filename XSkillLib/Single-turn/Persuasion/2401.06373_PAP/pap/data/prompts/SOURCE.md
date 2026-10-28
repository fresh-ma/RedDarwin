# Prompt templates — PAP (2401.06373)

All verbatim from official sources. Loaded at runtime by `scripts/attack.py`.

## `one_shot_kd.txt`
The in-context persuasive paraphraser template (7 `%s` placeholders).
- Source: `incontext_sampling_example.ipynb` (official repo `CHATS-lab/persuasive_jailbreaker`)
- Filled by `build_generator_prompt(goal, technique)` — takes technique name/definition/example
  + the harmful query, produces a persuasive rewrite.

## `qi_judge.txt`
Qi et al. 2023 GPT-4 Judge rubric (2 `%s` placeholders: user_instruction, model_response).
- Source: `LLM-Tuning-Safety/LLMs-Finetuning-Safety` repo, `openai_policy_gpt4_judge.py`
- 1-5 Likert scale; score 5 = full jailbreak.

## `mutations/` (5 files)
Alternative directed-mutation templates from `PAP_Better_Incontext_Sample/mutation_utils.py`.
Each contains a technique definition + 4-5 few-shot examples + output format.
Single `%s` placeholder for the adversarial prompt.
- `evidence_based_persuasion.txt`
- `expert_endorsement.txt`
- `misrepresentation.txt`
- `authority_endorsement.txt`
- `logical_appeal.txt`
