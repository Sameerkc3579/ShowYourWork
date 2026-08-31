# ShowYourWork — MCP Proof of Process

> **Tamper-evident, cryptographically signed provenance for AI-assisted academic work.**

AI-text detectors (Turnitin, GPTZero) are statistically unreliable and documented to be biased against non-native English speakers. Multiple 2026 papers propose "provenance instead of detection" as the fix — capture and verify the *process*, not guess from the *final text*.

This project builds that fix as a working MCP gateway.

---

## How It Works

```
Student / AI Agent
       │
       ▼
┌─────────────────────────┐
│  ShowYourWork Gateway   │  ← intercepts every tool call
│  (MCP server + client)  │
└──────────┬──────────────┘
           │  hash + diff + chain
           ▼
┌─────────────────────────┐
│   Hash-Chain Ledger     │  ← SQLite, append-only
│   (sha256 chained)      │
└──────────┬──────────────┘
           │  Ed25519 sign
           ▼
┌─────────────────────────┐
│   Verifiable Report     │  ← Markdown timeline
│   + Standalone Verifier │  ← runs with just Python + cryptography
└─────────────────────────┘
```

Every tool call (search, note, document edit) becomes a **ledger entry**. Each entry is hash-chained to the previous one — so any retroactive edit to the history is detectable. The chain is signed with **Ed25519** so its origin is verifiable.

This flips the burden of proof: instead of an algorithm guessing "this looks AI-written," the student can **show their work**, verifiably.

---

## Quick Start

### 1. Install dependencies

```bash
uv sync --extra dev
```

### 2. Generate a keypair

```bash
uv run python main.py keygen
```

Produces `private_key.pem` (keep secret) and `public_key.pem` (share freely).

### 3. Run the automated demo

```bash
uv run python main.py demo
```

This simulates a full "research + write" session (searches, notes, document edits), seals and signs the ledger, generates a report, and verifies the chain — no MCP client needed.

### 4. View the report

```bash
cat provenance_report.md
```

### 5. Verify independently

```bash
uv run python main.py verify ledger.db public_key.pem ledger.sig
```

Or with zero project dependencies (just Python + `pip install cryptography`):

```bash
python proof_of_process/verifier.py ledger.db public_key.pem ledger.sig
```

---

## Using the Gateway (live MCP mode)

Start the gateway proxy:

```bash
uv run python main.py gateway
```

Configure your MCP client (Claude Desktop, any MCP-compatible agent) to connect to this process via stdio. All tool calls are automatically captured.

Configure downstream servers in `gateway_config.toml` (optional — defaults to three mock servers):

```toml
[gateway]
ledger_path = "ledger.db"
session_id  = "my-paper-session"

[[servers]]
name    = "mock_search"
command = "uv"
args    = ["run", "python", "mock_servers/mock_search.py"]

[[servers]]
name    = "mock_notes"
command = "uv"
args    = ["run", "python", "mock_servers/mock_notes.py"]

[[servers]]
name    = "mock_document"
command = "uv"
args    = ["run", "python", "mock_servers/mock_document.py"]
```

---

## Project Structure

```
ShowYourWork/
├── gateway/
│   ├── proxy.py            # Dual-role MCP proxy (server + client)
│   ├── session_state.py    # Per-session state (document content, call count)
│   └── config.py           # Config loader (TOML / env vars / defaults)
├── proof_of_process/
│   ├── ledger.py           # Append-only SQLite hash-chain ledger
│   ├── diff_engine.py      # Paragraph-level document diffs
│   ├── signing.py          # Ed25519 key management + sign/verify
│   ├── report_generator.py # Markdown provenance report
│   └── verifier.py         # Standalone chain + signature verifier
├── mock_servers/
│   ├── mock_search.py      # Simulated web search MCP server
│   ├── mock_notes.py       # File-backed notes MCP server
│   └── mock_document.py    # Markdown document editor MCP server
├── tests/
│   ├── test_ledger.py
│   ├── test_signing.py
│   ├── test_diff_engine.py
│   └── test_gateway.py
├── main.py                 # CLI entry point
└── pyproject.toml
```

---

## Running Tests

```bash
uv run pytest tests/ -v
```

---

## Example Ledger Entry

```json
{
  "seq": 3,
  "timestamp": "2026-08-29T10:15:03Z",
  "session_id": "my-essay-session",
  "tool": "web_search",
  "actor": "agent",
  "input_hash": "sha256:9f2c...",
  "output_hash": "sha256:71ab...",
  "content_diff": "+ Added paragraph: 'False-positive rates up to 62%…'",
  "prev_hash": "sha256:0044...",
  "entry_hash": "sha256:8b91..."
}
```

---

## Why This Is Different From AI-Text Detectors

| AI-Text Detectors | ShowYourWork |
|---|---|
| Classify final text as "AI" or "human" | Record the *process* of writing |
| ~50–70% accuracy, biased vs. non-native speakers | Cryptographically verifiable — math, not statistics |
| Black-box decision | Transparent, auditable timeline |
| Requires trusting the vendor's model | Verifier needs only `hashlib` + `cryptography` |
| Retroactive judgement | Real-time capture |

---

## Verified Tamper Resistance

A raw SQLite UPDATE was used to simulate an attacker bypassing the app entirely and directly editing one ledger row's content_diff field, to prove the hash chain and signature actually catch tampering rather than just claiming to.

### Test 1: Direct row tampering

```text
❌ Chain verification: Entry #3 has been tampered with: stored entry_hash '201beda192a66ddd…' ≠ computed '55531cc758e300ef…'.
❌ Signature verification: ❌ Signature INVALID — the ledger may have been altered or signed with a different key.
❌ FAIL — verification failed (see details above).
```

The tamper was caught because entry_hash is bound to the actual row content, not just to the chain links, and both checks failed for independently correct reasons (local hash mismatch vs. final-state mismatch).

### Test 2: Wrong public key (untampered ledger)

```text
✅ Chain verification: Hash chain OK — all 7 entries verified.
❌ Signature verification: ❌ Signature INVALID — the ledger may have been altered or signed with a different key.
❌ FAIL — verification failed (see details above).
```

This proves the chain check and signature check are independent — chain correctly reports OK since the data wasn't altered, signature correctly reports INVALID due to the wrong key, ruling out the two checks being secretly coupled.

Both tests are reproducible via `uv run python main.py demo`, then tampering with the resulting demo_ledger.db directly via sqlite3, then re-running `uv run python main.py verify` against it.

---

## Risks & Limitations (MVP)

| Risk | Status |
|---|---|
| Student could route only selected calls through the gateway | Known MVP limitation — see writeup; OS-level capture is v2 |
| Self-signed keys | Fine for MVP; production would use institution-issued keys |
| Diff granularity | Paragraph-level (intentional) — readable over precise |

---

## License

MIT
