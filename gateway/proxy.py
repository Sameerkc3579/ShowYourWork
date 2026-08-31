"""
gateway/proxy.py
================
The Provenance Gateway — a dual-role MCP entity that:

  1. Acts as an **MCP Server** (using the official MCP SDK) toward the agent / client.
     Exposes all wrapped downstream tools under their original names.

  2. Acts as an **MCP Client** (via the MCP SDK ClientSession) toward each
     real or mock downstream MCP server.

  3. Intercepts every tool call in both directions:
       - Hashes inputs and outputs.
       - Computes a document diff if the tool mutates the document.
       - Appends a ledger entry.
       - Forwards the result to the caller.

Transport
---------
Both sides use **stdio** for the MVP:
  * The downstream servers are launched as subprocesses (one per call).
  * The gateway itself is launched as a subprocess by the MCP client / agent.

Design
------
Tools are **pre-discovered** synchronously at startup, then served
dynamically via the official `mcp.server.Server` API. This avoids schema
parsing issues with wrapper libraries like FastMCP.

Usage
-----
  uv run python main.py gateway
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import mcp.types as types
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from gateway.config import GatewayConfig, ServerConfig, load_config
from gateway.session_state import SessionState
from proof_of_process.diff_engine import compute_diff
from proof_of_process.ledger import Ledger

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: call a downstream tool via a transient MCP client session
# ---------------------------------------------------------------------------

async def _call_downstream(
    server_cfg: ServerConfig,
    tool_name: str,
    arguments: dict,
) -> Any:
    """
    Spawn the downstream server, call a single tool, return the text result.
    A fresh subprocess is used per call (correct for stdio MVP).
    """
    params = StdioServerParameters(
        command=server_cfg.command,
        args=server_cfg.args,
        env=server_cfg.env or None,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            if result.content:
                first = result.content[0]
                if hasattr(first, "text"):
                    return first.text
            return None


# ---------------------------------------------------------------------------
# Tool discovery 
# ---------------------------------------------------------------------------

async def _discover_tools_async(
    cfg: GatewayConfig,
) -> dict[str, tuple[ServerConfig, types.Tool]]:
    """Return {tool_name: (server_cfg, tool_schema)} for all downstream servers."""
    discovered: dict[str, tuple[ServerConfig, types.Tool]] = {}
    for srv in cfg.servers:
        # FASTMCP_QUIET suppresses the FastMCP startup banner that mock servers
        # print to stdout on launch. Without this the banner JSON-corrupts the
        # stdio MCP channel and causes parse errors in the ClientSession.
        import os
        env: dict[str, str] = {**os.environ, "FASTMCP_QUIET": "1", **(srv.env or {})}
        params = StdioServerParameters(
            command=srv.command,
            args=srv.args,
            env=env,
        )
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools_result = await session.list_tools()
                    for t in tools_result.tools:
                        if hasattr(t, "outputSchema"):
                            t.outputSchema = None
                        discovered[t.name] = (srv, t)
                        logger.info(
                            f"Discovered tool '{t.name}' on server '{srv.name}'"
                        )
        except Exception as exc:
            logger.warning(f"Could not discover tools from '{srv.name}': {exc}")
    return discovered


# ---------------------------------------------------------------------------
# Build the proxy server using standard MCP SDK
# ---------------------------------------------------------------------------

async def run_gateway_async(cfg: GatewayConfig | None = None) -> None:
    """Run the proxy over stdio using the official MCP Server class."""
    if cfg is None:
        cfg = load_config()

    state = SessionState(session_id=cfg.session_id)
    ledger = Ledger(cfg.ledger_path)

    logger.info("Discovering downstream tools…")
    try:
        discovered = await _discover_tools_async(cfg)
    except Exception as exc:
        logger.error(f"Tool discovery failed: {exc}. Starting with no tools.")
        discovered = {}

    logger.info(f"Discovered {len(discovered)} tools: {list(discovered.keys())}")

    app = Server(cfg.gateway_name)

    @app.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return [t[1] for t in discovered.values()]

    @app.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict | None
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        if name not in discovered:
            raise ValueError(f"Tool not found: {name}")

        srv_cfg, tool_schema = discovered[name]
        args_dict = arguments or {}
        state.tick()

        # --- Call downstream (inject FASTMCP_QUIET so mock server banner is suppressed) ---
        import os
        srv_cfg_with_quiet = ServerConfig(
            name=srv_cfg.name,
            command=srv_cfg.command,
            args=srv_cfg.args,
            env={**os.environ, "FASTMCP_QUIET": "1", **(srv_cfg.env or {})},
        )

        try:
            raw_output = await _call_downstream(srv_cfg_with_quiet, name, args_dict)
        except Exception as exc:
            raw_output = f"ERROR: {exc}"
            logger.error(f"Downstream call to '{name}' failed: {exc}")

        # --- Document diff for document-mutating tools ---
        content_diff = ""
        _DOC_TOOLS = {"append_to_document", "replace_section"}
        if name in _DOC_TOOLS:
            try:
                new_doc = await _call_downstream(srv_cfg_with_quiet, "get_document", {})
                if new_doc is not None:
                    old_doc = state.update_document(new_doc)
                    content_diff = compute_diff(old_doc, new_doc)
            except Exception:
                pass

        # --- Ledger append ---
        await ledger.append(
            tool=name,
            input_data=args_dict,
            output_data=raw_output,
            session_id=state.session_id,
            actor="agent",
            content_diff=content_diff,
        )

        logger.info(
            f"[call #{state.call_count}] Captured '{name}' -> ledger entry appended"
        )

        out_text = raw_output if raw_output is not None else ""
        return [types.TextContent(type="text", text=out_text)]

    options = InitializationOptions(
        server_name=cfg.gateway_name,
        server_version=cfg.gateway_version,
        capabilities=app.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        )
    )

    # Open ledger, start stdio stream, close ledger on exit
    await ledger.open()
    logger.info(f"Ledger opened at {cfg.ledger_path}")
    try:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                options,
            )
    finally:
        await ledger.close()
        logger.info("Ledger closed.")


def run_gateway(cfg: GatewayConfig | None = None) -> None:
    asyncio.run(run_gateway_async(cfg))
