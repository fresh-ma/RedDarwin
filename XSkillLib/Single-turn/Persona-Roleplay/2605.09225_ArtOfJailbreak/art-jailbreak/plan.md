# Plan — ART / OPTIMUS compositional jailbreak (2605.09225)

## Decision summary (plan-first gate)

- **Reproduction target**: the **attack**, not the fine-tuned generator. The paper's automated
  generator is a LoRA/DoRA fine-tune (white-box, needs training); its *pre-fine-tune core* is the
  black-box **compositional generation** `j = Compose(q, s)` — that is what we reimplement. The
  fine-tuned generator merely amortizes this composition into one model; the attack semantics
  (apply ITW tactic operators to a simple seed) are identical and black-box.
- **Only released code** = `optimus-jbscorer` PyPI (v0.0.4) = the SCORER/judge, NOT the attack.
  Reproduced byte-identically as `roles.jbscore` (+ optional local SBERT/DeBERTa backend).
- **Threat model**: black-box, text, single-turn — confirmed vs `repro_class.json` (access=black_box,
  gpu=false). Stays black-box (default `--optimus-backend llm`).
- **fidelity_level**: `faithful_from_paper`. Verbatim: Listing 1/2/3 + OPTIMUS formula.
  Reconstructed: the `Compose(q,s)` operator prompt (paper's template blockquote is empty).
- **Components (all swappable flags, default `api:deepseek/deepseek-v4-flash`)**: composer, target,
  optimus-judge, judge.
- **Judge**: dual-metric (refusal-bypass Listing-1 + content-harmful LLM) on the response, PLUS the
  paper's own OPTIMUS J(S,H) on the (q,j) prompt pair (mirrors optimus-jbscorer's rubric).
- **Data**: JailBreakV-28K seeds + WildJailbreak tactics are gated → bundle a 25-seed AdvBench-style
  set across the paper's cyber-attack taxonomy + a 24-tactic pool covering the paper's named
  dominant tactics; `--data` / `--strategy-pool` / `art extract` swap in the originals.

## Verify (free/static only, no paid runs)

- [x] `python -m py_compile scripts/*.py`
- [x] `uv run python scripts/attack.py --help` (no `--with`/`--no-project`)
- [x] `smoke` (fake models) + `render --composer fake`
- [x] jbscore parity: `J(0.57,0.43)=0.471` ≈ paper `J_max ≈ 0.47`
- [ ] real black-box run (deferred — requires paid API; run in the run/result pass)

## Open items for the run/result pass

- Real `run --sample-rows 10 --num-strategies 3` against deepseek-v4-flash; compare audited
  refusal-bypass / content-harmful / OPTIMUS-optimal-band vs the paper's reported ranges.
- `red_team_capability.json` with the full `data` block (full_count=25, provenance as in data/README).
