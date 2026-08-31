"""
gateway/session_state.py
========================
Holds mutable per-session state that the gateway proxy needs across
multiple tool calls within a single session:

  - document_content : the last-seen full text of the document being edited,
                        used as the "before" side when the diff engine runs.
  - session_id       : identifier for this provenance session.
  - call_count       : running count of intercepted tool calls this session.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class SessionState:
    """Mutable state shared across all tool-call interceptions in a session."""

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    """A unique ID for this gateway session (becomes part of every ledger entry)."""

    document_content: str = ""
    """The current full text of the document being tracked.
    Updated after every document-mutating tool call."""

    call_count: int = 0
    """Total number of tool calls intercepted this session."""

    def tick(self) -> None:
        """Increment the call counter. Call once per intercepted tool call."""
        self.call_count += 1

    def update_document(self, new_content: str) -> str:
        """
        Replace the stored document content and return the *old* content
        so the diff engine can compute a delta.
        """
        old = self.document_content
        self.document_content = new_content
        return old

    def snapshot(self) -> dict:
        """Return a plain-dict snapshot suitable for logging / debugging."""
        return {
            "session_id": self.session_id,
            "call_count": self.call_count,
            "document_length": len(self.document_content),
        }
