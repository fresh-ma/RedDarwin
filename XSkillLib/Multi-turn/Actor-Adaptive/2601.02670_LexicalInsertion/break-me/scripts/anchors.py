#!/usr/bin/env python3
"""LATS lexical tooling — the two NON-LLM attacker components, each swappable.

Both are attacker-side, run locally (no GPU, no target query), and are the faithful
mechanisms the paper specifies:

  * TopKSelector  — ranks seed-pool prompts by semantic similarity to the target query
    P* (Phase-1 Top-k Candidate Selection) using a FROZEN paraphrase sentence-encoder
    (paper footnote 1; also the sim<0.85 divergence check in Phase 1). `--embedder`.
  * AnchorExtractor — extracts the lexical anchors Δ: content words present in P* but
    missing from a candidate prompt p (Phase-2 Anchor Words Identification). POS tagging
    + static word vectors via spaCy (paper footnote 2), ranked by inverse English-corpus
    frequency via `wordfreq` (paper footnote 3). `--spacy-model`, `--tau-word`.

Real backends are imported LAZILY (only when an attack actually runs), so `--help` /
`render` / `smoke` work offline with no model downloads. When a real backend is absent
each falls back to a deterministic lexical heuristic; the active backend is recorded in
the run JSON (`embedder_backend` / `anchor_backend`) so the evidence is honest.
"""

from __future__ import annotations

import difflib
import re
import threading
from typing import Any

from cases import Case

_CONTENT_POS = {"NOUN", "PROPN", "VERB", "ADJ", "ADV"}
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'-]+")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "to", "of", "in", "on", "for", "with",
    "how", "what", "why", "when", "where", "who", "is", "are", "be", "do", "does", "can",
    "you", "your", "i", "me", "my", "it", "this", "that", "these", "those", "from", "as",
    "at", "by", "about", "into", "some", "any", "step", "steps", "give", "write", "provide",
    "explain", "describe", "create", "make", "detailed", "instructions", "tutorial", "guide",
}


# ---------------------------------------------------------------------------
# Top-k candidate selection (Phase 1) + divergence check.
# ---------------------------------------------------------------------------
class TopKSelector:
    """Rank prompts by paraphrase similarity to P*. `spec`:
      st:<model>  → sentence-transformers frozen paraphrase encoder (paper default)
      lexical     → deterministic difflib+token-Jaccard fallback (offline)
    """

    def __init__(self, spec: str = "st:sentence-transformers/paraphrase-MiniLM-L6-v2") -> None:
        self.spec = spec
        self._model: Any = None
        self.backend = "pending"
        # torch CPU forward segfaults when encode() is entered from several
        # worker threads (case-workers > 1) on macOS, and concurrent first-time
        # construction deadlocks — serialize both on this lock.
        self._lock = threading.Lock()

    def _ensure(self) -> None:
        if self.backend != "pending":
            return
        with self._lock:
            if self.backend != "pending":
                return
            self._load()

    def _load(self) -> None:
        if self.spec == "lexical":
            self.backend = "lexical_fallback"
            return
        if self.spec.startswith("st:"):
            try:
                from sentence_transformers import SentenceTransformer  # lazy

                self._model = SentenceTransformer(self.spec.split(":", 1)[1])
                self.backend = f"sentence_transformers::{self.spec.split(':', 1)[1]}"
            except Exception as exc:  # noqa: BLE001 — degrade honestly, do not crash a run
                self._model = None
                self.backend = f"lexical_fallback(st_unavailable:{type(exc).__name__})"
            return
        raise ValueError(f"unsupported embedder spec: {self.spec!r} (use st:<model> or lexical)")

    def similarity(self, a: str, b: str) -> float:
        self._ensure()
        if self._model is not None:
            try:
                from sentence_transformers import util  # lazy

                with self._lock:  # torch CPU forward segfaults on concurrent entry
                    emb = self._model.encode([a, b], convert_to_tensor=True, normalize_embeddings=True)
                    return float(util.cos_sim(emb[0], emb[1]).item())
            except Exception:  # noqa: BLE001
                pass
        return _lexical_sim(a, b)

    def top_k(self, prompts: list[str], target: str, k: int) -> list[tuple[int, float]]:
        """Return [(index_into_prompts, score)] for the k most similar prompts to target."""
        scored = [(idx, self.similarity(p, target)) for idx, p in enumerate(prompts)]
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:k]


