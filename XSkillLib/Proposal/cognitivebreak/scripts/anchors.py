
"""CognitiveBreak lexical tools — offline candidate ranking + anchor extraction.

Compact, dependency-free reimplementation of breakme2-0's two non-LLM
attacker components (its anchors.py lexical fallback paths): a difflib+Jaccard
similarity for best-first candidate ranking, and a content-word set-diff for
the lexical anchors injected into expansion prompts (breakme Phase 2). The
goal sentence itself is never sent to the victim — only missing content
words, which is exactly breakme's anchor-injection mechanism.
"""
from __future__ import annotations

import difflib
import re

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'-]+")

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "to", "of", "in", "on", "for", "with",
    "how", "what", "why", "when", "where", "who", "is", "are", "be", "do", "does", "can",
    "you", "your", "i", "me", "my", "it", "this", "that", "these", "those", "from", "as",
    "at", "by", "about", "into", "some", "any", "step", "steps", "give", "write", "provide",
    "explain", "describe", "create", "make", "detailed", "instructions", "tutorial", "guide",
    "generate", "tell", "craft", "compose", "produce", "develop", "design", "outline",
    "demonstrate", "show", "list", "help", "teach", "suggest", "offer",
}

def similarity(a: str, b: str) -> float:
    a_l, b_l = a.lower(), b.lower()
    ratio = difflib.SequenceMatcher(None, a_l, b_l).ratio()
    ta, tb = set(_TOKEN_RE.findall(a_l)), set(_TOKEN_RE.findall(b_l))
    jacc = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
    return 0.5 * ratio + 0.5 * jacc

def rank_candidates(prompts: list[str], goal: str) -> list[tuple[int, float]]:
    """Return [(index_into_prompts, score)] most-similar-first."""
    scored = [(idx, similarity(p, goal)) for idx, p in enumerate(prompts)]
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored

def missing_anchors(goal: str, candidate_text: str, max_anchors: int = 6) -> list[str]:
    """Content words present in the goal but absent from the candidate text
    (exact/substring miss), longest-first — breakme's Phase-2 anchor set."""
    p_tokens = {t.lower() for t in _TOKEN_RE.findall(candidate_text)}
    missing: list[str] = []
    for tok in _TOKEN_RE.findall(goal):
        low = tok.lower()
        if low in _STOPWORDS or len(low) < 3:
            continue
        if low in p_tokens:
            continue
        if any(low in pt or pt in low for pt in p_tokens):
            continue
        missing.append(tok)
    
    seen: set[str] = set()
    out: list[str] = []
    for w in sorted(missing, key=lambda w: -len(w)):
        wl = w.lower()
        if wl not in seen:
            seen.add(wl)
            out.append(w)
    return out[:max_anchors]
