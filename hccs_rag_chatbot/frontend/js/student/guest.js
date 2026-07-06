// Guest chat — anonymous, stateless, restricted to enrollment + scholarship
// documents. Posts to the public /chat/guest endpoint (no auth token, no
// session/history). Reuses api.js (apiPost) and faq.js (GUEST_FAQS / renderFaqChips).

document.addEventListener("DOMContentLoaded", () => {
    // Guests have no theme controls, so just follow the OS light/dark preference.
    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
        document.body.classList.add("light-theme");
    }

    const chatInput = document.getElementById("chat-input");
    const sendBtn = document.getElementById("send-btn");
    const chatHistory = document.getElementById("chat-history");
    const greeting = document.getElementById("greeting-text");
    let busy = false;

    const DOC_ICON = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>';

    function scrollToBottom() {
        setTimeout(() => (chatHistory.scrollTop = chatHistory.scrollHeight), 50);
    }

    function addBubble(role, text, isHTML = false) {
        const row = document.createElement("div");
        row.className = `chat-row chat-row-${role}`;
        const wrap = document.createElement("div");
        wrap.className = "chat-msg-content";
        if (isHTML) wrap.innerHTML = text;
        else if (role === "bot" && typeof marked !== "undefined") wrap.innerHTML = marked.parse(text);
        else wrap.textContent = text;
        row.appendChild(wrap);
        chatHistory.appendChild(row);
        scrollToBottom();
        return wrap;
    }

    function cleanSourceName(name) {
        return String(name)
            .replace(/\s*\((orig|original)\)\s*$/i, "")
            .replace(/\.(pdf|docx?|txt|md)$/i, "")
            .replace(/[_-]+/g, " ")
            .replace(/\s+/g, " ")
            .trim();
    }

    function addSources(sources) {
        if (!sources || !sources.length) return;
        const seen = new Set();
        const cleaned = sources
            .map(cleanSourceName)
            .filter((n) => n && !seen.has(n.toLowerCase()) && seen.add(n.toLowerCase()));
        if (!cleaned.length) return;

        const row = document.createElement("div");
        row.className = "chat-row source-row";
        const wrap = document.createElement("div");
        wrap.className = "chat-msg-content chat-source";

        const label = document.createElement("span");
        label.className = "source-label";
        label.textContent = cleaned.length > 1 ? "Sources" : "Source";
        wrap.appendChild(label);

        const list = document.createElement("div");
        list.className = "source-pills";
        cleaned.forEach((name) => {
            const pill = document.createElement("span");
            pill.className = "source-pill";
            pill.title = name;
            pill.innerHTML = DOC_ICON + "<span>" + name.replace(/</g, "&lt;") + "</span>";
            list.appendChild(pill);
        });
        wrap.appendChild(list);
        row.appendChild(wrap);
        chatHistory.appendChild(row);
        scrollToBottom();
    }

    function revealHistory() {
        chatHistory.classList.remove("hidden");
        if (greeting) greeting.style.display = "none";
    }

    function renderGreetingFaqs() {
        if (!greeting || typeof renderFaqChips !== "function") return;
        const faqs = typeof GUEST_FAQS !== "undefined" ? GUEST_FAQS : [];
        renderFaqChips(greeting, faqs, (q) => {
            chatInput.value = q;
            handleSend();
        });
    }

    async function handleSend() {
        const text = chatInput.value.trim();
        if (!text || busy) return;
        busy = true;
        chatInput.value = "";
        revealHistory();
        addBubble("user", text);

        const loaderHTML = `<div class="typing-indicator"><span></span><span></span><span></span></div>`;
        const thinking = addBubble("bot", loaderHTML, true);
        try {
            const data = await apiPost("/chat/guest", { message: text });
            thinking.innerHTML = typeof marked !== "undefined" ? marked.parse(data.answer) : data.answer;
            addSources(data.sources);
        } catch (err) {
            thinking.textContent = "Error: " + err.message;
        } finally {
            busy = false;
            chatInput.focus();
            scrollToBottom();
        }
    }

    if (sendBtn) sendBtn.addEventListener("click", handleSend);
    if (chatInput) chatInput.addEventListener("keypress", (e) => { if (e.key === "Enter") handleSend(); });

    renderGreetingFaqs();
});
