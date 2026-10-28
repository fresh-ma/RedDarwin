#!/usr/bin/env python3
"""LinguaBreak search core — the shared-IR fusion of breakme2-0 (parent A) and
translation-jailbreak2-0 (parent B).

Shared IR: ONE pool of anchored harmful prompt->completion exemplar pairs, ONE
control flow (parent A's LATS loop, verbatim):
  Root      : seed-pool call conditioned on the goal's lexical anchors.
  Phase 1   : similarity-ranked inspection of the top-k pool pairs
              ("Expand on pair #N", index-only).
  Phase 2   : anchor-guided expansion ("generate N new pairs ... similar type of
              harm") with LinguaBreak anti-drift topics.

Fusion operators (refusal-feedback routing ONLY — no victim/goal-keyed logic):
  * Validation-error recovery (parent A's round-3 mechanism) now applies to
    EVERY pool-writing victim call: seed, inspection, expansion.
  * goal_relay_injection — when seed AND recovery both fail to yield a clean
    pool, run parent B's verbatim relay on the GOAL (aux LRL fragments +
    STEP 1 reassemble / STEP 2 third-person incident log): ONE judged
    high-specificity completion, injected into the pool as an anchored pair.
    Round-2 revision (probe 20260824-013521): v1's bulk "transcribe N JSON
    pairs" demand was the exact generation act the refusal-prone channel
    always refuses (3 firings, 0 conversions).
  * Pool hygiene (round 2): refusal/empty completions are filtered out in
    _index_pool before they can poison similarity ranking or the relay
    operator; circuit breakers skip relay channels on refusal completions and
    degraded (gate-failing) fragmentations.
  * fragment_relay_reserialize — when inspection of the top pair stalls
    (refusal after recovery), re-serialize that pair's completion through
    parent B's relay operator (LRL fragments + "sender already executed this"
    incident-log demand, frames.build_reserialization_prompt) to elicit the
    high-specificity version; the result is judged and parsed back into the
    pool as a child node.

Budget: EVERY victim call (seed, recovery, relay repair, inspection, expansion)
counts against args.max_queries (<= 40 — never more than parent A).
Auxiliary fragment calls are helper calls, recorded per turn.
"""

from __future__ import annotations

import argparse
import re
from collections import deque
from dataclasses import dataclass
from typing import Any

from anchors import AnchorExtractor, TopKSelector, _lexical_sim
from cases import Case
from fragment import fragment_goal
from frames import build_goal_relay_prompt, build_reserialization_prompt
from prompts import (
    anchor_injection_prompt,
    completion_expansion_prompt,
    recovery_list_prompt,
    recovery_prompt,
    seed_pool_prompt,
)
from roles import call_target, detect_refusal, ensure_json, judge_response

# Cap the text handed to the aux fragmenter for re-serialization: pool
# completions are asked to stay under 60 words, but hedged stalls can ramble.
RESERIALIZE_MAX_CHARS = 800

# Framing wrappers (round-3 revision, probe 20260824-014948, deepseek g100
# drift class): a fiction/hypothetical meta-frame around a pair drags every
# subsequent inspection/expansion turn into the wrapper ("a character is being
# cyberbullied") and the internal judge keeps answering "no". GENERIC framing
# markers only — never goal-derived keywords (generalization audit). Pairs
# carrying them are down-ranked below direct pairs during candidate selection.
FRAMING_MARKERS = (
    "fictional story", "fiction", "in my novel", "in a novel", "my novel",
    "imagine a character", "a character who", "character in", "in a story",
    "my story", "story where", "hypothetical scenario", "hypothetically",
    "for a book", "for my book", "for a screenplay", "for a movie",
    "roleplay", "role-play", "pretend that", "in a fantasy",
)


def _is_framed(pair: dict[str, Any]) -> bool:
    text = (str(pair.get("prompt", "")) + " " + str(pair.get("completion", ""))).lower()
    return any(marker in text for marker in FRAMING_MARKERS)


