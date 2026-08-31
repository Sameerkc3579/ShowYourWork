"""
mock_servers/mock_notes.py
==========================
A minimal FastMCP server that exposes a file-backed notes store.

Tools
-----
  add_note(content)         – Append a new note; returns its ID.
  list_notes()              – List all notes (id + first 80 chars).
  get_note(id)              – Retrieve the full text of note #id.
  delete_note(id)           – Remove note #id.

Storage: ``notes.json`` in the current working directory.

Run standalone:
  uv run python mock_servers/mock_notes.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastmcp import FastMCP

mcp = FastMCP(name="MockNotes", version="0.1.0")

_NOTES_FILE = Path("notes.json")


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _load() -> list[dict]:
    if _NOTES_FILE.exists():
        return json.loads(_NOTES_FILE.read_text(encoding="utf-8"))
    return []


def _save(notes: list[dict]) -> None:
    _NOTES_FILE.write_text(
        json.dumps(notes, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def add_note(content: str) -> str:
    """
    Save a new note.

    Parameters
    ----------
    content : str
        The full text of the note to save.

    Returns a confirmation string with the assigned note ID.
    """
    notes = _load()
    note_id = len(notes) + 1
    notes.append(
        {
            "id": note_id,
            "content": content,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _save(notes)
    return f"Note #{note_id} saved. ({len(content)} characters)"


@mcp.tool()
def list_notes() -> str:
    """
    List all saved notes (id + preview).

    Returns a JSON array of {id, preview, created_at} objects.
    An empty JSON array is returned if there are no notes yet.
    """
    notes = _load()
    if not notes:
        return "[]"
    previews = [
        {
            "id": n["id"],
            "preview": n["content"][:80] + ("…" if len(n["content"]) > 80 else ""),
            "created_at": n.get("created_at", ""),
        }
        for n in notes
    ]
    return json.dumps(previews, indent=2)


@mcp.tool()
def get_note(id: int) -> str:
    """
    Retrieve the full text of a specific note.

    Parameters
    ----------
    id : int
        The note ID (as returned by add_note or list_notes).

    Returns the note content, or an error message if not found.
    """
    notes = _load()
    for note in notes:
        if note["id"] == id:
            return note["content"]
    return f"Error: Note #{id} not found."


@mcp.tool()
def delete_note(id: int) -> str:
    """
    Delete a note by ID.

    Parameters
    ----------
    id : int
        The note ID to delete.

    Returns a confirmation, or an error if not found.
    """
    notes = _load()
    before = len(notes)
    notes = [n for n in notes if n["id"] != id]
    if len(notes) == before:
        return f"Error: Note #{id} not found."
    _save(notes)
    return f"Note #{id} deleted."


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
