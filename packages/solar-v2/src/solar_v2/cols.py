"""Excel column-letter helpers (A..Z, AA..AZ, ...)."""

from __future__ import annotations


def col_letters(start: str, count: int) -> list[str]:
    """count column letters starting at start, e.g. col_letters('G', 25) → G..AE."""
    idx = col_index(start)
    return [col_name(idx + i) for i in range(count)]


def col_index(letters: str) -> int:
    """0-based index of a column letter sequence (A=0)."""
    idx = 0
    for ch in letters.upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def col_name(idx: int) -> str:
    """Column letters for a 0-based index."""
    out = ""
    idx += 1
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        out = chr(ord("A") + rem) + out
    return out