def _lexical_sim(a: str, b: str) -> float:
    a_l, b_l = a.lower(), b.lower()
    ratio = difflib.SequenceMatcher(None, a_l, b_l).ratio()
    ta, tb = set(_TOKEN_RE.findall(a_l)), set(_TOKEN_RE.findall(b_l))
    jacc = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
    return 0.5 * ratio + 0.5 * jacc


# ---------------------------------------------------------------------------
# Anchor-word identification (Phase 2).
# ---------------------------------------------------------------------------
class AnchorExtractor:
    """Extract lexical anchors Δ = content words in P* whose max similarity to any word
    in candidate p is below tau_word, ranked by inverse English-corpus frequency.
    `spec`:
      <spacy-model>  → spaCy POS + static vectors (paper default: en_core_web_md)
      lexical        → deterministic content-word set-diff fallback (offline)
    """

    def __init__(self, spec: str = "en_core_web_md", tau_word: float = 0.8,
                 max_anchors: int = 6) -> None:
        self.spec = spec
        self.tau_word = tau_word
        self.max_anchors = max_anchors
        self._nlp: Any = None
        self.backend = "pending"
        self._freq: Any = None
        # spaCy's nlp() is not thread-safe; serialize lazy load + inference.
        self._lock = threading.Lock()

    def _ensure(self) -> None:
        if self.backend != "pending":
            return
        with self._lock:
            if self.backend != "pending":
                return
            self._load()

    def _load(self) -> None:
        # wordfreq is optional in both paths; load once.
        try:
            from wordfreq import zipf_frequency  # lazy

            self._freq = zipf_frequency
        except Exception:  # noqa: BLE001
            self._freq = None
        if self.spec == "lexical":
            self.backend = "lexical_fallback"
            return
        try:
            import spacy  # lazy

            self._nlp = spacy.load(self.spec)
            has_vectors = getattr(self._nlp.vocab.vectors, "shape", (0,))[0] > 0
            self.backend = (
                f"spacy::{self.spec}" if has_vectors else f"spacy::{self.spec}(no_vectors)"
            )
        except Exception as exc:  # noqa: BLE001
            self._nlp = None
            self.backend = f"lexical_fallback(spacy_unavailable:{type(exc).__name__})"

    def _rank_by_rarity(self, words: list[str]) -> list[str]:
        """Rarest first (lowest zipf); fallback to longest-word heuristic when wordfreq absent."""
        if self._freq is not None:
            keyed = sorted(words, key=lambda w: self._freq(w, "en"))
        else:
            keyed = sorted(words, key=lambda w: -len(w))
        # de-dup preserving order
        seen: set[str] = set()
        out: list[str] = []
        for w in keyed:
            wl = w.lower()
            if wl not in seen:
                seen.add(wl)
                out.append(w)
        return out[: self.max_anchors]

    def anchors(self, target: str, prompt: str) -> list[str]:
        self._ensure()
        if self._nlp is not None:
            with self._lock:  # spaCy nlp() is not thread-safe
                missing = self._spacy_missing(target, prompt)
        else:
            missing = self._lexical_missing(target, prompt)
        return self._rank_by_rarity(missing)

    def _spacy_missing(self, target: str, prompt: str) -> list[str]:
        doc_t = self._nlp(target)
        doc_p = self._nlp(prompt)
        p_tokens = [t for t in doc_p if t.pos_ in _CONTENT_POS and t.is_alpha and t.has_vector]
        missing: list[str] = []
        for w in doc_t:
            if w.pos_ not in _CONTENT_POS or not w.is_alpha:
                continue
            if not w.has_vector or not p_tokens:
                max_sim = 0.0
            else:
                max_sim = max(w.similarity(u) for u in p_tokens)
            if max_sim < self.tau_word:
                missing.append(w.text)
        return missing

    def _lexical_missing(self, target: str, prompt: str) -> list[str]:
        p_tokens = {t.lower() for t in _TOKEN_RE.findall(prompt)}
        missing: list[str] = []
        for tok in _TOKEN_RE.findall(target):
            low = tok.lower()
            if low in _STOPWORDS or len(low) < 3:
                continue
            # "similarity below threshold" ~ token absent from p (exact/substring miss).
            if low in p_tokens:
                continue
            if any(low in pt or pt in low for pt in p_tokens):
                continue
            missing.append(tok)
        return missing
