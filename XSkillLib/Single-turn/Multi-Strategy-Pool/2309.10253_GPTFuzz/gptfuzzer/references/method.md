# Method

GPTFuzzer treats jailbreak prompts as templates containing `[INSERT PROMPT HERE]`.
It keeps a seed pool of human-written jailbreak templates, selects a promising
template, mutates it with an LLM, renders the mutant against target harmful
questions, queries the target LLM, and adds the mutant back into the pool when
the judge marks at least one target response as jailbroken.

## Faithful port (official sherdencooper/GPTFuzz @ 0c26ccc)

The paper-local `scripts/attack.py` ports the official algorithm:

- **Seed pool / PromptNode tree.** Released seed templates loaded from the
  official `datasets/prompts/GPTFuzzer.csv` (`text` column). Each is a
  `PromptNode` with parent/children, level, visit count, reward.
- **Selection = `MCTSExploreSelectPolicy`.** Same UCT score
  `reward/(visits+1) + ratio*sqrt(2*ln(step)/(visits+0.01))`, descend from the
  best initial seed through children, breaking out of a non-leaf with
  probability `alpha`; reward back-propagated along the selected path with the
  level penalty `max(beta, 1 - 0.1*level)`. Defaults `ratio=0.5, alpha=0.1,
  beta=0.2` match the official `MCTSExploreSelectPolicy.__init__`.
- **Mutators = the five official LLM mutators** with their VERBATIM prompts
  (`generate_similar`, `cross_over`, `expand`, `shorten`, `rephrase`), copied
  from `gptfuzzer/fuzzer/mutator.py`. `expand` prepends the LLM output to the
  seed; `MutateRandomSinglePolicy(concatentate=True)` then appends the parent
  prompt — both reproduced. One mutator is chosen at random per energy step.
- **Mutator LLM via `api:`.** The paper used `gpt-3.5-turbo` at temperature 0.
  OpenRouter's `openai/*` route returns HTTP 403 (provider ToS) on the
  jailbreak-template mutator prompt, so the default mutator is the documented
  substitute `meta-llama/llama-3.3-70b-instruct` (override with
  `--mutator-model`); `deepseek/deepseek-chat` also works.
- **Target via `api:`** (black-box) over any OpenAI-compatible endpoint.
- **Retain-on-jailbreak** back into the pool, same as official `update()`.

## Judge

The **official judge** is the paper's finetuned RoBERTa-large harmfulness
classifier `hubert233/GPTFuzz` (`gptfuzzer/utils/predict.py`,
`RoBERTaPredictor`): label `1` == jailbroken. The paper-local `RoBERTaJudge`
loads it via `transformers` and runs it on **CPU** (it is small), scoring each
target response exactly as the official `predict()` does (softmax → argmax). A
refusal-bypass string proxy is reported only as a **secondary** metric.

## Fidelity

`fidelity_level = paper_algorithm_code`. The search loop, the five mutator
prompts, the MCTS selection, and the official RoBERTa judge are all reproduced.
The only substitution is the mutator LLM identity (gpt-3.5-turbo → an available
OpenRouter model), labeled `model_substitution_run`; the judge is the paper's
actual classifier, not a proxy.
