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

        // Week-over-week growth: green "+" when up, red when down (the metrics
        // endpoint can return a negative query_growth).
        const up = data.query_growth >= 0;
        const growth = `${up ? "+" : ""}${data.query_growth}%`;

        // AI success badge reflects the actual rate (was a permanent "Optimal"):
        // >=90 Optimal, 70-89 Fair, <70 Low.
        const rate = data.ai_success_rate;
        const successBadge = rate >= 90 ? { cls: "badge-optimal", txt: "Optimal" }
                           : rate >= 70 ? { cls: "badge-fair", txt: "Fair" }
                           : { cls: "badge-low", txt: "Low" };

        document.getElementById("kpi-container").innerHTML = `
            <div class="kpi-card">
                <p class="kpi-label">Total Queries</p>
                <div class="kpi-value-row">
                    <span class="kpi-value">${data.total_queries.toLocaleString()}</span>
                    <span class="kpi-trend ${up ? "green" : "red"}">${growth}</span>
                </div>
            </div>
            <div class="kpi-card">
                <p class="kpi-label">Active Sessions</p>
                <div class="kpi-value-row">
                    <span class="kpi-value">${data.active_sessions.toLocaleString()}</span>
                </div>
                <p class="kpi-sub">Authenticated &middot; last 30 min</p>
            </div>
            <div class="kpi-card">
                <p class="kpi-label">AI Success Rate</p>
                <div class="kpi-value-row">
                    <span class="kpi-value">${data.ai_success_rate}%</span>
                    <span class="${successBadge.cls}">${successBadge.txt}</span>
                </div>
            </div>
            <div class="kpi-card">
                <p class="kpi-label">Indexed Knowledge</p>
                <div class="kpi-value-row">
                    <span class="kpi-value">${data.indexed_documents}</span>
                    <span class="kpi-trend">Docs</span>
                </div>
            </div>
        `;
    } catch (err) {
        showError("kpi-container", "Could not load metrics.");
    }
}


