"""
proof_of_process/signing.py
============================
Ed25519 key management, ledger signing, and signature verification.

Design
------
* We generate a fresh Ed25519 keypair on first run (``keygen``).
* The private key is saved as PEM (PKCS8) on disk — only the gateway holds it.
* The public key is saved as PEM (SubjectPublicKeyInfo) — distribute freely.
* To seal a ledger, we sign ``sha256(serialized_ledger_bytes)`` with the
  private key.  The verifier only needs the public key + signature file.

The cryptography library handles all the hard parts; we just wire it up.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------

def generate_keypair(
    private_key_path: Path | str = "private_key.pem",
    public_key_path: Path | str = "public_key.pem",
) -> tuple[Path, Path]:
    """
    Generate a fresh Ed25519 keypair and write both keys to PEM files.

    Returns (private_key_path, public_key_path).

    .. warning::
        Overwrites existing key files without prompting.
        In production you would protect the private key with a passphrase.
    """
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    priv_path = Path(private_key_path)
    pub_path = Path(public_key_path)

    priv_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    pub_path.write_bytes(
        public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return priv_path, pub_path


# ---------------------------------------------------------------------------
# Load keys from disk
# ---------------------------------------------------------------------------

def load_private_key(path: Path | str) -> Ed25519PrivateKey:
    """Load an Ed25519 private key from a PEM file."""
    raw = Path(path).read_bytes()
    key = serialization.load_pem_private_key(raw, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError(f"Expected Ed25519PrivateKey, got {type(key)}")
    return key


def load_public_key(path: Path | str) -> Ed25519PublicKey:
    """Load an Ed25519 public key from a PEM file."""
    raw = Path(path).read_bytes()
    key = serialization.load_pem_public_key(raw)
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError(f"Expected Ed25519PublicKey, got {type(key)}")
    return key


# ---------------------------------------------------------------------------
# Serialize ledger to canonical bytes
# ---------------------------------------------------------------------------

def serialize_ledger(entries: list[dict]) -> bytes:
    """
    Produce a canonical, deterministic byte representation of the ledger.

    We serialize to JSON with sorted keys — this is what we hash and sign.
    """
    return json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()


def ledger_digest(entries: list[dict]) -> bytes:
    """Return sha256(serialized_ledger)."""
    return hashlib.sha256(serialize_ledger(entries)).digest()


# ---------------------------------------------------------------------------
# Sign / verify
# ---------------------------------------------------------------------------

def sign_ledger(
    entries: list[dict],
    private_key: Ed25519PrivateKey,
    signature_path: Path | str = "ledger.sig",
) -> Path:
    """
    Sign the ledger and write the signature to *signature_path*.

    Ed25519 signs arbitrary data directly (no pre-hashing needed by the
    algorithm), but we pre-hash ourselves so the signature covers a fixed-size
    digest and the ledger can be verified without loading the full DB into RAM.

    Returns the path where the signature was written.
    """
    digest = ledger_digest(entries)
    signature = private_key.sign(digest)

    sig_path = Path(signature_path)
    sig_path.write_bytes(signature)
    return sig_path


def verify_signature(
    entries: list[dict],
    signature: bytes,
    public_key: Ed25519PublicKey,
) -> bool:
    """
    Verify that *signature* was produced by the private key paired with
    *public_key* over *entries*.

    Returns ``True`` if valid, ``False`` if the signature is invalid.
    Raises nothing — verification failures are returned as ``False``.
    """
    digest = ledger_digest(entries)
    try:
        public_key.verify(signature, digest)
        return True
    except InvalidSignature:
        return False
