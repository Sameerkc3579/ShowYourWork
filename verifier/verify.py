"""
verifier/verify.py
==================
**Standalone** tamper-evident chain + signature verifier for ProcessLedger.

Design goals
------------
* Zero imports from the project codebase. Only needs:
    - Python standard library  (hashlib, json, sqlite3, sys, pathlib)
    - The ``cryptography`` package  (Ed25519 public-key verification)

* A reviewer (professor, institution, third party) can run this on a received
  ledger WITHOUT installing or trusting the full gateway codebase. They only
  need Python and ``pip install cryptography``.

* The algorithm here is intentionally a direct re-implementation of the
  hashing logic in proof_of_process/ledger.py, NOT an import of it.
  This makes it trustworthy independent of whether the gateway itself was
  compromised.

Usage
-----
  python verifier/verify.py <ledger.db> <public_key.pem> <ledger.sig>

  # Example:
  python verifier/verify.py demo/demo_ledger.db demo/demo_keys/public_key.pem demo/demo_ledger.sig

Exit codes
----------
  0 — chain intact AND signature valid
  1 — chain broken OR signature invalid
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
# Constants — must match the ledger writer exactly
# ---------------------------------------------------------------------------

GENESIS_HASH = "0" * 64


# ---------------------------------------------------------------------------
# Pure helpers — no project imports, easy to audit
# ---------------------------------------------------------------------------

def _sha256(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def _payload_json(entry: dict) -> str:
    """
    Reproduce the canonical payload JSON that was hashed when the entry was
    written.  Field order is alphabetical (sort_keys=True) and no spaces in
    separators — this MUST match proof_of_process/ledger.py::_payload_json().
    """
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
    Re-walk the entire hash chain.

    Returns (ok: bool, message: str).
    If ok is False, message pinpoints which entry broke the chain.
    """
    if not entries:
        return True, "Ledger is empty (nothing to verify)."

    expected_prev = GENESIS_HASH

    for entry in entries:
        seq  = entry["seq"]
        prev = entry["prev_hash"]
        got  = entry["entry_hash"]
        want = _expected_entry_hash(prev, entry)

        # Check that stored prev_hash matches what we expect
        if prev != expected_prev:
            return (
                False,
                f"Chain broken at entry #{seq}: "
                f"prev_hash is '{prev[:16]}...' but expected '{expected_prev[:16]}...'.",
            )

        # Check that entry_hash is correct
        if got != want:
            return (
                False,
                f"Entry #{seq} has been tampered with: "
                f"stored entry_hash '{got[:16]}...' != computed '{want[:16]}...'.",
            )

        expected_prev = got

    return True, f"Hash chain OK — all {len(entries)} entries verified."


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def _serialize_ledger(entries: list[dict]) -> bytes:
    """
    Canonical, deterministic serialization of the full ledger.
    MUST match proof_of_process/signing.py::serialize_ledger().
    """
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
        return False, "Signature INVALID — ledger may have been altered or signed with a different key."


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    # Reconfigure stdout to UTF-8 on Windows (CP1252 can't handle ✅/❌).
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    args = argv if argv is not None else sys.argv[1:]

    if len(args) != 3:
        print(
            "Usage: python verifier/verify.py "
            "<ledger.db> <public_key.pem> <ledger.sig>",
            file=sys.stderr,
        )
        print("", file=sys.stderr)
        print("Example:", file=sys.stderr)
        print("  python verifier/verify.py demo/demo_ledger.db demo/demo_keys/public_key.pem demo/demo_ledger.sig", file=sys.stderr)
        return 2

    db_path, pub_path, sig_path = Path(args[0]), Path(args[1]), Path(args[2])

    for p in (db_path, pub_path, sig_path):
        if not p.exists():
            print(f"[ERROR] File not found: {p}", file=sys.stderr)
            return 2

    print("=" * 60)
    print("  ProcessLedger — Standalone Chain Verifier")
    print("=" * 60)
    print(f"\nLedger:     {db_path}")
    print(f"Public key: {pub_path}")
    print(f"Signature:  {sig_path}")

    # --- Load ---
    print(f"\nLoading ledger...")
    entries = _load_entries(db_path)
    print(f"  {len(entries)} entries found.")

    raw_pub = pub_path.read_bytes()
    public_key = serialization.load_pem_public_key(raw_pub)
    if not isinstance(public_key, Ed25519PublicKey):
        print("[ERROR] Public key file is not an Ed25519 key.", file=sys.stderr)
        return 2

    signature = sig_path.read_bytes()

    # --- Verify chain ---
    print("\n--- Hash Chain Verification ---")
    chain_ok, chain_msg = verify_chain(entries)
    _c = "✅" if chain_ok else "❌"
    print(f"{_c}  {chain_msg}")

    if not chain_ok:
        print("\n  Tip: a broken chain means at least one entry was added,")
        print("  removed, or edited after the session was signed.")

    # --- Verify signature ---
    print("\n--- Signature Verification ---")
    sig_ok, sig_msg = verify_signature(entries, public_key, signature)
    _s = "✅" if sig_ok else "❌"
    print(f"{_s}  {sig_msg}")

    # --- Overall verdict ---
    print("\n" + "=" * 60)
    if chain_ok and sig_ok:
        print("✅  PASS — ledger is intact and authentic.")
        print("=" * 60)
        return 0
    else:
        print("❌  FAIL — verification failed (see details above).")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
