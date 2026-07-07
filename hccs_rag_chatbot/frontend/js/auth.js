// Auth flow. Requires api.js (apiGet/apiPost/token helpers) to be loaded first.
// Auth endpoints are mounted under /api on the backend; api.js BASE_URL has no
// /api, so the calls below include it explicitly.

// Relative (same-origin) — see the BASE_URL note in api.js. Auth routes are
// mounted under /api on the backend.
const AUTH_BASE = "/api";

document.addEventListener("DOMContentLoaded", () => {
    const loginBtn = document.getElementById("google-login-btn");
    if (loginBtn) {
        loginBtn.addEventListener("click", () => initiateGoogleLogin());
    }

    const path = window.location.pathname;
    if (path === "/frontend/index.html" || path === "/" || path.endsWith("/frontend/")) {
        handleOAuthCallback();
        injectDevLogin();
    }

    // On admin pages, fill the header profile (name / role / Google photo).
    // No-op anywhere without a .profile-block (student chat, login page).
    populateAdminProfile();
});

// --- CORE AUTH FUNCTIONS ---

function initiateGoogleLogin() {
    window.location.href = `${AUTH_BASE}/auth/login`;
}

async function handleOAuthCallback() {
    // Errors stay in the query string (no secret); the token arrives in the URL
    // fragment (#token=...) so it never hits server logs or Referer headers.
    const error = new URLSearchParams(window.location.search).get("error");
    if (error) {
        showLoginError(error);
        return;
    }

    const token = new URLSearchParams(window.location.hash.slice(1)).get("token");
    if (token) {
        // Scrub the token from the address bar / history before doing anything.
        history.replaceState(null, "", window.location.pathname);
        setToken(token);
        try {
            const user = await apiGet("/api/auth/me");
            setUser(user);
            redirectByRole(user.role);
        } catch (err) {
            removeToken();
            showLoginError("Could not verify your account. Please try again.");
        }
    }
}

function redirectByRole(role) {
    if (role === "Student") {
        window.location.href = "/frontend/student/index.html";
    } else if (["Head Admin", "Registrar", "Finance Officer"].includes(role)) {
        window.location.href = "/frontend/admin/dashboard.html";
    } else {
        window.location.href = "/frontend/index.html";
    }
}

async function logout() {
    try {
        await apiPost("/api/auth/logout", {});
    } catch (err) {
        console.error("Logout error:", err);
    } finally {
        removeToken();
        window.location.href = "/frontend/index.html";
    }
}

// --- ROUTE GUARDS ---

// Re-validate when a page is restored from the browser's back/forward cache
// (bfcache). The browser can show a fully-rendered cached page WITHOUT re-running
// page scripts, so after logout, pressing Back would otherwise reveal the old
// authenticated page. On a bfcache restore with no token, bounce to login.
// Idempotent: only the first call attaches the listener.
let _bfcacheGuardInstalled = false;
function installBfcacheGuard() {
    if (_bfcacheGuardInstalled) return;
    _bfcacheGuardInstalled = true;
    window.addEventListener("pageshow", (event) => {
        if (event.persisted && !getToken()) {
            window.location.href = "/frontend/index.html";
        }
    });
}

async function requireAuth() {
    installBfcacheGuard();
    const token = getToken();
    if (!token) {
        window.location.href = "/frontend/index.html";
        return null;
    }
    try {
        const user = await apiGet("/api/auth/me");
        setUser(user);
        return user;
    } catch (err) {
        removeToken();
        window.location.href = "/frontend/index.html";
        return null;
    }
}

async function requireAdmin() {
    const user = await requireAuth();
    if (!user) return null;

    const adminRoles = ["Head Admin", "Registrar", "Finance Officer"];
    if (!adminRoles.includes(user.role)) {
        window.location.href = "/frontend/student/index.html";
        return null;
    }
    return user;
}

// Populate the admin header's profile block (top-right) with the signed-in user:
// real name, role, and Google profile photo. The block ships with placeholder
// text ("Admin_Maria" / a person icon); this replaces it with the actual account.
// Safe to call on every page — it no-ops where there's no .profile-block.
async function populateAdminProfile() {
    const block = document.querySelector(".profile-block");
    if (!block || !getToken()) return;

    let user;
    try {
        user = await apiGet("/api/auth/me");
    } catch (err) {
        return; // not signed in / unreachable — the page's own guard handles it
    }

    const nameEl = block.querySelector(".profile-text .role");
    const roleEl = block.querySelector(".profile-text .portal");
    if (nameEl) nameEl.textContent = user.display_name || user.email || "Admin";
    if (roleEl) roleEl.textContent = user.role || "HCCS Portal";

    // Swap the placeholder person icon for the Google photo when we have one.
    // referrerpolicy=no-referrer: Google avatar URLs often 403 when a Referer is
    // sent, which would show a broken image.
    if (user.picture) {
        const avatar = block.querySelector(".avatar-sm");
        if (avatar) {
            avatar.innerHTML = '<img src="' + user.picture + '" alt="Profile" referrerpolicy="no-referrer" style="width:100%;height:100%;border-radius:50%;object-fit:cover;">';
        }
    }

    wireProfileMenu(block, user);
}

