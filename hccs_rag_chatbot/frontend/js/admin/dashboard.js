document.addEventListener("DOMContentLoaded", async () => {

    // 1. Verify user is authenticated and is an admin
    const user = await requireAdmin();
    if (!user) return; // requireAdmin handles redirect

    // 2. Inject user info into sidebar
    renderSidebar(user);

    // 3. Load all dashboard data in parallel
    await Promise.all([
        loadMetricCards(),
        loadQueryVolumeChart(),
        loadSystemHealth(),
        loadRecentInquiries()
    ]);

    // 4. Wire the header search + "View All Activity" toggle
    wireDashboardSearch();
    wireViewAllActivity();

});


function renderSidebar(user) {
    // dashboard.html already ships a complete, styled static sidebar and has no
    // element with id="sidebar", so there is nothing to populate here. Without
    // this guard, getElementById returns null and the .innerHTML assignment
    // throws, which aborts the rest of DOMContentLoaded — leaving every KPI
    // card, chart and the recent-inquiries table empty.
    const sidebar = document.getElementById("sidebar");
    if (!sidebar) return;

    const initials = user.display_name
        .split(" ")
        .map(n => n[0])
        .join("")
        .toUpperCase()
        .slice(0, 2);

    sidebar.innerHTML = `
        <div class="sidebar-brand">
            <p class="sidebar-brand-title">HCCS Admin Portal</p>
            <p class="sidebar-brand-sub">Holy Child Catholic School</p>
        </div>
        <nav class="sidebar-nav">
            <a href="/frontend/admin/dashboard.html"
               class="nav-item active">
                <i class="ti ti-layout-dashboard"></i> Dashboard Overview
            </a>
            <a href="/frontend/admin/clusters.html"
               class="nav-item">
                <i class="ti ti-chart-dots"></i> Query Clusters
            </a>
            <a href="/frontend/admin/documents.html"
               class="nav-item">
                <i class="ti ti-folder-open"></i> Document Directory
            </a>
            <a href="/frontend/admin/settings.html"
               class="nav-item">
                <i class="ti ti-settings"></i> Portal Settings
            </a>
        </nav>
        <div class="sidebar-footer">
            <div class="avatar">${initials}</div>
            <div>
                <p class="sidebar-name">${user.display_name}</p>
                <p class="sidebar-role">${user.role}</p>
            </div>
            <button onclick="logout()" title="Logout">
                <i class="ti ti-logout"></i>
            </button>
        </div>
    `;
}


async function loadMetricCards() {
    try {
        const data = await apiGet("/dashboard/metrics");

        document.getElementById("metric-cards").innerHTML = `
            <div class="metric-card">
                <p class="metric-label">Total Queries</p>
                <p class="metric-value">
                    ${data.total_queries.toLocaleString()}
                    <span class="metric-tag green">
                        +${data.query_growth}%
                    </span>
                </p>
            </div>
            <div class="metric-card">
                <p class="metric-label">Active Sessions</p>
                <p class="metric-value">
                    ${data.active_sessions.toLocaleString()}
                </p>
                <p class="metric-sub">Authenticated · last 30 min</p>
            </div>
            <div class="metric-card">
                <p class="metric-label">AI Success Rate</p>
                <p class="metric-value">
                    ${data.ai_success_rate}%
                    <span class="metric-tag blue">Optimal</span>
                </p>
            </div>
            <div class="metric-card">
                <p class="metric-label">Indexed Knowledge</p>
                <p class="metric-value">
                    ${data.indexed_documents} Docs
                </p>
            </div>
        `;
    } catch (err) {
        showError("metric-cards", "Could not load metrics.");
    }
}


async function loadQueryVolumeChart() {
    try {
        const data = await apiGet("/dashboard/query-volume");

        const ctx = document.getElementById("query-volume-chart");
        new Chart(ctx, {
            type: "bar",
            data: {
                labels: data.labels,   // ["Mon", "Tue", ...]
                datasets: [{
                    label: "Queries",
                    data: data.values, // [412, 380, 560, ...]
                    backgroundColor: data.values.map((_, i) =>
                        i === data.peak_day_index
                            ? "#1a365d"
                            : "#cbd5e1"
                    ),
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true },
                    x: { grid: { display: false } }
                }
            }
        });
    } catch (err) {
        showError("query-volume-chart", "Could not load chart.");
    }
}


