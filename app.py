import os
import streamlit as st
from src.rag_engine import run_rag_pipeline, log_query_to_db

st.set_page_config(page_title="HCCS Chatbot", page_icon="🎓", layout="centered")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=Source+Sans+3:wght@400;500;600&display=swap');

:root {
    --navy:      #0d2a5e;
    --navy-mid:  #1a3a7a;
    --gold:      #f5c100;
    --gold-dark: #c99a00;
    --white:     #ffffff;
    --off-white: #f5f7fc;
    --text:      #1a1a2e;
    --muted:     #5a6a88;
    --border:    #d0d9ee;
}

/* ═══════════════════════════════════════════════
   FORCE ENTIRE APP TO LIGHT — all Streamlit layers
   ═══════════════════════════════════════════════ */
html, body,
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stAppViewBlockContainer"],
[data-testid="stMain"],
[data-testid="stMainBlockContainer"],
section[data-testid="stMain"],
.main, .main > div,
.block-container,
[data-testid="stVerticalBlock"],
[data-testid="stVerticalBlockBorderWrapper"],
div[data-testid="stDecoration"],
[class*="appview-container"],
[class*="main-content"] {
    background-color: var(--off-white) !important;
    color: var(--text) !important;
}

/* ── Sidebar ── */
[data-testid="stSidebar"],
[data-testid="stSidebar"] > div,
[data-testid="stSidebarContent"],
[data-testid="stSidebarUserContent"],
section[data-testid="stSidebar"] > div {
    background-color: var(--white) !important;
    border-right: 1.5px solid var(--border) !important;
}
[data-testid="stSidebar"] * { color: var(--text) !important; }

/* ── Bottom / chat input bar ── */
[data-testid="stBottom"],
[data-testid="stBottom"] > div,
[data-testid="stBottomBlockContainer"],
.stBottom, .stBottom > div,
[class*="stBottom"] {
    background-color: var(--off-white) !important;
    border-top: 1px solid var(--border) !important;
}

/* ── Chat messages (transparent so page bg shows) ── */
[data-testid="stChatMessage"],
[data-testid="stChatMessageContent"],
[data-testid="stChatMessageAvatarUser"],
[data-testid="stChatMessageAvatarAssistant"],
.stChatMessage, .stChatMessage > div,
[class*="stChatMessage"] {
    background-color: transparent !important;
    border: none !important;
    box-shadow: none !important;
}

/* ── Chat input ── */
[data-testid="stChatInput"],
[data-testid="stChatInput"] > div,
[data-testid="stChatInputContainer"],
[class*="stChatInput"] {
    background-color: var(--white) !important;
    border: 2px solid var(--border) !important;
    border-radius: 12px !important;
    box-shadow: 0 2px 8px rgba(13,42,94,0.07) !important;
}
[data-testid="stChatInput"] > div:focus-within,
[data-testid="stChatInputContainer"]:focus-within {
    border-color: var(--navy) !important;
    box-shadow: 0 2px 12px rgba(13,42,94,0.14) !important;
}
[data-testid="stChatInput"] textarea,
[data-testid="stChatInputTextArea"],
textarea {
    background-color: var(--white) !important;
    color: var(--text) !important;
    font-family: 'Source Sans 3', sans-serif !important;
    font-size: 0.95rem !important;
}

/* ── Generic inputs ── */
input, input[type="text"], .stTextInput input {
    background-color: var(--white) !important;
    color: var(--text) !important;
}

/* ── Typography ── */
html, body, p, span, div, label, [class*="css"] {
    font-family: 'Source Sans 3', sans-serif;
}

/* ── Streamlit chrome ── */
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 2rem !important; max-width: 780px !important; }

/* ═══════════════════════════════════
   CUSTOM COMPONENTS
   ═══════════════════════════════════ */

.hccs-header {
    background: linear-gradient(135deg, var(--navy) 0%, var(--navy-mid) 100%);
    border-radius: 16px;
    padding: 2rem 2.4rem 1.6rem;
    margin-bottom: 1.5rem;
    position: relative;
    overflow: hidden;
    box-shadow: 0 4px 24px rgba(13,42,94,0.18);
}
.hccs-header::before {
    content: '';
    position: absolute; top: -30px; right: -30px;
    width: 160px; height: 160px;
    background: var(--gold); opacity: 0.1; border-radius: 50%;
}
.hccs-header::after {
    content: '';
    position: absolute; bottom: -50px; left: 40%;
    width: 220px; height: 220px;
    background: var(--gold); opacity: 0.06; border-radius: 50%;
}
.hccs-badge {
    display: inline-block;
    background: var(--gold); color: var(--navy);
    font-size: 0.68rem; font-weight: 700; letter-spacing: 0.12em;
    text-transform: uppercase; padding: 0.25rem 0.75rem;
    border-radius: 20px; margin-bottom: 0.75rem;
}
.hccs-title {
    font-family: 'Playfair Display', serif;
    color: var(--white); font-size: 1.75rem; font-weight: 700;
    margin: 0 0 0.35rem 0; line-height: 1.2;
}
.hccs-subtitle { color: rgba(255,255,255,0.65); font-size: 0.9rem; margin: 0; }

