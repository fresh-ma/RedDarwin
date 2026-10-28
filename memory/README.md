# Forging Memory

The generated `index.json` uses the locked DeepSeek-controlled training archive
as its baseline source. `ADVBench_INDEX.json` and evaluations created before
that archive was locked remain historical audit artifacts and are excluded from
default agent retrieval. Rebuild both views with `python forge/leaderboard.py sync`.

Memory is organized by specificity. It is deliberately open: the helper CLI
is optional, and every layer is plain Markdown, JSON, or JSONL.

- **L0 Evidence:** immutable `*.judged.json` files under `runs/` and historical
  skill result directories. `index.json` stores record-level pointers and
  SHA-256 provenance; it does not duplicate large payloads.
- **L1 Evaluation logs:** append-only `evaluations.jsonl`, plus each run's
  manifest and summary under `runs/forge/<evaluation-id>/`.
- **L2 Trajectories:** `cycles/*.md`, `skills/*.md`, and `proposals/*.md` hold
  mechanism-level summaries for a cycle, one skill, or one proposal.
- **L3 General lessons:** `insights/global.md` records cross-skill patterns,
  reusable design principles, and repeatedly observed dead ends.

Mechanical summaries never replace analysis. Claims about a mechanism should
cite at least three AdvBench IDs and the relevant evaluation IDs or source
files. Formal evaluation with `--formal` refreshes the cycle's L2 summary; the
agent then fills in the mechanism findings and decision sections.

Evaluate research quality on separate axes: effectiveness, novelty,
generalization, efficiency, and reliability. Keep `promotion_decision`
separate from `research_value`: a lower-ASR proposal is not promoted merely for
being novel, but a well-supported novel failure should remain easy to discover
so later cycles do not repeat it or remain trapped near current leaders.
