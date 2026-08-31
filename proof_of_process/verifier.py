"""
proof_of_process/verifier.py
=============================
**Standalone** tamper-evident chain + signature verifier.

Design goal
-----------
This script deliberately imports *nothing* from the gateway or any other
project module.  It only needs:
  - Python standard library  (hashlib, json, sqlite3, sys, pathlib)
  - The ``cryptography`` package  (Ed25519 signature verification)

This means a reviewer (a professor, an institution, a third party) can run
it on a received ledger without trusting or installing the full gateway
codebase. They just need Python + ``pip install cryptography``.

Usage
-----
  python proof_of_process/verifier.py <ledger.db> <public_key.pem> <ledger.sig>

Exit codes
----------
  0 — chain intact and signature valid
  1 — chain broken or signature invalid
  2 — usage error / file not found
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

# Ed25519 from cryptography — the ONLY third-party import
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GENESIS_HASH = "0" * 64


# ---------------------------------------------------------------------------
# Pure helpers — no project imports
# ---------------------------------------------------------------------------

def _sha256(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def _payload_json(entry: dict) -> str:
    """Reproduce the canonical payload JSON that was hashed during capture."""
    return json.dumps(
        {
            "timestamp":    entry["timestamp"],
            "session_id":   entry["session_id"],
            "tool":         entry["tool"],
            "actor":        entry["actor"],
            "input_hash":   entry["input_hash"],
            "output_hash":  entry["output_hash"],
            "content_diff": entry["content_diff"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _expected_entry_hash(prev_hash: str, entry: dict) -> str:
    payload = _payload_json(entry)
    return _sha256(prev_hash + payload)


# ---------------------------------------------------------------------------
# Load ledger from SQLite
# ---------------------------------------------------------------------------

def _load_entries(db_path: Path) -> list[dict]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute("SELECT * FROM entries ORDER BY seq ASC")
        return [dict(r) for r in cur.fetchall()]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Chain verification
# ---------------------------------------------------------------------------

def verify_chain(entries: list[dict]) -> tuple[bool, str]:
    """
    Re-walk the hash chain.

    Returns (ok: bool, message: str).
    If ok is False, message says which entry broke the chain.
    """
    if not entries:
        return True, "Ledger is empty (nothing to verify)."

    expected_prev = GENESIS_HASH

    for entry in entries:
        seq  = entry["seq"]
        prev = entry["prev_hash"]
        got  = entry["entry_hash"]
        want = _expected_entry_hash(prev, entry)

        # Check that the stored prev_hash matches what we expect
        if prev != expected_prev:
            return (
                False,
                f"Chain broken at entry #{seq}: "
                f"prev_hash is '{prev[:16]}…' but expected '{expected_prev[:16]}…'.",
            )

        # Check that entry_hash is correct
        if got != want:
            return (
                False,
                f"Entry #{seq} has been tampered with: "
                f"stored entry_hash '{got[:16]}…' ≠ computed '{want[:16]}…'.",
            )

        expected_prev = got

    return True, f"Hash chain OK — all {len(entries)} entries verified."


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def _serialize_ledger(entries: list[dict]) -> bytes:
    return json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()


def _ledger_digest(entries: list[dict]) -> bytes:
    return hashlib.sha256(_serialize_ledger(entries)).digest()


def verify_signature(
    entries: list[dict],
    public_key: Ed25519PublicKey,
    signature: bytes,
) -> tuple[bool, str]:
    """
    Check that *signature* was produced by the private key paired with
    *public_key* over the canonical serialization of *entries*.

    Returns (ok: bool, message: str).
    """
    digest = _ledger_digest(entries)
    try:
        public_key.verify(signature, digest)
        return True, "Signature OK — ledger authenticity confirmed."
    except InvalidSignature:
        return False, "❌ Signature INVALID — the ledger may have been altered or signed with a different key."


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    # Reconfigure stdout to UTF-8 on Windows (CP1252 can't handle emoji).
    # errors='replace' means broken terminals still get readable output.
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    args = argv if argv is not None else sys.argv[1:]

    if len(args) != 3:
        print(
            "Usage: python proof_of_process/verifier.py "
            "<ledger.db> <public_key.pem> <ledger.sig>",
            file=sys.stderr,
        )
        return 2

    db_path, pub_path, sig_path = Path(args[0]), Path(args[1]), Path(args[2])

    for p in (db_path, pub_path, sig_path):
        if not p.exists():
            print(f"[ERROR] File not found: {p}", file=sys.stderr)
            return 2

    # --- Load ---
    print(f"Loading ledger from: {db_path}")
    entries = _load_entries(db_path)
    print(f"  {len(entries)} entries found.")

    raw_pub = pub_path.read_bytes()
    public_key = serialization.load_pem_public_key(raw_pub)
    if not isinstance(public_key, Ed25519PublicKey):
        print("[ERROR] Public key file is not an Ed25519 key.", file=sys.stderr)
        return 2

    signature = sig_path.read_bytes()

    # --- Verify chain ---
    chain_ok, chain_msg = verify_chain(entries)
    _ok   = "✅" if chain_ok else "❌"
    print(f"\n{_ok} Chain verification: {chain_msg}")

    # --- Verify signature ---
    sig_ok, sig_msg = verify_signature(entries, public_key, signature)
    _ok2  = "✅" if sig_ok else "❌"
    print(f"{_ok2} Signature verification: {sig_msg}")

    if chain_ok and sig_ok:
        print("\n✅ PASS — ledger is intact and authentic.")
        return 0
    else:
        print("\n❌ FAIL — verification failed (see details above).")
        return 1


if __name__ == "__main__":
    sys.exit(main())
