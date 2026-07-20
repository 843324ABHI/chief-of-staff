from groq.types.chat import chat_completion_assistant_message_param
from groq.types.chat import chat_completion_assistant_message_param
from groq.types.chat import chat_completion_assistant_message_param
from asyncio import threads
import streamlit as st
import json
import time
import os
import datetime
import html
from task_logger import log_action, get_action_log

# --- GCP Auth Files Setup ---
if not os.path.exists("credentials.json") and "gcp_credentials" in st.secrets:
    with open("credentials.json", "w") as f:
        f.write(st.secrets["gcp_credentials"])

if not os.path.exists("token.json") and "gcp_token" in st.secrets:
    with open("token.json", "w") as f:
        f.write(st.secrets["gcp_token"])
try:
    import engine  # type: ignore
except ImportError:
    engine = None

@st.cache_resource
def _get_calendar_engine():
    import calendar_engine
    return calendar_engine

try:
    import triage  # type: ignore
except ImportError:
    triage = None

try:
    import draft_machine
    import importlib
    importlib.reload(draft_machine)
except ImportError:
    draft_machine = None

# 1. Page config
st.set_page_config(page_title="The Draft Desk", page_icon="✍️", layout="wide")

# 3. Session state initialization
if 'threads' not in st.session_state:
    st.session_state['threads'] = []
if 'triaged' not in st.session_state:
    st.session_state['triaged'] = {}
if 'drafts_dict' not in st.session_state:
    st.session_state['drafts_dict'] = {}
if 'approved_dict' not in st.session_state:
    st.session_state['approved_dict'] = {}
if 'rejected_set' not in st.session_state:
    st.session_state['rejected_set'] = set()
if 'current_phase' not in st.session_state:
    st.session_state['current_phase'] = "Inbox & Triage"
if 'booked' not in st.session_state:
    st.session_state['booked'] = {}
if 'pipeline_running' not in st.session_state:
    st.session_state['pipeline_running'] = False
if 'pipeline_log' not in st.session_state:
    st.session_state['pipeline_log'] = []

# 2. Sidebar
st.sidebar.title("The Draft Desk")
source = st.sidebar.radio("Source", ["Gmail via engine.py", "Sample threads for demo"], index=1)

st.sidebar.markdown("---")

if st.sidebar.button("Run Full Pipeline", type="primary", use_container_width=True):
    st.session_state.pipeline_running = True
    st.rerun()
st.sidebar.caption("Fetches, triages, and drafts -- stops at Approval Gate.")

llm_provider = "Groq"

# --- API KEY MANAGEMENT ---
api_key = None
try:
    if "GROQ_API_KEY" in st.secrets:
        api_key = st.secrets["GROQ_API_KEY"]
    elif "Groq_API_KEY" in st.secrets:
        api_key = st.secrets["Groq_API_KEY"]
except Exception:
    pass

if not api_key:
    api_key = os.environ.get("GROQ_API_KEY") or os.environ.get("Groq_API_KEY")

if api_key:
    os.environ["GROQ_API_KEY"] = api_key

st.sidebar.markdown("---")
st.sidebar.subheader("Workflow Navigation")
if st.sidebar.button("Inbox & Triage"):
    st.session_state['current_phase'] = "Inbox & Triage"
if st.sidebar.button("Draft Generation"):
    st.session_state['current_phase'] = "Draft Generation"
if st.sidebar.button("Approval Gate"):
    st.session_state['current_phase'] = "Approval Gate"
if st.sidebar.button("Export Proof"):
    st.session_state['current_phase'] = "Export Proof"

def fetch_threads_via_engine():
    formatted_threads = []
    if engine and hasattr(engine, 'fetch_threads'):
        raw_threads = engine.fetch_threads()
        for t in raw_threads:
            formatted_threads.append({
                "id": t.get("thread_id"),
                "subject": t.get("subject"),
                "messages": [{
                    "from": t.get("sender"),
                    "date": t.get("date"),
                    "body": t.get("snippet"),
                    "message_id": t.get("message_id")
                }]
            })
    return formatted_threads

def load_sample_threads():
    try:
        with open("sample_threads.json", "r") as f:
            return json.load(f)
    except Exception:
        return []

