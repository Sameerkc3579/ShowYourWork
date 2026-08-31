"""
report/generate.py
==================
Standalone CLI wrapper to generate a markdown report from a ledger.
"""

import sys
from pathlib import Path

from proof_of_process.ledger import load_ledger
from proof_of_process.report_generator import save_report

async def generate_report_async(ledger_path: Path, log_path: Path | None = None) -> Path:
    session_log = None
    if log_path and log_path.exists():
        import json
        session_log = []
        for line in log_path.read_text("utf-8").splitlines():
            if line.strip():
                session_log.append(json.loads(line))
                
    entries = await load_ledger(ledger_path)
    return save_report(
        entries,
        output_path="provenance_report.md",
        ledger_path=str(ledger_path),
        session_log=session_log
    )

def main(argv: list[str] | None = None) -> int:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    args = argv if argv is not None else sys.argv[1:]

    if not args:
        print("Usage: python report/generate.py <ledger.db> [session_log.jsonl]")
        return 1

    ledger_path = Path(args[0])
    if not ledger_path.exists():
        print(f"Error: Ledger file not found at {ledger_path}")
        return 1

    log_path = Path(args[1]) if len(args) > 1 else None

    import asyncio
    out_path = asyncio.run(generate_report_async(ledger_path, log_path))
    print(f"✅ Report generated: {out_path.absolute()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
