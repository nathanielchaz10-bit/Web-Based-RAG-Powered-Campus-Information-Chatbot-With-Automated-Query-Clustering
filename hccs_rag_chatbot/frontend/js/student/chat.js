// Student chat — wired to the RAG backend.
// Requires api.js, auth.js, and marked.js to be loaded before this script.

document.addEventListener("DOMContentLoaded", async () => {
    // --- DOM Elements ---
    const chatInput = document.getElementById("chat-input");
    const sendBtn = document.getElementById("send-btn");
    const chatHistory = document.getElementById("chat-history");
    const greeting = document.querySelector(".greeting-text");
    const newChatBtn = document.querySelector(".new-chat-btn");
    const historyList = document.querySelector(".history-list");
    const chatHeader = document.getElementById("chat-header");
    const chatTitle = document.getElementById("chat-title");

    // --- Profile Popover Elements ---
    const profileBtn = document.getElementById("sidebar-footer-btn");
    const profilePopover = document.getElementById("profile-popover");
    const closePopoverBtn = document.getElementById("close-popover");
    const popoverSignOut = document.getElementById("popover-sign-out");

    let currentSessionId = null;
    let busy = false;

    // 1. Initial Setup: Live API Fetch
    try {
        const currentUser = await apiGet("/api/auth/me");
        if (currentUser) {
            if (typeof setUser === "function") setUser(currentUser);

            // Sidebar Footer variables
            const profileName = document.querySelector(".user-info .display-name");
            const profileRole = document.querySelector(".user-info .role");
            const greetingName = document.querySelector(".greeting-text h1");

            let displayName = currentUser.display_name || currentUser.email || "Student";
            const profilePictureUrl = currentUser.picture || null; // Grab the picture URL if it exists

            // Populate Sidebar Text
            if (profileName) profileName.textContent = displayName;
            if (profileRole && currentUser.role) profileRole.textContent = currentUser.role;
            if (greetingName && currentUser.display_name) {
                greetingName.textContent = `Your move, ${currentUser.display_name.split(' ')[0]}!`;
            }

            // Populate the Hidden Profile Popover and Settings Modal Text
            const popoverEmail = document.getElementById("popover-email");
            const popoverGreeting = document.getElementById("popover-greeting");
            const settingsFullName = document.getElementById("settings-fullname");
            const settingsNickname = document.getElementById("settings-nickname");

            if (popoverEmail) popoverEmail.textContent = currentUser.email || "student@hccs.edu.ph";
            if (settingsFullName) settingsFullName.value = currentUser.display_name || "Student User";
            if (settingsNickname) settingsNickname.value = displayName.split(' ')[0];

            if (popoverGreeting) {
                const firstName = displayName.split(' ')[0];
                popoverGreeting.textContent = `Hi, ${firstName}!`;
            }

            // --- AVATAR LOGIC: Picture vs Initial ---
            const sidebarAvatarContainer = document.getElementById("user-avatar");
            const popoverAvatarContainer = document.querySelector(".popover-avatar-inner");
            const settingsAvatarContainer = document.querySelector(".setting-avatar-circle");

            if (profilePictureUrl) {
                // If a Google picture exists, inject the <img> tag
                const imgTag = `<img src="${profilePictureUrl}" alt="Profile" style="width: 100%; height: 100%; border-radius: 50%; object-fit: cover;">`;

                if (sidebarAvatarContainer) {
                    sidebarAvatarContainer.innerHTML = `${imgTag}<span class="status-dot"></span>`;
                }
                if (popoverAvatarContainer) popoverAvatarContainer.innerHTML = imgTag;
                if (settingsAvatarContainer) settingsAvatarContainer.innerHTML = imgTag;
            } else {
                // Fallback: If no picture, use the first letter of their name
                const initial = displayName.charAt(0).toUpperCase();
                const sidebarInitialSpan = document.querySelector(".user-avatar .avatar-initial");
                const popoverInitialSpan = document.getElementById("popover-avatar-initial");
                const settingsInitialSpan = document.getElementById("settings-modal-initial");

                if (sidebarInitialSpan) sidebarInitialSpan.textContent = initial;
                if (popoverInitialSpan) popoverInitialSpan.textContent = initial;
                if (settingsInitialSpan) settingsInitialSpan.textContent = initial;
            }
        }
    } catch (err) {
        console.error("Profile fetch failed:", err);
    }

    // Load initial sidebar history
    await loadSidebarHistory();

    // 2. Chat UI Functions
    function resetChatUI() {
        currentSessionId = null;
        chatHistory.innerHTML = "";
        chatHistory.classList.add("hidden");
        if (chatHeader) chatHeader.classList.add("hidden");
        if (greeting) greeting.style.display = "block";
        document.querySelectorAll(".history-list li").forEach(li => li.classList.remove("active"));
    }

    function revealHistory() {
        chatHistory.classList.remove("hidden");
        if (chatHeader) chatHeader.classList.remove("hidden");
        if (greeting) greeting.style.display = "none";
    }

    function addBubble(role, text, isHTML = false) {
        const row = document.createElement("div");
        row.className = `chat-row chat-row-${role}`;

        const wrap = document.createElement("div");
        wrap.className = "chat-msg-content";

        if (isHTML) {
            wrap.innerHTML = text; // Used for animated typing indicator
        } else if (role === "bot" && typeof marked !== "undefined") {
            wrap.innerHTML = marked.parse(text); // Used for markdown
        } else {
            wrap.textContent = text;
        }

        row.appendChild(wrap);
        chatHistory.appendChild(row);
        scrollToBottom();

        return wrap;
    }

    function addSuggestedChips(chipsArray) {
        if (!chipsArray || chipsArray.length === 0) return;

        const row = document.createElement("div");
        row.className = "chat-row source-row";

        const container = document.createElement("div");
        container.className = "chat-msg-content suggested-chips";

        chipsArray.forEach(chipText => {
            const btn = document.createElement("button");
            btn.className = "suggestion-chip";
            btn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"></polyline></svg> ${chipText}`;

            btn.addEventListener("click", () => {
                chatInput.value = chipText;
                handleSend();
            });

            container.appendChild(btn);
        });

        row.appendChild(container);
        chatHistory.appendChild(row);
        scrollToBottom();
    }

    function addSources(sources) {
        if (!sources || !sources.length) return;

        const row = document.createElement("div");
        row.className = "chat-row source-row"; // Deliberately NOT .chat-row-bot

        const wrap = document.createElement("div");
        wrap.className = "chat-msg-content chat-source";
        wrap.textContent = "Source: " + sources.join(", ");

        row.appendChild(wrap);
        chatHistory.appendChild(row);
        scrollToBottom();
    }

    function scrollToBottom() {
        setTimeout(() => chatHistory.scrollTop = chatHistory.scrollHeight, 50);
    }

    // 3. API Communication
    async function handleSend() {
        const text = chatInput.value.trim();
        if (!text || busy) return;

        busy = true;
        chatInput.value = "";

        // Generate Header Title
        if (!currentSessionId && chatTitle) {
            chatTitle.textContent = text.length > 30 ? text.substring(0, 30) + '...' : text;
        }

        revealHistory();

        // Remove old onboarding tip if it exists
        const oldTip = document.querySelector(".onboarding-tip");
        if (oldTip) oldTip.remove();

        // Print User Message
        addBubble("user", text);

        // Inject the animated bouncing dots while waiting
        const loaderHTML = `<div class="typing-indicator"><span></span><span></span><span></span></div>`;
        const thinking = addBubble("bot", loaderHTML, true);

        try {
            const data = await apiPost("/chat", { message: text, session_id: currentSessionId });

            // If new session, save ID and refresh sidebar
            if (!currentSessionId && data.session_id) {
                currentSessionId = data.session_id;
                await loadSidebarHistory();
            }

            // Replace typing dots with actual answer
            thinking.innerHTML = typeof marked !== "undefined" ? marked.parse(data.answer) : data.answer;
            addSources(data.sources);

            // If backend supports suggestions, render them:
            // if (data.suggestions) addSuggestedChips(data.suggestions);

        } catch (err) {
            thinking.textContent = "Error: " + err.message;
        } finally {
            busy = false;
            chatInput.focus();
            scrollToBottom();
        }
    }

    // 4. Session Handling
    async function loadSession(sessionId, title) {
        if (busy || currentSessionId === sessionId) return;
        busy = true;
        chatHistory.innerHTML = "";
        const history = await apiGet(`/chat/sessions/${sessionId}/history`);

        currentSessionId = sessionId;
        if (chatTitle) chatTitle.textContent = title;
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
        busy = false;
    }

    async function loadSidebarHistory() {
        if (!historyList) return;

        try {
            const sessions = await apiGet("/chat/sessions");
            historyList.innerHTML = "";

            if (!sessions || sessions.length === 0) {
                 historyList.innerHTML = `<li style="color:#64748b; cursor:default; pointer-events:none;">No recent chats</li>`;

                 // Show onboarding tip if there is no history and the chat is empty
                 if (chatHistory.children.length === 0 && greeting && greeting.style.display !== "none") {
                     const tip = document.createElement("div");
                     tip.className = "onboarding-tip";
                     tip.innerHTML = "<strong>💡 Tip:</strong> Try asking about 'Tuition Fees', 'Enrollment Requirements', or 'Library Hours'.";
                     greeting.appendChild(tip);
                 }
                 return;
            }

            sessions.forEach(session => {
                const li = document.createElement("li");
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

                li.addEventListener("click", () => loadSession(session.session_id, session.title));

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

    // 5. Event Listeners

    // Ghost Session Fix for New Chat Button
    if (newChatBtn) {
        newChatBtn.addEventListener("click", () => {
            if (busy) return;
            currentSessionId = null; // Do not call backend yet!
            resetChatUI();
            if (chatTitle) chatTitle.textContent = "New Conversation";
            document.querySelectorAll(".history-list li").forEach(li => li.classList.remove("active"));
        });
    }

    if (sendBtn) sendBtn.addEventListener("click", handleSend);
    if (chatInput) chatInput.addEventListener("keypress", (e) => { if (e.key === "Enter") handleSend(); });

    // --- Profile Popover Listeners ---
    if (profileBtn && profilePopover) {

        // Toggle popover on profile click
        profileBtn.addEventListener("click", (e) => {
            e.stopPropagation(); // Prevents document click from immediately closing it
            profilePopover.classList.toggle("hidden");
        });

        // Close via X button
        if (closePopoverBtn) {
            closePopoverBtn.addEventListener("click", () => {
                profilePopover.classList.add("hidden");
            });
        }

        // Close if clicking anywhere outside the popover
        document.addEventListener("click", (e) => {
            if (!profilePopover.classList.contains("hidden") && !profilePopover.contains(e.target)) {
                profilePopover.classList.add("hidden");
            }
        });
    }

    // Sign Out Button inside the Popover
    if (popoverSignOut) {
        popoverSignOut.addEventListener("click", () => {
            if (typeof removeToken === "function") removeToken();
            window.location.href = "/frontend/index.html"; // Takes them to your landing page
        });
    }

    // NEW: Switch Account Button inside the Popover
    // Switch Account Button inside the Popover
    const popoverSwitchAccount = document.getElementById("popover-switch-account");
    if (popoverSwitchAccount) {
        popoverSwitchAccount.addEventListener("click", () => {
            // 1. Clear the local storage token
            if (typeof removeToken === "function") removeToken();
            
            // 2. Redirect directly to the backend Google Login route
            window.location.href = "/api/auth/login"; 
        });
    }

    // ==========================================
    // --- SETTINGS MODAL LOGIC ---
    // ==========================================
    const settingsBtn = document.getElementById("settings-btn");
    const settingsOverlay = document.getElementById("settings-overlay");
    const closeSettingsBtn = document.getElementById("close-settings");

    if (settingsBtn && settingsOverlay) {
        // 1. Open Modal
        settingsBtn.addEventListener("click", () => {
            // Hide the profile popover first
            if (profilePopover) profilePopover.classList.add("hidden");
            // Show the blurred settings overlay
            settingsOverlay.classList.remove("hidden");
        });

        // 2. Close Modal via X button
        if (closeSettingsBtn) {
            closeSettingsBtn.addEventListener("click", () => {
                settingsOverlay.classList.add("hidden");
            });
        }

        // 3. Close Modal by clicking the blurred background
        settingsOverlay.addEventListener("click", (e) => {
            if (e.target === settingsOverlay) {
                settingsOverlay.classList.add("hidden");
            }
        });
    }

    // 4. Tab Switching Logic
    const settingsTabs = document.querySelectorAll(".settings-nav li");
    const settingsPanes = document.querySelectorAll(".settings-tab-pane");

    settingsTabs.forEach(tab => {
        tab.addEventListener("click", () => {
            settingsTabs.forEach(t => t.classList.remove("active"));
            settingsPanes.forEach(p => p.classList.add("hidden"));

            tab.classList.add("active");
            const targetPaneId = tab.getAttribute("data-tab");
            document.getElementById(targetPaneId).classList.remove("hidden");
        });
    });

    // ==========================================
    // --- APPEARANCE & THEME LOGIC ---
    // ==========================================
    const themeBtnSystem = document.getElementById("theme-btn-system");
    const themeBtnLight = document.getElementById("theme-btn-light");
    const themeBtnDark = document.getElementById("theme-btn-dark");
    const fontSelect = document.getElementById("settings-font-select");
    const themeBtns = [themeBtnSystem, themeBtnLight, themeBtnDark];

    // Map UI dropdown names to actual CSS font-family strings
    const fontMap = {
        "System Default": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
        "Inter": "'Inter', sans-serif",
        "Roboto": "'Roboto', sans-serif",
        "Open Sans": "'Open Sans', sans-serif"
    };

    function applyTheme(themeMode) {
        // Reset active states
        if (themeBtnSystem) themeBtns.forEach(btn => btn.classList.remove("active"));

        if (themeMode === 'light') {
            document.body.classList.add("light-theme");
            if (themeBtnLight) themeBtnLight.classList.add("active");
        } else if (themeMode === 'dark') {
            document.body.classList.remove("light-theme");
            if (themeBtnDark) themeBtnDark.classList.add("active");
        } else {
            // System Sync
            if (themeBtnSystem) themeBtnSystem.classList.add("active");
            if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
                document.body.classList.add("light-theme");
            } else {
                document.body.classList.remove("light-theme");
            }
        }
        localStorage.setItem("hccs-theme", themeMode);
    }

    // Event Listeners for Theme Buttons
    if (themeBtnLight) themeBtnLight.addEventListener("click", () => applyTheme('light'));
    if (themeBtnDark) themeBtnDark.addEventListener("click", () => applyTheme('dark'));
    if (themeBtnSystem) themeBtnSystem.addEventListener("click", () => applyTheme('system'));

    // Listen for OS theme changes
    window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
        if (localStorage.getItem("hccs-theme") === 'system') {
            applyTheme('system');
        }
    });

    // Event Listener for Font Dropdown
    if (fontSelect) {
        fontSelect.addEventListener("change", (e) => {
            const selectedFont = e.target.value;
            document.documentElement.style.setProperty('--app-font', fontMap[selectedFont]);
            localStorage.setItem("hccs-font", selectedFont);
        });
    }

    // --- INIT: Load Saved Preferences on Startup ---
    const savedTheme = localStorage.getItem("hccs-theme") || 'system';
    applyTheme(savedTheme);

    const savedFont = localStorage.getItem("hccs-font") || 'System Default';
    if (fontSelect) {
        fontSelect.value = savedFont;
        document.documentElement.style.setProperty('--app-font', fontMap[savedFont]);
    }
});
