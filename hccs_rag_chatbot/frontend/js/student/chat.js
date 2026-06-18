// Student chat — wired to the RAG backend (POST /chat).
// Requires api.js (apiPost) to be loaded before this script.

document.addEventListener("DOMContentLoaded", () => {
    const chatInput = document.getElementById("chat-input");
    const sendBtn = document.getElementById("send-btn");
    const chatHistory = document.getElementById("chat-history");
    const greeting = document.querySelector(".greeting-text");

    let sessionId = null;
    let busy = false;

    chatInput.focus();

    function revealHistory() {
        chatHistory.classList.remove("hidden");
        if (greeting) greeting.style.display = "none";
    }

    function addBubble(role, text) {
        const wrap = document.createElement("div");
        wrap.className = `chat-msg chat-msg-${role}`;
        // Inline fallback styling so it's readable even without dedicated CSS.
        wrap.style.cssText =
            "margin:10px 0;padding:12px 16px;border-radius:12px;max-width:75%;" +
            "white-space:pre-wrap;line-height:1.45;" +
            (role === "user"
                ? "margin-left:auto;background:#0d2a5e;color:#fff;"
                : "margin-right:auto;background:#f0f3fa;color:#1a1a2e;");
        wrap.textContent = text;
        chatHistory.appendChild(wrap);
        chatHistory.scrollTop = chatHistory.scrollHeight;
        return wrap;
    }

    function addSources(sources) {
        if (!sources || !sources.length) return;
        const el = document.createElement("div");
        el.style.cssText =
            "margin:-4px auto 10px 0;font-size:0.72rem;color:#5a6a88;max-width:75%;";
        el.textContent = "Source: " + sources.join(", ");
        chatHistory.appendChild(el);
    }

    async function handleSend() {
        const text = chatInput.value.trim();
        if (!text || busy) return;

        busy = true;
        chatInput.value = "";
        revealHistory();
        addBubble("user", text);

        const thinking = addBubble("bot", "Searching school documents…");

        try {
            const data = await apiPost("/chat", { message: text, session_id: sessionId });
            sessionId = data.session_id;
            thinking.textContent = data.answer;
            addSources(data.sources);
        } catch (err) {
            thinking.textContent = "Sorry — " + err.message;
        } finally {
            busy = false;
            chatInput.focus();
        }
    }

    sendBtn.addEventListener("click", handleSend);
    chatInput.addEventListener("keypress", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            handleSend();
        }
    });
});
