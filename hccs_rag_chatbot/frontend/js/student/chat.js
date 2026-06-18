// Student chat — wired to the RAG backend.
// Requires api.js and auth.js to be loaded before this script.

document.addEventListener("DOMContentLoaded", async () => {
    const chatInput = document.getElementById("chat-input");
    const sendBtn = document.getElementById("send-btn");
    const chatHistory = document.getElementById("chat-history");
    const greeting = document.querySelector(".greeting-text");
    const newChatBtn = document.querySelector(".new-chat-btn");
    const historyList = document.querySelector(".history-list");

    let currentSessionId = null;
    let busy = false;

    // 1. Initial Setup (Live API Fetch)
    try {
        // Actively fetch the real user data from the backend
        const currentUser = await apiGet("/api/auth/me");

        if (currentUser) {
            // Backup the fetched data to storage
            if (typeof setUser === "function") setUser(currentUser);

            const profileName = document.querySelector(".sidebar-footer .display-name");
            const avatarInitial = document.querySelector(".sidebar-footer .avatar-initial");
            const profileRole = document.querySelector(".sidebar-footer .role");
            const greetingName = document.querySelector(".greeting-text h1");

            // Determine best available name directly from the API response
            let displayName = currentUser.display_name || currentUser.email || "Student";

            // Dynamically overwrite the static HTML
            if (profileName) {
                profileName.textContent = displayName;
            }

            if (avatarInitial) {
                avatarInitial.textContent = displayName.charAt(0).toUpperCase();
            }

            if (profileRole && currentUser.role) {
                profileRole.textContent = currentUser.role;
            }

            if (greetingName && currentUser.display_name) {
                const firstName = currentUser.display_name.split(' ')[0];
                greetingName.textContent = `Your move, ${firstName}!`;
            }
        }
    } catch (err) {
        console.error("Could not fetch live user profile:", err);
        const profileName = document.querySelector(".sidebar-footer .display-name");
        if (profileName) profileName.textContent = "Offline User";
    }

    // Load sidebar history
    await loadSidebarHistory();

    // 2. Chat UI Functions
    function resetChatUI() {
        currentSessionId = null;
        chatHistory.innerHTML = "";
        chatHistory.classList.add("hidden");
        if (greeting) greeting.style.display = "block";

        // Clear active state in sidebar
        document.querySelectorAll(".history-list li").forEach(li => li.classList.remove("active"));
    }

    function revealHistory() {
        chatHistory.classList.remove("hidden");
        if (greeting) greeting.style.display = "none";
    }

    function addBubble(role, text) {
        const wrap = document.createElement("div");
        wrap.className = `chat-msg chat-msg-${role}`;
        wrap.textContent = text;
        chatHistory.appendChild(wrap);
        scrollToBottom();
        return wrap;
    }

    function addSources(sources) {
        if (!sources || !sources.length) return;
        const el = document.createElement("div");
        el.className = "chat-source";
        el.textContent = "Source: " + sources.join(", ");
        chatHistory.appendChild(el);
        scrollToBottom();
    }

    function scrollToBottom() {
        setTimeout(() => {
            chatHistory.scrollTop = chatHistory.scrollHeight;
        }, 50);
    }

    // 3. API Communication
    async function handleSend() {
        const text = chatInput.value.trim();
        if (!text || busy) return;

        busy = true;
        chatInput.value = "";
        revealHistory();
        addBubble("user", text);

        const thinking = addBubble("bot", "Thinking...");

        try {
            const data = await apiPost("/chat", {
                message: text,
                session_id: currentSessionId
            });

            // If this was a new session, update the ID and refresh the sidebar
            if (!currentSessionId && data.session_id) {
                currentSessionId = data.session_id;
                await loadSidebarHistory();
            }

            thinking.textContent = data.answer || "I'm sorry, I couldn't generate a response.";
            addSources(data.sources);

        } catch (err) {
            thinking.textContent = err.message || "Connection error. Make sure the FastAPI server is running.";
        } finally {
            busy = false;
            chatInput.focus();
            scrollToBottom();
        }
    }

    // 4. Sidebar History Logic
    async function loadSidebarHistory() {
        if (!historyList) return;

        try {
            const sessions = await apiGet("/chat/sessions");
            historyList.innerHTML = "";

            if (!sessions || sessions.length === 0) {
                 historyList.innerHTML = `<li style="color:#64748b; cursor:default; pointer-events:none;">No recent chats</li>`;
                 return;
            }

            sessions.forEach(session => {
                const li = document.createElement("li");

                // Make the entire row explicitly act as a pointer/button
                li.style.cursor = "pointer";

                const activeId = typeof currentSessionId !== 'undefined' ? currentSessionId : null;
                if (session.session_id === activeId) {
                    li.classList.add("active");
                }

                li.innerHTML = `
                    <div class="session-info">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
                        <span style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis; width: 140px;">${session.title}</span>
                    </div>
                    <button class="delete-session-btn" title="Delete Chat">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                    </button>
                `;

                // Attach the load function to the entire 'li' row
                li.addEventListener("click", () => loadSession(session.session_id));

                // Ensure clicking the trash can doesn't trigger the row click
                const deleteBtn = li.querySelector('.delete-session-btn');
                deleteBtn.addEventListener("click", async (e) => {
                    e.stopPropagation();
                    if(confirm("Are you sure you want to delete this chat?")) {
                        await deleteSession(session.session_id);
                    }
                });

                historyList.appendChild(li);
            });
        } catch (err) {
            console.error("Failed to load chat history:", err);
        }
    }

    async function loadSession(sessionId) {
        if (busy || currentSessionId === sessionId) return;

        try {
            busy = true;
            chatHistory.innerHTML = "";
            const history = await apiGet(`/chat/sessions/${sessionId}/history`);

            currentSessionId = sessionId;
            revealHistory();

            await loadSidebarHistory();

            if (history && history.length > 0) {
                 history.forEach(turn => {
                     addBubble(turn.role, turn.content);
                     if (turn.role === 'bot' && turn.sources) {
                         addSources(turn.sources);
                     }
                 });
            } else {
                addBubble("bot", "This session is empty.");
            }
            scrollToBottom();

        } catch (err) {
            console.error("Failed to load session:", err);
            addBubble("bot", "Error loading previous conversation.");
        } finally {
            busy = false;
        }
    }

    async function deleteSession(id) {
        try {
            await apiDelete(`/chat/sessions/${id}`);
            if (currentSessionId === id) {
                resetChatUI();
            }
            await loadSidebarHistory();
        } catch (err) {
            alert("Failed to delete session.");
        }
    }

    const logoutBtn = document.getElementById("logout-btn");
    if (logoutBtn) {
        logoutBtn.addEventListener("click", () => {
            removeToken();
            window.location.href = "/frontend/index.html";
        });
    }

    // 5. Event Listeners
    if (newChatBtn) {
        newChatBtn.addEventListener("click", resetChatUI);
    }

    if (sendBtn) {
        sendBtn.addEventListener("click", handleSend);
    }

    if (chatInput) {
        chatInput.addEventListener("keypress", (e) => {
            if (e.key === "Enter") handleSend();
        });
    }
});
