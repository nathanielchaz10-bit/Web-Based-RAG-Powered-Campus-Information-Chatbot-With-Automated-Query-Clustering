

const BASE_URL = "http://localhost:8000";

// Token helpers //

function getToken() {
    return sessionStorage.getItem("hccs_token");
}

function setToken(token) {
    sessionStorage.setItem("hccs_token", token);
}

function removeToken() {
    sessionStorage.removeItem("hccs_token");
    sessionStorage.removeItem("hccs_user");
}

function getUser() {
    const raw = sessionStorage.getItem("hccs_user");
    return raw ? JSON.parse(raw) : null;
}

function setUser(user) {
    sessionStorage.setItem("hccs_user", JSON.stringify(user));
}

// Core fetch wrapper //

async function apiFetch(endpoint, options = {}) {
    const token = getToken();

    const headers = {
        "Content-Type": "application/json",
        ...(token ? { "Authorization": `Bearer ${token}` } : {}),
        ...(options.headers || {})
    };

    const config = {
        ...options,
        headers
    };

    try {
        const response = await fetch(`${BASE_URL}${endpoint}`, config);

        // Token expired or invalid — redirect to login //
        if (response.status === 401) {
            removeToken();
            window.location.href = "/frontend/index.html";
            return null;
        }

        // Access denied //
        if (response.status === 403) {
            const data = await response.json();
            throw new Error(data.detail || "Access denied");
        }

        // Rate limited //
        if (response.status === 429) {
            throw new Error("Too many requests. Please wait a moment.");
        }

        // Other errors //
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.detail || `Request failed: ${response.status}`);
        }

        // Return JSON if content exists //
        const text = await response.text();
        return text ? JSON.parse(text) : null;

    } catch (error) {
        console.error(`API Error [${endpoint}]:`, error.message);
        throw error;
    }
}

// Convenience methods //

async function apiGet(endpoint) {
    return apiFetch(endpoint, { method: "GET" });
}

async function apiPost(endpoint, body) {
    return apiFetch(endpoint, {
        method: "POST",
        body: JSON.stringify(body)
    });
}

async function apiPut(endpoint, body) {
    return apiFetch(endpoint, {
        method: "PUT",
        body: JSON.stringify(body)
    });
}

async function apiDelete(endpoint) {
    return apiFetch(endpoint, { method: "DELETE" });
}

// File upload — uses FormData, no Content-Type header //
async function apiUpload(endpoint, formData) {
    const token = getToken();
    const response = await fetch(`${BASE_URL}${endpoint}`, {
        method: "POST",
        headers: token ? { "Authorization": `Bearer ${token}` } : {},
        body: formData
    });

    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "Upload failed");
    }

    return response.json();
}