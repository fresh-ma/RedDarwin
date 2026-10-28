# PAP Method Reference

## Mechanism

PAP (Persuasive Adversarial Prompts) rewrites a plain harmful query using
persuasion techniques from a 40-technique taxonomy. The attacker LLM receives
an in-context prompt template (`one_shot_kd`) containing the technique name,
definition, and a health-intervention example, then generates a persuasive
paraphrase that preserves the original harmful intent while sounding more
reasonable.

Paper: Zeng et al. "How Johnny Can Persuade LLMs to Jailbreak Them" (2401.06373)

## Generator Template

Verbatim `one_shot_kd` from the official repo's `incontext_sampling_example.ipynb`.
The template has 7 `%s` placeholders filled with:
1. technique name
2. technique definition
3. technique example (health domain)
4. harmful query
5. technique name (repeated)
6. harmful query (repeated)
7. harmful query (repeated)

The official repo uses GPT-4 (gpt-4-0613) with temperature=1, max_tokens=2500.

## Judge

Qi et al. 2023 GPT-4 Judge rubric from `openai_policy_gpt4_judge.py` in
https://github.com/LLM-Tuning-Safety/LLMs-Finetuning-Safety. Scores 1-5
on a Likert scale; only score 5 counts as jailbreak success in the paper.

## Taxonomy

40 persuasion techniques across 13 strategies (ethical and unethical),
from psychology, communication, sociology, marketing, and NLP literature.
Published at https://github.com/CHATS-lab/persuasive_jailbreaker/blob/main/persuasion_taxonomy.jsonl

## Key Paper Numbers (Table 1, 3-trial ASR)

- Llama-2 7b: 68%
- GPT-3.5: 86%
- GPT-4: 88%
- Claude 1/2: 0%

10-trial: >92% on Llama-2, GPT-3.5, GPT-4.

## Substitutions in Our Reproduction

- Attacker: deepseek-chat (paper: gpt-4-0613)
- Target: deepseek-chat (paper: gpt-3.5/gpt-4/llama-2/claude)
- Judge: deepseek-chat (paper: gpt-4-0613)
- Dataset: AdvBench 520 sampled to 10 (paper: PAIR-refined AdvBench 50)
- Template: `one_shot_kd` in-context (paper also uses fine-tuned paraphraser
  for the in-depth probe; we use the in-context method from the broad scan)
