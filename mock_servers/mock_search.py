"""
mock_servers/mock_search.py
============================
A minimal FastMCP server that exposes a ``web_search`` tool.

The "results" are realistic-looking canned responses keyed by keyword.
This keeps the mock useful as a demo without requiring a real API key.

Run standalone:
  uv run python mock_servers/mock_search.py
"""

from __future__ import annotations

import json
import re

from fastmcp import FastMCP

mcp = FastMCP(name="MockWebSearch", version="0.1.0")

# ---------------------------------------------------------------------------
# Canned result bank — realistic enough for a demo
# ---------------------------------------------------------------------------

_RESULTS: list[dict] = [
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

_FALLBACK = {
    "title": "General Web Search Result",
    "snippet": (
        "No specific canned result matched your query. "
        "In a production deployment, this would return real search results."
    ),
    "url": "https://example.com/fallback",
}


def _find_result(query: str) -> dict:
    """Return the best matching canned result for *query*."""
    q_lower = query.lower()
    for result in _RESULTS:
        if any(kw in q_lower for kw in result["keywords"]):
            return result
    return _FALLBACK


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

@mcp.tool()
def web_search(query: str) -> str:
    """
    Search the web for information related to a query.

    Parameters
    ----------
    query : str
        The search query string.

    Returns a JSON string with title, snippet, and URL of the top result.
    """
    result = _find_result(query)
    return json.dumps(
        {
            "query": query,
            "top_result": {
                "title":   result.get("title", result["title"]),
                "snippet": result.get("snippet", result["snippet"]),
                "url":     result.get("url", result["url"]),
            },
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
