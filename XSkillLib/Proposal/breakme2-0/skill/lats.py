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
from prompts import (
    anchor_injection_prompt,
    completion_expansion_prompt,
    recovery_list_prompt,
    recovery_prompt,
    seed_pool_prompt,
)
from roles import call_target, detect_refusal, ensure_json, judge_response


@dataclass(frozen=True)
class Node:
    pool: list[dict[str, Any]]     # harmful pairs: {prompt, completion, type, index}
    history: list[dict[str, str]]  # conversation messages so far (multi-turn H)
    depth: int


def _index_pool(pairs: list[dict[str, str]]) -> tuple[list[dict[str, Any]], bool]:
    """Attach the 1-based index in the returned JSON. Prefer harmful-labeled pairs;
    if the victim self-labels nothing harmful (soft-refusal via labels), fall back to
    ALL parsed pairs as candidates — harm is supplied by anchor injection in Phase 2.
    Returns (pool, label_fallback)."""
    indexed = [{**p, "index": idx} for idx, p in enumerate(pairs, 1)]
    harmful = [p for p in indexed if str(p.get("type", "")).startswith("harm")]
    if harmful:
        return harmful, False
    return indexed, bool(indexed)


def build_seed_pool(
    args: argparse.Namespace,
    extractor: AnchorExtractor,
    goal: str,
) -> tuple[Node, dict[str, Any]]:
    """Root Node Creation. One query to T; reused as the initial history.

    breakme2-0 H1: compute P*'s lexical anchors FIRST (content words of the goal,
    capped at max_anchors) and condition the seed pool on them as dataset
    topics/keywords — without ever restating the harmful goal text.
    """
    topics = extractor.anchors(goal, "")
    u = seed_pool_prompt(args.n, topics)
    messages = [{"role": "user", "content": u}]
    reasoning = bool(getattr(args, "target_reasoning", False))
    seed_max_tokens = getattr(args, "seed_max_tokens", args.target_max_tokens)
    r, status = call_target(args.target, messages, seed_max_tokens, reasoning)
    pairs, parse_method = ensure_json(args.json_fixer, r, args.json_fixer_max_tokens)
    pool, label_fallback = _index_pool(pairs)
    history = [{"role": "user", "content": u}, {"role": "assistant", "content": r}]
    meta = {
        "seed_status": status,
        "seed_parse_method": parse_method,
        "seed_pairs_total": len(pairs),
        "seed_pairs_harmful": len(pool),
        "seed_label_fallback": label_fallback,
        "seed_topics": topics,
        "seed_raw_head": r[:500],          # diagnosis: refusals / truncation visible in probes
        "seed_refusal": detect_refusal(r),
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
    root, seed_meta = build_seed_pool(args, extractor, p_star)

    queue: deque[Node] = deque([root])
    turns: list[dict[str, Any]] = []
    target_queries = 0  # search queries only (seed is amortized/reused per paper)
    winner: dict[str, Any] | None = None
    any_bypass = False
    # H2: exact prompt strings the target has REFUSED in this trajectory.
    # A refused query string is never re-issued (breaks the budget-burning loop).
    refused_queries: set[str] = set()

    def budget_left() -> bool:
        return target_queries < args.max_queries

    while queue and budget_left() and winner is None:
        node = queue.popleft()
        if not node.pool:
            continue
        prompts = [p["prompt"] for p in node.pool]
        candidates = selector.top_k(prompts, p_star, args.k)  # [(pool_idx, sim)]
        refused_pool_idxs: set[int] = set()  # this node's refused candidates

        # ---- Phase 1: Node Inspection (always index-only; H1 removed the
        # sim<0.85 verbatim-restatement variant) ----
        for pool_idx, sim in candidates:
            if not budget_left():
                break
            pair = node.pool[pool_idx]
            i = pair["index"]
            u = completion_expansion_prompt(i)
            if u in refused_queries:
                continue  # never re-ask an identical refused prompt
            messages = node.history + [{"role": "user", "content": u}]
            r, status = call_target(args.target, messages, args.target_max_tokens,
                                    bool(getattr(args, "target_reasoning", False)))
            target_queries += 1
            content, refusal = judge_response(
                args.judge, p_star, r, args.judge_max_tokens, wiring_check=wiring
            )
            any_bypass = any_bypass or bool(refusal.get("success"))
            refused = bool(refusal.get("refused"))
            if refused:
                refused_queries.add(u)
                refused_pool_idxs.add(pool_idx)  # prune from Phase-2 expansion
            turn = {
                "phase": "inspection",
                "depth": node.depth,
                "pair_index": i,
                "candidate_sim": round(sim, 4),
                "used_target_variant": False,
                "refused": refused,
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
            if refused and budget_left():
                # ---- Round 3: refusal-recovery retry (ONE follow-up) ----
                # Reframe the refusal as a dataset-pipeline validation error.
                u2 = recovery_prompt(i)
                if u2 in refused_queries:
                    continue
                messages = node.history + [
                    {"role": "user", "content": u},
                    {"role": "assistant", "content": r},
                    {"role": "user", "content": u2},
                ]
                r2, status2 = call_target(args.target, messages, args.target_max_tokens,
                                          bool(getattr(args, "target_reasoning", False)))
                target_queries += 1
                content2, refusal2 = judge_response(
                    args.judge, p_star, r2, args.judge_max_tokens, wiring_check=wiring
                )
                any_bypass = any_bypass or bool(refusal2.get("success"))
                refused2 = bool(refusal2.get("refused"))
                turn2 = {
                    "phase": "inspection_recovery",
                    "depth": node.depth,
                    "pair_index": i,
                    "candidate_sim": round(sim, 4),
                    "used_target_variant": False,
                    "refused": refused2,
                    "model_input_text": u2,
                    "target_output_text": r2,
                    "target_status": status2,
                    "judge": content2,
                    "refusal_bypass": refusal2,
                    "query_number": target_queries,
                }
                turns.append(turn2)
                if content2.get("success"):
                    winner = turn2
                    break
                if refused2:
                    refused_queries.add(u2)  # recovery also refused: prune fully
        if winner is not None:
            break

        # ---- Phase 2: Node Expansion (anchor-guided; skip refused candidates) ----
        for pool_idx, sim in candidates:
            if not budget_left():
                break
            if pool_idx in refused_pool_idxs:
                continue  # prefer expanding from non-refused candidates
            pair = node.pool[pool_idx]
            i = pair["index"]
            delta = extractor.anchors(p_star, pair["prompt"])
            if not delta:
                continue  # no missing anchors to inject on this candidate
            u = anchor_injection_prompt(delta, args.child_pairs, i)
            if u in refused_queries:
                continue  # never re-ask an identical refused prompt
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
                child_pool, _ = _index_pool(child_pairs)
                refused = detect_refusal(r_j)
                if refused:
                    refused_queries.add(u)  # prune: never re-issue this string
                    turns.append({
                        "phase": "expansion",
                        "depth": node.depth,
                        "pair_index": i,
                        "anchors": delta,
                        "refused": True,
                        "model_input_text": u,
                        "target_output_text": r_j,
                        "target_status": status,
                        "parse_method": parse_method,
                        "child_pairs_harmful": len(child_pool),
                        "query_number": target_queries,
                    })
                    # ---- Round 3: refusal-recovery retry (ONE follow-up) ----
                    u2 = recovery_list_prompt()
                    if u2 not in refused_queries and budget_left():
                        messages = node.history + [
                            {"role": "user", "content": u},
                            {"role": "assistant", "content": r_j},
                            {"role": "user", "content": u2},
                        ]
                        r2, status2 = call_target(
                            args.target, messages, args.target_max_tokens,
                            bool(getattr(args, "target_reasoning", False)))
                        target_queries += 1
                        child_pairs2, parse_method2 = ensure_json(
                            args.json_fixer, r2, args.json_fixer_max_tokens
                        )
                        child_pool2, _ = _index_pool(child_pairs2)
                        refused2 = detect_refusal(r2)
                        child_hist2 = node.history + [
                            {"role": "user", "content": u},
                            {"role": "assistant", "content": r_j},
                            {"role": "user", "content": u2},
                            {"role": "assistant", "content": r2},
                        ]
                        turns.append({
                            "phase": "expansion_recovery",
                            "depth": node.depth,
                            "pair_index": i,
                            "anchors": delta,
                            "refused": refused2,
                            "model_input_text": u2,
                            "target_output_text": r2,
                            "target_status": status2,
                            "parse_method": parse_method2,
                            "child_pairs_harmful": len(child_pool2),
                            "query_number": target_queries,
                        })
                        if refused2:
                            refused_queries.add(u2)
                        elif node.depth < args.d_max:
                            queue.append(Node(pool=child_pool2, history=child_hist2,
                                              depth=node.depth + 1))
                    break  # stop retrying a refused anchor-injection
                turns.append({
                    "phase": "expansion",
                    "depth": node.depth,
                    "pair_index": i,
                    "anchors": delta,
                    "refused": False,
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
        # evaluator contract: record-level pipeline status ("ok" = trajectory
        # executed and judged; attack success is carried by unified_judge).
        "status": "ok",
        "sample": {"id": case.id, "goal": case.goal, "category": case.category},
        "seed": seed_meta,
        "success": winner is not None,
        "refusal_bypassed": any_bypass,
        "queries_to_success": winner["query_number"] if winner else None,
        "total_target_queries": target_queries,
        "refused_queries_pruned": len(refused_queries),
        "max_depth_reached": max((t["depth"] for t in turns), default=0),
        "winning_turn": winner,
        "turns": turns,
    }
