import argparse
import asyncio
import os
import sys
from pathlib import Path


def _banner() -> None:
    print(
        "+--------------------------------------------------------------------------+\n"
        "| ShowYourWork — MCP Proof of Process                                      |\n"
        "| Tamper-evident, cryptographically signed provenance for AI-assisted work |\n"
        "+--------------------------------------------------------------------------+"
    )


# ---------------------------------------------------------------------------
# Command Implementations
# ---------------------------------------------------------------------------

def cmd_keygen(priv_path: str, pub_path: str) -> None:
    """Generate Ed25519 keypair."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    _banner()
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    Path(priv_path).write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    Path(pub_path).write_bytes(
        public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    print(f"✅ Generated new Ed25519 keypair.")
    print(f"   Private key: {priv_path}")
    print(f"   Public key:  {pub_path}")


def cmd_gateway() -> None:
    """Run the proxy gateway."""
    from gateway.proxy import run_gateway

    run_gateway()


def cmd_report(ledger_path: str, out_path: str, pub_path: str, sig_path: str) -> None:
    """Generate a Markdown report."""
    from proof_of_process.ledger import load_ledger
    from proof_of_process.report_generator import save_report

    async def _run() -> None:
        _banner()
        entries = await load_ledger(ledger_path)
        if not entries:
            print("Ledger is empty.")
            return

        out = save_report(
            entries,
            output_path=out_path,
            public_key_path=pub_path,
            signature_path=sig_path,
            ledger_path=ledger_path,
        )
        print(f"✅ Report written → {out}")
        print(f"   {len(entries)} entries, covering "
              f"{entries[0]['timestamp'][:10]} — {entries[-1]['timestamp'][:10]}")

        # Tally
        counts = {}
        for e in entries:
            counts[e['tool']] = counts.get(e['tool'], 0) + 1
        print("\n      Tool Call Summary       ")
        print("+----------------------------+")
        print("| Tool               | Count |")
        print("|--------------------+-------|")
        for tool, count in counts.items():
            print(f"| {tool:<18} | {count:>5} |")
        print("+----------------------------+")

    asyncio.run(_run())


def cmd_verify(db_path: str, pub_path: str, sig_path: str) -> None:
    """Verify ledger via the standalone script logic."""
    from proof_of_process.verifier import main as verifier_main

    _banner()
    exit_code = verifier_main([db_path, pub_path, sig_path])
    sys.exit(exit_code)


def cmd_demo() -> None:
    """Run an automated demo pilot session."""
    import subprocess
    import sys
    from pathlib import Path
    import os
    
    _banner()
    print("Running end-to-end demo script...\n")
    
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    demo_script = Path(__file__).parent / "demo" / "demo_session.py"
    
    try:
        subprocess.run(
            [sys.executable, str(demo_script)], 
            env=env,
            check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Demo failed with exit code {e.returncode}")
        sys.exit(e.returncode)


# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    import sys
    
    # Enable UTF-8 for console output to support emoji (✅/❌) on Windows CP1252
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        prog="showyourwork",
        description="ShowYourWork — MCP Proof of Process gateway",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # keygen
    p_keygen = sub.add_parser("keygen", help="Generate Ed25519 keypair")
    p_keygen.add_argument("--private", default="private_key.pem")
    p_keygen.add_argument("--public",  default="public_key.pem")

    # gateway
    sub.add_parser("gateway", help="Start the provenance gateway proxy (stdio)")

    # report
    p_report = sub.add_parser("report", help="Generate provenance Markdown report")
    p_report.add_argument("ledger",    nargs="?", default="ledger.db")
    p_report.add_argument("--output",  default="provenance_report.md")
    p_report.add_argument("--pubkey",  default="public_key.pem")
    p_report.add_argument("--sig",     default="ledger.sig")

    # verify
    p_verify = sub.add_parser("verify", help="Verify chain + signature")
    p_verify.add_argument("ledger",    nargs="?", default="ledger.db")
    p_verify.add_argument("pubkey",    nargs="?", default="public_key.pem")
    p_verify.add_argument("signature", nargs="?", default="ledger.sig")

    # demo
    sub.add_parser("demo", help="Run an automated demo session")

    args = parser.parse_args()

    if args.command == "keygen":
        cmd_keygen(args.private, args.public)
    elif args.command == "gateway":
        cmd_gateway()
    elif args.command == "report":
        cmd_report(args.ledger, args.output, args.pubkey, args.sig)
    elif args.command == "verify":
        cmd_verify(args.ledger, args.pubkey, args.signature)
    elif args.command == "demo":
        cmd_demo()


if __name__ == "__main__":
    main()