def triage_threads(threads):
    if triage and hasattr(triage, 'triage_inbox'):
        triaged_data = triage.triage_inbox(threads)
    else:
        triaged_data = {
            "urgent": [t for t in threads if "urgent" in t.get("subject", "").lower()],
            "needs-reply": [t for t in threads if "feedback" in t.get("subject", "").lower() or "vendor" in t.get("subject", "").lower() or "review" in t.get("subject", "").lower()],
            "fyi": [t for t in threads if "notes" in t.get("subject", "").lower()],
            "ignore": []
        }
    st.session_state['triaged'] = triaged_data
    return triaged_data

def _get_draft_reply(thread):
    if not draft_machine:
        raise Exception("draft_machine module not found.")
    provider = globals().get('llm_provider', 'Groq')
    return draft_machine.draft_reply(thread, provider=provider)

def run_full_pipeline():
    log = []
    log.append("Starting full pipeline run...")
    try:
        source = st.session_state.get('source', "Sample threads for demo")
        
        if source == "Gmail via engine.py":
            log.append("Fetching threads via engine...")
            threads = fetch_threads_via_engine()
        else:
            log.append("Loading sample threads...")
            threads = load_sample_threads()
                
        st.session_state['threads'] = threads
        
        log.append("Triaging threads...")
        triage_threads(threads)
            
        log.append("Resetting downstream session state...")
        st.session_state['drafts'] = {}
        st.session_state['drafts_dict'] = {}
        st.session_state['approved_dict'] = {}
        st.session_state['rejected_set'] = set()
        st.session_state['sent'] = set()
        st.session_state['booked'] = {}
        
        triaged = st.session_state.get('triaged', {})
        urgent = triaged.get("urgent", [])
        needs_reply = triaged.get("needs-reply", [])
        if not needs_reply and "needs_reply" in triaged:
            needs_reply = triaged.get("needs_reply", [])
            
        actionable_threads = urgent + needs_reply
        log.append(f"Found {len(actionable_threads)} actionable threads.")
        
        for thread in actionable_threads:
            thread_id = thread.get('id', 'Unknown')
            try:
                log.append(f"Drafting reply for thread {thread_id}...")
                draft = _get_draft_reply(thread)
                st.session_state['drafts'][thread_id] = draft
                st.session_state['drafts_dict'][thread_id] = draft
            except Exception as e:
                log.append(f"Error drafting reply for thread {thread_id}: {e}")
                
        st.session_state['current_phase'] = "Approval Gate"
        log.append("Pipeline complete. Moving to Approval Gate.")
        
    except Exception as e:
        log.append(f"Pipeline error: {e}")
        
    return log

def _render_pipeline_execution():
    log = []
    log.append("Starting live pipeline execution...")
    
    with st.status("Running full pipeline...", expanded=True) as status:
        try:
            source = st.session_state.get('source', "Sample threads for demo")
            
            # Step 1: Fetch
            status.update(label="Fetching threads...")
            try:
                if source == "Gmail via engine.py":
                    log.append("Fetching threads via engine...")
                    threads = fetch_threads_via_engine()
                else:
                    log.append("Loading sample threads...")
                    threads = load_sample_threads()
                
                st.session_state['threads'] = threads
                st.write("✅ Threads fetched")
            except Exception as e:
                log.append(f"Fetch failed: {e}")
                st.write(f"❌ Fetch failed: {e}")
                status.update(state="error")
                return

            # Step 2: Triage
            status.update(label="Triaging threads...")
            try:
                log.append("Triaging threads...")
                triage_threads(threads)
                
                log.append("Resetting downstream session state...")
                st.session_state['drafts'] = {}
                st.session_state['drafts_dict'] = {}
                st.session_state['approved_dict'] = {}
                st.session_state['rejected_set'] = set()
                st.session_state['sent'] = set()
                st.session_state['booked'] = {}
                st.write("✅ Threads triaged")
            except Exception as e:
                log.append(f"Triage failed: {e}")
                st.write(f"❌ Triage failed: {e}")
                status.update(state="error")
                return
            
            # Step 3: Draft Loop
            status.update(label="Drafting replies...")
            triaged = st.session_state.get('triaged', {})
            urgent = triaged.get("urgent", [])
            needs_reply = triaged.get("needs-reply", [])
            if not needs_reply and "needs_reply" in triaged:
                needs_reply = triaged.get("needs_reply", [])
                
            actionable_threads = urgent + needs_reply
            log.append(f"Found {len(actionable_threads)} actionable threads.")
            
            for thread in actionable_threads:
                thread_id = thread.get('id', 'Unknown')
                subject = thread.get('subject', 'No Subject')
                try:
                    log.append(f"Drafting reply for thread {thread_id}...")
                    draft = _get_draft_reply(thread)
                    st.session_state['drafts'][thread_id] = draft
                    st.session_state['drafts_dict'][thread_id] = draft
                    st.write(f"✅ Draft generated for: {subject}")
                except Exception as e:
                    log.append(f"Error drafting reply for thread {thread_id}: {e}")
                    st.write(f"❌ Draft failed for: {subject} ({e})")
            
            status.update(label="Pipeline complete!", state="complete")
            log.append("Pipeline complete.")
            
        except Exception as e:
            log.append(f"Pipeline encountered critical error: {e}")
            st.write(f"❌ Pipeline failed: {e}")
            status.update(state="error")
            return

    # Outside the status block
    st.session_state['pipeline_log'] = log
    st.session_state['current_phase'] = "Approval Gate"
    st.session_state['pipeline_running'] = False
    st.rerun()

