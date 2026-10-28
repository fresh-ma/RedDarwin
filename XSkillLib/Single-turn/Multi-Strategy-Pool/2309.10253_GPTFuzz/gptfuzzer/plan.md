# GPTFuzzer (2309.10253) — reproduction plan

## Access classification

**black_box.** The target is queried as a chat API only; no gradients, logits,
or local target weights. The attacker side is an **LLM mutator** (the five
official OpenAI mutators), and the judge is the paper's finetuned RoBERTa
classifier run locally on CPU. Feasible black-box against OpenRouter.

## Algorithm core

GPTFuzzer is a fuzzing loop over jailbreak templates:

1. Seed pool of human-written jailbreak templates (`PromptNode` tree).
2. `MCTSExploreSelectPolicy` seed selection (UCT exploit+explore, level penalty
   `mcts_alpha`, minimal reward `mcts_beta`, non-leaf termination prob `mcts_ratio`).
3. `MutateRandomSinglePolicy`: pick one of the five official mutators
   (generate_similar / cross_over / expand / shorten / rephrase, verbatim prompts)
   driven by an attacker LLM; `concatenate=True`.
4. Render each mutant with a harmful question, query the target, judge with the
   official RoBERTa classifier (`hubert233/GPTFuzz`, label 1 == jailbroken),
   retain successful mutants back into the pool.

## Reproduction choices (confirmed)

- **Target + mutator LLM** = `api:deepseek/deepseek-chat` (OpenRouter).
  `run_kind = model_substitution_run` — paper used GPT-3.5 / Llama-2 / Vicuna
  targets + GPT-3.5 mutator; DeepSeek is the documented open substitute.
- **Judge** = the paper's OFFICIAL finetuned RoBERTa `hubert233/GPTFuzz`, loaded
  in-process on CPU (verbatim, the most goal-faithful judge available — it is the
  exact classifier the paper used). A refusal-bypass heuristic is recorded only as
  a labelled secondary metric. Needs `transformers==4.46.3` (newer transformers
  rejects the checkpoint's int-valued `id2label`).
- **Data** = official GPTFuzz CSVs vendored at `data/` (77 seed
  templates, 100 AdvBench-style harmful questions).

## Completion gate (met)

Real run, >=10 cases x >=2 configs:

| Setting | params | goals | attempts | RoBERTa JB | ASR |
|---|---|---|---|---|---|
| A | seed20260609, e1 iter3, mcts 0.5/0.1/0.2, mutators {cross_over, expand} | 20 | 60 | 54 | 0.90 |
| B | seed4242, e1 iter2, mcts 0.3/0.2/0.3, mutators {cross_over, shorten} | 20 | 40 | 25 | 0.625 |
| Combined | | 40 | 100 | 79 | **0.79** |

0 provider/mutator errors. Refusal-bypass secondary = 0.65 combined. Full model
I/O + RoBERTa label saved per record in
`results/gptfuzzer_deepseek_roberta_setting{A,B}_20260610.json`.

## Fidelity deltas

Faithful algorithm port of `sherdencooper/GPTFuzz @ 0c26ccc` (seed pool, MCTS
selection, five verbatim mutators, retain-on-success) with the official RoBERTa
judge. Not run at paper scale (paper sweeps many models / full question set);
this is a benchmark-unit gate, not a full ASR-table replication.
