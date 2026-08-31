"""
proof_of_process/report_generator.py
=====================================
Turns the raw ledger into a human-readable Markdown provenance report that a
professor or reviewer can actually read.

The report shows:
  * A session summary (start/end time, total tool calls).
  * A chronological timeline of every tool call with relevant details.
  * A legend explaining the actor codes.
  * Instructions for the standalone verifier.

Optional: if a session_log (list of dicts with seq, tool, input, output) is
provided, the timeline is enriched with actual search queries, note content
previews, and output summaries.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Sequence


# ---------------------------------------------------------------------------
# Emoji / icon helpers
# ---------------------------------------------------------------------------

_TOOL_ICONS: dict[str, str] = {
    "web_search":         "🔍",
    "add_note":           "📝",
    "list_notes":         "📋",
    "get_note":           "📌",
    "delete_note":        "🗑️",
    "get_document":       "📄",
    "append_to_document": "✏️",
    "replace_section":    "🔄",
    "clear_document":     "🧹",
}
_DEFAULT_ICON = "⚙️"


def _icon(tool: str) -> str:
    return _TOOL_ICONS.get(tool, _DEFAULT_ICON)


def _fmt_ts(iso: str) -> str:
    """Format an ISO-8601 timestamp into a readable string."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return iso


def _actor_badge(actor: str) -> str:
    return "🤖 AI Agent" if actor == "agent" else "👤 Student"


def _truncate(text: str, max_len: int = 120) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


# ---------------------------------------------------------------------------
# Session-log annotation helpers
# ---------------------------------------------------------------------------

