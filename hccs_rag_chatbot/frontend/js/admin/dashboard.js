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

        const ctx = document.getElementById("queryChart");
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
                    borderRadius: 4,
                    maxBarThickness: 64
                }]
            },
            options: {
                responsive: true,
                // Let the chart fill the container's width AND height instead
                // of locking to a 2:1 ratio (which left it small + left-aligned).
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: (items) => `${items[0].label} (${items[0].formattedValue} queries)`,
                            label: () => "Student questions received",
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: { precision: 0 },
                        title: { display: true, text: "Queries", color: "#94a3b8", font: { size: 11, weight: "600" } },
                        grid: { color: "#f1f5f9" }
                    },
                    x: {
                        title: { display: true, text: "Day (last 7 days)", color: "#94a3b8", font: { size: 11, weight: "600" } },
                        grid: { display: false }
                    }
                }
            }
        });
    } catch (err) {
        showError("queryChart", "Could not load chart.");
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


// The inquiries table has two modes:
//   - Compact (default): page 1, 10 rows. The header search filters these
//     loaded rows client-side — cheap, no round-trips.
//   - Browse ("View All Activity"): the full history, paginated server-side,
//     with the header search querying the server so it spans every page.
const BROWSE_PAGE_SIZE = 15;
let recentInquiries = [];      // rows currently loaded into the table
let inquirySearchTerm = "";
let showingAllActivity = false;
// True when browse mode was entered by typing in the search box (not the
// button). Lets us drop back to the compact view once the search is cleared,
// while leaving a manually-opened browse view alone.
let autoExpandedBySearch = false;
let currentPage = 1;
let totalInquiries = 0;
let searchDebounce = null;

// Update the table's mode (label, heading, scroll cap) without loading data.
function setActivityMode(showAll) {
    showingAllActivity = showAll;

    const link = document.getElementById("view-all-activity");
    if (link) link.textContent = showAll ? "SHOW RECENT ONLY" : "VIEW ALL ACTIVITY";

    const heading = document.getElementById("inquiries-heading");
    if (heading) heading.textContent = showAll ? "ALL STUDENT INQUIRIES" : "RECENT STUDENT INQUIRIES";

    // Cap the height + scroll in browse mode so a full page of rows doesn't
    // push the rest of the dashboard down.
    document.querySelector(".table-responsive")?.classList.toggle("expanded", showAll);
}

async function loadRecentInquiries() {
    try {
        const params = new URLSearchParams();
        if (showingAllActivity) {
            params.set("page", currentPage);
            params.set("page_size", BROWSE_PAGE_SIZE);
            params.set("q", inquirySearchTerm.trim());
        } else {
            params.set("page", 1);
            params.set("page_size", 10);
        }

        const data = await apiGet(`/dashboard/recent-inquiries?${params.toString()}`);
        recentInquiries = Array.isArray(data?.items) ? data.items : [];
        totalInquiries = typeof data?.total === "number" ? data.total : recentInquiries.length;

        renderInquiries();
        renderPager();
    } catch (err) {
        showError("inquiries-tbody", "Could not load recent inquiries.");
    }
}

function wireViewAllActivity() {
    const link = document.getElementById("view-all-activity");
    if (!link) return;

    link.addEventListener("click", async (e) => {
        e.preventDefault();
        setActivityMode(!showingAllActivity);
        autoExpandedBySearch = false; // manual toggle now owns the mode
        currentPage = 1;
        await loadRecentInquiries();
    });
}

function renderPager() {
    const pager = document.getElementById("inquiries-pager");
    if (!pager) return;

    if (!showingAllActivity) {
        pager.classList.add("hidden");
        pager.innerHTML = "";
        return;
    }

    const totalPages = Math.max(1, Math.ceil(totalInquiries / BROWSE_PAGE_SIZE));
    if (currentPage > totalPages) currentPage = totalPages;

    pager.classList.remove("hidden");
    pager.innerHTML = `
        <button class="pager-btn" id="pager-prev" ${currentPage <= 1 ? "disabled" : ""}>Prev</button>
        <span class="pager-info">Page ${currentPage} of ${totalPages} · ${totalInquiries.toLocaleString()} total</span>
        <button class="pager-btn" id="pager-next" ${currentPage >= totalPages ? "disabled" : ""}>Next</button>
    `;

    document.getElementById("pager-prev")?.addEventListener("click", () => {
        if (currentPage > 1) { currentPage--; loadRecentInquiries(); }
    });
    document.getElementById("pager-next")?.addEventListener("click", () => {
        if (currentPage < totalPages) { currentPage++; loadRecentInquiries(); }
    });
}

function renderInquiries() {
    const tbody = document.getElementById("inquiries-tbody");
    if (!tbody) return;

    // In browse mode the server already filtered + paginated; only the compact
    // mode filters its 10 loaded rows on the client.
    const term = inquirySearchTerm.trim().toLowerCase();
    const rows = (!showingAllActivity && term)
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
        const hasTerm = inquirySearchTerm.trim().length > 0;

        // Compact + typing -> auto-expand so the search spans the whole history.
        if (!showingAllActivity && hasTerm) {
            setActivityMode(true);
            autoExpandedBySearch = true;
        }

        // Cleared the search that auto-expanded us -> collapse back to recent.
        if (showingAllActivity && autoExpandedBySearch && !hasTerm) {
            setActivityMode(false);
            autoExpandedBySearch = false;
            currentPage = 1;
            loadRecentInquiries();
            return;
        }

        if (showingAllActivity) {
            // Browse mode: search the server across all pages (debounced,
            // reset to the first page of results).
            currentPage = 1;
            clearTimeout(searchDebounce);
            searchDebounce = setTimeout(loadRecentInquiries, 250);
        } else {
            renderInquiries();
        }
    });
}


function intentClass(intent) {
    const map = {
        "Scholarship Info": "intent-blue",
        "Enrollment": "intent-amber",
        "Campus Directory": "intent-purple",
        "Payments": "intent-teal",
        "Portal & Accounts": "intent-indigo",
        "Documents & Records": "intent-cyan",
        "Student Welfare": "intent-pink",
        "Schedule & Events": "intent-rose",
        "Facilities & Services": "intent-green",
        "Academic Policy": "intent-grey"
    };
    return map[intent] || "intent-grey";
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