async function loadSystemHealth() {
    try {
        const data = await apiGet("/dashboard/system-health");

        document.getElementById("system-health").innerHTML = `
            <div class="health-row">
                <div>
                    <p class="health-label">RAG Vector Index</p>
                    <div class="progress-bar">
                        <div class="progress-fill"
                             style="width:${data.vector_index_health}%">
                        </div>
                    </div>
                </div>
                <span class="health-status ${data.vector_index_status.toLowerCase()}">
                    ${data.vector_index_status}
                </span>
            </div>
            <div class="health-row">
                <span>Average Latency</span>
                <strong>${data.avg_latency_ms}ms</strong>
            </div>
            <div class="health-row">
                <span>Memory Usage</span>
                <strong>${data.memory_usage_percent}%</strong>
            </div>
        `;
    } catch (err) {
        showError("system-health", "Could not load system health.");
    }
}


// Recent inquiries are cached so the header search can filter them client-side
// (by question text, student email, intent or sentiment) without re-fetching.
// "View All Activity" swaps the capped recent set for the full history, which
// also makes the search meaningful (it searches whatever is currently loaded).
let recentInquiries = [];
let inquirySearchTerm = "";
let showingAllActivity = false;

async function loadRecentInquiries() {
    try {
        const limit = showingAllActivity ? 0 : 10; // limit<=0 -> full history
        const data = await apiGet(`/dashboard/recent-inquiries?limit=${limit}`);
        recentInquiries = Array.isArray(data) ? data : [];
        renderInquiries();
    } catch (err) {
        showError("inquiries-tbody", "Could not load recent inquiries.");
    }
}

function wireViewAllActivity() {
    const link = document.getElementById("view-all-activity");
    if (!link) return;

    link.addEventListener("click", async (e) => {
        e.preventDefault();
        showingAllActivity = !showingAllActivity;

        link.textContent = showingAllActivity ? "SHOW RECENT ONLY" : "VIEW ALL ACTIVITY";
        const heading = document.getElementById("inquiries-heading");
        if (heading) {
            heading.textContent = showingAllActivity ? "ALL STUDENT INQUIRIES" : "RECENT STUDENT INQUIRIES";
        }
        // Cap the height + scroll only when the full list is shown, so a long
        // history doesn't push the rest of the page down.
        document.querySelector(".table-responsive")?.classList.toggle("expanded", showingAllActivity);

        await loadRecentInquiries();
    });
}

function renderInquiries() {
    const tbody = document.getElementById("inquiries-tbody");
    if (!tbody) return;

    const term = inquirySearchTerm.trim().toLowerCase();
    const rows = term
        ? recentInquiries.filter(r =>
            `${r.query_text} ${r.user_email} ${r.intent} ${r.sentiment}`.toLowerCase().includes(term))
        : recentInquiries;

    tbody.innerHTML = "";

    if (!rows.length) {
        const msg = term ? "No inquiries match your search." : "No queries yet.";
        tbody.innerHTML = `
            <tr>
                <td colspan="5" class="empty-state">${msg}</td>
            </tr>
        `;
        return;
    }

    rows.forEach(row => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${row.timestamp}</td>
            <td>${escapeHtml(row.query_text)}</td>
            <td class="text-secondary">${row.user_email}</td>
            <td>
                <span class="intent-pill ${intentClass(row.intent)}">
                    ${row.intent}
                </span>
            </td>
            <td>
                <span class="sentiment ${sentimentClass(row.sentiment)}">
                    ${row.sentiment}
                </span>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function wireDashboardSearch() {
    const input = document.querySelector(".search-bar input");
    if (!input) return;
    input.addEventListener("input", (e) => {
        inquirySearchTerm = e.target.value || "";
        renderInquiries();
    });
}


function intentClass(intent) {
    const map = {
        "Scholarship Info": "intent-blue",
        "Enrollment": "intent-amber",
        "Campus Directory": "intent-purple",
        "Payments": "intent-teal",
        "Academic Policy": "intent-gray"
    };
    return map[intent] || "intent-gray";
}

function sentimentClass(sentiment) {
    const map = {
        // Labels produced by app/services/nlp/sentiment.py
        "Positive / Inquisitive": "sentiment-positive",
        "Neutral / Transactional": "sentiment-neutral",
        "Urgent / Frustrated": "sentiment-urgent",
        // Short-form fallbacks (e.g. the API's "Neutral" default when a row
        // pre-dates NLP enrichment and has no stored sentiment).
        "Positive": "sentiment-positive",
        "Negative": "sentiment-urgent",
        "Neutral": "sentiment-neutral"
    };
    return map[sentiment] || "sentiment-neutral";
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.appendChild(document.createTextNode(text));
    return div.innerHTML;
}

function showError(elementId, message) {
    const el = document.getElementById(elementId);
    if (el) {
        el.innerHTML = `
            <p class="error-state">
                <i class="ti ti-alert-circle"></i> ${message}
            </p>
        `;
    }
}