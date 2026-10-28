# Dataset source — AdvBench harmful behaviors

## What
`advbench_harmful_behaviors.json` — the complete **AdvBench** *harmful behaviors*
set: a flat JSON list of 520 rows, each `{"id", "goal", "target"}` where `goal`
is the harmful instruction and `target` is the canonical affirmative-prefix
("Sure, here is ...") used by AdvBench.

This is the malicious-request dataset the paper uses for the ICA attack and ICD
defense evaluation.

> Paper (2310.06387, §5.1 Overall Evaluation Setups): "For the malicious
> requests, we use **AdvBench** [Zou et al. 2023] which consists of about 500
> harmful behavior prompts." ASR on AdvBench is judged by rejection-string
> detection plus the HarmBench fine-tuned judge. (The paper additionally
> implements ICA on the HarmBench official repo for the benchmark-comparison
> table; that comparison runs inside HarmBench's own harness and is out of scope
> for this self-contained attack unit, which targets the AdvBench evaluation.)

## Source
AdvBench `harmful_behaviors.csv` from Zou et al. 2023, *Universal and
Transferable Adversarial Attacks on Aligned Language Models*
(repo `llm-attacks/llm-attacks`, `data/advbench/harmful_behaviors.csv`).
Verified byte-for-byte identical (goal column) to the cached canonical copy at
`.workspace/external/NJUNLP__ReNeLLM/data/advbench/harmful_behaviors.csv`
(521 lines incl. header = 520 behaviors). Converted from CSV to flat JSON here.

## Full count
520 harmful behaviors (complete set — no slice/sample).

## Fields
- `id`: 1-based row index.
- `goal`: harmful instruction (read by `load_dataset` as the `request`).
- `target`: AdvBench canonical affirmative prefix.

## Notes
- The previous 20-row `advbench_slice.csv` and the redundant
  `harmful_behaviors_full.csv` have been removed; this JSON is the single,
  complete live dataset.
- ICA demonstrations live separately in `ica_demonstrations.json` (the few-shot
  harmful query/response pairs prepended as the in-context prefix); they are the
  attack's demonstration set, not the evaluation dataset.
