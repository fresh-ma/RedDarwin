# plan — LATS / break-me (arXiv 2601.02670)

> plan-first gate record. This unit was built in the consolidate/pilot pass (DH-CoT pattern).
> Depth, target/judge routing, and dataset choices below are the defaults; the paid full run
> is done later by the orchestrator (this pass is static/wiring only).

## What it is

Multi-turn, **attacker-LLM-free**, black-box jailbreak (LATS = Lexical Anchor Tree Search).
The victim T generates its own seed pool of benign/harmful prompt-completion pairs; a BFS tree
search inspects the top-k pool prompts (completion-expansion) and, on failure, injects the
missing lexical anchors of the goal P* (anchor-injection) to grow child conversations.

## Reproduction depth: faithful_from_paper

No official code (`code_repos: []`). Algorithm 1 + Appendix 12–14 prompts reimplemented
verbatim. Modular consolidate shape (prompts/models/roles/anchors/cases/lats/attack).

## Choices (defaults; revisit before the paid run)

- **Target**: black-box `api:` / local `auto:` (multi-turn ⇒ dozens of calls/goal; prefer
  `auto:` local victim for large runs). Default judge/json-fixer `api:deepseek/deepseek-v4-flash`.
- **Judge**: single HarmBench-yes/no LLM + refusal-bypass heuristic (dual metric). The paper's
  3-model majority-vote ensemble is documented, not reproduced.
- **Lexical tools**: sentence-transformers Top-k + spaCy/wordfreq anchors (optional `faithful`
  extra); deterministic lexical fallback keeps it runnable offline.
- **Dataset**: 25-goal AdvBench-style seed (`data/advbench_seed.csv`); full AdvBench/HarmBench
  droppable via `--data`.
- **Budget**: `--max-queries 40` per goal (paper avg ~6.4 successful; modern aligned victims
  may exhaust the budget — expect a faithful negative there, not a bug).

## Open questions for Oscar (before scale run)

- Victim model choice for the canonical run (open model era-matched to the paper's targets?).
- Whether to pull the full 520-row AdvBench for the headline comparison.
