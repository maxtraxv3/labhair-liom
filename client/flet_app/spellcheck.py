"""Lightweight spell checker using pyspellchecker."""

from __future__ import annotations

from spellchecker import SpellChecker as _SpellChecker

_spell: _SpellChecker | None = None


def _get_spell() -> _SpellChecker:
    global _spell
    if _spell is None:
        _spell = _SpellChecker()
    return _spell


def check_text(text: str) -> list[tuple[str, int]]:
    """Return list of (misspelled_word, position) in text."""
    spell = _get_spell()
    words = text.split()
    misspelled = []
    pos = 0
    for word in words:
        # Strip punctuation for checking
        clean = word.strip(".,!?;:\"'()[]{}")
        if clean and clean.lower() not in spell:
            misspelled.append((clean, pos))
        pos += len(word) + 1  # +1 for space
    return misspelled


def suggestions(word: str, max_suggestions: int = 5) -> list[str]:
    """Return spelling suggestions for a word."""
    spell = _get_spell()
    return list(spell.candidates(word))[:max_suggestions]
