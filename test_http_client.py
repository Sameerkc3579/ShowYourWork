"""
test_http_client.py
===================
Small integration test: connect to the ShowYourWork server running over HTTP,
call web_search, confirm we get a result, and confirm the ledger got a new entry.

Run AFTER starting the server:
    uv run fastmcp run server.py:mcp --transport http --port 8765

Then in a second terminal:
    uv run python test_http_client.py
"""

import asyncio
import sqlite3
import sys

# Ensure Unicode output works on Windows (CP1252 consoles)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import fastmcp


SERVER_URL = "http://127.0.0.1:8765/mcp/"
LEDGER_PATH = "ledger.db"


async def main() -> None:
    print("=" * 60)
    print("ShowYourWork HTTP Transport Test")
    print("=" * 60)

    # --- Count ledger rows BEFORE the call ---
    try:
        con = sqlite3.connect(LEDGER_PATH)
        before_count = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        con.close()
        print(f"\n[ledger] Rows before call: {before_count}")
    except Exception as e:
        print(f"\n[ledger] Could not read ledger before call: {e}")
        before_count = None

    # --- Connect and call web_search ---
    print(f"\n[client] Connecting to {SERVER_URL} ...")
    async with fastmcp.Client(SERVER_URL) as client:
        print("[client] Connected OK")

        tools = await client.list_tools()
        tool_names = [t.name for t in tools]
        print(f"[client] Tools visible: {tool_names}")
        assert "web_search" in tool_names, f"web_search not found in tools: {tool_names}"

        print("\n[client] Calling web_search(query='MCP model context protocol') ...")
        result = await client.call_tool("web_search", {"query": "MCP model context protocol"})
        # FastMCP 3.x: call_tool returns CallToolResult with .data attribute
        text = str(result.data) if result.data is not None else ""
        print(f"[client] Response:\n{text}")
        assert text, "web_search returned empty result"
        assert "mcp" in text.lower() or "model" in text.lower(), \
            f"Unexpected response: {text}"

        # --- Call append_to_document too, to test diffing ---
        print("\n[client] Calling append_to_document(text='Test paragraph from HTTP client.') ...")
        doc_result = await client.call_tool(
            "append_to_document", {"text": "Test paragraph from HTTP client."}
        )
        doc_text = str(doc_result.data) if doc_result.data is not None else ""
        print(f"[client] Response: {doc_text}")
        assert "Appended" in doc_text, f"Unexpected response: {doc_text}"

    # --- Count ledger rows AFTER the calls ---
    try:
        con = sqlite3.connect(LEDGER_PATH)
        after_count = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        rows = con.execute(
            "SELECT seq, tool, timestamp, entry_hash FROM entries ORDER BY seq DESC LIMIT 3"
        ).fetchall()
        con.close()
        print(f"\n[ledger] Rows after call:  {after_count}")
        if before_count is not None:
            added = after_count - before_count
            print(f"[ledger] New entries added: {added}")
            assert added == 2, f"Expected 2 new ledger entries, got {added}"
            print("[ledger] PASS — 2 new entries (web_search + append_to_document)")
        print("\n[ledger] Last 3 entries:")
        print(f"  {'seq':>4}  {'tool':<25} {'timestamp':<30} {'entry_hash[:16]'}")
        print(f"  {'-'*4}  {'-'*25} {'-'*30} {'-'*16}")
        for seq, tool, ts, eh in reversed(rows):
            print(f"  {seq:>4}  {tool:<25} {ts:<30} {eh[:16]}...")
    except Exception as e:
        print(f"\n[ledger] Could not read ledger after call: {e}")
        raise

    print("\nHTTP transport test PASSED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
