# Data sources — PAP (2401.06373)

## `data/` (paper-local inputs, tracked)

- **`persuasion_taxonomy.jsonl`** (40) — official 40-technique social-influence taxonomy,
  from `CHATS-lab/persuasive_jailbreaker`. Each row: `{ss_technique, ss_definition, ss_example}`.
  Also in `official/persuasion_taxonomy.jsonl` (identical).
- **`advbench_harmful_behaviors.csv`** (520) — AdvBench harmful behaviors from
  `llm-attacks/llm-attacks`. Columns: `goal`, `target`.

## `official/` (verbatim official repo, data artifacts only)

- `PAP_Better_Incontext_Sample/mutation_utils.py` — mutation template source
  (5 techniques extracted to `data/prompts/mutations/`)
- `persuasion_taxonomy.jsonl` — identical to `data/` copy

Official repo: `github.com/CHATS-lab/persuasive_jailbreaker`
