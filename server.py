"""
server.py
=========
ShowYourWork — FastMCP Cloud–deployable provenance server.

This file is the single FastMCP entry-point that:

  1. Exposes all downstream tools (web_search, notes, document editing)
     as **in-process functions** — no subprocess spawning at runtime.
     This is required for cloud deployment where spawning child processes
     is not available.

  2. Intercepts every tool call with a **provenance capture** layer that:
       - Hashes inputs and outputs.
       - Computes a document diff for document-mutating calls.
       - Appends a tamper-evident hash-chain entry to the ledger.
       - Preserves the original tool result unchanged.

  3. Exposes a module-level ``mcp = FastMCP(...)`` object so that
     ``fastmcp run server.py:mcp`` (or the FastMCP Cloud runner) can
     discover and serve it over HTTP / streamable-HTTP.

  4. Reads all paths (ledger DB, signing keys, data files) from env vars
     with sensible local defaults, so no path is hardcoded.

Transports
----------
* **Local stdio** (for Claude Desktop / Cursor):
      fastmcp run server.py:mcp --transport stdio

* **Local HTTP** (for testing before cloud):
      fastmcp run server.py:mcp --transport http --port 8000
      # or: fastmcp run server.py:mcp --transport streamable-http --port 8000

* **FastMCP Cloud**:
      Set entrypoint ``server.py:mcp`` in the cloud dashboard.
      The runner handles transport automatically.

Environment Variables
---------------------
GATEWAY_LEDGER_PATH        Path to the SQLite ledger DB.   Default: ledger.db
GATEWAY_PRIVATE_KEY_PATH   Path to Ed25519 private key.    Default: private_key.pem
GATEWAY_PUBLIC_KEY_PATH    Path to Ed25519 public key.     Default: public_key.pem
NOTES_FILE_PATH            Path to notes JSON store.        Default: notes.json
DOCUMENT_FILE_PATH         Path to the Markdown document.   Default: document.md
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

# ---------------------------------------------------------------------------
# Ensure repo root is on sys.path so local packages resolve whether the
# cloud runner pip-installs the project or not. Must come before local imports.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastmcp import FastMCP

from proof_of_process.diff_engine import compute_diff
from proof_of_process.ledger import Ledger

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
import tempfile
import uuid

def _get_writable_path(env_var: str, default_filename: str) -> Path:
    val = os.environ.get(env_var)
    if val:
        return Path(val)
    
    p = Path(default_filename)
    try:
        # Docker root user makes os.access(_, os.W_OK) return True even on read-only mounts.
        # We must perform an actual write test to confirm writability.
        test_file = p.parent / f".test_write_{uuid.uuid4().hex}"
        test_file.touch()
        test_file.unlink()
        return p
    except OSError:
        return Path(tempfile.gettempdir()) / default_filename

_LEDGER_PATH = _get_writable_path("GATEWAY_LEDGER_PATH", "ledger.db")
_PRIVATE_KEY_PATH = _get_writable_path("GATEWAY_PRIVATE_KEY_PATH", "private_key.pem")
_PUBLIC_KEY_PATH = _get_writable_path("GATEWAY_PUBLIC_KEY_PATH", "public_key.pem")
_NOTES_FILE = _get_writable_path("NOTES_FILE_PATH", "notes.json")
_DOC_FILE = _get_writable_path("DOCUMENT_FILE_PATH", "document.md")


# ---------------------------------------------------------------------------
# Module-level state (in-process, per-server-instance)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Module-level state (in-process, per-server-instance)
# Inlined here so server.py has zero dependency on the gateway package.
# ---------------------------------------------------------------------------

class _ServerState:
    """Minimal session + ledger state for the lifetime of this server process."""
    def __init__(self) -> None:
        self.ledger: Ledger | None = None
        self.session_id: str = str(uuid.uuid4())
        self.call_count: int = 0
        self.document_content: str = ""

    def tick(self) -> None:
        self.call_count += 1

    def update_document(self, new_content: str) -> str:
        old = self.document_content
        self.document_content = new_content
        return old


_state = _ServerState()


# ---------------------------------------------------------------------------
# Lifespan: open ledger when server starts, close when it stops
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[None]:
    """Open the SQLite ledger on startup and close it cleanly on shutdown."""
    # Ensure all configurable paths have existing parent directories (essential for Cloud deployments)
    _LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    _NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _DOC_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    _state.ledger = Ledger(_LEDGER_PATH)
    await _state.ledger.open()
    logger.info(f"[ShowYourWork] Ledger opened at {_LEDGER_PATH}")
    try:
        yield
    finally:
        if _state.ledger:
            await _state.ledger.close()
            logger.info("[ShowYourWork] Ledger closed.")


# ---------------------------------------------------------------------------
# Module-level FastMCP instance — required by fastmcp run / FastMCP Cloud
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="ShowYourWork",
    instructions=(
        "ShowYourWork is a provenance gateway that records every tool call "
        "in a tamper-evident, cryptographically hash-chained ledger. "
        "Use these tools as you would use any research assistant — every "
        "search, note, and document edit is logged automatically."
    ),
    lifespan=_lifespan,
)


# ---------------------------------------------------------------------------
# Internal capture helper
# ---------------------------------------------------------------------------

async def _capture(
    tool_name: str,
    input_data: Any,
    output_data: Any,
    content_diff: str = "",
) -> None:
    """Append a provenance entry to the ledger. No-ops gracefully if ledger is not open."""
    if _state.ledger is None:
        logger.warning("[ShowYourWork] Ledger not open — skipping capture for %s", tool_name)
        return

    _state.tick()
    await _state.ledger.append(
        tool=tool_name,
        input_data=input_data,
        output_data=output_data,
        session_id=_state.session_id,
        actor="agent",
        content_diff=content_diff,
    )
    logger.info(
        "[ShowYourWork] call #%d captured: %s -> ledger entry appended",
        _state.call_count,
        tool_name,
    )



# ===========================================================================
# TOOL GROUP 1 — Web Search  (replaces mock_servers/mock_search.py)
# ===========================================================================

_SEARCH_RESULTS: list[dict] = [
    {
        "keywords": ["ai", "detection", "turnitin", "gptzero"],
        "title": "AI-Text Detectors Are Unreliable, Study Finds (Nature, 2026)",
        "snippet": (
            "A large-scale evaluation across six major AI-text detection tools found "
            "false-positive rates of up to 62% on essays written by non-native English "
            "speakers, calling into question their use in academic integrity enforcement."
        ),
        "url": "https://example.com/nature-2026-ai-detectors",
    },
    {
        "keywords": ["provenance", "academic", "integrity", "writing"],
        "title": "Provenance-Based Academic Integrity: A Framework Proposal (arXiv 2026)",
        "snippet": (
            "Rather than detecting AI-generated text post-hoc, the authors propose "
            "capturing the *process* of writing — every search, draft, and edit — "
            "in a tamper-evident log. Detection becomes verification."
        ),
        "url": "https://example.com/arxiv-provenance-2026",
    },
    {
        "keywords": ["mcp", "model context protocol", "anthropic"],
        "title": "Model Context Protocol (MCP) — Official Documentation",
        "snippet": (
            "MCP is an open protocol that standardises how AI models interact with "
            "external tools and data sources via a JSON-RPC interface. Clients and "
            "servers communicate over stdio or HTTP+SSE transports."
        ),
        "url": "https://modelcontextprotocol.io/docs",
    },
    {
        "keywords": ["ed25519", "signature", "cryptography", "signing"],
        "title": "Ed25519: High-Speed, High-Security Signatures (Bernstein et al.)",
        "snippet": (
            "Ed25519 is a public-key signature scheme offering 128-bit security, "
            "fast verification, and small key/signature sizes (32-byte keys, "
            "64-byte signatures). Ideal for provenance systems where signatures "
            "must be stored alongside each log entry."
        ),
        "url": "https://example.com/ed25519-paper",
    },
    {
        "keywords": ["hash", "chain", "blockchain", "tamper", "ledger"],
        "title": "Append-Only Hash Chains for Audit Logs (USENIX Security 2025)",
        "snippet": (
            "A minimal hash-chain approach — where each entry's hash is computed "
            "over the previous hash plus the entry payload — provides strong tamper "
            "evidence without the overhead of a full distributed ledger."
        ),
        "url": "https://example.com/usenix-hashchain-2025",
    },
]

_SEARCH_FALLBACK = {
    "title": "General Web Search Result",
    "snippet": (
        "No specific canned result matched your query. "
        "In a production deployment this would return real search results."
    ),
    "url": "https://example.com/fallback",
}


def _find_search_result(query: str) -> dict:
    q_lower = query.lower()
    for result in _SEARCH_RESULTS:
        if any(kw in q_lower for kw in result["keywords"]):
            return result
    return _SEARCH_FALLBACK


@mcp.tool()
async def web_search(query: str) -> str:
    """
    Search the web for information related to a query.

    Parameters
    ----------
    query : str
        The search query string.

    Returns a JSON string with title, snippet, and URL of the top result.
    Every call is recorded in the provenance ledger.
    """
    result = _find_search_result(query)
    output = json.dumps(
        {
            "query": query,
            "top_result": {
                "title": result["title"],
                "snippet": result["snippet"],
                "url": result["url"],
            },
        },
        indent=2,
    )
    await _capture("web_search", {"query": query}, output)
    return output


# ===========================================================================
# TOOL GROUP 2 — Notes  (replaces mock_servers/mock_notes.py)
# ===========================================================================

def _load_notes() -> list[dict]:
    if _NOTES_FILE.exists():
        return json.loads(_NOTES_FILE.read_text(encoding="utf-8"))
    return []


def _save_notes(notes: list[dict]) -> None:
    _NOTES_FILE.write_text(
        json.dumps(notes, indent=2, ensure_ascii=False), encoding="utf-8"
    )


@mcp.tool()
async def add_note(content: str) -> str:
    """
    Save a new note.

    Parameters
    ----------
    content : str
        The full text of the note to save.

    Returns a confirmation string with the assigned note ID.
    Every call is recorded in the provenance ledger.
    """
    notes = _load_notes()
    note_id = len(notes) + 1
    notes.append(
        {
            "id": note_id,
            "content": content,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _save_notes(notes)
    output = f"Note #{note_id} saved. ({len(content)} characters)"
    await _capture("add_note", {"content": content}, output)
    return output


@mcp.tool()
async def list_notes() -> str:
    """
    List all saved notes (id + preview).

    Returns a JSON array of {id, preview, created_at} objects.
    An empty JSON array is returned if there are no notes yet.
    Every call is recorded in the provenance ledger.
    """
    notes = _load_notes()
    if not notes:
        output = "[]"
    else:
        previews = [
            {
                "id": n["id"],
                "preview": n["content"][:80] + ("…" if len(n["content"]) > 80 else ""),
                "created_at": n.get("created_at", ""),
            }
            for n in notes
        ]
        output = json.dumps(previews, indent=2)
    await _capture("list_notes", {}, output)
    return output


@mcp.tool()
async def get_note(id: int) -> str:
    """
    Retrieve the full text of a specific note.

    Parameters
    ----------
    id : int
        The note ID (as returned by add_note or list_notes).

    Returns the note content, or an error message if not found.
    Every call is recorded in the provenance ledger.
    """
    notes = _load_notes()
    for note in notes:
        if note["id"] == id:
            output = note["content"]
            await _capture("get_note", {"id": id}, output)
            return output
    output = f"Error: Note #{id} not found."
    await _capture("get_note", {"id": id}, output)
    return output


@mcp.tool()
async def delete_note(id: int) -> str:
    """
    Delete a note by ID.

    Parameters
    ----------
    id : int
        The note ID to delete.

    Returns a confirmation, or an error if not found.
    Every call is recorded in the provenance ledger.
    """
    notes = _load_notes()
    before = len(notes)
    notes = [n for n in notes if n["id"] != id]
    if len(notes) == before:
        output = f"Error: Note #{id} not found."
    else:
        _save_notes(notes)
        output = f"Note #{id} deleted."
    await _capture("delete_note", {"id": id}, output)
    return output


# ===========================================================================
# TOOL GROUP 3 — Document Editing  (replaces mock_servers/mock_document.py)
# ===========================================================================

def _read_doc() -> str:
    if _DOC_FILE.exists():
        return _DOC_FILE.read_text(encoding="utf-8")
    return ""


def _write_doc(content: str) -> None:
    _DOC_FILE.write_text(content, encoding="utf-8")


@mcp.tool()
async def get_document() -> str:
    """
    Retrieve the full current text of the document.

    Returns the raw Markdown text, or an empty string if the document is empty.
    Every call is recorded in the provenance ledger.
    """
    output = _read_doc()
    await _capture("get_document", {}, output)
    return output


@mcp.tool()
async def append_to_document(text: str) -> str:
    """
    Append text to the end of the document.

    Parameters
    ----------
    text : str
        The Markdown text to append. A blank line is automatically inserted
        before the new content if the document is not empty.

    Returns a confirmation string showing the new document length.
    Every call is recorded in the provenance ledger, including a paragraph-level diff.
    """
    old_content = _read_doc()
    separator = "\n\n" if old_content.strip() else ""
    new_content = old_content + separator + text
    _write_doc(new_content)

    output = (
        f"Appended {len(text)} characters. "
        f"Document is now {len(new_content)} characters."
    )

    # Compute and store the diff
    content_diff = compute_diff(old_content, new_content)
    # Update session document snapshot for future diffs
    _state.session.update_document(new_content)

    await _capture("append_to_document", {"text": text}, output, content_diff=content_diff)
    return output


@mcp.tool()
async def replace_section(section_title: str, new_text: str) -> str:
    """
    Replace the content of a Markdown section identified by its heading.

    The section is identified by a line starting with one or more ``#``
    characters followed by *section_title*. Everything from that heading
    up to (but not including) the next same-or-higher-level heading is
    replaced with *new_text*.

    Parameters
    ----------
    section_title : str
        The heading text to search for (case-insensitive, leading # ignored).
    new_text : str
        The replacement content (the heading line is preserved; only the
        body under it is replaced).

    Returns a confirmation, or an error if the section is not found.
    Every call is recorded in the provenance ledger, including a paragraph-level diff.
    """
    old_content = _read_doc()
    lines = old_content.splitlines(keepends=True)

    target_lower = section_title.strip().lstrip("#").strip().lower()
    start_idx: int | None = None
    heading_level: int = 1

    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m and m.group(2).strip().lower() == target_lower:
            start_idx = i
            heading_level = len(m.group(1))
            break

    if start_idx is None:
        output = f"Error: Section '{section_title}' not found in the document."
        await _capture(
            "replace_section",
            {"section_title": section_title, "new_text": new_text},
            output,
        )
        return output

    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        m = re.match(r"^(#{1,6})\s+", lines[i])
        if m and len(m.group(1)) <= heading_level:
            end_idx = i
            break

    heading_line = lines[start_idx]
    new_section = heading_line + new_text.strip("\n") + "\n"
    new_lines = lines[:start_idx] + [new_section] + lines[end_idx:]
    new_content = "".join(new_lines)
    _write_doc(new_content)

    replaced_chars = sum(len(l) for l in lines[start_idx + 1 : end_idx])
    output = (
        f"Section '{section_title}' replaced. "
        f"({replaced_chars} chars removed, {len(new_text)} chars inserted)"
    )

    content_diff = compute_diff(old_content, new_content)
    _state.session.update_document(new_content)

    await _capture(
        "replace_section",
        {"section_title": section_title, "new_text": new_text},
        output,
        content_diff=content_diff,
    )
    return output


@mcp.tool()
async def clear_document() -> str:
    """
    Clear the entire document (sets it to an empty string).

    Useful for resetting between demo sessions or test runs.
    Every call is recorded in the provenance ledger.
    """
    _write_doc("")
    _state.session.update_document("")
    output = "Document cleared."
    await _capture("clear_document", {}, output)
    return output


# ---------------------------------------------------------------------------
# Local entry point — allows `python server.py` for quick stdio testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    transport = "stdio"
    if len(sys.argv) > 1 and sys.argv[1] in ("http", "streamable-http", "sse"):
        transport = sys.argv[1]

    mcp.run(transport=transport)
