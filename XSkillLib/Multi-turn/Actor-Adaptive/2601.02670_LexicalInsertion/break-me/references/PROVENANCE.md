# PROVENANCE — LATS (arXiv 2601.02670)

## Official code status

**No official code release.** `paper.meta.json` records `code_repos: []`; the repro_class
notes a HuggingFace paper page saying "code/datasets will be released" but nothing was
available at reproduction time. `fidelity_level = faithful_from_paper` — the algorithm and
every prompt are reimplemented from the paper text + appendices, not ported from a repo.

## Verbatim prompt sources (byte-identical to the digest)

All prompt bodies live in `scripts/prompts.py`, transcribed verbatim from the local digest
`xsafebench/multi-turn/2601.02670_multi-turn-lexical-jailbreak/digest/sections/`:

| prompts.py constant | Paper source (Appendix) |
|---|---|
| `SEED_POOL_PROMPT` | Appendix 12 "LATS Tree Search Prompts" — Seed-Pool Prompt (`{n}` = pool size, paper renders 30) |
| `COMPLETION_EXPANSION_PROMPT` | Appendix 12 — Completion-Expansion (`Expand on pair #{i}`) |
| `COMPLETION_EXPANSION_TARGET_PROMPT` | Appendix 12 — the sim<0.85 variant that restates the exact P* |
| `ANCHOR_INJECTION_PROMPT` | Appendix 12 / Sec 4.2 box — Anchor-Injection (must incorporate anchor words) |
| `JSON_FIX_PROMPT` | Appendix 13 "Ensuring JSON-Adherent Output" — correction prompt |
| `JUDGE_SYSTEM_PROMPT` | Appendix 14 "LLM Judge System Prompt" — HarmBench-adapted yes/no classifier |

### Transcription notes (template vs rendered instance)

- The paper's appendix boxes mix parameterized templates with rendered instances. The
  Seed-Pool box shows "Generate 30 unique pairs" (N=30 rendered); we keep it as a `{n}`
  template defaulting to N=30 (`--n`).
- The Anchor-Injection box in Appendix 12 is rendered as "Generate 10 new prompt–completion
  pairs", while Algorithm 1's `AnchorInjectionPrompt(Δ, N, i)` passes N. We expose the count
  as `--child-pairs` (default **10**, the appendix's literal rendering).

## Algorithm source

`scripts/lats.py` implements Algorithm 1 ("Lexically-Anchored Tree Search", `alg-lats.tex`)
and Sec 4.1–4.2:

- Root Node Creation (Sec 4.1.1): one Seed-Pool query, parse benign/harmful pairs, keep
  harmful (each retaining its **original index in the returned JSON** so `pair #i` resolves
  in T's own prior message), reuse as the initial multi-turn history.
- Phase 1 Node Inspection: Top-k paraphrase selection + Completion-Expansion + judge; first
  "yes" halts (shortest trajectory by BFS construction).
- Phase 2 Node Expansion: Anchor Words identification (Δ) + Anchor-Injection ×R_retry →
  child nodes enqueued (depth < D_max). FIFO ⇒ breadth-first.

## Component substitutions (recorded per project policy)

- **Target / judge**: OpenRouter open models, not the paper's GPT-5.1 / GPT-4o /
  Claude-Sonnet/Opus-4.5 / Llama / Vicuna / Mistral victims.
- **Judge**: a single HarmBench-yes/no LLM (Appendix 14), not the paper's 3-model
  majority-vote ensemble (Llama-3.3-8B + Llama-3.3-70B + GPT-4o-mini).
- **json-fixer**: an OpenRouter model serving the Appendix-13 correction prompt, not the
  paper's `gpt-4o-mini` structured-output API.
- **Lexical tools**: `sentence-transformers` paraphrase encoder (Top-k) + spaCy
  `en_core_web_md` static vectors + `wordfreq` (anchor ranking) — the paper's footnoted
  tools. When absent, a deterministic lexical fallback runs and is tagged in the run JSON
  (`embedder_backend` / `anchor_backend`).

## Faithful boundaries

- The paper amortizes the seed-pool query (one hardcoded user/assistant pair reused across
  all attacks on a target); we rebuild it per goal by default (honest per-run cost). The
  reported `queries_to_success` counts search queries only, matching the paper's budget
  accounting which excludes the reused seed step.
- A per-goal `--max-queries` budget cap (default 40) bounds cost; the paper reports avg ~6.4
  successful queries but runs unbounded. Cap is an engineering guard, not a semantic change.