# Main Content
if st.session_state.get('pipeline_running', False):
    st.title("Full Pipeline Execution")
    _render_pipeline_execution()
    st.stop()

st.title(st.session_state['current_phase'])

# 4. Phase 1 "Inbox & Triage" section
if st.session_state['current_phase'] == "Inbox & Triage":
    if st.button("Pull & Triage Threads"):
        with st.spinner("Pulling and triaging threads..."):
            formatted_threads = []
            triaged_data = {}
            
            if source == "Gmail via engine.py":
                if engine and hasattr(engine, 'fetch_threads'):
                    try:
                        raw_threads = engine.fetch_threads()
                        # Convert format: engine returns [{thread_id, sender, subject, snippet, date}]
                        # Pipeline needs: [{id, subject, messages: [{from, date, body}]}]
                        for t in raw_threads:
                            formatted_threads.append({
                                "id": t.get("thread_id"),
                                "subject": t.get("subject"),
                                "messages": [{
                                    "from": t.get("sender"),
                                    "date": t.get("date"),
                                    "body": t.get("snippet"),
                                    "message_id": t.get("message_id")
                                }]
                            })
                        st.session_state['threads'] = formatted_threads
                        
                        if triage and hasattr(triage, 'triage_inbox'):
                            triaged_data = triage.triage_inbox(formatted_threads)
                        else:
                            st.warning("triage.py module not found or missing triage_inbox function. Using mock triage.")
                            # Simple mock triage fallback
                            triaged_data = {
                                "urgent": formatted_threads,
                                "needs-reply": [],
                                "fyi": [],
                                "ignore": []
                            }
                        st.session_state['triaged'] = triaged_data
                        st.success("Successfully pulled and triaged from Gmail!")
                    except Exception as e:
                        st.error(f"Error fetching from Gmail: {e}")
                else:
                    st.error("engine.py module not found or missing fetch_threads function.")
            else:
                try:
                    with open("sample_threads.json", "r") as f:
                        sample_data = json.load(f)
                    st.session_state['threads'] = sample_data
                    
                    if triage and hasattr(triage, 'triage_inbox'):
                        triaged_data = triage.triage_inbox(sample_data)
                    else:
                        # Mock triage based on subject for demo purposes
                        triaged_data = {
                            "urgent": [t for t in sample_data if "urgent" in t.get("subject", "").lower()],
                            "needs-reply": [t for t in sample_data if "feedback" in t.get("subject", "").lower() or "vendor" in t.get("subject", "").lower() or "review" in t.get("subject", "").lower()],
                            "fyi": [t for t in sample_data if "notes" in t.get("subject", "").lower()],
                            "ignore": []
                        }
                    st.session_state['triaged'] = triaged_data
                    st.success("Successfully loaded and triaged sample threads!")
                except FileNotFoundError:
                    st.error("sample_threads.json not found.")
                except Exception as e:
                    st.error(f"Error loading sample threads: {e}")

    # Display threads grouped by priority
    triaged = st.session_state.get('triaged', {})
    if triaged:
        urgent = triaged.get("urgent", [])
        needs_reply = triaged.get("needs-reply", [])
        fyi = triaged.get("fyi", [])
        ignore = triaged.get("ignore", [])
        
        # In case triage uses underscore instead of hyphen
        if not needs_reply and "needs_reply" in triaged:
            needs_reply = triaged.get("needs_reply", [])
            
        actionable_count = len(urgent) + len(needs_reply)
        st.info(f"You have **{actionable_count}** actionable threads.")
        
        def display_group(title, threads):
            if threads:
                st.subheader(f"{title} ({len(threads)})")
                for t in threads:
                    with st.expander(f"{t.get('subject', 'No Subject')} (ID: {t.get('id', 'N/A')})"):
                        for m in t.get("messages", []):
                            st.markdown(f"**From:** {m.get('from', 'Unknown')} | **Date:** {m.get('date', 'Unknown')}")
                            st.write(m.get('body', ''))
                        st.markdown("---")
        
        display_group("🚨 Urgent", urgent)
        display_group("✉️ Needs Reply", needs_reply)
        display_group("ℹ️ FYI", fyi)
        display_group("🗑️ Ignore", ignore)

