import streamlit as st
import json
import os
import datetime
from draft_machine import draft_reply_with_metadata, SAMPLE_THREADS
from context_builder import format_thread_history

st.set_page_config(page_title="AI Email Approval Gate", layout="wide")

# Styling
st.markdown("""
<style>
    .stApp {
        background-color: #1a1a2e;
        color: #ffffff;
    }
    .thread-box {
        background-color: #16213e;
        padding: 15px;
        border-radius: 5px;
        margin-bottom: 10px;
        border-left: 4px solid #0f3460;
    }
    .draft-box {
        background-color: #0f3460;
        padding: 20px;
        border-radius: 5px;
        font-size: 16px;
        line-height: 1.5;
        margin-bottom: 20px;
    }
    .status-approved {
        color: #4CAF50;
        font-weight: bold;
        padding: 10px;
        background-color: rgba(76, 175, 80, 0.1);
        border-radius: 5px;
        margin-bottom: 20px;
    }
    .status-rejected {
        color: #f44336;
        font-weight: bold;
        padding: 10px;
        background-color: rgba(244, 67, 54, 0.1);
        border-radius: 5px;
        margin-bottom: 20px;
    }
    /* Force text area to be readable */
    div.stTextArea > div > div > textarea {
        background-color: #16213e !important;
        color: #ffffff !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("🛡️ AI Email Approval Gate")
st.caption("NEVER auto-send without human approval. This is the guardrail that makes AI assistants safe for real use.")

# Initialize session state
if "draft_text" not in st.session_state:
    st.session_state.draft_text = None
if "draft_metadata" not in st.session_state:
    st.session_state.draft_metadata = None
if "status" not in st.session_state:
    st.session_state.status = "none" # none, approved, editing, rejected
if "gen_count" not in st.session_state:
    st.session_state.gen_count = 0

# --- API KEY MANAGEMENT ---
api_key = None
try:
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    # Streamlit raises StreamlitSecretNotFoundError if secrets.toml doesn't exist
    pass

if not api_key and "GEMINI_API_KEY" in os.environ:
    api_key = os.environ["GEMINI_API_KEY"]

if not api_key:
    st.sidebar.warning("API Key not found in secrets or environment.")
    api_key = st.sidebar.text_input("Enter your Gemini API Key:", type="password")
    if api_key:
        os.environ["GEMINI_API_KEY"] = api_key

# --- SIDEBAR: THREAD SELECTION ---
st.sidebar.header("Thread Selection")
thread_options = {f"Sample {i+1}: {t['subject']}": t for i, t in enumerate(SAMPLE_THREADS)}
selected_option = st.sidebar.selectbox("Choose a sample thread:", list(thread_options.keys()))

st.sidebar.markdown("---")
st.sidebar.subheader("Or Paste Custom Thread (JSON)")
custom_json = st.sidebar.text_area("Paste thread JSON here:", height=200)

current_thread = None
if custom_json.strip():
    try:
        current_thread = json.loads(custom_json)
    except json.JSONDecodeError:
        st.sidebar.error("Invalid JSON format.")
else:
    current_thread = thread_options[selected_option]

if st.sidebar.button("Generate Draft", type="primary", use_container_width=True):
    if not api_key:
        st.sidebar.error("Please provide an API Key first.")
    elif current_thread:
        with st.spinner("Ghostwriter is drafting..."):
            try:
                result = draft_reply_with_metadata(current_thread)
                st.session_state.draft_text = result["draft"]
                st.session_state.draft_metadata = result
                st.session_state.status = "none"
                st.session_state.gen_count += 1
            except Exception as e:
                st.sidebar.error(f"Error: {e}")

# --- MAIN LAYOUT ---
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("Email Thread History")
    if current_thread:
        st.markdown(f"**Subject:** {current_thread.get('subject', 'No Subject')}")
        for msg in current_thread.get("messages", []):
            st.markdown(f"""
            <div class="thread-box">
                <b>From:</b> {msg.get('from', 'Unknown')} <br>
                <small><b>Date:</b> {msg.get('date', 'Unknown')}</small>
                <p style="margin-top: 10px; white-space: pre-wrap;">{msg.get('body', '')}</p>
            </div>
            """, unsafe_allow_html=True)

def save_approval(draft_text, metadata):
    approval_record = {
        "timestamp": datetime.datetime.now().isoformat(),
        "subject": metadata.get("subject", ""),
        "reply_to": metadata.get("reply_to", ""),
        "approved_text": draft_text,
        "model": metadata.get("model", "")
    }
    
    approved_file = "approved_drafts.json"
    drafts = []
    if os.path.exists(approved_file):
        try:
            with open(approved_file, "r") as f:
                drafts = json.load(f)
        except:
            pass
    drafts.append(approval_record)
    with open(approved_file, "w") as f:
        json.dump(drafts, f, indent=4)

with col2:
    st.subheader("AI-Generated Draft")
    
    if st.session_state.draft_text:
        
        # Display status
        if st.session_state.status == "approved":
            st.markdown('<div class="status-approved">✅ Draft Approved and Saved to ready queue!</div>', unsafe_allow_html=True)
        elif st.session_state.status == "rejected":
            st.markdown('<div class="status-rejected">❌ Draft Rejected. Please regenerate or write manually.</div>', unsafe_allow_html=True)
            
        # Display Draft
        if st.session_state.status == "editing":
            edited_text = st.text_area("Edit Draft", value=st.session_state.draft_text, height=200)
            if st.button("Approve Edited Version", type="primary"):
                st.session_state.draft_text = edited_text
                st.session_state.status = "approved"
                save_approval(st.session_state.draft_text, st.session_state.draft_metadata)
                st.rerun()
                
        else:
            st.markdown(f'<div class="draft-box"><pre style="white-space: pre-wrap; font-family: inherit;">{st.session_state.draft_text}</pre></div>', unsafe_allow_html=True)
            
            # Action Buttons
            if st.session_state.status == "none":
                bcol1, bcol2, bcol3 = st.columns(3)
                
                with bcol1:
                    if st.button("✅ APPROVE", use_container_width=True):
                        st.session_state.status = "approved"
                        save_approval(st.session_state.draft_text, st.session_state.draft_metadata)
                        st.rerun()
                        
                with bcol2:
                    if st.button("✏️ EDIT", use_container_width=True):
                        st.session_state.status = "editing"
                        st.rerun()
                        
                with bcol3:
                    if st.button("❌ REJECT", use_container_width=True):
                        st.session_state.status = "rejected"
                        st.rerun()
    else:
        st.info("👈 Select a thread and click 'Generate Draft' to see the magic.")
