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

function showLoginError(message) {
    const errorEl = document.getElementById("login-error");
    if (errorEl) {
        errorEl.textContent = message;
        errorEl.classList.remove("hidden");
    } else {
        console.error("Login Error:", message);
        alert(message);
    }
}
