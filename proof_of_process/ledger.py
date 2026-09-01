"""
proof_of_process/ledger.py
==========================
Append-only, hash-chain ledger backed by SQLite (via aiosqlite).

Schema
------
Each row in the ``entries`` table stores:

  seq           INTEGER  – monotonically increasing sequence number
  timestamp     TEXT     – ISO-8601 UTC timestamp
  session_id    TEXT     – gateway session identifier
  tool          TEXT     – name of the MCP tool that was called
  actor         TEXT     – "agent" or "student"
  input_hash    TEXT     – sha256 of the raw tool input (JSON)
  output_hash   TEXT     – sha256 of the raw tool output (JSON)
  content_diff  TEXT     – human-readable diff of document content (may be empty)
  prev_hash     TEXT     – entry_hash of the immediately preceding entry
  entry_hash    TEXT     – sha256( prev_hash + payload_json )

The chain is verifiable because:
  entry_hash[n] = sha256(entry_hash[n-1] + canonical_json(entry_without_hash[n]))

Tampering with *any* entry breaks every subsequent entry_hash.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

# Sentinel used as the "previous hash" of the very first entry.
GENESIS_HASH = "0" * 64

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS entries (
    seq           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT    NOT NULL,
    session_id    TEXT    NOT NULL,
    tool          TEXT    NOT NULL,
    actor         TEXT    NOT NULL DEFAULT 'agent',
    input_hash    TEXT    NOT NULL,
    output_hash   TEXT    NOT NULL,
    content_diff  TEXT    NOT NULL DEFAULT '',
    prev_hash     TEXT    NOT NULL,
    entry_hash    TEXT    NOT NULL UNIQUE
);
"""


# ---------------------------------------------------------------------------
# Pure helpers (no I/O — easy to unit-test)
# ---------------------------------------------------------------------------

def _sha256(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def _payload_json(
    *,
    timestamp: str,
    session_id: str,
    tool: str,
    actor: str,
    input_hash: str,
    output_hash: str,
    content_diff: str,
) -> str:
    """Canonical JSON for the entry payload (everything except hashes)."""
    return json.dumps(
        {
            "timestamp": timestamp,
            "session_id": session_id,
            "tool": tool,
            "actor": actor,
            "input_hash": input_hash,
            "output_hash": output_hash,
            "content_diff": content_diff,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def compute_entry_hash(prev_hash: str, payload: str) -> str:
    """Compute sha256( prev_hash + payload_json ). Deterministic, pure."""
    return _sha256(prev_hash + payload)


def hash_content(content: Any) -> str:
    """Stable hash of arbitrary JSON-serialisable content."""
    raw = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return _sha256(raw)


# ---------------------------------------------------------------------------
# Ledger class
# ---------------------------------------------------------------------------

class Ledger:
    """
    Async context-managed ledger.

    Usage::

        async with Ledger("ledger.db") as ledger:
            await ledger.append(tool="web_search", ...)
    """

    def __init__(self, db_path: Path | str = "ledger.db") -> None:
        self.db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None

    # --- lifecycle ---

    async def open(self) -> None:
        path_str = str(self.db_path)
        self._db = await aiosqlite.connect(path_str)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(_CREATE_TABLE_SQL)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> "Ledger":
        await self.open()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # --- read ---

    async def get_last_hash(self) -> str:
        """Return the entry_hash of the most recent entry, or GENESIS_HASH."""
        assert self._db is not None, "Ledger not open"
        async with self._db.execute(
            "SELECT entry_hash FROM entries ORDER BY seq DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        return row["entry_hash"] if row else GENESIS_HASH

    async def get_all_entries(self) -> list[dict]:
        """Return all entries ordered by seq ascending."""
        assert self._db is not None, "Ledger not open"
        async with self._db.execute(
            "SELECT * FROM entries ORDER BY seq ASC"
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def count(self) -> int:
        assert self._db is not None, "Ledger not open"
        async with self._db.execute("SELECT COUNT(*) FROM entries") as cur:
            row = await cur.fetchone()
        return row[0] if row else 0

    # --- write ---

    async def append(
        self,
        *,
        tool: str,
        input_data: Any,
        output_data: Any,
        session_id: str = "default",
        actor: str = "agent",
        content_diff: str = "",
        timestamp: str | None = None,
    ) -> dict:
        """
        Append a new entry to the ledger.

        Returns the full entry dict (including seq, prev_hash, entry_hash).
        """
        assert self._db is not None, "Ledger not open"

        ts = timestamp or datetime.now(timezone.utc).isoformat()
        input_hash = hash_content(input_data)
        output_hash = hash_content(output_data)
        prev_hash = await self.get_last_hash()

        payload = _payload_json(
            timestamp=ts,
            session_id=session_id,
            tool=tool,
            actor=actor,
            input_hash=input_hash,
            output_hash=output_hash,
            content_diff=content_diff,
        )
        entry_hash = compute_entry_hash(prev_hash, payload)

        await self._db.execute(
            """
            INSERT INTO entries
                (timestamp, session_id, tool, actor,
                 input_hash, output_hash, content_diff,
                 prev_hash, entry_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ts, session_id, tool, actor,
             input_hash, output_hash, content_diff,
             prev_hash, entry_hash),
        )
        await self._db.commit()

        # Return the full entry for downstream use (signing, reporting, etc.)
        async with self._db.execute(
            "SELECT * FROM entries ORDER BY seq DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        return dict(row)


async def load_ledger(db_path: Path | str) -> list[dict]:
    """Helper to read the entire ledger from disk."""
    async with Ledger(db_path) as ledger:
        return await ledger.get_all_entries()
