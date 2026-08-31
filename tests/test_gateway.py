"""
tests/test_gateway.py
======================
Integration-level tests for the proxy capture layer.

Instead of spinning up real subprocesses (which would make tests fragile and
slow), we test the core capture logic directly:

  - hash_content() is called on inputs and outputs.
  - Ledger entries are appended correctly.
  - Content diff is computed for document-mutating tools.

We mock the downstream call so no subprocess is needed.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from proof_of_process.ledger import Ledger, GENESIS_HASH


@pytest.mark.asyncio
async def test_ledger_entry_created_on_capture(tmp_path: Path):
    """
    Simulate the capture logic: hash input/output, append to ledger.
    Verify that the ledger contains the expected entry.
    """
    from proof_of_process.ledger import hash_content

    tool = "web_search"
    input_data = {"query": "AI text detection bias"}
    output_data = {"result": "Some article about detectors"}

    async with Ledger(tmp_path / "test.db") as ledger:
        entry = await ledger.append(
            tool=tool,
            input_data=input_data,
            output_data=output_data,
            session_id="test-session",
            actor="agent",
        )

        assert entry["tool"] == tool
        assert entry["input_hash"] == hash_content(input_data)
        assert entry["output_hash"] == hash_content(output_data)
        assert entry["prev_hash"] == GENESIS_HASH
        assert entry["actor"] == "agent"


@pytest.mark.asyncio
async def test_chain_integrity_across_multiple_captures(tmp_path: Path):
    """Multiple tool calls should form a valid chain."""
    from proof_of_process.verifier import verify_chain

    async with Ledger(tmp_path / "test.db") as ledger:
        await ledger.append(tool="web_search",  input_data="q1", output_data="r1")
        await ledger.append(tool="add_note",    input_data="n1", output_data="ok1")
        await ledger.append(tool="append_to_document", input_data="text1", output_data="ok2", content_diff="+ Added paragraph: 'text1'")
        await ledger.append(tool="web_search",  input_data="q2", output_data="r2")

        entries = await ledger.get_all_entries()

    ok, msg = verify_chain(entries)
    assert ok, f"Chain should be valid but got: {msg}"


@pytest.mark.asyncio
async def test_content_diff_stored_in_entry(tmp_path: Path):
    """Verify content_diff is preserved in the ledger entry."""
    diff_text = "+ Added paragraph: 'My thesis statement.'"

    async with Ledger(tmp_path / "test.db") as ledger:
        entry = await ledger.append(
            tool="append_to_document",
            input_data={"text": "My thesis statement."},
            output_data="Appended 22 characters.",
            content_diff=diff_text,
        )

        assert entry["content_diff"] == diff_text


@pytest.mark.asyncio
async def test_report_generated_from_ledger(tmp_path: Path):
    """Report generator should produce non-empty Markdown from ledger entries."""
    from proof_of_process.report_generator import generate_markdown_report

    async with Ledger(tmp_path / "test.db") as ledger:
        await ledger.append(tool="web_search",  input_data="q", output_data="r")
        await ledger.append(tool="add_note",    input_data="n", output_data="ok")
        entries = await ledger.get_all_entries()

    md = generate_markdown_report(entries)
    assert "# 📜 Provenance Report" in md
    assert "web_search" in md
    assert "add_note" in md
    assert "Timeline" in md
    assert "Verification" in md