elif st.session_state['current_phase'] == "Draft Generation":
    st.header("Draft Generation")
    
    triaged = st.session_state.get('triaged', {})
    urgent = triaged.get("urgent", [])
    needs_reply = triaged.get("needs-reply", [])
    if not needs_reply and "needs_reply" in triaged:
        needs_reply = triaged.get("needs_reply", [])
        
    actionable_threads = urgent + needs_reply
    
    if not actionable_threads:
        st.info("No actionable threads to draft replies for. Go to Inbox & Triage to pull threads.")
    else:
        st.write(f"Found **{len(actionable_threads)}** actionable thread(s).")
        
        if st.button("Generate All Drafts"):
            if not api_key:
                st.error(f"Please provide your {llm_provider} API Key in the sidebar first.")
            elif not draft_machine:
                st.error("draft_machine.py module not found.")
            else:
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for i, thread in enumerate(actionable_threads):
                    status_text.text(f"Drafting for: {thread.get('subject', 'No Subject')}...")
                    try:
                        draft = draft_machine.draft_reply(thread, provider=llm_provider)
                        st.session_state['drafts_dict'][thread.get('id')] = draft
                    except Exception as e:
                        st.error(f"Error generating draft for {thread.get('id')}: {e}")
                    
                    progress_bar.progress((i + 1) / len(actionable_threads))
                    
                status_text.text("All drafts generated!")
                st.success("Draft generation complete. Please proceed to **Approval Gate** using the sidebar.")
                
        # Display threads and drafts side-by-side
        if st.session_state['drafts_dict']:
            st.markdown("---")
            st.subheader("Review Drafts")
            for thread in actionable_threads:
                thread_id = thread.get('id')
                if thread_id in st.session_state['drafts_dict']:
                    with st.expander(f"{thread.get('subject', 'No Subject')} (ID: {thread_id})", expanded=True):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown("**Original Thread (Latest Message)**")
                            messages = thread.get('messages', [])
                            if messages:
                                latest_msg = messages[-1]
                                st.markdown(f"**From:** {latest_msg.get('from', 'Unknown')} | **Date:** {latest_msg.get('date', 'Unknown')}")
                                st.write(latest_msg.get('body', ''))
                            else:
                                st.write("No messages found.")
                        with col2:
                            st.markdown("**AI-Generated Draft**")
                            # We can use text_area to let the user see it clearly, or just write it.
                            st.text_area("Draft content", value=st.session_state['drafts_dict'][thread_id], height=200, label_visibility="collapsed", key=f"draft_{thread_id}")
    
