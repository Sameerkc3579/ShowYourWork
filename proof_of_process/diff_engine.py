"""
proof_of_process/diff_engine.py
================================
Computes human-readable content deltas between two versions of a document.

Strategy
--------
We diff at the *paragraph* level (blank-line-separated blocks) rather than
at the character level. This keeps ledger entries readable by non-technical
reviewers (professors, etc.) while still capturing meaningful changes.

If both texts are identical the function returns an empty string.

Dependencies: diff-match-patch (for fine-grained fallback),
              difflib (stdlib, for paragraph-level primary path).
"""

from __future__ import annotations

import difflib
import re
from typing import Sequence


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs on one-or-more blank lines."""
    return [p.strip() for p in re.split(r"\n{2,}", text.strip()) if p.strip()]


def _short_repr(para: str, max_len: int = 60) -> str:
    """Truncate a paragraph to a short representative string."""
    one_line = " ".join(para.split())
    if len(one_line) <= max_len:
        return one_line
    return one_line[:max_len] + "…"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_diff(old_text: str, new_text: str) -> str:
    """
    Return a human-readable summary of changes from *old_text* to *new_text*.

    Output examples
    ---------------
    * ``""``  — no change
    * ``"+ Added paragraph: 'Climate change is …'"``
    * ``"~ Modified paragraph: 'Introduction' → 'Introduction (revised)'"``
    * ``"- Removed paragraph: 'Placeholder text'"``
    * ``"+ Added 3 paragraphs; - Removed 1 paragraph"``  (summary for large diffs)
    """
    if old_text == new_text:
        return ""

    old_paras = _split_paragraphs(old_text)
    new_paras = _split_paragraphs(new_text)

    if not old_paras and not new_paras:
        return ""

    matcher = difflib.SequenceMatcher(None, old_paras, new_paras, autojunk=False)
    opcodes = matcher.get_opcodes()

    lines: list[str] = []
    added = removed = modified = 0

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            continue
        elif tag == "insert":
            count = j2 - j1
            added += count
            if count == 1:
                lines.append(f"+ Added paragraph: '{_short_repr(new_paras[j1])}'")
            else:
                lines.append(f"+ Added {count} paragraphs")
        elif tag == "delete":
            count = i2 - i1
            removed += count
            if count == 1:
                lines.append(f"- Removed paragraph: '{_short_repr(old_paras[i1])}'")
            else:
                lines.append(f"- Removed {count} paragraphs")
        elif tag == "replace":
            old_count = i2 - i1
            new_count = j2 - j1
            modified += max(old_count, new_count)
            if old_count == 1 and new_count == 1:
                lines.append(
                    f"~ Modified paragraph: '{_short_repr(old_paras[i1])}'"
                    f" → '{_short_repr(new_paras[j1])}'"
                )
            else:
                lines.append(
                    f"~ Replaced {old_count} paragraph(s) with {new_count} paragraph(s)"
                )

    if not lines:
        # Whitespace-only changes or very minor differences
        return "~ Minor formatting change (no paragraph-level diff)"

    # If the diff is very large, collapse to a summary line
    total_changes = added + removed + modified
    if total_changes > 10 and len(lines) > 5:
        summary_parts = []
        if added:
            summary_parts.append(f"+{added} paragraph(s) added")
        if removed:
            summary_parts.append(f"-{removed} paragraph(s) removed")
        if modified:
            summary_parts.append(f"~{modified} paragraph(s) modified")
        return "; ".join(summary_parts)

    return "\n".join(lines)


def compute_word_count_delta(old_text: str, new_text: str) -> int:
    """Return the net change in word count (positive = words added)."""
    old_words = len(old_text.split())
    new_words = len(new_text.split())
    return new_words - old_words
