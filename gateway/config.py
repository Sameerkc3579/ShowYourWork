"""
gateway/config.py
=================
Loads and holds gateway configuration: downstream MCP server definitions,
ledger path, key paths, and session settings.

Priority: environment variables > config TOML > built-in defaults.
"""

from __future__ import annotations

import os
import tomllib
import uuid
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ServerConfig:
    """Configuration for a single downstream MCP server."""
    name: str
    command: str          # e.g. "uv run python mock_servers/mock_search.py"
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class GatewayConfig:
    """Top-level gateway configuration."""
    ledger_path: Path = Path("ledger.db")
    private_key_path: Path = Path("private_key.pem")
    public_key_path: Path = Path("public_key.pem")
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    servers: list[ServerConfig] = field(default_factory=list)

    # Gateway's own stdio transport name shown to the client
    gateway_name: str = "ShowYourWork Provenance Gateway"
    gateway_version: str = "0.1.0"


_DEFAULT_CONFIG_PATH = Path("gateway_config.toml")


def _make_default_config() -> GatewayConfig:
    """Return a fresh GatewayConfig with built-in defaults each time.

    IMPORTANT: this must be a factory, NOT a module-level singleton.
    load_config() mutates the returned object, so sharing a singleton would
    cause mutations from one call to persist into the next call.
    """
    return GatewayConfig(
        servers=[
            ServerConfig(
                name="mock_search",
                command="uv",
                args=["run", "python", "mock_servers/mock_search.py"],
            ),
            ServerConfig(
                name="mock_notes",
                command="uv",
                args=["run", "python", "mock_servers/mock_notes.py"],
            ),
            ServerConfig(
                name="mock_document",
                command="uv",
                args=["run", "python", "mock_servers/mock_document.py"],
            ),
        ]
    )


def load_config(config_path: Path | None = None) -> GatewayConfig:
    """
    Load gateway configuration.

    Resolution order:
    1. TOML file at `config_path` (or `gateway_config.toml` if not given).
    2. Environment variables (``GATEWAY_LEDGER_PATH``, ``GATEWAY_KEY_PATH``).
    3. Built-in defaults (three mock downstream servers).
    """
    cfg = _make_default_config()

    # --- TOML override ---
    path = config_path or _DEFAULT_CONFIG_PATH
    if path.exists():
        with open(path, "rb") as fh:
            data = tomllib.load(fh)

        gateway_section = data.get("gateway", {})
        if "ledger_path" in gateway_section:
            cfg.ledger_path = Path(gateway_section["ledger_path"])
        if "private_key_path" in gateway_section:
            cfg.private_key_path = Path(gateway_section["private_key_path"])
        if "public_key_path" in gateway_section:
            cfg.public_key_path = Path(gateway_section["public_key_path"])
        if "session_id" in gateway_section:
            cfg.session_id = gateway_section["session_id"]

        raw_servers = data.get("servers", [])
        if raw_servers:
            cfg.servers = [
                ServerConfig(
                    name=s["name"],
                    command=s["command"],
                    args=s.get("args", []),
                    env=s.get("env", {}),
                )
                for s in raw_servers
            ]

    # --- Env var overrides ---
    if lp := os.environ.get("GATEWAY_LEDGER_PATH"):
        cfg.ledger_path = Path(lp)
    if kp := os.environ.get("GATEWAY_PRIVATE_KEY_PATH"):
        cfg.private_key_path = Path(kp)

    return cfg