elif st.session_state['current_phase'] == "Approval Gate":
    st.header("Approval Gate")
    
    pipeline_log = st.session_state.get('pipeline_log', [])
    if pipeline_log:
        with st.expander("Pipeline Execution Log"):
            for entry in pipeline_log:
                if "ERROR" in entry.upper() or "FAILED" in entry.upper():
                    st.write(f"❌ {entry}")
                else:
                    st.write(f"✅ {entry}")
            if st.button("Clear log"):
                st.session_state['pipeline_log'] = []
                st.rerun()
        st.markdown("---")
    
    drafts = st.session_state.get('drafts_dict', {})
    if not drafts:
        st.info("No drafts generated yet. Go to Draft Generation first.")
    else:
        approved = st.session_state.get('approved_dict', {})
        rejected = st.session_state.get('rejected_set', set())
        
        pending_thread_ids = [tid for tid in drafts.keys() if tid not in approved and tid not in rejected]
        
        st.write(f"**Status:** {len(approved)} approved, {len(rejected)} rejected, {len(pending_thread_ids)} pending")
        
        if len(pending_thread_ids) == 0 and len(drafts) > 0:
            st.balloons()
            st.success("All drafts reviewed! Proceed to **Export Proof** using the sidebar.")
        else:
            def get_emoji(tid):
                triaged = st.session_state.get('triaged', {})
                for t in triaged.get("urgent", []):
                    if t.get('id') == tid: return "🚨"
                for t in triaged.get("needs-reply", []) + triaged.get("needs_reply", []):
                    if t.get('id') == tid: return "✉️"
                return "📄"
                
            def get_thread(tid):
                for t in st.session_state.get('threads', []):
                    if t.get('id') == tid:
                        return t
                return None

            st.markdown("---")
            for tid in pending_thread_ids:
                thread = get_thread(tid)
                if not thread:
                    continue
                    
                subject = thread.get('subject', 'No Subject')
                emoji = get_emoji(tid)
                
                with st.expander(f"{emoji} {subject}", expanded=True):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown("**Original Thread**")
                        for msg in thread.get('messages', []):
                            st.markdown(f"**From:** {msg.get('from', 'Unknown')} | **Date:** {msg.get('date', 'Unknown')}")
                            st.write(msg.get('body', ''))
                            st.markdown("---")
                            
                    with col2:
                        st.markdown("**Review & Edit Draft**")
                        edited_draft = st.text_area("Draft", value=drafts[tid], height=300, label_visibility="collapsed", key=f"edit_{tid}")
                        
                        bcol1, bcol2, bcol3 = st.columns(3)
                        with bcol1:
                            if st.button("✅ Approve", key=f"app_{tid}", use_container_width=True):
                                st.session_state['approved_dict'][tid] = edited_draft
                                st.rerun()
                        with bcol2:
                            if st.button("🔄 Regenerate", key=f"reg_{tid}", use_container_width=True):
                                with st.spinner("Regenerating..."):
                                    if not api_key:
                                        st.error(f"Please provide your {llm_provider} API Key in the sidebar first.")
                                    elif draft_machine:
                                        try:
                                            new_draft = draft_machine.draft_reply(thread, provider=llm_provider)
                                            st.session_state['drafts_dict'][tid] = new_draft
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Error regenerating: {e}")
                                    else:
                                        st.error("draft_machine module not found.")
                        with bcol3:
                            if st.button("❌ Reject", key=f"rej_{tid}", use_container_width=True):
                                st.session_state['rejected_set'].add(tid)
                                st.rerun()

