
const BASE_URL = "http://localhost:8000/api";

// --- EVENT LISTENERS ---
document.addEventListener("DOMContentLoaded", () => {
    const loginBtn = document.getElementById("google-login-btn");

    if (loginBtn) {
        loginBtn.addEventListener("click", () => {
            initiateGoogleLogin();
        });
    }

    if (window.location.pathname === "/frontend/index.html" || window.location.pathname === "/") {
        handleOAuthCallback();
    }
});

// --- CORE AUTH FUNCTIONS ---

function initiateGoogleLogin() {
    window.location.href = `${BASE_URL}/auth/login`;
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
            const user = await apiGet("/auth/me"); /
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
        await apiPost("/auth/logout", {});
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
        const user = await apiGet("/auth/me");
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