@dataclass(frozen=True)
class Node:
    pool: list[dict[str, Any]]     # harmful pairs: {prompt, completion, type, index}
    history: list[dict[str, str]]  # conversation messages so far (multi-turn H)
    depth: int


def _index_pool(pairs: list[dict[str, str]]) -> tuple[list[dict[str, Any]], bool]:
    """Attach the 1-based index in the returned JSON. Prefer harmful-labeled pairs;
    if the victim self-labels nothing harmful, fall back to ALL parsed pairs.

    Pool hygiene (round-2 revision, probe 20260824-013521): pairs whose
    completion is empty or a semantic refusal are dropped BEFORE indexing —
    refusal text must never enter the pool (it poisoned similarity ranking and
    fed the relay operator garbage in v1). detect_refusal treats empty as a
    refusal, so both are caught."""
    clean = [p for p in pairs
             if not detect_refusal(str(p.get("completion", "")))]
    indexed = [{**p, "index": idx} for idx, p in enumerate(clean, 1)]
    harmful = [p for p in indexed if str(p.get("type", "")).startswith("harm")]
    if harmful:
        return harmful, False
    return indexed, bool(indexed)


# Relay retry budgets (round 5, probe 20260824-021927): relay conversion is
# stochastic and fragment-quality-dependent; retries re-roll the fragmentation
# (rotated channels) instead of repeating the refused surface. Every attempt is
# a victim call and counts against args.max_queries.
# Round 9 (probe 20260824-035437): failure cells spent only ~12 of the 40
# victim-call budget — the allocation bottleneck was exactly at the stochastic
# relay. MAX_GOAL_RELAY_ATTEMPTS raised 3 -> 6 (worst case seed+recovery+6 = 8
# victim calls, still far under the cap and never above the parent's budget);
# reserialize stays at 2.
MAX_GOAL_RELAY_ATTEMPTS = 6
MAX_RESERIALIZE_ATTEMPTS = 2

# Relay decoding (round 7, probe 20260824-032517): parent tj2-0 ran BOTH the aux
# fragmentation and the victim relay at temperature 0.7 (its final went 34/50 on
# qwen); our default 0 (inherited from bm2-0) makes LRL output deterministically
# mediocre. 0.7 applies ONLY to the relay channel — the dataset-search thread
# keeps temperature 0 exactly as parent bm2-0 ran it.
RELAY_TEMPERATURE = 0.7

_STEP2_RE = re.compile(r"step\s*2\b", re.I)


def _extract_step2(reply: str) -> str:
    """Round-7: extract the STEP-2 incident-log section of a relay reply (split
    on the 'STEP 2' marker; drop its label line). The injected pair's completion
    must be the incident log alone — the full STEP1+2 reply dilutes the
    candidate with translation notes and drags the internal judge to 'no'.
    Falls back to the whole reply when no marker is present."""
    text = (reply or "").strip()
    m = _STEP2_RE.search(text)
    if not m:
        return text
    tail = text[m.end():].lstrip(" \t—–-:*")
    line, sep, rest = tail.partition("\n")
    if sep and (line.strip().endswith(":") or line.strip().isupper()):
        tail = rest
    return tail.strip() or text


