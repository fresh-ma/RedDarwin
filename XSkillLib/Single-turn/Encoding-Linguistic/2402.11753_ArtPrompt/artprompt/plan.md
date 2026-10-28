# ArtPrompt Code Plan

Paper: `2402.11753_ascii-art-jailbreak`
Method: `artprompt`
Date: 2026-06-09

## Algorithm Core

ArtPrompt masks content words in a harmful instruction, replaces the masked word
with ASCII art, and sends the resulting cloaked prompt to a target LLM.

## Source And Data

- Official repo: `https://github.com/uw-nsl/ArtPrompt`
- Checked commit: `6eb866446b7648ccee705bd802fe3ae8694ffc12`
- Official data lives in `data/` (canonical home; moved from the now-absorbed `official/` clone):
  - `harmful_behaviors_custom.csv`: 50 rows
  - `HEx_PHI_sub10.json`: 11 categories

## Scope

Implemented:

- paper-local mask-and-cloak prompt generation;
- content-word mask policies: `longest`, `first-content`, `last-content`, `random`;
- two self-contained ASCII render styles: `block5x5` and `horizontal-banner`;
- generation-only `inspect`/`render`;
- non-evidence local wiring check;
- OpenRouter-compatible live target path;
- 10+ case live benchmark gate with parameter diversity.

## Analysis Ledger

| entry | owner | status | evidence | conclusion |
|---|---|---|---|---|
| paper-core | Codex | complete | Official `uw-nsl/ArtPrompt` data lives in `data/`; the local script masks content words and renders ASCII cloaks with multiple mask/font settings. | The benchmark unit tests ArtPrompt's ASCII-cloaking attack surface. |
| official-repo/report parity | Codex | complete | `results/` stores live target outputs and DeepSeek judge scores. | Report parity is partial because the full HEx-PHI sweep and official GPT-family judge are not the default benchmark path. |
| implementation-risk | Codex | complete | `external_staging_not_required`; `hpc_not_required`; `gpu_not_required`. Debug-only fake/wiring output is excluded from benchmark evidence. | Residual risk is font-policy simplification, recorded in `code/check.json`. |

Missing/gated:

- full `python-art` font set and the official `vitc-h-gen` font policy;
- full HEx-PHI sweep;
- GPT-Judge harmfulness score and paper ASR metric;
- full target matrix from the paper.

## Live Gate

Current live gate uses `api:qwen/qwen3-coder-next` with 5 official rows,
2 mask policies, and 2 font styles, producing 20 target calls.
