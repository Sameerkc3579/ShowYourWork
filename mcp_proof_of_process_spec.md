# MCP Project Spec: Proof of Process
### MCP-Native Provenance for AI-Assisted Work

A project idea built around a genuine gap: academics have proposed "provenance instead of detection" as the fix for unreliable AI-text detectors, but nobody has built it — and MCP is a natural capture layer for it. Verified against current research/products as of Aug 2026 — re-check yourself before you start, this space moves fast.

---

## Table of Contents

1. [The Problem](#problem)
2. [Core Concept](#concept)
3. [System Architecture](#architecture)
4. [Example Ledger Entry](#ledger-entry)
5. [Execution Plan](#execution-plan)
6. [What "Done" Looks Like](#done)
7. [Risks & Mitigations](#risks)
8. [Repo Structure](#repo-structure)
9. [Appendix: Getting Started](#appendix)

---

<a name="problem"></a>
## 1. The Problem

AI-text detectors (Turnitin, GPTZero) are statistically unreliable and documented to be biased against non-native English speakers and international students. Multiple 2026 papers propose "provenance instead of detection" as the fix — capture and verify the *process*, not guess from the *final text*. That fix has been proposed academically. I did not find it actually built as a tool, and specifically not built on top of MCP as the natural capture layer.

---

<a name="concept"></a>
## 2. Core Concept

If a student's research and writing tools (search, notes, drafting, editing) are all mediated through one MCP gateway, that gateway is perfectly positioned to produce a **tamper-evident, cryptographically signed log** of the entire process:

- Every tool call (search query, note taken, paragraph drafted or edited) becomes a **ledger entry**.
- Each entry is **hash-chained** to the previous one (like a minimal blockchain, no need for anything fancier) — so any retroactive edit to the history is detectable.
- The chain is **signed** (Ed25519) so its origin is verifiable.
- A **report generator** turns the raw ledger into something a professor or reviewer can actually read: a timeline of what was searched, what was AI-drafted vs. self-typed, and in what order.

This flips the burden of proof: instead of an algorithm guessing "this looks AI-written," the student can *show their work*, verifiably.

---

<a name="architecture"></a>
## 3. System Architecture

```
┌───────────────┐        ┌────────────────────────────────────────────┐
│    Student     │ ──────▶ │              PROVENANCE GATEWAY               │
│ (research/write)         │                                                │
└───────────────┘        │  ┌────────────────┐   ┌─────────────────┐     │
                          │  │ Capture Layer  │──▶│   Diff Engine    │     │
                          │  │ (tool-call log)│   │ (content deltas) │     │
                          │  └───────┬────────┘   └────────┬────────┘     │
                          │          │                      │              │
                          │          ▼                      ▼              │
                          │  ┌──────────────────────────────────────┐    │
                          │  │           Hash-Chain Ledger            │    │
                          │  │  (append-only; each entry hashes the   │    │
                          │  │        previous entry + payload)       │    │
                          │  └────────────────────┬─────────────────┘    │
                          │                        ▼                       │
                          │  ┌──────────────────────────────────────┐    │
                          │  │      Signing Service (Ed25519)         │    │
                          │  └────────────────────┬─────────────────┘    │
                          └───────────────────────┼──────────────────────┘
                                                    ▼
                          ┌────────────────────────────────────────────┐
                          │     Verifiable Report Generator / Viewer      │
                          │  (human-readable timeline + a standalone       │
                          │   verifier script anyone can run, no trust     │
                          │   in you required — just the math)            │
                          └────────────────────────────────────────────┘
```

**Downstream MCP servers wrapped:** a web-search server, a notes server (can be a simple file-backed MCP server you write), and a document-edit server (the document being written itself, tracked as content diffs on every save).

**Components**

| Component | Responsibility | Suggested tech |
|---|---|---|
| Capture Layer | Intercepts every tool call and its input/output before forwarding | Python proxy built on the official MCP SDK (or FastMCP), acting as both server (to the agent) and client (to real tools) |
| Diff Engine | Computes content deltas between document versions | Python `difflib`, or `diff-match-patch` for finer-grained diffs |
| Hash-Chain Ledger | Append-only, tamper-evident record | SQLite table or JSON-lines file; each row stores `sha256(prev_hash + payload)` |
| Signing Service | Signs each entry (or batches) so authorship is verifiable | Python `cryptography` library, Ed25519 keys |
| Report Generator | Renders the ledger into a human-readable timeline | Python script → Markdown/HTML report; optional Next.js viewer using your existing React skills |
| Verifier | Standalone script that re-walks the chain and checks hashes + signatures | Deliberately kept separate from the gateway so it doesn't need to trust your app code — just the math |

---

<a name="ledger-entry"></a>
## 4. Example Ledger Entry (JSON)

```json
{
  "seq": 42,
  "timestamp": "2026-08-29T10:15:03Z",
  "tool": "web_search",
  "input_hash": "sha256:9f2c...",
  "output_hash": "sha256:71ab...",
  "content_diff": "+3 sentences added to Section 2, paraphrased from search result",
  "actor": "agent",
  "prev_hash": "sha256:0044...",
  "entry_hash": "sha256:8b91..."
}
```

---

<a name="execution-plan"></a>
## 5. Execution Plan

1. **Build the gateway core.** A proxy (FastAPI or the MCP SDK's own server primitives) that sits between an MCP client and real MCP servers, routing calls through in both directions. This is the foundation everything else attaches to.
2. **Wrap 2–3 real tools**: a web-search MCP server, a simple notes MCP server (you write this — a thin wrapper around a local file), and a document-edit MCP server (wrap your actual editor, or a plain markdown file you edit through the gateway).
3. **Implement the capture layer.** Every call in/out gets hashed and logged before forwarding, with content diffs attached where relevant.
4. **Implement the hash chain.** Each entry stores the hash of the previous entry plus its own payload hash — a few dozen lines of code, no external dependency needed beyond `hashlib`.
5. **Add signing.** Generate an Ed25519 keypair, sign each entry (or sign the whole chain's final hash for simplicity in the MVP).
6. **Build the report generator.** Turn the raw ledger into a readable timeline: what was searched, what was AI-drafted, what was self-typed, in order.
7. **Build the standalone verifier.** A separate script that takes the ledger + signature and independently confirms nothing was altered — this is the piece that makes the whole thing trustworthy rather than "trust me."
8. **Pilot it on your own work.** Use it while writing your next paper or assignment and generate a real report — this becomes your demo.

---

<a name="done"></a>
## 6. What "Done" Looks Like for a Resume-Ready MVP

- A working gateway that captures a real research/writing session end-to-end.
- A verifiable hash chain + signature that a professor (or anyone) can independently check with the standalone verifier — no trust in your server required.
- A generated report that's actually readable by a non-technical person.
- A short writeup explaining why this is structurally different from AI-text detectors (verification vs. classification).

---

<a name="risks"></a>
## 7. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| "Who do I trust to run the honest gateway?" (a student could route only the parts they want logged) | Be upfront in your writeup: MVP demonstrates the mechanism, not a tamper-proof institutional deployment — that would need OS-level capture or institutional infrastructure, which is a v2 problem, not a blocker for a portfolio piece |
| Key management / trust root at scale | Self-signed keys are fine for the MVP to prove the mechanism works; note in your writeup what a production trust root (e.g., institution-issued keys) would look like |
| Diffing gets noisy on heavily-edited documents | Cap the diff granularity (paragraph-level, not character-level) for readability in the report |

---

<a name="repo-structure"></a>
## 8. Repo Structure

```
mcp-proof-of-process/
├── gateway/
│   ├── proxy.py            # MCP server-facing + client-facing proxy core
│   ├── session_state.py    # per-session state store
│   └── config.py           # config loader
├── proof_of_process/
│   ├── diff_engine.py
│   ├── ledger.py
│   ├── signing.py
│   ├── report_generator.py
│   └── verifier.py
├── mock_servers/
│   ├── mock_search.py
│   ├── mock_notes.py
│   └── mock_document.py
├── tests/
└── README.md
```

---

<a name="appendix"></a>
## 9. Appendix: Getting Started

- Use the official MCP Python SDK (or FastMCP) for both the server-facing and client-facing sides of the gateway — don't hand-roll the JSON-RPC layer.
- Python's built-in `hashlib` and the `cryptography` package cover everything this project needs for hashing and signing — no exotic dependencies required.
- Keep the mock downstream servers (search, notes, document) dead simple — their only job is to give the gateway something real to mediate, not to be interesting themselves.
- Re-verify novelty with a fresh search right before you start building in earnest — this space moves in weeks, not years.
