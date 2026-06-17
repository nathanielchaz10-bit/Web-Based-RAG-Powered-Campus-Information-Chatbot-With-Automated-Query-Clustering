// Auth flow. Requires api.js (apiGet/apiPost/token helpers) to be loaded first.
// Auth endpoints are mounted under /api on the backend; api.js BASE_URL has no
// /api, so the calls below include it explicitly.

const AUTH_BASE = "http://localhost:8000/api";

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
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    const error = params.get("error");

    if (error) {
        showLoginError(error);
        return;
    }

    if (token) {
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

async function requireAuth() {
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

function injectDevLogin() {
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
