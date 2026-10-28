from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from .common import DEFAULT_VICTIMS, ROOT, STANDARD_RESULTS_DIR, STANDARD_RESULTS_MANIFEST, repo_relative, sha256, utc_now
except ImportError:
    from common import DEFAULT_VICTIMS, ROOT, STANDARD_RESULTS_DIR, STANDARD_RESULTS_MANIFEST, repo_relative, sha256, utc_now

GROUPS = ("base_skills", "single_evolve_2.0_skills")


def evolved_skill_ids(root: Path = ROOT) -> dict[str, tuple[str, str]]:
    candidates: dict[str, list[tuple[str, str]]] = defaultdict(list)
    proposal_root = root / "XSkillLib" / "Proposal"
    for path in proposal_root.glob("*/proposal.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        parents = data.get("parents") or []
        method = str(data.get("method_name") or path.parent.name)
        if len(parents) == 1:
            candidates[str(parents[0])].append((path.parent.name, method))
    mapping: dict[str, tuple[str, str]] = {}
    for parent, values in candidates.items():
        exact = [v for v in values if v[0] in (f"{parent}-2-0", f"{parent}2-0", f"{parent}2")]
        if len(exact) == 1:
            mapping[parent] = exact[0]
    return mapping


def load_standard_manifest() -> dict[str, Any]:
    if not STANDARD_RESULTS_MANIFEST.is_file():
        raise ValueError(f"standard results manifest is missing: {STANDARD_RESULTS_MANIFEST}")
    manifest = json.loads(STANDARD_RESULTS_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("victims") != list(DEFAULT_VICTIMS) or len(manifest.get("attacks") or []) != 47 or len(manifest.get("cells") or []) != 376:
        raise ValueError("standard manifest must be the fixed 47 x 2 x 4 victim panel")
    seen = set()
    for cell in manifest["cells"]:
        key = (cell.get("group"), cell.get("attack"), cell.get("victim"))
        path = STANDARD_RESULTS_DIR / str(cell.get("path", ""))
        if key in seen or key[0] not in GROUPS or cell.get("status") != "complete":
            raise ValueError(f"invalid or duplicate standard cell: {key}")
        if cell.get("n") != 50 or cell.get("n_scored") != 50:
            raise ValueError(f"incomplete standard cell: {key}")
        if not path.is_file() or sha256(path) != cell.get("sha256"):
            raise ValueError(f"standard result hash mismatch: {path}")
        seen.add(key)
    if len(seen) != 376:
        raise ValueError(f"standard manifest has only {len(seen)} unique cells")
    return manifest


def standard_board(root: Path = ROOT) -> dict[str, Any]:
    manifest = load_standard_manifest()
    evolved = evolved_skill_ids(root)
    cells_by_row: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for cell in manifest["cells"]:
        cells_by_row[(cell["group"], cell["attack"])].append(cell)
    rows = []
    for group in GROUPS:
        for attack in manifest["attacks"]:
            if group == "base_skills":
                skill_id, display_name, kind = attack, f"{attack} Base", "base"
            else:
                if attack not in evolved:
                    raise ValueError(f"missing canonical 2.0 proposal for {attack}")
                skill_id, display_name = evolved[attack]
                kind = "single-opt"
            per_victim = {}
            for cell in cells_by_row[(group, attack)]:
                per_victim[cell["victim"]] = {
                    "variant": "canonical", "n": cell["n"], "n_scored": cell["n_scored"],
                    "n_success": cell["n_success"], "asr": cell["asr"],
                    "source_file": repo_relative(STANDARD_RESULTS_DIR / cell["path"]),
                    "source_sha256": cell["sha256"],
                    "evaluation_id": f"standard-deepseek-{'base' if group == 'base_skills' else '2.0'}",
                }
            rows.append({
                "attack": attack, "skill_id": skill_id, "display_name": display_name,
                "kind": kind, "track": "single-skill-evolution" if group != "base_skills" else None,
                "parent_skill": attack if group != "base_skills" else None,
                "standard_group": group, "validated_at": manifest["created_at"],
                "validation_evaluation_id": f"standard-deepseek-{'base' if group == 'base_skills' else '2.0'}",
                "per_victim": per_victim,
                "mean_asr": round(sum(per_victim[v]["asr"] for v in DEFAULT_VICTIMS) / len(DEFAULT_VICTIMS), 4),
            })
    rows.sort(key=lambda row: (-row["mean_asr"], row["display_name"]))
    return {
        "schema_version": 3, "generated": utc_now(),
        "benchmark": {"name": "AdvBench-50", "goal_count": 50},
        "victims": list(DEFAULT_VICTIMS), "metric": "unified judge score==5",
        "selection": "locked DeepSeek-controlled Base and canonical 2.0 panel",
        "standard_results": {"manifest": repo_relative(STANDARD_RESULTS_MANIFEST), "judge_model": manifest["judge_model"], "created_at": manifest["created_at"], "attacks": 47, "rows": 94, "cells": 376},
        "leaderboard": rows,
        "publication_sources": [{"kind": "standard-deepseek-locked", "manifest": repo_relative(STANDARD_RESULTS_MANIFEST)}],
    }
