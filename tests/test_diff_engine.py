"""
tests/test_diff_engine.py
==========================
Unit tests for the paragraph-level diff engine.

Tests
-----
- Identical texts produce empty diff.
- Adding a paragraph is detected and labelled.
- Removing a paragraph is detected.
- Modifying a paragraph is detected.
- Word count delta is calculated correctly.
- Large diffs produce a compact summary.
"""

from __future__ import annotations

import pytest

from proof_of_process.diff_engine import compute_diff, compute_word_count_delta


def test_identical_texts_no_diff():
    text = "Hello world.\n\nThis is a second paragraph."
    assert compute_diff(text, text) == ""


def test_empty_to_nonempty():
    result = compute_diff("", "First paragraph here.")
    assert "+" in result  # something was added


def test_nonempty_to_empty():
    result = compute_diff("First paragraph here.", "")
    assert "-" in result  # something was removed


def test_paragraph_added():
    old = "Introduction paragraph here."
    new = "Introduction paragraph here.\n\nNew findings paragraph."
    result = compute_diff(old, new)
    assert "+" in result
    assert "Added" in result


def test_paragraph_removed():
    old = "Introduction.\n\nThis section will be removed."
    new = "Introduction."
    result = compute_diff(old, new)
    assert "-" in result
    assert "Removed" in result


def test_paragraph_modified():
    old = "The hypothesis is supported by the data."
    new = "The hypothesis is strongly supported by multiple data points."
    result = compute_diff(old, new)
    # Should detect a modification (replace)
    assert result != ""  # some change noted


def test_word_count_delta_positive():
    old = "one two three"
    new = "one two three four five"
    assert compute_word_count_delta(old, new) == 2


def test_word_count_delta_negative():
    old = "one two three four five"
    new = "one two"
    assert compute_word_count_delta(old, new) == -3


def test_word_count_delta_no_change():
    text = "alpha beta gamma"
    assert compute_word_count_delta(text, text) == 0


def test_large_diff_collapses_to_summary():
    """A large diff with many paragraph changes should produce a compact summary."""
    old_paras = [f"Original paragraph {i}." for i in range(20)]
    new_paras = [f"Revised paragraph {i}." for i in range(20)]
    old = "\n\n".join(old_paras)
    new = "\n\n".join(new_paras)
    result = compute_diff(old, new)
    # Should not list all 20 changes individually
    assert len(result.splitlines()) < 10