// Turn the header profile block into a click-to-open account menu whose job is
// Sign out — replacing the logout button that used to sit loose in the sidebar.
// Closes on outside-click or Escape. Idempotent per block.
function wireProfileMenu(block, user) {
    if (block.dataset.menuWired) return;
    block.dataset.menuWired = "1";

    const menu = document.createElement("div");
    menu.className = "profile-menu hidden";
    menu.setAttribute("role", "menu");
    menu.innerHTML =
        '<div class="profile-menu-head">' +
            '<span class="profile-menu-name"></span>' +
            '<span class="profile-menu-email"></span>' +
        '</div>' +
        '<button class="profile-menu-item" type="button" role="menuitem">' +
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>' +
            'Sign out' +
        '</button>';
    // User-controlled text set via textContent (never innerHTML) — no XSS.
    menu.querySelector(".profile-menu-name").textContent = user.display_name || "Admin";
    menu.querySelector(".profile-menu-email").textContent = user.email || "";
    block.appendChild(menu);

    block.setAttribute("role", "button");
    block.setAttribute("tabindex", "0");
    block.setAttribute("aria-haspopup", "menu");
    block.setAttribute("aria-expanded", "false");

    const setOpen = (open) => {
        menu.classList.toggle("hidden", !open);
        block.setAttribute("aria-expanded", open ? "true" : "false");
    };

    block.addEventListener("click", (e) => {
        if (menu.contains(e.target)) return;   // clicks inside the menu don't toggle it
        setOpen(menu.classList.contains("hidden"));
    });
    block.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen(menu.classList.contains("hidden")); }
        else if (e.key === "Escape") setOpen(false);
    });
    menu.querySelector(".profile-menu-item").addEventListener("click", () => logout());
    document.addEventListener("click", (e) => {
        if (!block.contains(e.target)) setOpen(false);
    });
}

// --- DEV LOGIN (local testing without Google OAuth) ---
// Calls /api/auth/dev-login, which only works while the backend is in DEV_MODE.

async function devLogin(role) {
    try {
        const data = await apiGet(`/api/auth/dev-login?role=${encodeURIComponent(role)}`);
        setToken(data.access_token);
        setUser(data.user);
        redirectByRole(data.user.role);
    } catch (err) {
        showLoginError("Dev login failed: " + err.message);
    }
}

async function injectDevLogin() {
    // Only show the Google-login bypass when the server is actually in DEV_MODE.
    // Fail closed: if we can't confirm it, don't render the panel.
    try {
        const cfg = await apiGet("/api/auth/config");
        if (!cfg || !cfg.dev_mode) return;
    } catch (err) {
        return;
    }

    const card = document.querySelector(".login-card");
    if (!card || document.getElementById("dev-login-panel")) return;

    const panel = document.createElement("div");
    panel.id = "dev-login-panel";
    panel.style.cssText = "margin-top:16px;padding-top:12px;border-top:1px dashed #cbd5e1;";
    panel.innerHTML = `
        <p style="font-size:0.7rem;color:#94a3b8;letter-spacing:0.08em;margin-bottom:8px;">
            DEV ONLY — bypass Google login
        </p>
        <div style="display:flex;gap:8px;justify-content:center;">
            <button type="button" id="dev-student" style="flex:1;padding:8px;border:1px solid #cbd5e1;border-radius:6px;background:#fff;cursor:pointer;">Student</button>
            <button type="button" id="dev-admin" style="flex:1;padding:8px;border:1px solid #cbd5e1;border-radius:6px;background:#fff;cursor:pointer;">Head Admin</button>
        </div>
    `;
    card.appendChild(panel);
    document.getElementById("dev-student").addEventListener("click", () => devLogin("Student"));
    document.getElementById("dev-admin").addEventListener("click", () => devLogin("Head Admin"));
}

// Friendly copy for the short error codes the backend puts in ?error=.
// Anything not listed (e.g. JS-supplied messages) is shown as-is.
const LOGIN_ERROR_MESSAGES = {
    "Access denied":
        "The chatbot is only available to Holy Child Catholic School accounts. " +
        "Please sign in with your @hccs.edu.ph Google account.",
    "Account deactivated":
        "Your account has been deactivated. If you think this is a mistake, " +
        "please contact the school office.",
};

function showLoginError(message) {
    const errorEl = document.getElementById("login-error");
    const text = LOGIN_ERROR_MESSAGES[message] || message;
    if (errorEl) {
        errorEl.textContent = text;
        errorEl.classList.remove("hidden");
    } else {
        console.error("Login Error:", text);
        alert(text);
    }
}
