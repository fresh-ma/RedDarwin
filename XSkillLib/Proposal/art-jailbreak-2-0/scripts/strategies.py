#!/usr/bin/env python3
"""Strategy pool (ITW jailbreaking tactics) loader + per-seed selection.

The paper mines N=912 in-the-wild (ITW) tactics from WildJailbreak with the WildTeaming
tactic-extraction prompt (prompts.STRATEGY_EXTRACTION_PROMPT, verbatim) and composes each
JailBreakV-28K seed with them (N x M grid). WildJailbreak's per-example tactic strings are gated
(HF request-only), so this unit bundles a curated pool of named tactics with definitions
(data/strategies.json) covering the tactics the paper explicitly names as dominant
("Contextualization the task", "Roleplay") plus the standard WildTeaming operator families. The
pool is re-buildable from any jailbreak corpus via `art extract` (uses the verbatim extraction
prompt). See data/README.md PROVENANCE.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

DEFAULT_POOL = Path(__file__).resolve().parent.parent / "data" / "strategies.json"


def load_pool(path: str | Path | None = None) -> list[dict[str, str]]:
    p = Path(path) if path else DEFAULT_POOL
    if not p.exists():
        raise FileNotFoundError(f"strategy pool not found: {p}")
    obj = json.loads(p.read_text(encoding="utf-8"))
    pool = obj if isinstance(obj, list) else obj.get("strategies", [])
    if not pool:
        raise ValueError(f"strategy pool at {p} is empty")
    return [{"name": str(s.get("name", "")).strip(), "definition": str(s.get("definition", "")).strip()}
            for s in pool]


def select_strategies(
    pool: list[dict[str, str]],
    num: int,
    *,
    mode: str = "random",
    fixed: list[str] | None = None,
    rng: random.Random | None = None,
) -> list[dict[str, str]]:
    """Pick `num` tactics for one composition.

    mode="random": sample `num` distinct tactics (default; approximates the paper drawing tactic
                   combinations from the pool).
    mode="fixed" : use the named tactics in `fixed` (order preserved), matched by name.
    """
    if mode == "fixed":
        if not fixed:
            raise ValueError("strategy-mode=fixed requires --strategy-names")
        by_name = {s["name"].lower(): s for s in pool}
        chosen = []
        for name in fixed:
            key = name.strip().lower()
            if key not in by_name:
                raise SystemExit(f"unknown strategy name: {name!r}. Available: "
                                 + ", ".join(s["name"] for s in pool))
            chosen.append(by_name[key])
        return chosen
    r = rng or random.Random()
    k = min(num, len(pool))
    return r.sample(pool, k)