elif st.session_state['current_phase'] == "Export Proof":
    st.header("Export Proof")
    
    approved = st.session_state.get('approved_dict', {})
    threads = st.session_state.get('threads', [])
    
    if not approved:
        st.info("No approved drafts yet. Go to Approval Gate to approve drafts.")
    else:
        st.write(f"Ready to export **{len(approved)}** approved drafts.")
        
        # 1. Preview of all approved drafts side-by-side
        st.markdown("### Preview")
        for tid, draft in approved.items():
            thread = next((t for t in threads if t.get('id') == tid), None)
            if not thread:
                continue
                
            subject = thread.get('subject', 'No Subject')
            with st.expander(f"Preview: {subject}", expanded=False):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**Original Thread**")
                    for msg in thread.get('messages', []):
                        st.markdown(f"**From:** {msg.get('from', 'Unknown')} | **Date:** {msg.get('date', 'Unknown')}")
                        st.write(msg.get('body', ''))
                        st.markdown("---")
                with col2:
                    st.markdown("**Approved Draft**")
                    st.write(draft)
                    
                    st.markdown("---")
                    col_send, col_book = st.columns(2)
                    with col_send:
                        if st.button("✉️ Send Reply", key=f"send_{tid}", type="primary", use_container_width=True):
                            with st.spinner("Dispatching via Gmail..."):
                                try:
                                    # Get the recipient from the latest message in the thread
                                    to_address = thread.get('messages', [])[-1].get('from', 'Unknown')
                                    message_id = thread.get('messages', [])[-1].get('message_id')
                                    reply_subject = subject if subject.startswith("Re:") else f"Re: {subject}"
                                    
                                    if source == "Sample threads for demo":
                                        st.success("Successfully dispatched mock reply (Demo mode)!")
                                        log_action(
                                            action_type="sent",
                                            thread_subject=thread.get("subject", subject),
                                            detail=to_address,
                                            action_id=f"mock_{tid}"
                                        )
                                    elif engine and hasattr(engine, 'send_reply'):
                                        result = engine.send_reply(
                                            thread_id=tid,
                                            to_address=to_address,
                                            subject=reply_subject,
                                            body_text=draft,
                                            message_id=message_id
                                        )
                                        st.success("Successfully dispatched to Gmail!")
                                        if result and "id" in result:
                                            log_action(
                                                action_type="sent",
                                                thread_subject=thread.get("subject", subject),
                                                detail=to_address,
                                                action_id=result["id"]
                                            )
                                    else:
                                        st.warning("Gmail engine is not available. Please run in Gmail mode.")
                                except Exception as e:
                                    st.error(f"Failed to send email: {e}")
                    
                    with col_book:
                        is_meeting = thread.get('category') == 'meeting-request' or "meeting" in subject.lower() or "call" in subject.lower()
                        if is_meeting:
                            if tid in st.session_state['booked']:
                                st.success(f"Booked! [Calendar Link]({st.session_state['booked'][tid]})")
                            else:
                                if st.button("📅 Book Meeting", key=f"book_{tid}", use_container_width=True):
                                    with st.spinner("Booking..."):
                                        try:
                                            calendar_engine = _get_calendar_engine()
                                            meeting_details = calendar_engine.parse_meeting_request(thread)
                                            if "parsing_error" in meeting_details:
                                                st.error(meeting_details["parsing_error"])
                                            else:
                                                st.info(f"Extracted: {meeting_details.get('topic')}, {meeting_details.get('duration_minutes')}min")
                                                slot = calendar_engine.find_free_slot(meeting_details.get("proposed_times", []), meeting_details.get("duration_minutes", 30))
                                                if slot:
                                                    event = calendar_engine.create_event(
                                                        summary=meeting_details.get("topic", subject),
                                                        start_time=slot,
                                                        duration_minutes=meeting_details.get("duration_minutes", 30),
                                                        attendees=meeting_details.get("attendees", []),
                                                        description=draft
                                                    )
                                                    st.session_state['booked'][tid] = event.get('htmlLink', '#')
                                                    st.success("Booked successfully!")
                                                    if event and "id" in event:
                                                        log_action(
                                                            action_type="booked",
                                                            thread_subject=thread.get("subject", subject),
                                                            detail=meeting_details.get("topic", thread.get("subject", subject)),
                                                            action_id=event["id"]
                                                        )
                                                    time.sleep(1)
                                                    st.rerun()
                                                else:
                                                    st.warning("No free slots found.")
                                        except Exception as e:
                                            st.error(f"Error booking: {e}")
                    
        st.markdown("---")
        
        st.subheader("Action Log")
        logs = get_action_log()
        if not logs:
            st.info("No actions logged yet.")
        else:
            for log in logs:
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    icon = "📨" if log.get("action_type") == "sent" else "📅"
                    st.write(f"{icon} {log.get('action_type', '').upper()}")
                with c2:
                    st.markdown(f"**{log.get('thread_subject')}**")
                with c3:
                    st.markdown(f"`{log.get('detail')}`")
                with c4:
                    try:
                        dt = datetime.datetime.fromisoformat(log.get("timestamp"))
                        st.caption(dt.strftime("%b %d %I:%M %p"))
                    except Exception:
                        st.caption(log.get("timestamp"))
        
        st.markdown("---")
        
        # Helpers for Proofs
        def generate_proof_markdown(approved_dict, all_threads):
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            lines = [
                "# The Draft Desk — Proof of Work",
                f"**Date:** {now_str}",
                ""
            ]
            
            for t_id, d_text in approved_dict.items():
                t_obj = next((x for x in all_threads if x.get('id') == t_id), None)
                if not t_obj:
                    continue
                    
                lines.append(f"## Subject: {t_obj.get('subject', 'No Subject')}")
                lines.append("### Original Thread")
                for m in t_obj.get('messages', []):
                    lines.append(f"> **From:** {m.get('from', 'Unknown')} | **Date:** {m.get('date', 'Unknown')}")
                    for m_line in m.get('body', '').split('\\n'):
                        lines.append(f"> {m_line}")
                    lines.append(">")
                    
                lines.append("### Approved Draft")
                lines.append("```text")
                lines.append(d_text)
                lines.append("```")
                lines.append("---")
                lines.append("")
                
            return "\\n".join(lines)
            
        def generate_proof_html(approved_dict, all_threads):
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>The Draft Desk — Proof of Work</title>
<style>
    body {{
        background-color: #1a1a2e;
        color: #e0e0e0;
        font-family: sans-serif;
        margin: 40px;
    }}
    h1, h2, h3 {{ color: #ffffff; }}
    .date {{ color: #a0a0a0; font-style: italic; margin-bottom: 30px; }}
    .thread-container {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 20px;
        margin-bottom: 40px;
        padding-bottom: 40px;
        border-bottom: 1px solid #333;
    }}
    .original {{
        border: 2px solid orange;
        padding: 20px;
        border-radius: 8px;
        background-color: #16213e;
    }}
    .draft {{
        border: 2px solid green;
        padding: 20px;
        border-radius: 8px;
        background-color: #0f3460;
    }}
    .msg-header {{ font-weight: bold; margin-bottom: 10px; color: #ffb86c; }}
    .msg-body {{ white-space: pre-wrap; }}
</style>
</head>
<body>
    <h1>The Draft Desk — Proof of Work</h1>
    <div class="date">Date: {now_str}</div>
"""
            for t_id, d_text in approved_dict.items():
                t_obj = next((x for x in all_threads if x.get('id') == t_id), None)
                if not t_obj:
                    continue
                    
                subject = t_obj.get('subject', 'No Subject')
                
                orig_html = "<h3>Original Thread</h3>"
                for m in t_obj.get('messages', []):
                    from_esc = html.escape(m.get('from', 'Unknown'))
                    date_esc = html.escape(m.get('date', 'Unknown'))
                    orig_html += f"<div class='msg-header'>From: {from_esc} | Date: {date_esc}</div>"
                    body = html.escape(m.get('body', ''))
                    orig_html += f"<div class='msg-body'>{body}</div><hr style='border-color: #333;'>"
                    
                draft_escaped = html.escape(d_text)
                draft_html = f"<h3>Approved Draft</h3><div class='msg-body'>{draft_escaped}</div>"
                
                subj_esc = html.escape(subject)
                html_content += f"""
    <h2>Subject: {subj_esc}</h2>
    <div class="thread-container">
        <div class="original">{orig_html}</div>
        <div class="draft">{draft_html}</div>
    </div>
"""
            html_content += "</body></html>"
            return html_content
            
        md_data = generate_proof_markdown(approved, threads)
        html_data = generate_proof_html(approved, threads)
        
        # 4. Two download buttons
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            st.download_button(
                label="Download Proof (Markdown)",
                data=md_data,
                file_name="proof_of_work.md",
                mime="text/markdown",
                use_container_width=True
            )
        with col_btn2:
            st.download_button(
                label="Download Proof (HTML)",
                data=html_data,
                file_name="proof_of_work.html",
                mime="text/html",
                use_container_width=True
            )