def _annotate_entry(entry: dict, log_entry: dict | None) -> list[str]:
    """
    Return a list of Markdown bullet lines that annotate a ledger entry
    with human-readable context from the session log.
    """
    if log_entry is None:
        return []

    tool  = entry["tool"]
    inp   = log_entry.get("input", {})
    out   = log_entry.get("output", "")
    lines: list[str] = []

    if tool == "web_search":
        query = inp.get("query", "")
        if query:
            lines.append(f"- **Query:** `{query}`")
        try:
            data = json.loads(out) if isinstance(out, str) else out
            top  = data.get("top_result", {})
            if top.get("title"):
                lines.append(f"- **Top result:** {top['title']}")
            if top.get("url"):
                lines.append(f"- **URL:** <{top['url']}>")
        except Exception:
            if out:
                lines.append(f"- **Result:** {_truncate(str(out), 100)}")

    elif tool == "add_note":
        content = inp.get("content", "")
        if content:
            lines.append(f"- **Content preview:** *{_truncate(content, 150)}*")
        if out:
            lines.append(f"- **Server response:** {out}")

    elif tool == "get_note":
        note_id = inp.get("id", inp.get("note_id", ""))
        if note_id:
            lines.append(f"- **Retrieved note:** #{note_id}")
        if out:
            lines.append(f"- **Content preview:** *{_truncate(str(out), 150)}*")

    elif tool == "delete_note":
        note_id = inp.get("id", inp.get("note_id", ""))
        if note_id:
            lines.append(f"- **Deleted note:** #{note_id}")

    elif tool == "list_notes":
        try:
            notes = json.loads(out) if isinstance(out, str) else out
            if isinstance(notes, list):
                lines.append(f"- **Notes found:** {len(notes)}")
        except Exception:
            pass

    elif tool in ("append_to_document", "replace_section"):
        text = inp.get("text", inp.get("new_text", ""))
        if text:
            lines.append(f"- **Content added:** *{_truncate(text, 120)}*")
        if out:
            lines.append(f"- **Server response:** {_truncate(str(out), 80)}")

    return lines


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def generate_markdown_report(
    entries: list[dict],
    *,
    session_id: str | None = None,
    public_key_path: str = "public_key.pem",
    signature_path: str = "ledger.sig",
    ledger_path: str = "ledger.db",
    session_log: list[dict] | None = None,
) -> str:
    """
    Render the ledger as a Markdown provenance report.

    Parameters
    ----------
    entries:          All ledger rows, ordered by seq ascending.
    session_id:       Optional override; auto-detected from entries if omitted.
    public_key_path:  Shown in verification instructions.
    signature_path:   Shown in verification instructions.
    ledger_path:      Shown in verification instructions.
    session_log:      Optional list of dicts {seq, tool, input, output} from
                      session_log.jsonl. When provided, the timeline includes
                      actual queries, note content, and output summaries.

    Returns the full Markdown string.
    """
    if not entries:
        return "# Provenance Report\n\n_No entries found in this ledger._\n"

    sid      = session_id or entries[0].get("session_id", "unknown")
    first_ts = _fmt_ts(entries[0]["timestamp"])
    last_ts  = _fmt_ts(entries[-1]["timestamp"])
    n        = len(entries)

    # Build session_log lookup: seq -> log_entry
    log_by_seq: dict[int, dict] = {}
    if session_log:
        for le in session_log:
            log_by_seq[int(le["seq"])] = le

    # Tally tool call types
    tool_counts: dict[str, int] = {}
    for e in entries:
        tool_counts[e["tool"]] = tool_counts.get(e["tool"], 0) + 1

    lines: list[str] = []

    # ---- Header ----
    lines += [
        "# 📜 Provenance Report — Show Your Work",
        "",
        "> This report was automatically generated by the MCP Proof of Process gateway.",
        "> It provides a tamper-evident, chronological record of the research and writing",
        "> process. The hash chain and signature can be independently verified — see the",
        "> verification section at the bottom.",
        "",
        "---",
        "",
        "## 🗂️ Session Summary",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Session ID | `{sid}` |",
        f"| Started | {first_ts} |",
        f"| Ended | {last_ts} |",
        f"| Total tool calls | **{n}** |",
        f"| Chain length | {n} entries |",
        "",
    ]

    # Tool breakdown table
    lines += ["### Tool Call Breakdown", "", "| Tool | Count |", "|---|---|"]
    for tool, count in sorted(tool_counts.items(), key=lambda x: -x[1]):
        lines.append(f"| {_icon(tool)} `{tool}` | {count} |")
    lines += ["", "---", ""]

    # ---- Timeline ----
    lines += ["## ⏱️ Timeline", ""]

    for entry in entries:
        seq   = entry["seq"]
        ts    = _fmt_ts(entry["timestamp"])
        tool  = entry["tool"]
        actor = entry.get("actor", "agent")
        diff  = entry.get("content_diff", "")
        ehash = entry["entry_hash"][:16] + "…"
        log_e = log_by_seq.get(seq)

        lines += [
            f"### {_icon(tool)} Step {seq} — {tool.replace('_', ' ').title()}",
            "",
            f"- **Time:** {ts}",
            f"- **Actor:** {_actor_badge(actor)}",
        ]

        # Enrich with session log data (actual inputs/outputs)
        lines.extend(_annotate_entry(entry, log_e))

        lines += [
            "",
            "<details>",
            "<summary>🔍 Cryptographic Proof (Click to expand)</summary>",
            "",
            f"- **Entry hash:** `{ehash}`",
            "</details>",
        ]

        if diff:
            lines += [
                "- **Document changes:**",
                "",
                "  ```",
                *[f"  {line}" for line in diff.splitlines()],
                "  ```",
            ]

        lines += [""]

    # ---- Legend ----
    lines += [
        "---",
        "",
        "## 🔑 Legend",
        "",
        "| Symbol | Meaning |",
        "|---|---|",
        "| 🤖 AI Agent | Action was performed by the AI assistant |",
        "| 👤 Student  | Action was performed by the student directly |",
        "| 🔍 | Web search tool call |",
        "| 📝 | Note added |",
        "| 📋 | Notes listed |",
        "| 📌 | Note retrieved |",
        "| 🗑️ | Note deleted |",
        "| ✏️ | Document content appended |",
        "| 🔄 | Document section replaced |",
        "",
        "---",
        "",
    ]

    # ---- Verification ----
    lines += [
        "## ✅ Verification",
        "",
        "Anyone can independently verify that this ledger has not been tampered with.",
        "No trust in the gateway operator is required — just the math.",
        "",
        "**Standalone verifier** (only needs `pip install cryptography`, no project install):",
        "",
        "```bash",
        f"python verifier/verify.py {ledger_path} {public_key_path} {signature_path}",
        "```",
        "",
        "**Via project CLI:**",
        "",
        "```bash",
        f"uv run python main.py verify {ledger_path} {public_key_path} {signature_path}",
        "```",
        "",
        "A `✅ PASS` result means:",
        "1. Every entry's `entry_hash` correctly chains from the previous one.",
        "2. The signature was produced by the private key paired with the public key above.",
        "3. No entry has been added, removed, or modified since signing.",
        "",
    ]

    return "\n".join(lines)


def save_report(
    entries: list[dict],
    output_path: Path | str = "provenance_report.md",
    **kwargs,
) -> Path:
    """Write the Markdown report to *output_path* and return the path."""
    md = generate_markdown_report(entries, **kwargs)
    out = Path(output_path)
    out.write_text(md, encoding="utf-8")
    return out
