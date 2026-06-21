// ──────────────────────────────────────────────
// notifications.js
// Shared admin-header behaviour: the notification center (bell) and the
// signed-in user's profile block.
//
// The admin pages are separate documents (no SPA), so notifications are kept
// in localStorage and survive navigation between Dashboard / Documents /
// Clusters / Settings. Any page can raise one with:
//
//     pushNotification({ type, title, message });
//
// Currently raised when a document finishes processing (documents.js) and
// when a clustering run completes (clusters.js). The bell shows an unread
// count; opening the panel marks everything read.
//
// It also fills the header profile block from the logged-in user (getUser),
// so every page shows the real admin instead of a hardcoded placeholder.
//
// Loaded on every admin page before the page-specific script, so the global
// helper is available by the time those scripts run.
// ──────────────────────────────────────────────

(function () {
    const STORAGE_KEY = "hccs_admin_notifications";
    const MAX_ITEMS = 30;

    // Small inline glyphs keyed by notification type.
    const TYPE_ICONS = {
        document: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>',
        clustering: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="6" r="3"></circle><circle cx="18" cy="18" r="3"></circle><circle cx="6" cy="18" r="2"></circle><path d="M9 6h6M6 9v6"></path></svg>',
        error: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>',
        info: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>',
    };

    function load() {
        try {
            const arr = JSON.parse(localStorage.getItem(STORAGE_KEY));
            return Array.isArray(arr) ? arr : [];
        } catch {
            return [];
        }
    }

    function save(items) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, MAX_ITEMS)));
    }

    function escapeHtml(s) {
        return String(s ?? "").replace(/[&<>"']/g, c => (
            { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
        ));
    }

    function timeAgo(iso) {
        const then = new Date(iso).getTime();
        if (isNaN(then)) return "";
        const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
        if (secs < 60) return "just now";
        const mins = Math.round(secs / 60);
        if (mins < 60) return `${mins}m ago`;
        const hrs = Math.round(mins / 60);
        if (hrs < 24) return `${hrs}h ago`;
        const days = Math.round(hrs / 24);
        return `${days}d ago`;
    }

    // ── DOM wiring ──
    let bellBtn = null;
    let badgeEl = null;
    let panelEl = null;
    let listEl = null;

    // Fill the header profile block (name + role) from the logged-in user, so
    // the three pages that have one stop showing different hardcoded names
    // ("System Admin" vs "Admin_Maria"). The `.role` span is the prominent
    // identity line (-> the user's name); `.portal` is the subtitle (-> their
    // role). Falls back to neutral, *consistent* text when no user is known.
    function hydrateProfile() {
        const block = document.querySelector(".profile-block .profile-text");
        if (!block) return; // page has no header profile (e.g. settings)

        let name = "Administrator";
        let role = "HCCS Portal";
        try {
            const u = (typeof getUser === "function") ? getUser() : null;
            if (u) {
                name = u.display_name || (u.email ? u.email.split("@")[0] : name);
                role = u.role || role;
            }
        } catch { /* getUser missing/unparseable -> keep fallbacks */ }

        const nameEl = block.querySelector(".role");
        const roleEl = block.querySelector(".portal");
        if (nameEl) nameEl.textContent = name;
        if (roleEl) roleEl.textContent = role;
    }

    function init() {
        hydrateProfile();

        bellBtn = document.querySelector(".header-actions .icon-btn");
        if (!bellBtn) return; // page has no header bell

        bellBtn.id = bellBtn.id || "notif-bell";
        bellBtn.classList.add("notif-bell");
        bellBtn.title = "Notifications";
        bellBtn.style.position = "relative";

        const actions = bellBtn.parentElement; // .header-actions
        actions.style.position = actions.style.position || "relative";

        // Unread count badge, drawn on top of the bell glyph.
        badgeEl = document.createElement("span");
        badgeEl.className = "notif-badge hidden";
        bellBtn.appendChild(badgeEl);

        // Dropdown panel.
        panelEl = document.createElement("div");
        panelEl.className = "notif-panel hidden";
        panelEl.innerHTML = `
            <div class="notif-panel-head">
                <span>Notifications</span>
                <button type="button" class="notif-clear">Clear all</button>
            </div>
            <div class="notif-list"></div>`;
        actions.appendChild(panelEl);
        listEl = panelEl.querySelector(".notif-list");

        bellBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            togglePanel();
        });
        panelEl.addEventListener("click", (e) => e.stopPropagation());
        panelEl.querySelector(".notif-clear").addEventListener("click", () => {
            save([]);
            renderList();
            renderBadge();
        });
        document.addEventListener("click", closePanel);

        // Live-update the badge if another tab raises a notification.
        window.addEventListener("storage", (e) => {
            if (e.key === STORAGE_KEY) { renderBadge(); renderList(); }
        });

        renderBadge();
        renderList();
    }

    function togglePanel() {
        if (!panelEl) return;
        const opening = panelEl.classList.contains("hidden");
        if (opening) {
            renderList();
            panelEl.classList.remove("hidden");
            markAllRead();
        } else {
            panelEl.classList.add("hidden");
        }
    }

    function closePanel() {
        if (panelEl) panelEl.classList.add("hidden");
    }

    function unreadCount(items) {
        return (items || load()).filter(n => !n.read).length;
    }

    function renderBadge() {
        if (!badgeEl) return;
        const n = unreadCount();
        if (n > 0) {
            badgeEl.textContent = n > 9 ? "9+" : String(n);
            badgeEl.classList.remove("hidden");
        } else {
            badgeEl.classList.add("hidden");
        }
    }

    function renderList() {
        if (!listEl) return;
        const items = load();
        if (!items.length) {
            listEl.innerHTML = `<p class="notif-empty">You're all caught up.</p>`;
            return;
        }
        listEl.innerHTML = items.map(n => `
            <div class="notif-item ${n.read ? "" : "unread"}">
                <span class="notif-icon ${escapeHtml(n.type || "info")}">${TYPE_ICONS[n.type] || TYPE_ICONS.info}</span>
                <div class="notif-body">
                    <p class="notif-title">${escapeHtml(n.title)}</p>
                    ${n.message ? `<p class="notif-msg">${escapeHtml(n.message)}</p>` : ""}
                    <span class="notif-time">${escapeHtml(timeAgo(n.time))}</span>
                </div>
            </div>`).join("");
    }

    function markAllRead() {
        const items = load();
        if (!items.some(n => !n.read)) return;
        items.forEach(n => { n.read = true; });
        save(items);
        renderBadge();
    }

    // Public: raise a notification. type ∈ document|clustering|error|info.
    function pushNotification({ type = "info", title = "", message = "" } = {}) {
        const items = load();
        items.unshift({
            id: Date.now() + "-" + Math.random().toString(36).slice(2, 7),
            type, title, message,
            time: new Date().toISOString(),
            read: false,
        });
        save(items);
        renderBadge();
        renderList();
    }

    window.pushNotification = pushNotification;

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
