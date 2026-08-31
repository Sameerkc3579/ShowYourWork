"""
mock_servers/mock_document.py
==============================
A minimal FastMCP server that acts as a live Markdown document editor.

The document is stored as ``document.md`` in the current working directory.
Every write operation returns a diff summary (for the gateway's diff engine).

Tools
-----
  get_document()                           – Return the full document text.
  append_to_document(text)                 – Append text and return diff.
  replace_section(section_title, new_text) – Replace a section and return diff.
  clear_document()                         – Wipe the document (useful for tests).

Run standalone:
  uv run python mock_servers/mock_document.py
"""

from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP

mcp = FastMCP(name="MockDocument", version="0.1.0")

_DOC_FILE = Path("document.md")


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _read() -> str:
    if _DOC_FILE.exists():
        return _DOC_FILE.read_text(encoding="utf-8")
    return ""


def _write(content: str) -> None:
    _DOC_FILE.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_document() -> str:
    """
    Retrieve the full current text of the document.

    Returns the raw Markdown text, or an empty string if the document is empty.
    """
    return _read()


@mcp.tool()
def append_to_document(text: str) -> str:
    """
    Append text to the end of the document.

    Parameters
    ----------
    text : str
        The Markdown text to append. A blank line is automatically inserted
        before the new content if the document is not empty.

    Returns a confirmation string showing the new document length.
    """
    current = _read()
    separator = "\n\n" if current.strip() else ""
    new_content = current + separator + text
    _write(new_content)
    return (
        f"Appended {len(text)} characters. "
        f"Document is now {len(new_content)} characters."
    )


@mcp.tool()
def replace_section(section_title: str, new_text: str) -> str:
    """
    Replace the content of a Markdown section identified by its heading.

    The section is identified by a line starting with one or more ``#``
    characters followed by *section_title*.  Everything from that heading
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
    """
    import re

    content = _read()
    lines = content.splitlines(keepends=True)

    # Find the heading line
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
        return f"Error: Section '{section_title}' not found in the document."

    # Find the end of the section (next heading of same or higher level)
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        m = re.match(r"^(#{1,6})\s+", lines[i])
        if m and len(m.group(1)) <= heading_level:
            end_idx = i
            break

    # Rebuild: keep heading line, replace body
    heading_line = lines[start_idx]
    new_section = heading_line + new_text.strip("\n") + "\n"

    new_lines = lines[:start_idx] + [new_section] + lines[end_idx:]
    new_content = "".join(new_lines)
    _write(new_content)

    replaced_chars = sum(len(l) for l in lines[start_idx + 1:end_idx])
    return (
        f"Section '{section_title}' replaced. "
        f"({replaced_chars} chars removed, {len(new_text)} chars inserted)"
    )


@mcp.tool()
def clear_document() -> str:
    """
    Clear the entire document (sets it to an empty string).

    Useful for resetting between demo sessions or test runs.
    """
    _write("")
    return "Document cleared."


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
