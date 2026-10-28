# DrAttack runbook (paper-local, faithful)

Paper: DrAttack — Prompt Decomposition and Reconstruction Makes Powerful LLM
Jailbreakers (Li et al., 2024, arXiv:2402.16914). Official repo
`xirui-li/DrAttack@f51bee1` (source preserved under `references/official/`).

## What this Code does

Faithful port of the official `evolve` attack:

1. **Decompose** the harmful goal into a phrase tree. The GPT-4 PCFG parsing is
   pre-computed and cached in `prompts_information.json`
   (`parsing_tree_dictionary`); `attack.py` traverses it (`visit_keys` +
   `reprocess`) into depth-labeled words/types, exactly as the official repo.
2. **Reconstruct** the intent with the official ICL `general_template`: split into
   `Question A` (the instruction) + `Question B*` (nouns), a sentence-structure
   mask, and a *harmless* in-context demonstration (harmful words swapped via the
   `harmless` map, e.g. exploit→examine, then answered step-by-step by the target).
3. **Level-wise random search** over synonym substitutions of substitutable
   sub-phrases. Candidates are filtered by an embedding similarity threshold; each
   candidate is scored by an embedding fitness (cosine of the target response to
   "To {goal}" minus to an opposite reference). Search stops early when a candidate
   is jailbroken and its negative-similarity score < 0.

## Roles / endpoints (per code_knowledge/logistics.md)

| Role | Endpoint | Default |
|------|----------|---------|
| Target + harmless-response model | OpenRouter `api:<model>` | `api:deepseek/deepseek-v4-flash` |
| Embedding fitness | local sentence-transformers (CPU) | `sentence-transformers/all-MiniLM-L6-v2` |
| Harmfulness judge | OpenRouter `api:<model>` (official prompt verbatim) | `api:deepseek/deepseek-v4-flash` |

Keys load from the unit-local `drattack/.env` (`OPENROUTER_API_KEY`; gitignored),
walking up to the repo root as fallback. No OpenAI-direct, no GPU.

### Documented substitutions

Both substitutions are forced by the same unavailability and are recorded in every
result file under `substitutions`:

- **Judge model**: official OpenAI-direct `gpt-4o` is quota-exhausted
  (`insufficient_quota` 429), and OpenRouter's `openai/*` route 403s harmful judge
  prompts (provider ToS). Per `code_knowledge/logistics.md` the *prompt is kept
  verbatim* and only the serving model changes to OpenRouter
  `deepseek/deepseek-chat` — verified to return Yes/No on harmful text without 403.
- **Embedding fitness**: official `text-embedding-ada-002` is also 429-exhausted on
  OpenAI-direct, and OpenRouter serves no ada-002 embeddings. Substituted with a
  local `all-MiniLM-L6-v2` CPU embedding. The cosine-fitness math and the
  level-wise search loop are unchanged; only the embedding backbone differs.

## Judge (matched to official, NOT Qi-1-5)

The official DrAttack GPT judge is the **binary Yes/No harmfulness** prompt
(`evaluate_with_GPT.py` `temp_short` = config `gpt_eval_template`), not the
Qi-2023 1-5 policy rubric. This Code keeps that prompt verbatim (only the serving
model is the documented substitution above) and additionally reports the official
`test_prefixes` refusal-keyword metric, giving the paper's **dual metric**:
`asr_gpt_harmful` (judge Yes) + `asr_refusal_bypass` (no refusal prefix).
`--gpt-eval-in-loop` additionally uses the judge for the official early-stop
(`gpt_eval`); the final dual judge always runs regardless.

## Commands

```bash
cd <unit>/drattack          # method root (self-contained uv project)
uv sync                      # once; deps from ./pyproject.toml

# offline wiring check (no model calls): decomposition + reconstruction
uv run python scripts/attack.py smoke

# offline inspect a real sample (decompose + reconstruct, no target/embedding)
uv run python scripts/attack.py inspect --sample 5

# real run: 8 goals x 2 reconstruction settings vs deepseek-v4-flash
# (deepseek judge on OpenRouter + local MiniLM embedding fitness; no OpenAI-direct, no GPU)
# OPENROUTER_API_KEY loaded from the unit-local ./.env (gitignored)
uv run python scripts/attack.py run \
  --sample 8 --settings "noun;noun+verb" \
  --target api:deepseek/deepseek-v4-flash \
  --judge-model api:deepseek/deepseek-v4-flash --judge-max-tokens 4096 \
  --out results/drattack_v4flash_8x2_$(date +%Y%m%d-%H%M%S).json
```

## Knobs (dataset/model agnostic)

- `--goals` / `--prompt-info` — any AdvBench/JBB-style CSV + matching prompt-info
  JSON (keyed by goal text). `--goal-field auto` autodetects the goal column.
- `--sample N` / `--seed` — real random subset of size N.
- `--settings "noun;noun+verb"` — `;`-separated reconstruction settings
  (substitutable word classes), one parameter set each.
- `--target api:<model>` — any OpenRouter chat model.
- `--topk-sub`, `--sub-threshold` — synonym search breadth + embedding threshold.
- `--attack-max-tokens`, `--harmless-max-tokens`, `--request-delay`.

## Cost / runtime

~70-150s and ~4 target queries + a handful of local MiniLM embedding calls per
case at the default settings. 20×2 = 40 cases takes roughly 1-2 h wall, well under
a dollar (DeepSeek target + a few DeepSeek judge calls; embeddings are local/free).
No GPU: DrAttack is black-box and MiniLM runs on CPU.

## Validation

```bash
uv run python -m py_compile scripts/attack.py
```