async function loadQueryVolumeChart() {
    try {
        const data = await apiGet("/dashboard/query-volume");

        // The window ends on today, so the final bar is always "today".
        const todayIndex = data.labels.length - 1;

        const ctx = document.getElementById("queryChart");
        new Chart(ctx, {
            type: "bar",
            data: {
                labels: data.labels,   // [["Sat", "Jun 14"], ["Sun", "Jun 15"], ...]
                datasets: [{
                    label: "Queries",
                    data: data.values, // [412, 380, 560, ...]
                    backgroundColor: data.values.map((_, i) =>
                        i === data.peak_day_index
                            ? "#eab308"   // most queries — gold bar
                            : "#cbd5e1"   // every other day (incl. today) — grey bar
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
                            title: (items) => {
                                const lbl = items[0].label;
                                const day = Array.isArray(lbl) ? lbl.join(" ") : lbl;
                                return `${day} — ${items[0].formattedValue} queries`;
                            },
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
                        // No axis title: dates label each bar and the card subtitle
                        // ("Last 7 days") already supplies the window context.
                        // Today is always the last bar in the window -> highlight its
                        // tick label in gold so "today" is obvious at a glance.
                        ticks: {
                            // Busiest day's label is gold to match its bar; today's
                            // label is navy + bold. Everything else is plain grey.
                            color: (ctx) => {
                                if (ctx.index === data.peak_day_index) return "#eab308"; // matches gold bar
                                if (ctx.index === todayIndex) return "#1a365d";          // today
                                return "#64748b";
                            },
                            font: (ctx) => ({
                                size: 11,
                                weight: (ctx.index === todayIndex || ctx.index === data.peak_day_index) ? "700" : "600"
                            }),
                            maxRotation: 0,
                            autoSkip: false
                        },
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

        // Latency is stored in ms but the panel shows seconds (matches the
        // paper's "average response latency in seconds").
        const latencySec = (data.avg_latency_ms / 1000).toFixed(2);
        const indexClass = data.vector_index_health ? "green" : "grey";

        // Gemini rate-limit headroom: colour the bar/badge by how close the
        // global per-window turn budget is to saturation. Healthy < 70% < Busy
        // < 100% = Saturated (students start getting rejected).
        const g = data.gemini_headroom || { enabled: false };
        const gemColor = g.status === "Saturated" ? "red"
                       : g.status === "Busy" ? "yellow" : "green";
        const geminiBlock = g.enabled ? `
            <div class="health-status">
                <div class="status-header">
                    <span class="health-title">Gemini Rate-Limit Headroom</span>
                    <span class="health-badge ${gemColor}">${g.status}</span>
                </div>
                <div class="progress-bar"><div class="fill ${gemColor}-fill" style="width:${g.percent}%"></div></div>
                <p class="health-sub">${g.used} / ${g.max} turns used this window</p>
            </div>` : "";

        // Daily budget: how much of today's server-wide question cap is spent —
        // the cumulative-spend guard for the fixed Gemini key. Healthy < 70% <
        // Low < 100% = Exhausted (chat pauses until tomorrow).
        const d = data.daily_budget || { enabled: false };
        const dayColor = d.status === "Exhausted" ? "red"
                       : d.status === "Low" ? "yellow" : "green";
        const dailyBlock = d.enabled ? `
            <div class="health-status">
                <div class="status-header">
                    <span class="health-title">Daily Budget (Gemini)</span>
                    <span class="health-badge ${dayColor}">${d.status}</span>
                </div>
                <div class="progress-bar"><div class="fill ${dayColor}-fill" style="width:${d.percent}%"></div></div>
                <p class="health-sub">${d.used} / ${d.max} questions used today</p>
            </div>` : "";

        // Kill switch indicator: only shown when chat has been turned off.
        const chatOffBlock = (data.chat_enabled === false) ? `
            <div class="health-status">
                <div class="status-header">
                    <span class="health-title">Chatbot Availability</span>
                    <span class="health-badge red">Paused</span>
                </div>
                <p class="health-sub">The student chatbot is turned off in Portal Settings.</p>
            </div>` : "";

        document.getElementById("system-health").innerHTML = `
            <div class="health-status">
                <div class="status-header">
                    <div class="icon-box ${indexClass}"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="16" height="16" rx="2" ry="2"></rect><rect x="9" y="9" width="6" height="6"></rect><line x1="9" y1="1" x2="9" y2="4"></line><line x1="15" y1="1" x2="15" y2="4"></line><line x1="9" y1="20" x2="9" y2="23"></line><line x1="15" y1="20" x2="15" y2="23"></line><line x1="20" y1="9" x2="23" y2="9"></line><line x1="20" y1="14" x2="23" y2="14"></line><line x1="1" y1="9" x2="4" y2="9"></line><line x1="1" y1="14" x2="4" y2="14"></line></svg></div>
                    <span class="health-title">RAG Vector Index</span>
                    <span class="health-badge ${indexClass}">${data.vector_index_status}</span>
                </div>
                <div class="progress-bar"><div class="fill ${indexClass}-fill" style="width:${data.vector_index_health}%"></div></div>
            </div>

            ${chatOffBlock}
            ${geminiBlock}
            ${dailyBlock}

            <div class="metric-row">
                <span class="metric-label">Average Latency</span>
                <span class="metric-value">${latencySec}s</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Memory Usage</span>
                <span class="metric-value">${data.memory_usage_percent}%</span>
            </div>

            <div class="health-trend">
                <span class="metric-label">Latency &middot; last 7 days</span>
                <div class="trend-chart"><canvas id="latencyChart"></canvas></div>
            </div>
        `;

        renderLatencyTrend(data.latency_trend);
    } catch (err) {
        showError("system-health", "Could not load system health.");
    }
}


function renderLatencyTrend(trend) {
    if (!trend) return;
    const ctx = document.getElementById("latencyChart");
    if (!ctx) return;

    // Plot per-day average latency in seconds; null days (no traffic) are
    // skipped via spanGaps so a quiet day doesn't read as "0s".
    const seconds = trend.values.map(v => (v == null ? null : v / 1000));
    new Chart(ctx, {
        type: "line",
        data: {
            labels: trend.labels,   // [["Sat", "Jun 14"], ...]
            datasets: [{
                data: seconds,
                borderColor: "#3b82f6",
                backgroundColor: "rgba(59, 130, 246, 0.12)",
                fill: true,
                tension: 0.35,
                spanGaps: true,
                borderWidth: 2,
                pointRadius: 2,
                pointBackgroundColor: "#3b82f6",
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        title: (items) => {
                            const lbl = items[0].label;
                            return Array.isArray(lbl) ? lbl.join(" ") : lbl;
                        },
                        label: (item) => item.raw == null ? "No traffic" : `${item.formattedValue}s avg latency`,
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: { precision: 1, font: { size: 9 }, color: "#94a3b8", callback: (v) => `${v}s` },
                    grid: { color: "#f1f5f9" }
                },
                x: {
                    ticks: { font: { size: 9 }, color: "#94a3b8", maxRotation: 0, autoSkip: true, maxTicksLimit: 7 },
                    grid: { display: false }
                }
            }
        }
    });
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
        "Academic Policy": "intent-grey",
        // Catch-all bucket from intent.py for queries that match no category.
        "General Inquiry": "intent-grey"
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