.suggestions-wrap { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1.25rem; }
.chip {
    background: var(--white); border: 1.5px solid var(--border);
    border-radius: 20px; padding: 0.35rem 0.9rem;
    font-size: 0.82rem; color: var(--navy-mid); font-weight: 500;
}

.chat-divider {
    font-size: 0.72rem; color: var(--muted); letter-spacing: 0.08em;
    text-transform: uppercase; margin: 0.5rem 0 1rem;
    display: flex; align-items: center; gap: 0.75rem;
}
.chat-divider::before, .chat-divider::after {
    content: ''; flex: 1; height: 1px; background: var(--border);
}

.hccs-footer {
    text-align: center; font-size: 0.72rem; color: var(--muted);
    margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--border);
}
.hccs-footer span { color: var(--gold-dark); font-weight: 600; }

[data-testid="stSpinner"] > div { color: var(--navy) !important; }

::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--off-white); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="hccs-header">
    <div class="hccs-badge">🎓 AI Assistant</div>
    <div class="hccs-title">Holy Child Catholic School</div>
    <p class="hccs-subtitle">Ask me anything about the student handbook, uniforms, grades, or campus policies.</p>
</div>
""", unsafe_allow_html=True)

# ── Chips ─────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="suggestions-wrap">
</div>
""", unsafe_allow_html=True)

# ── Load AI Engine ────────────────────────────────────────────────────────────
@st.cache_resource
def load_ai():
    return run_rag_pipeline()

rag_chain = load_ai()

# ── Session State ─────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []

if st.session_state.messages:
    st.markdown('<div class="chat-divider">Conversation</div>', unsafe_allow_html=True)

# ── Display messages ──────────────────────────────────────────────────────────
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# ── Chat Input ────────────────────────────────────────────────────────────────
if user_question := st.chat_input("Type your question here…"):

    with st.chat_message("user"):
        st.markdown(user_question)

    st.session_state.messages.append({"role": "user", "content": user_question})

    with st.chat_message("assistant"):
        with st.spinner("Searching school documents…"):
            try:
                formatted_history = []
                for msg in st.session_state.messages[:-1]:
                    role = "human" if msg["role"] == "user" else "ai"
                    formatted_history.append((role, msg["content"]))

                results = rag_chain.invoke({
                    "input": user_question,
                    "chat_history": formatted_history
                })

                answer = results['answer']
                context_docs = results.get('context', [])

                st.markdown(answer)

                # Low-relevance fallback
                fallback_phrases = ["i don't know", "i do not know", "don't have information", "not in the context", "cannot find"]
                if any(phrase in answer.lower() for phrase in fallback_phrases):
                    st.markdown(
                        "<div style='font-size:0.82rem;color:#5a6a88;margin-top:0.5rem;'>"
                        "For more specific information, please contact the school administration office directly."
                        "</div>",
                        unsafe_allow_html=True
                    )

                # Source citations
                if context_docs:
                    sources = set()
                    for doc in context_docs:
                        src = doc.metadata.get('source', '')
                        if src:
                            name = os.path.splitext(os.path.basename(src))[0]
                            name = name.replace('_', ' ').replace('-', ' ').title()
                            sources.add(name)
                    if sources:
                        st.markdown(
                            f"<div style='font-size:0.75rem;color:#5a6a88;margin-top:0.75rem;'>"
                            f"Source: {', '.join(sorted(sources))}"
                            f"</div>",
                            unsafe_allow_html=True
                        )

                st.session_state.messages.append({"role": "assistant", "content": answer})
                log_query_to_db(user_question, answer)

            except Exception as e:
                st.error(f"An error occurred: {e}")

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="hccs-footer">
    Powered by <span>RAG · Gemini</span> · Answers sourced from official HCCS documents only
</div>
""", unsafe_allow_html=True)