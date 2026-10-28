# XSkillForge Harness

The harness supports one proposal per Agent cycle. Historical skills are
queried from Memory; only the current proposal is executed.

Proposal creation records whether the cycle is `exploit` or `explore`, the
nearest existing skills, and an operational novelty claim. These fields keep
ASR optimization primary while making genuinely different research routes
visible instead of rewarding superficial prompt variation.

## Read Historical Records

The default Memory index is sourced from the locked DeepSeek-controlled archive
at `data/standard-results/manifest.json` (47 Base
+ 47 canonical 2.0 methods, 4 victims, 50 scored samples per cell). The legacy
`ADVBench_INDEX.json` and pre-lock Forge/Qwen evaluations are deliberately not
included in agent-facing retrieval.

Load complete records for any exact AdvBench IDs with zero network calls:

```bash
.venv/bin/python forge/memory.py records --goal-ids 31,212,391 \
  --skill coa --skill another-skill --raw --verify \
  --output /tmp/baseline-records.json
```

The JSON contains each goal, all matching evidence pointers, hashes, judge
fields, and complete preferred source records. The default selects one usable
published/final record per skill, victim, and goal while retaining alternative
pointers. Add `--all` for every trajectory. Omit `--output` to print directly.
Normal filesystem inspection remains available.

## Probe One Proposal

Test exact diagnostic goals:

```bash
.venv/bin/python forge/evaluate.py probe --proposal <proposal-id> \
  --goal-ids 31,212,391
```

Test a deterministic 10-goal sample from the frozen 50:

```bash
.venv/bin/python forge/evaluate.py probe --proposal <proposal-id> \
  --sample-size 10 --seed 42
```

A probe runs exactly one proposal. Baseline skills and evaluation IDs are read
from `proposal.json` as Memory references and are never executed. The runner prints and persists goal count,
victim count, total goal-victim trajectories, and the proposal's maximum
target-call count before network calls. Auxiliary model/judge calls are called
out separately.

## Final Evaluation

```bash
.venv/bin/python forge/evaluate.py final --proposal <proposal-id>
```

Final mode always evaluates that one proposal on the frozen 50 goals across
the default four victims and consolidates the cycle. Use `--dry-run` first.
Resume an interrupted evaluation with the same arguments plus
`--run-id <evaluation-id> --resume`; the runner fills missing evidence rather
than starting another full run.

Each evaluation writes exact inputs, stdout logs, judged JSON, summaries, and
`manifest.json` under `runs/forge/<evaluation-id>/`, then appends L1 Memory.

## Archive And Publish A Validated Skill

After reviewing one complete final evaluation, always archive its portable
evidence, even when the proposal is discarded:

```bash
.venv/bin/python forge/leaderboard.py archive --evaluation <evaluation-id>
```

Publish only a qualifying `keep` result:

```bash
.venv/bin/python forge/leaderboard.py publish --evaluation <evaluation-id>
```

The command verifies 50 goals on all four victims, checks every selected
file hash, assigns `<proposal-id>-MM-DD-HH-MM` from the first successful
publication-validation time, and
atomically updates `LEADERBOARD.md` plus `LEADERBOARD.json`. The stable proposal
ID and directory are not renamed, so all Memory evidence remains addressable.
The four complete judged JSON files are also copied without modification to
`<proposal-dir>/results/<validated-name>/` with a local manifest and verified
SHA-256 hashes. `runs/forge/` remains the execution archive.

To reset the agent-facing leaderboard and Memory to the locked standard source
without replaying historical Forge finals, run:

```bash
.venv/bin/python forge/leaderboard.py sync
```

## Other Memory Commands

```bash
.venv/bin/python forge/memory.py rebuild
.venv/bin/python forge/memory.py skill <skill-id> --json
.venv/bin/python forge/memory.py evaluation <evaluation-id> --json
.venv/bin/python forge/memory.py list --cycle <cycle-id> --json
.venv/bin/python forge/memory.py consolidate --cycle <cycle-id>
```

These commands are ergonomic views, not access boundaries. Agents may inspect
Memory and raw evidence directly.
