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
        // Styling lives in chat.css (.chat-msg / .chat-msg-user / .chat-msg-bot)
        // so the bubbles stay in sync with the app's dark theme.
        wrap.className = `chat-msg chat-msg-${role}`;
        wrap.textContent = text;
        chatHistory.appendChild(wrap);
        chatHistory.scrollTop = chatHistory.scrollHeight;
        return wrap;
    }

    function addSources(sources) {
        if (!sources || !sources.length) return;
        const el = document.createElement("div");
        el.className = "chat-source";
        el.textContent = "Source: " + sources.join(", ");
        chatHistory.appendChild(el);
        chatHistory.scrollTop = chatHistory.scrollHeight;
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
