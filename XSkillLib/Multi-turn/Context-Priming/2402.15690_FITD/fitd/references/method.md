# Method Reference

- Paper evidence: `digest/algorithms/alg-1.tex`, `digest/sections/04.02-algorithm-design.md`,
  `digest/sections/04.03-split-instance.md`, `digest/sections/04.04-jailbreak-check.md`.
- Template evidence: `digest/sections/08.01-*` through `08.05-*`, plus
  `digest/sections/09-prompt-for-jailbreak-status-judgment.md`.
- No official public repo: `paper.meta.json.code_repos == []` (the cached
  `jinxiaolong1129/foot-in-the-door` repo is a different paper, arXiv:2502.19820).
  Faithfulness is measured against this paper's Algorithm 1 + appendix prompts.
- **Implemented (faithful):** Algorithm 1 per-turn query + judge + recursive
  split-on-refusal (`run_fitd_episode`); the 3-layer split instance
  background -> villain -> plot (`base_prompts`); the two-part and good-purpose
  splitters (`split_prompt`, Sec 8.4/8.5); the verbatim 1-10 oracle judge
  (`PAPER_JUDGE_PROMPT`, Sec 9).
- **Documented substitution:** the split instance is the paper's deterministic
  published template (the paper's optional LLM splitter is one instantiation of
  a "split instance"); judge serving model is OpenRouter (prompt verbatim).
