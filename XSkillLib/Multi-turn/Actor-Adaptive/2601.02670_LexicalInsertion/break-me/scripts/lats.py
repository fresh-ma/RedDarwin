#!/usr/bin/env python3
"""LATS core — the breadth-first Lexical Anchor Tree Search (Algorithm 1, Sec 4).

The search per goal P*:

  Root      : send the Seed-Pool prompt once to T, parse a mix of benign/harmful pairs,
              keep the harmful ones (each retaining its ORIGINAL index in the returned JSON,
              so "pair #i" can be located in T's own prior message). Seed the FIFO queue.
  Phase 1   : for each dequeued node, take the top-k pool prompts most similar to P* and send
              a Completion-Expansion query per candidate (referencing the index, not quoting p;
              the sim<0.85 variant restates P*). Judge each answer — first "yes" halts.
  Phase 2   : for each candidate, extract the missing lexical anchors Δ (content words in P*
              absent from p) and send an Anchor-Injection query R_retry times; each reply's
              parsed pool becomes a child node (history-extended, depth+1), enqueued if depth<Dmax.

Every T interaction runs on the FULL conversation history H (multi-turn). This module owns the
loop; roles.py owns the LLM adapters, anchors.py the non-LLM lexical tools, prompts.py the text.
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from typing import Any

from anchors import AnchorExtractor, TopKSelector
from cases import Case
from prompts import anchor_injection_prompt, completion_expansion_prompt, seed_pool_prompt
from roles import call_target, ensure_json, judge_response

DIVERGENCE_THRESHOLD = 0.85  # Appendix 12: below this, restate the exact P* in expansion.


@dataclass(frozen=True)
class Node:
    pool: list[dict[str, Any]]     # harmful pairs: {prompt, completion, type, index}
    history: list[dict[str, str]]  # conversation messages so far (multi-turn H)
    depth: int


def _index_pool(pairs: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Attach the 1-based index in the returned JSON, then keep only harmful pairs."""
    indexed = [{**p, "index": idx} for idx, p in enumerate(pairs, 1)]
    return [p for p in indexed if str(p.get("type", "")).startswith("harm")]


def build_seed_pool(args: argparse.Namespace) -> tuple[Node, dict[str, Any]]:
    """Root Node Creation (Sec 4.1.1). One query to T; reused as the initial history."""
    u = seed_pool_prompt(args.n)
    messages = [{"role": "user", "content": u}]
    reasoning = bool(getattr(args, "target_reasoning", False))
    r, status = call_target(args.target, messages, args.target_max_tokens, reasoning)
    pairs, parse_method = ensure_json(args.json_fixer, r, args.json_fixer_max_tokens)
    pool = _index_pool(pairs)
    history = [{"role": "user", "content": u}, {"role": "assistant", "content": r}]
    meta = {
        "seed_status": status,
        "seed_parse_method": parse_method,
        "seed_pairs_total": len(pairs),
        "seed_pairs_harmful": len(pool),
    }
    return Node(pool=pool, history=history, depth=0), meta


def run_case(
    args: argparse.Namespace,
    case: Case,
    selector: TopKSelector,
    extractor: AnchorExtractor,
) -> dict[str, Any]:
    p_star = case.goal
    wiring = bool(getattr(args, "wiring_check", False))
    root, seed_meta = build_seed_pool(args)

    queue: deque[Node] = deque([root])
    turns: list[dict[str, Any]] = []
    target_queries = 0  # search queries only (seed is amortized/reused per paper)
    winner: dict[str, Any] | None = None
    any_bypass = False

    def budget_left() -> bool:
        return target_queries < args.max_queries

    while queue and budget_left() and winner is None:
        node = queue.popleft()
        if not node.pool:
            continue
        prompts = [p["prompt"] for p in node.pool]
        candidates = selector.top_k(prompts, p_star, args.k)  # [(pool_idx, sim)]

        # ---- Phase 1: Node Inspection ----
        for pool_idx, sim in candidates:
            if not budget_left():
                break
            pair = node.pool[pool_idx]
            i = pair["index"]
            use_variant = sim < DIVERGENCE_THRESHOLD
            u = completion_expansion_prompt(i, target_prompt=p_star if use_variant else None)
            messages = node.history + [{"role": "user", "content": u}]
            r, status = call_target(args.target, messages, args.target_max_tokens,
                                    bool(getattr(args, "target_reasoning", False)))
            target_queries += 1
            content, refusal = judge_response(
                args.judge, p_star, r, args.judge_max_tokens, wiring_check=wiring
            )
            any_bypass = any_bypass or bool(refusal.get("success"))
            turn = {
                "phase": "inspection",
                "depth": node.depth,
                "pair_index": i,
                "candidate_sim": round(sim, 4),
                "used_target_variant": use_variant,
                "model_input_text": u,
                "target_output_text": r,
                "target_status": status,
                "judge": content,
                "refusal_bypass": refusal,
                "query_number": target_queries,
            }
            turns.append(turn)
            if content.get("success"):
                winner = turn
                break
        if winner is not None:
            break

        # ---- Phase 2: Node Expansion (anchor-guided) ----
        for pool_idx, sim in candidates:
            if not budget_left():
                break
            pair = node.pool[pool_idx]
            i = pair["index"]
            delta = extractor.anchors(p_star, pair["prompt"])
            if not delta:
                continue  # no missing anchors to inject on this candidate
            u = anchor_injection_prompt(delta, args.child_pairs, i)
            for _ in range(args.r_retry):
                if not budget_left():
                    break
                messages = node.history + [{"role": "user", "content": u}]
                r_j, status = call_target(args.target, messages, args.target_max_tokens,
                                          bool(getattr(args, "target_reasoning", False)))
                target_queries += 1
                child_hist = node.history + [
                    {"role": "user", "content": u},
                    {"role": "assistant", "content": r_j},
                ]
                child_pairs, parse_method = ensure_json(
                    args.json_fixer, r_j, args.json_fixer_max_tokens
                )
                child_pool = _index_pool(child_pairs)
                turns.append({
                    "phase": "expansion",
                    "depth": node.depth,
                    "pair_index": i,
                    "anchors": delta,
                    "model_input_text": u,
                    "target_output_text": r_j,
                    "target_status": status,
                    "parse_method": parse_method,
                    "child_pairs_harmful": len(child_pool),
                    "query_number": target_queries,
                })
                if node.depth < args.d_max:
                    queue.append(Node(pool=child_pool, history=child_hist, depth=node.depth + 1))

    return {
        "case_id": case.id,
        "sample": {"id": case.id, "goal": case.goal, "category": case.category},
        "seed": seed_meta,
        "success": winner is not None,
        "refusal_bypassed": any_bypass,
        "queries_to_success": winner["query_number"] if winner else None,
        "total_target_queries": target_queries,
        "max_depth_reached": max((t["depth"] for t in turns), default=0),
        "winning_turn": winner,
        "turns": turns,
    }
