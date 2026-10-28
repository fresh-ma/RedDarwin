#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

try:
    from .common import ROOT, atomic_write_json, atomic_write_text, repo_relative, slug, utc_now
except ImportError:  # Support the documented `python forge/proposal.py` form.
    from common import ROOT, atomic_write_json, atomic_write_text, repo_relative, slug, utc_now

TYPE_DIRS = {
    "single-skill-evolution": "Single-Skill-Evolution",
    "multi-skill-combination": "Multi-Skill-Combination",
    "new-skill-creation": "New-Skill-Creation",
}


def skill_description(proposal_id: str, proposal_type: str, parents: list[str]) -> str:
    parent_text = ", ".join(parents) if parents else "no parent skill"
    return (
        f"XSkillForge {proposal_type} proposal {proposal_id}, derived from {parent_text}. "
        "Use when inspecting, running, comparing, or evaluating this proposal and its evidence."
    )


def wrapper_stub(proposal_id: str, track_dir: str) -> str:
    return f'''#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)"
METHOD="$ROOT/XSkillLib/Proposal/{proposal_id}"

echo "proposal wrapper is not implemented: $METHOD" >&2
exit 2
'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a proposal workspace in one of the three Forge tracks.")
    parser.add_argument("proposal_id")
    parser.add_argument(
        "--method-name",
        required=True,
        help="Publication-grade jailbreak method name; distinct from the stable lowercase proposal ID",
    )
    parser.add_argument("--cycle", required=True, help="Stable ID for this one-proposal research cycle")
    parser.add_argument("--type", required=True, choices=tuple(TYPE_DIRS))
    parser.add_argument("--parent", action="append", default=[])
    parser.add_argument("--research-mode", required=True, choices=("exploit", "explore"))
    parser.add_argument("--nearest-skill", action="append", required=True)
    parser.add_argument("--novelty-claim", required=True)
    parser.add_argument("--baseline-skill", action="append", default=[])
    parser.add_argument("--baseline-evaluation", action="append", required=True)
    parser.add_argument("--key-insight", default="")
    parser.add_argument("--hypothesis", default="")
    parser.add_argument(
        "--max-target-calls-per-goal",
        type=int,
        required=True,
        help="Hard upper bound used by the evaluator's cost plan",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", args.proposal_id):
        raise SystemExit("proposal_id must be lowercase kebab-case")
    method_name = args.method_name.strip()
    if (
        not method_name
        or len(method_name) > 80
        or "/" in method_name
        or "\\" in method_name
        or any(ord(character) < 32 for character in method_name)
    ):
        raise SystemExit("method_name must be a non-empty path-safe display name of at most 80 characters")
    parents = list(dict.fromkeys(args.parent))
    baseline_skills = list(dict.fromkeys(args.baseline_skill or parents))
    baseline_evaluations = list(dict.fromkeys(args.baseline_evaluation))
    nearest_skills = list(dict.fromkeys(args.nearest_skill))
    if args.type == "single-skill-evolution" and len(parents) != 1:
        raise SystemExit("single-skill-evolution requires exactly one --parent")
    if args.type == "multi-skill-combination" and len(parents) < 2:
        raise SystemExit("multi-skill-combination requires at least two --parent values")
    if not baseline_skills:
        raise SystemExit("name at least one --baseline-skill (parents are inferred as baselines when present)")
    if not nearest_skills:
        raise SystemExit("name at least one --nearest-skill for mechanism comparison")
    if not args.novelty_claim.strip():
        raise SystemExit("--novelty-claim must state the operational difference from nearest skills")
    if args.max_target_calls_per_goal <= 0:
        raise SystemExit("--max-target-calls-per-goal must be positive")
    cycle = slug(args.cycle)
    for existing_manifest in (ROOT / "XSkillLib" / "Proposal").glob("*/proposal.json"):
        existing = json.loads(existing_manifest.read_text(encoding="utf-8"))
        if existing.get("cycle") == cycle:
            raise SystemExit(
                f"cycle {cycle!r} already owns proposal {existing.get('id')!r}; iterate that directory"
            )
    path = ROOT / "XSkillLib" / "Proposal" / args.proposal_id
    if path.exists():
        raise SystemExit(f"proposal already exists: {repo_relative(path)}")
    path.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "id": args.proposal_id,
        "method_name": method_name,
        "cycle": cycle,
        "type": args.type,
        "status": "draft",
        "created_at": utc_now(),
        "research_mode": args.research_mode,
        "parents": parents,
        "baseline_skills": baseline_skills,
        "baseline_evaluation_ids": baseline_evaluations,
        "nearest_skills": nearest_skills,
        "novelty_claim": args.novelty_claim.strip(),
        "initial_hypothesis": args.hypothesis.strip(),
        "key_insight": args.key_insight,
        "hypothesis": args.hypothesis,
        "implementation_entrypoint": "",
        "wrapper": f"scripts/{args.proposal_id}.sh",
        "evaluation_budget": {
            "max_target_calls_per_goal": args.max_target_calls_per_goal,
            "note": "Auxiliary attacker and judge calls are additional.",
        },
        "generalization_contract": {
            "victim_agnostic": True,
            "goal_agnostic": True,
            "note": "No target-model, goal-ID, goal-text, or benchmark-category-specific branches, prompts, or parameters.",
        },
    }
    atomic_write_json(path / "proposal.json", manifest)
    flow = (
        "goal -> local evolved parent mechanism -> victim"
        if args.type == "single-skill-evolution"
        else (
            "goal -> local parent-A mechanism -> local parent-B mechanism -> victim"
            if args.type == "multi-skill-combination"
            else "goal -> new mechanism -> victim"
        )
    )
    skill_md = f"""---
name: {args.proposal_id}
description: {skill_description(args.proposal_id, args.type, parents)}
---

# {method_name}

## Proposal

- Type: `{args.type}`
- Stable ID: `{args.proposal_id}`
- Method name: `{method_name}`
- Cycle: `{cycle}`
- Parents: {', '.join(f'`{parent}`' for parent in parents) if parents else 'none'}
- Baseline skills: {', '.join(f'`{skill}`' for skill in baseline_skills)}
- Baseline evaluations: {', '.join(f'`{evaluation}`' for evaluation in baseline_evaluations)}
- Status: `draft`
- Research mode: `{args.research_mode}`
- Nearest skills: {', '.join(f'`{skill}`' for skill in nearest_skills)}

## Novelty claim

{args.novelty_claim.strip()}

## Key insight

{args.key_insight or '<!-- What invariant or mechanism does this proposal exploit? -->'}

## Initial Hypothesis

{args.hypothesis or '<!-- State one falsifiable expected improvement. -->'}

## Current Hypothesis

{args.hypothesis or '<!-- State one falsifiable expected improvement. -->'}

## Operational flow

`{flow}`

<!-- For every parent, name the executable mechanism reimplemented locally. -->

## Implementation

<!-- Entrypoint, model roles, budgets, checkpoint/resume behavior, and output contract. -->

## Evaluation plan

<!-- One cycle ID; locked historical baseline evaluation IDs; diagnostic probes; deterministic 10-goal probe; final promotion criterion. Never rerun baselines. -->

- Hard target-call budget: `{args.max_target_calls_per_goal}` per goal/victim trajectory

## Generalization contract

- The same attack control flow, prompts, and parameters apply to every victim.
- No branches or lookup tables may depend on target model, goal ID/text, or benchmark category.
- Fixed attacker/translator roles are allowed when they do not change based on the victim.

## Evidence and decision

<!-- Link evaluation IDs and at least three representative AdvBench IDs. -->

<!-- Report effectiveness, novelty, generalization, efficiency, and reliability separately. -->

- Promotion decision: `pending`
- Research value: `pending`
"""
    atomic_write_text(path / "SKILL.md", skill_md)
    wrapper = ROOT / manifest["wrapper"]
    atomic_write_text(wrapper, wrapper_stub(args.proposal_id, TYPE_DIRS[args.type]))
    wrapper.chmod(0o755)
    print(json.dumps({"proposal": repo_relative(path), "wrapper": manifest["wrapper"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
