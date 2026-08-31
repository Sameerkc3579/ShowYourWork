"""
demo/demo_session.py
====================
End-to-end simulation of a student writing a paper with AI assistance.
Produces a real, cryptographically signed ledger and a rich provenance report.

This script calls the mock servers using the gateway's `_call_downstream`
function. This authentically tests the MCP communication just like the real
gateway does.
"""

import asyncio
import json
import logging
import shutil
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

# Set up paths relative to this script
DEMO_DIR = Path(__file__).parent
DB_PATH = DEMO_DIR / "demo_ledger.db"
LOG_PATH = DEMO_DIR / "session_log.jsonl"
KEYS_DIR = DEMO_DIR / "demo_keys"
PRIV_KEY = KEYS_DIR / "private_key.pem"
PUB_KEY = KEYS_DIR / "public_key.pem"
SIG_PATH = DEMO_DIR / "demo_ledger.sig"
REPORT_PATH = DEMO_DIR / "demo_report.md"

# Configure logging to ignore debug noise
logging.basicConfig(level=logging.WARNING)

from gateway.config import load_config, ServerConfig
from gateway.proxy import _call_downstream
from gateway.session_state import SessionState
from proof_of_process.diff_engine import compute_diff
from proof_of_process.ledger import Ledger
from proof_of_process.signing import sign_ledger


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup_demo_environment():
    """Wipe old demo data and generate fresh keys."""
    print("🧹 Cleaning previous demo state...")
    if DB_PATH.exists(): DB_PATH.unlink()
    if LOG_PATH.exists(): LOG_PATH.unlink()
    if SIG_PATH.exists(): SIG_PATH.unlink()
    if REPORT_PATH.exists(): REPORT_PATH.unlink()
    
    # Ensure document and notes are empty
    if Path("document.md").exists(): Path("document.md").unlink()
    if Path("notes.json").exists(): Path("notes.json").unlink()

    KEYS_DIR.mkdir(exist_ok=True)
    print("🔑 Generating fresh Ed25519 keypair for demo...")
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    PRIV_KEY.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    PUB_KEY.write_bytes(
        public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


# ---------------------------------------------------------------------------
# The Demo Story
# ---------------------------------------------------------------------------

async def run_demo():
    setup_demo_environment()
    
    cfg = load_config()
    ledger = Ledger(str(DB_PATH))
    await ledger.open()
    
    state = SessionState()
    
    # Find the downstream servers we need
    srv_search: ServerConfig | None = None
    srv_notes: ServerConfig | None = None
    srv_doc: ServerConfig | None = None
    
    for srv in cfg.servers:
        if srv.name == "mock_search": srv_search = srv
        elif srv.name == "mock_notes": srv_notes = srv
        elif srv.name == "mock_document": srv_doc = srv
        
        # Inject FASTMCP_QUIET so the banners don't ruin the stdio stream
        if srv.env is None:
            srv.env = {}
        srv.env["FASTMCP_QUIET"] = "1"
        
    assert srv_search and srv_notes and srv_doc, "Mock servers not found in config"

    print(f"\n🚀 Starting demo session: {state.session_id}")
    
    with open(LOG_PATH, "a", encoding="utf-8") as log_file:
        
        async def invoke_tool(name: str, args: dict, actor: str, srv: ServerConfig):
            print(f"\n[{actor}] Calling {name}...")
            state.tick()
            
            result = await _call_downstream(srv, name, args)
            
            # Document diff check
            content_diff = ""
            if name in ("append_to_document", "replace_section"):
                new_doc = await _call_downstream(srv_doc, "get_document", {})
                if new_doc is not None:
                    old_doc = state.update_document(new_doc)
                    content_diff = compute_diff(old_doc, new_doc)
            
            await ledger.append(
                tool=name,
                input_data=args,
                output_data=result,
                session_id=state.session_id,
                actor=actor,
                content_diff=content_diff
            )
            
            log_file.write(json.dumps({
                "seq": state.call_count,
                "tool": name,
                "input": args,
                "output": result,
            }) + "\n")
            
            return result
        
        # 1. AI searches for information
        await invoke_tool("web_search", {"query": "accuracy of AI text detectors"}, "agent", srv_search)
        
        # 2. AI saves a note with the findings
        await invoke_tool(
            "add_note",
            {"content": "AI text detectors have high false positive rates for non-native English speakers (often 12-61%). They struggle with paraphrased text and short passages."},
            "agent", srv_notes
        )
        
        # 3. AI searches for another topic
        await invoke_tool("web_search", {"query": "how do provenance systems solve AI plagiarism"}, "agent", srv_search)
        
        # 4. Student adds a manual note
        await invoke_tool(
            "add_note",
            {"content": "Thesis idea: Instead of guessing if text is AI-generated after the fact, we should track the *process* of how the text was created using cryptography."},
            "user", srv_notes
        )
        
        # 5. AI drafts the introduction
        draft_text = (
            "# Introduction\n"
            "As generative AI becomes ubiquitous in education, traditional plagiarism "
            "detection is failing. Current AI text detectors rely on statistical heuristics "
            "like burstiness and perplexity, but these methods are easily fooled by light "
            "editing and disproportionately flag non-native English speakers.\n"
        )
        await invoke_tool("append_to_document", {"text": draft_text}, "agent", srv_doc)
        
        # 6. AI drafts the proposed solution
        solution_text = (
            "# Proposed Solution\n"
            "To solve this, we propose a provenance-based approach. By cryptographically "
            "logging the research and drafting process—such as web searches, note-taking, "
            "and incremental edits—we can prove the authenticity of the work rather than "
            "relying on post-hoc detection.\n"
        )
        await invoke_tool("append_to_document", {"text": solution_text}, "agent", srv_doc)
        
        # 7. Student manually edits the solution section
        refined_text = (
            "# Proposed Solution\n"
            "To solve this, we propose 'ProcessLedger', a provenance-based system. "
            "By cryptographically logging the research and drafting process—including web "
            "searches, note-taking, and every incremental edit—we can affirmatively prove "
            "human effort rather than relying on flawed post-hoc detection algorithms.\n"
        )
        await invoke_tool(
            "replace_section",
            {"section_title": "Proposed Solution", "new_text": refined_text},
            "user", srv_doc
        )

    await ledger.close()
    print("\n✍️ Session complete. Signing ledger...")
    import proof_of_process.ledger
    entries = await proof_of_process.ledger.load_ledger(DB_PATH)
    private_key = serialization.load_pem_private_key(PRIV_KEY.read_bytes(), password=None)
    sign_ledger(entries, private_key, str(SIG_PATH))
    print(f"✅ Signed! Signature saved to: {SIG_PATH.name}")
    
    print("\n📄 Generating provenance report...")
    from report.generate import generate_report_async
    await generate_report_async(DB_PATH, LOG_PATH)
    
    if Path("provenance_report.md").exists():
        shutil.move("provenance_report.md", str(REPORT_PATH))
        print(f"✅ Report saved to: {REPORT_PATH}")
    
    print("\n🔍 Running standalone verifier...")
    import sys
    import verifier.verify
    verifier.verify.main([str(DB_PATH), str(PUB_KEY), str(SIG_PATH)])
    
    print("\n🎉 Demo completed successfully!")


if __name__ == "__main__":
    asyncio.run(run_demo())
