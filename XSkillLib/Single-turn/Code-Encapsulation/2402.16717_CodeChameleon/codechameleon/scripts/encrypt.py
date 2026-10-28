#!/usr/bin/env python3
"""CodeChameleon encryption transforms (verbatim port of official encrypt.py).

The query passed to the model is the Python str() of the structure (single-quote
repr), exactly as the official pipeline serializes it via pandas/.format().
This is CodeChameleon's deterministic 加壳 core — no LLM.
"""
from __future__ import annotations

from typing import Any

RULES = ("reverse", "binary_tree", "odd_even", "length", "none")


def encrypt_reverse(sentence: str) -> str:
    return " ".join(sentence.split(" ")[::-1])


def encrypt_none(sentence: str) -> str:
    return sentence


def encrypt_odd_even(sentence: str) -> str:
    words = sentence.split()
    odd_words = words[::2]
    even_words = words[1::2]
    return " ".join(odd_words + even_words)


def encrypt_length(sentence: str) -> list[dict[str, int]]:
    words = sentence.split()
    word_data = [(word, i) for i, word in enumerate(words)]
    word_data.sort(key=lambda x: len(x[0]))
    return [{word: index} for word, index in word_data]


def encrypt_binary_tree(sentence: str) -> dict[str, Any] | None:
    words = sentence.split()

    def build(start: int, end: int) -> dict[str, Any] | None:
        if start > end:
            return None
        mid = (start + end) // 2
        return {
            "value": words[mid],
            "left": build(start, mid - 1),
            "right": build(mid + 1, end),
        }

    return build(0, len(words) - 1)


def get_encrypted_query(sentence: str, rule: str) -> Any:
    if rule == "none":
        return encrypt_none(sentence)
    if rule == "binary_tree":
        return encrypt_binary_tree(sentence)
    if rule == "reverse":
        return encrypt_reverse(sentence)
    if rule == "odd_even":
        return encrypt_odd_even(sentence)
    if rule == "length":
        return encrypt_length(sentence)
    raise ValueError(f"unknown encryption rule: {rule}")


def encrypted_to_text(encrypted: Any) -> str:
    """How the official pipeline serializes the encrypted query into the prompt:
    str() of the structure (Python repr for dict/list, plain str otherwise)."""
    if isinstance(encrypted, str):
        return encrypted
    return str(encrypted)