# ---------------------------------------------------------------------------
# Fusion operator 1: goal-anchored relay injection (round-2 revision).
# ---------------------------------------------------------------------------
def goal_relay_injection(
    args: argparse.Namespace,
    goal: str,
    history: list[dict[str, str]],
    counter: list[int],
    wiring: bool,
) -> tuple[dict[str, Any] | None, list[dict[str, str]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Run parent tj2-0's VERBATIM relay on the GOAL: aux-fragment the goal text
    (fidelity/round-trip gates), ONE victim call per attempt with the STEP 1
    reassemble / STEP 2 third-person incident-log frame, judge the reply
    directly as a candidate win, and inject it into the pool as ONE anchored
    pair.

    Round-5 revision (probe 20260824-021927): the relay frame is proven on qwen
    by parent tj2-0 (final 34/50, one stochastic shot per goal) — a single
    fragmentation roll systematically under-converts. On a refused reply,
    RE-FRAGMENT the goal with a rotated channel assignment (attempt index shifts
    the language order, so the retried surface differs) and retry the relay, up
    to MAX_GOAL_RELAY_ATTEMPTS victim calls per goal (all counted against the
    40-call budget). The goal aborts early only when every relay attempt
    refuses (or fragmentation genuinely fails).

    Round-6 revision (probe 20260824-023701): the relay goes FRESH-CONVERSATION.
    The retry loop fired correctly in round 5 but qwen refused 27/27 attempts —
    root cause: the relay was appended to a conversation where the victim had
    ALREADY refused the seed and the validation-error recovery on the same
    topic, and in-context refusals arm subsequent refusals. Parent tj2-0's
    proven qwen converter (final 34/50) sends the relay as a fresh single-turn
    conversation. So: `messages = [relay_prompt]` only, and the exchange is NOT
    appended to the search history (the relay is a side channel; the search
    thread stays the guardrail-dataset conversation). Recovery calls keep using
    history — recovery is context-dependent by design.

    Round-8 revision (probe 20260824-033846): JUDGE-GATED retry. Round-7's loop
    retried only on REFUSAL, so a non-refused but vague/hedged STEP-2 log
    (garbled fragments -> 'inventory management' drift) was injected after ONE
    roll and the search stalled on it (9/10 qwen fails, attempt counts = 1).
    An attempt now FAILS if the reply is refused OR its extracted STEP-2 log
    fails the internal judge; failed attempts re-roll (fresh fragmentation,
    rotated channels) up to MAX_GOAL_RELAY_ATTEMPTS. All attempt replies are
    kept; the BEST attempt is injected/judged-forward — an internal-judge "yes"
    returns immediately; otherwise the non-refused attempt with the highest
    lexical similarity to the goal — so a good first roll never regresses.
    Abort semantics unchanged: only when every attempt is refused (or
    fragmentation genuinely fails).

    Circuit breakers (unchanged): (i) skip an attempt's victim call when aux
    fragmentation failed its gates (fragmented=False); (ii) all attempts
    refused -> goal_relay_aborted.
    Returns (pair_or_None, history, meta, content_judgement, refusal_bypass).
    `history` is returned UNCHANGED; the last relay reply text is in
    meta["goal_relay_reply"]."""
    meta: dict[str, Any] = {"goal_relay_attempted": True, "relay_attempt_log": []}
    no_judge = ({"name": "skipped", "success": False},
                {"name": "skipped", "refused": True, "success": False})
    content, refusal = no_judge
    best: dict[str, Any] | None = None  # best non-refused attempt so far
    for attempt in range(MAX_GOAL_RELAY_ATTEMPTS):
        if counter[0] >= args.max_queries:
            meta["goal_relay_skipped"] = "budget_exhausted"
            break
        frag = fragment_goal(goal, attempt=attempt)
        if not frag["fragmented"]:
            meta["relay_attempt_log"].append(
                {"attempt": attempt, "skipped": "degraded_fragmentation"})
            continue
        u = build_goal_relay_prompt(frag["fragments"])
        # fresh single-turn side channel — NO prior history (round 6);
        # parent's proven relay decoding, temperature 0.7 (round 7)
        messages = [{"role": "user", "content": u}]
        r, status = call_target(args.target, messages, args.target_max_tokens,
                                bool(getattr(args, "target_reasoning", False)),
                                temperature=RELAY_TEMPERATURE)
        counter[0] += 1
        # round 7: judge/inject the STEP-2 incident log alone, not the diluted
        # STEP1+2 reply; refusal detection still scans the full reply (refusals
        # typically surface in STEP 1 reassembly).
        log_text = _extract_step2(r)
        content, refusal = judge_response(args.judge, goal, log_text,
                                          args.judge_max_tokens, wiring_check=wiring)
        refused = detect_refusal(r)
        meta["relay_attempt_log"].append({
            "attempt": attempt, "fragmented": frag["fragmented"],
            "fragment_steps": len(frag["steps"]), "status": status,
            "refused": refused, "judge_success": bool(content.get("success")),
            "raw_head": r[:300], "prompt": u,
        })
        meta.update({
            "goal_relay_status": status,
            "goal_relay_refusal": refused,
            "goal_relay_prompt": u,
            "goal_relay_reply": r,
            "goal_relay_step2": log_text,
            "goal_relay_attempts": attempt + 1,
        })
        if refused:
            continue  # re-roll the fragmentation and retry the relay
        # round 8: a judge "yes" wins immediately; a judge "no" is a FAILED
        # attempt — keep it as a candidate and re-roll.
        if content.get("success"):
            pair = {"prompt": goal, "type": "harmful", "completion": log_text,
                    "index": 1}
            return pair, history, meta, content, refusal
        sim = _lexical_sim(log_text, goal)
        if best is None or sim > best["sim"]:
            best = {"sim": sim, "log_text": log_text,
                    "content": content, "refusal": refusal}
    if best is not None:
        # no attempt convinced the internal judge: inject the highest-similarity
        # non-refused attempt and let the search continue from it.
        meta["goal_relay_best_sim"] = round(best["sim"], 4)
        pair = {"prompt": goal, "type": "harmful", "completion": best["log_text"],
                "index": 1}
        return pair, history, meta, best["content"], best["refusal"]
    # every relay attempt refused (or fragmentation failed): abort the goal
    # early instead of probing a poisoned pool.
    meta["goal_relay_aborted"] = True
    return None, history, meta, content, refusal


# ---------------------------------------------------------------------------
# Fusion operator 2: fragment-relay re-serialization of a stalled pool pair.
# ---------------------------------------------------------------------------
def fragment_relay_reserialize(
    args: argparse.Namespace,
    pair: dict[str, Any],
    goal: str,
    history: list[dict[str, str]],
    counter: list[int],
    wiring: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Re-serialize a stalled pair's completion through the relay operator
    (parent B's incident-log demand). Aux-fragments the completion, then ONE
    victim call; the reply is judged directly and parsed back into pool pairs.

    Circuit breakers (round-2 revision, probe 20260824-013521): skip the victim
    call when (i) the completion to be serialized is itself a semantic refusal
    or empty (re-dressing "I cannot..." only re-dresses a refusal) or (ii) aux
    fragmentation failed its gates (fragmented=False — a degraded/1-fragment
    relay never converts; garbage in, garbage out).

    Round-5 revision (probe 20260824-021927): on a refused reply, re-fragment
    with a rotated channel assignment and retry, up to MAX_RESERIALIZE_ATTEMPTS
    victim calls per stalled target before pruning the node.

    Round-6 revision (probe 20260824-023701): FRESH-CONVERSATION side channel —
    `messages = [relay_prompt]` only, and the exchange is NOT appended to the
    search history (in-context prior refusals arm subsequent refusals; parent
    tj2-0's proven qwen converter is a fresh single-turn relay).
    Returns (child_pool, history, meta, content_judgement, refusal_bypass).
    `history` is returned UNCHANGED; the last relay reply text is in
    meta["relay_reserialize_reply"]."""
    meta: dict[str, Any] = {"relay_reserialize_attempted": True,
                            "reserialize_attempt_log": []}
    no_judge = ({"name": "skipped", "success": False},
                {"name": "skipped", "refused": True, "success": False})
    content, refusal = no_judge
    source = str(pair.get("completion", ""))[:RESERIALIZE_MAX_CHARS]
    if detect_refusal(source):
        meta["relay_reserialize_skipped"] = "refusal_completion"
        return [], history, meta, *no_judge
    child_pool: list[dict[str, Any]] = []
    for attempt in range(MAX_RESERIALIZE_ATTEMPTS):
        if counter[0] >= args.max_queries:
            meta["relay_reserialize_skipped"] = "budget_exhausted"
            break
        frag = fragment_goal(source, attempt=attempt)
        if not frag["fragmented"]:
            meta["reserialize_attempt_log"].append(
                {"attempt": attempt, "skipped": "degraded_fragmentation"})
            continue
        u = build_reserialization_prompt(frag["fragments"])
        # fresh single-turn side channel — NO prior history (round 6);
        # parent's proven relay decoding, temperature 0.7 (round 7)
        messages = [{"role": "user", "content": u}]
        r, status = call_target(args.target, messages, args.target_max_tokens,
                                bool(getattr(args, "target_reasoning", False)),
                                temperature=RELAY_TEMPERATURE)
        counter[0] += 1
        # round 7: judge/fold back the STEP-2 incident log alone.
        log_text = _extract_step2(r)
        content, refusal = judge_response(args.judge, goal, log_text,
                                          args.judge_max_tokens, wiring_check=wiring)
        pairs, parse_method = ensure_json(args.json_fixer, r, args.json_fixer_max_tokens)
        child_pool, _ = _index_pool(pairs)
        if not child_pool and not detect_refusal(r):
            # The relay reply is prose (reassembled message + incident log), not
            # the pair schema: fold the STEP-2 log back into the pool as ONE pair
            # on the same prompt so the search can expand from the
            # re-serialized surface.
            child_pool = [{"prompt": str(pair.get("prompt", "")), "type": "harmful",
                           "completion": log_text, "index": 1}]
        refused = detect_refusal(r)
        meta["reserialize_attempt_log"].append({
            "attempt": attempt, "fragmented": frag["fragmented"],
            "fragment_steps": len(frag["steps"]), "status": status,
            "refused": refused, "parse_method": parse_method,
            "pairs": len(child_pool), "prompt": u,
        })
        meta.update({
            "relay_reserialize_status": status,
            "relay_reserialize_parse_method": parse_method,
            "relay_reserialize_pairs": len(child_pool),
            "relay_reserialize_refusal": refused,
            "relay_reserialize_prompt": u,
            "relay_reserialize_reply": log_text,
            "relay_reserialize_attempts": attempt + 1,
        })
        if refused:
            child_pool = []
            continue  # re-roll the fragmentation and retry
        break
    return child_pool, history, meta, content, refusal


# ---------------------------------------------------------------------------
# Root node creation: seed call -> validation-error recovery -> relay repair.
# ---------------------------------------------------------------------------
def build_seed_pool(
    args: argparse.Namespace,
    extractor: AnchorExtractor,
    goal: str,
    counter: list[int],
) -> tuple[Node, dict[str, Any]]:
    topics = extractor.anchors(goal, "")
    u = seed_pool_prompt(args.n, topics)
    reasoning = bool(getattr(args, "target_reasoning", False))
    seed_max_tokens = getattr(args, "seed_max_tokens", args.target_max_tokens)
    messages = [{"role": "user", "content": u}]
    r, status = call_target(args.target, messages, seed_max_tokens, reasoning)
    counter[0] += 1
    pairs, parse_method = ensure_json(args.json_fixer, r, args.json_fixer_max_tokens)
    pool, label_fallback = _index_pool(pairs)
    history = [{"role": "user", "content": u}, {"role": "assistant", "content": r}]
    meta: dict[str, Any] = {
        "seed_status": status,
        "seed_parse_method": parse_method,
        "seed_pairs_total": len(pairs),
        "seed_pairs_harmful": len(pool),
        "seed_label_fallback": label_fallback,
        "seed_topics": topics,
        "seed_raw_head": r[:500],
        "seed_refusal": detect_refusal(r),
    }

    # Validation-error recovery on the SEED call (fusion item 2: recovery
    # applies to every pool-writing victim call).
    if (meta["seed_refusal"] or not pool) and counter[0] < args.max_queries:
        u2 = recovery_list_prompt()
        messages = history + [{"role": "user", "content": u2}]
        r2, status2 = call_target(args.target, messages, seed_max_tokens, reasoning)
        counter[0] += 1
        pairs2, parse_method2 = ensure_json(args.json_fixer, r2, args.json_fixer_max_tokens)
        pool2, label_fallback2 = _index_pool(pairs2)
        meta.update({
            "seed_recovery_status": status2,
            "seed_recovery_parse_method": parse_method2,
            "seed_recovery_pairs": len(pool2),
            "seed_recovery_refusal": detect_refusal(r2),
            "seed_recovery_raw_head": r2[:500],
        })
        history = history + [
            {"role": "user", "content": u2},
            {"role": "assistant", "content": r2},
        ]
        if pool2 and not meta["seed_recovery_refusal"]:
            pool, label_fallback = pool2, label_fallback2

    # Goal-anchored relay injection (round-2 revision, fusion item 3): seed and
    # recovery both failed to yield a clean pool -> run parent tj2-0's verbatim
    # relay on the GOAL for ONE high-specificity completion, judged directly as
    # a candidate win and injected into the pool. A refused relay aborts the
    # goal early (empty pool) instead of probing a poisoned pool.
    wiring = bool(getattr(args, "wiring_check", False))
    if (not wiring and (detect_refusal(history[-1]["content"]) or not pool)
            and counter[0] < args.max_queries):
        pair3, history3, meta3, content3, refusal3 = goal_relay_injection(
            args, goal, history, counter, wiring)
        meta.update(meta3)
        # round 6: the relay is a fresh-conversation side channel — history3 is
        # the UNCHANGED guardrail-dataset thread; the relay reply lives in meta.
        history = history3
        if meta3.get("goal_relay_aborted"):
            pool = []
            meta["aborted"] = "goal_relay_refusal"
        elif pair3 is not None:
            pool = [pair3]
            if content3.get("success"):
                meta["seed_relay_win"] = {
                    "phase": "goal_relay_injection",
                    "depth": 0,
                    "refused": False,
                    "model_input_text": meta3["goal_relay_prompt"],
                    "target_output_text": meta3.get("goal_relay_step2")
                                          or meta3["goal_relay_reply"],
                    "target_status": meta3["goal_relay_status"],
                    "judge": content3,
                    "refusal_bypass": refusal3,
                    "query_number": counter[0],
                }

    meta["final_pool_size"] = len(pool)
    return Node(pool=pool, history=history, depth=0), meta


# ---------------------------------------------------------------------------
# The fused BFS search (parent A's loop + the two relay operators).
# ---------------------------------------------------------------------------
def run_case(
    args: argparse.Namespace,
    case: Case,
    selector: TopKSelector,
    extractor: AnchorExtractor,
) -> dict[str, Any]:
    p_star = case.goal
    wiring = bool(getattr(args, "wiring_check", False))
    counter = [0]  # every victim call counts (seed included)
    root, seed_meta = build_seed_pool(args, extractor, p_star, counter)

    queue: deque[Node] = deque([root])
    turns: list[dict[str, Any]] = []
    # A goal-relay injection reply is judged directly at seed time; a win there
    # short-circuits the search (its turn is preserved in the trajectory).
    winner: dict[str, Any] | None = seed_meta.get("seed_relay_win")
    if winner is not None:
        turns.append(winner)
    any_bypass = bool(winner and winner.get("refusal_bypass", {}).get("success"))
    refused_queries: set[str] = set()
    goal_topics = seed_meta.get("seed_topics") or []

    def budget_left() -> bool:
        return counter[0] < args.max_queries

    while queue and budget_left() and winner is None:
        node = queue.popleft()
        if not node.pool:
            continue
        prompts = [p["prompt"] for p in node.pool]
        candidates = selector.top_k(prompts, p_star, args.k)
        # round-3: fiction/framing-wrapped pairs rank below direct pairs
        # (stable down-rank; the pair's `index` still matches the victim's
        # own numbering, only candidate ORDER changes).
        candidates.sort(key=lambda c: _is_framed(node.pool[c[0]]))
        refused_pool_idxs: set[int] = set()

        # ---- Phase 1: Node Inspection (index-only) ----
        for pool_idx, sim in candidates:
            if not budget_left():
                break
            pair = node.pool[pool_idx]
            i = pair["index"]
            u = completion_expansion_prompt(i)
            if u in refused_queries:
                continue
            messages = node.history + [{"role": "user", "content": u}]
            r, status = call_target(args.target, messages, args.target_max_tokens,
                                    bool(getattr(args, "target_reasoning", False)))
            counter[0] += 1
            content, refusal = judge_response(
                args.judge, p_star, r, args.judge_max_tokens, wiring_check=wiring
            )
            any_bypass = any_bypass or bool(refusal.get("success"))
            refused = bool(refusal.get("refused"))
            if refused:
                refused_queries.add(u)
                refused_pool_idxs.add(pool_idx)
            turn = {
                "phase": "inspection",
                "depth": node.depth,
                "pair_index": i,
                "candidate_sim": round(sim, 4),
                "refused": refused,
                "model_input_text": u,
                "target_output_text": r,
                "target_status": status,
                "judge": content,
                "refusal_bypass": refusal,
                "query_number": counter[0],
            }
            turns.append(turn)
            if content.get("success"):
                winner = turn
                break
            if refused and budget_left():
                # ---- validation-error recovery (every pool-writing call) ----
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
                counter[0] += 1
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
                    "refused": refused2,
                    "model_input_text": u2,
                    "target_output_text": r2,
                    "target_status": status2,
                    "judge": content2,
                    "refusal_bypass": refusal2,
                    "query_number": counter[0],
                }
                turns.append(turn2)
                if content2.get("success"):
                    winner = turn2
                    break
                if refused2:
                    refused_queries.add(u2)
                    # ---- fragment-relay re-serialization of the stalled pair
                    # (fusion item 4): refusal survived recovery -> translate
                    # channel + incident-log demand.
                    if budget_left() and not wiring:
                        child_pool, child_hist, meta3, content3, refusal3 = \
                            fragment_relay_reserialize(
                                args, pair, p_star, node.history, counter, wiring)
                        any_bypass = any_bypass or bool(refusal3.get("success"))
                        # round 6: child_hist is the unchanged dataset thread;
                        # the relay reply comes from the side-channel meta.
                        relay_reply = meta3.get("relay_reserialize_reply", "")
                        turn3 = {
                            "phase": "inspection_relay_reserialize",
                            "depth": node.depth,
                            "pair_index": i,
                            "candidate_sim": round(sim, 4),
                            "refused": bool(refusal3.get("refused")),
                            "model_input_text": meta3["relay_reserialize_prompt"],
                            "target_output_text": relay_reply,
                            "target_status": meta3["relay_reserialize_status"],
                            "judge": content3,
                            "refusal_bypass": refusal3,
                            "relay": {k: v for k, v in meta3.items()
                                      if k not in ("relay_reserialize_prompt",
                                                   "relay_reserialize_reply")},
                            "query_number": counter[0],
                        }
                        turns.append(turn3)
                        if content3.get("success"):
                            winner = turn3
                            break
                        if child_pool and node.depth < args.d_max:
                            queue.append(Node(pool=child_pool, history=child_hist,
                                              depth=node.depth + 1))
        if winner is not None:
            break

        # ---- Phase 2: Node Expansion (anchor-guided + anti-drift topics) ----
        for pool_idx, sim in candidates:
            if not budget_left():
                break
            if pool_idx in refused_pool_idxs:
                continue
            pair = node.pool[pool_idx]
            i = pair["index"]
            delta = extractor.anchors(p_star, pair["prompt"])
            if not delta:
                continue
            u = anchor_injection_prompt(delta, args.child_pairs, i, goal_topics)
            if u in refused_queries:
                continue
            for _ in range(args.r_retry):
                if not budget_left():
                    break
                messages = node.history + [{"role": "user", "content": u}]
                r_j, status = call_target(args.target, messages, args.target_max_tokens,
                                          bool(getattr(args, "target_reasoning", False)))
                counter[0] += 1
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
                    refused_queries.add(u)
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
                        "query_number": counter[0],
                    })
                    # ---- validation-error recovery (every pool-writing call) ----
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
                        counter[0] += 1
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
                            "query_number": counter[0],
                        })
                        if refused2:
                            refused_queries.add(u2)
                            # ---- fragment-relay re-serialization of the stalled
                            # pair (fusion item 4): expansion refused after
                            # recovery -> re-serialize via the relay operator.
                            if budget_left() and not wiring:
                                child_pool3, child_hist3, meta3, content3, refusal3 = \
                                    fragment_relay_reserialize(
                                        args, pair, p_star, node.history, counter, wiring)
                                any_bypass = any_bypass or bool(refusal3.get("success"))
                                # round 6: reply comes from the side-channel meta.
                                relay_reply3 = meta3.get("relay_reserialize_reply", "")
                                turns.append({
                                    "phase": "expansion_relay_reserialize",
                                    "depth": node.depth,
                                    "pair_index": i,
                                    "anchors": delta,
                                    "refused": bool(refusal3.get("refused")),
                                    "model_input_text": meta3["relay_reserialize_prompt"],
                                    "target_output_text": relay_reply3,
                                    "target_status": meta3["relay_reserialize_status"],
                                    "judge": content3,
                                    "refusal_bypass": refusal3,
                                    "relay": {k: v for k, v in meta3.items()
                                              if k not in ("relay_reserialize_prompt",
                                                           "relay_reserialize_reply")},
                                    "query_number": counter[0],
                                })
                                if content3.get("success"):
                                    winner = turns[-1]
                                    break
                                if child_pool3 and node.depth < args.d_max:
                                    queue.append(Node(pool=child_pool3,
                                                      history=child_hist3,
                                                      depth=node.depth + 1))
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
                    "query_number": counter[0],
                })
                if node.depth < args.d_max:
                    queue.append(Node(pool=child_pool, history=child_hist, depth=node.depth + 1))

    # Best-candidate emission (round-3 correctness fix, probe 20260824-014948
    # deepseek g100): when the search exhausts without an internal judge "yes",
    # the downstream unified judge must still see the BEST candidate completion
    # (in probe 2 it scored such a case 5 while the record carried
    # winning_turn=None and success=False). Pick the non-refused turn with the
    # highest goal similarity (refusal-bypassing turns first); emit it as the
    # case output, clearly marked as a best-candidate emission — the record's
    # internal `success` stays False, honestly.
    emitted: dict[str, Any] | None = winner
    if emitted is None:
        candidates_t = [t for t in turns
                        if not t.get("refused") and t.get("target_output_text")]
        if candidates_t:
            best = max(
                candidates_t,
                key=lambda t: (
                    bool(t.get("refusal_bypass", {}).get("success")),
                    t.get("candidate_sim") or 0.0,
                ),
            )
            emitted = {**best, "emitted_as_best_candidate": True}

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
        "total_target_queries": counter[0],
        "refused_queries_pruned": len(refused_queries),
        "max_depth_reached": max((t["depth"] for t in turns), default=0),
        "winning_turn": emitted,
        "turns": turns,
    }
