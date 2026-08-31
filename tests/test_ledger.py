"""
tests/test_ledger.py
=====================
Unit tests for the hash-chain ledger.

Tests
-----
- Appending entries creates valid entries.
- Hash chain links correctly (prev_hash of entry N == entry_hash of entry N-1).
- Mutating a stored entry is detectable by re-verifying the chain.
- Empty ledger returns GENESIS_HASH as last hash.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from proof_of_process.ledger import (
    GENESIS_HASH,
    Ledger,
    compute_entry_hash,
    hash_content,
)


@pytest.fixture
async def tmp_ledger(tmp_path: Path):
    """Open a fresh in-memory-like ledger in a temp dir."""
    db_path = tmp_path / "test_ledger.db"
    async with Ledger(db_path) as ledger:
        yield ledger, db_path


@pytest.mark.asyncio
async def test_empty_ledger_genesis_hash(tmp_path: Path):
    async with Ledger(tmp_path / "l.db") as ledger:
        assert await ledger.get_last_hash() == GENESIS_HASH
        assert await ledger.count() == 0


@pytest.mark.asyncio
async def test_append_single_entry(tmp_path: Path):
    async with Ledger(tmp_path / "l.db") as ledger:
        entry = await ledger.append(
            tool="web_search",
            input_data={"query": "AI detectors"},
            output_data={"result": "some text"},
            session_id="test-session",
            actor="agent",
        )
        assert entry["seq"] == 1
        assert entry["tool"] == "web_search"
        assert entry["prev_hash"] == GENESIS_HASH
        assert len(entry["entry_hash"]) == 64  # sha256 hex


@pytest.mark.asyncio
async def test_hash_chain_links(tmp_path: Path):
    """entry[n].prev_hash must equal entry[n-1].entry_hash."""
    async with Ledger(tmp_path / "l.db") as ledger:
        e1 = await ledger.append(tool="web_search", input_data="q1", output_data="r1")
        e2 = await ledger.append(tool="add_note",   input_data="n1", output_data="ok")
        e3 = await ledger.append(tool="web_search", input_data="q2", output_data="r2")

        assert e2["prev_hash"] == e1["entry_hash"]
        assert e3["prev_hash"] == e2["entry_hash"]


@pytest.mark.asyncio
async def test_tamper_detection(tmp_path: Path):
    """Mutating a stored entry breaks the recomputed hash."""
    db_path = tmp_path / "l.db"
    async with Ledger(db_path) as ledger:
        await ledger.append(tool="web_search", input_data="q", output_data="r")
        await ledger.append(tool="add_note",   input_data="n", output_data="ok")

    # Directly mutate the first entry's tool field via sqlite3
    con = sqlite3.connect(db_path)
    con.execute("UPDATE entries SET tool = 'TAMPERED' WHERE seq = 1")
    con.commit()
    con.close()

    # Re-open and verify that the stored entry_hash no longer matches
    async with Ledger(db_path) as ledger:
        entries = await ledger.get_all_entries()

    from proof_of_process.verifier import verify_chain
    ok, msg = verify_chain(entries)
    assert not ok
    assert "tampered" in msg.lower() or "broken" in msg.lower()


@pytest.mark.asyncio
async def test_content_hash_is_deterministic():
    """Same input always produces the same hash."""
    data = {"query": "test", "flags": [1, 2, 3]}
    h1 = hash_content(data)
    h2 = hash_content(data)
    assert h1 == h2
    assert len(h1) == 64


@pytest.mark.asyncio
async def test_multiple_entries_count(tmp_path: Path):
    async with Ledger(tmp_path / "l.db") as ledger:
        for i in range(5):
            await ledger.append(tool=f"tool_{i}", input_data=i, output_data=i * 2)
        assert await ledger.count() == 5
        entries = await ledger.get_all_entries()
        assert len(entries) == 5
        # Ensure seq is monotonically increasing
        seqs = [e["seq"] for e in entries]
        assert seqs == sorted(seqs)
