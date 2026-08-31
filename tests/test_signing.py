"""
tests/test_signing.py
======================
Unit tests for the Ed25519 signing module.

Tests
-----
- Keypair generation writes valid PEM files.
- sign_ledger writes a signature file.
- verify_signature returns True on untampered ledger.
- verify_signature returns False when ledger is mutated.
- verify_signature returns False with wrong key.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proof_of_process.signing import (
    generate_keypair,
    load_private_key,
    load_public_key,
    sign_ledger,
    verify_signature,
)


@pytest.fixture
def keypair(tmp_path: Path):
    priv_path = tmp_path / "private.pem"
    pub_path  = tmp_path / "public.pem"
    generate_keypair(priv_path, pub_path)
    return priv_path, pub_path


_SAMPLE_ENTRIES = [
    {
        "seq": 1,
        "timestamp": "2026-08-29T10:00:00+00:00",
        "session_id": "test",
        "tool": "web_search",
        "actor": "agent",
        "input_hash": "a" * 64,
        "output_hash": "b" * 64,
        "content_diff": "",
        "prev_hash": "0" * 64,
        "entry_hash": "c" * 64,
    }
]


def test_keypair_files_created(keypair, tmp_path: Path):
    priv_path, pub_path = keypair
    assert priv_path.exists()
    assert pub_path.exists()
    assert b"PRIVATE KEY" in priv_path.read_bytes()
    assert b"PUBLIC KEY" in pub_path.read_bytes()


def test_load_keys(keypair):
    priv_path, pub_path = keypair
    priv = load_private_key(priv_path)
    pub  = load_public_key(pub_path)
    # Verify the loaded pub key matches what the private key generates
    from cryptography.hazmat.primitives import serialization
    expected_pub_bytes = priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    assert pub_path.read_bytes() == expected_pub_bytes


def test_sign_and_verify(keypair, tmp_path: Path):
    priv_path, pub_path = keypair
    priv = load_private_key(priv_path)
    pub  = load_public_key(pub_path)

    sig_path = tmp_path / "ledger.sig"
    sign_ledger(_SAMPLE_ENTRIES, priv, sig_path)

    assert sig_path.exists()
    assert len(sig_path.read_bytes()) == 64  # Ed25519 signature is always 64 bytes

    assert verify_signature(_SAMPLE_ENTRIES, sig_path.read_bytes(), pub)


def test_tampered_entries_fail_verification(keypair, tmp_path: Path):
    priv_path, pub_path = keypair
    priv = load_private_key(priv_path)
    pub  = load_public_key(pub_path)

    sig_path = tmp_path / "ledger.sig"
    sign_ledger(_SAMPLE_ENTRIES, priv, sig_path)

    # Tamper with a field
    tampered = [dict(e) for e in _SAMPLE_ENTRIES]
    tampered[0]["tool"] = "TAMPERED"

    assert not verify_signature(tampered, sig_path.read_bytes(), pub)


def test_wrong_key_fails_verification(keypair, tmp_path: Path):
    priv_path, pub_path = keypair
    priv = load_private_key(priv_path)

    sig_path = tmp_path / "ledger.sig"
    sign_ledger(_SAMPLE_ENTRIES, priv, sig_path)

    # Generate a second, different key pair
    priv2_path = tmp_path / "private2.pem"
    pub2_path  = tmp_path / "public2.pem"
    generate_keypair(priv2_path, pub2_path)
    wrong_pub = load_public_key(pub2_path)

    assert not verify_signature(_SAMPLE_ENTRIES, sig_path.read_bytes(), wrong_pub)
