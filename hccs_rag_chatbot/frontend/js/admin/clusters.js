// ──────────────────────────────────────────────
// clusters.js
// Query Clusters & Analytics page (admin).
//
// Expects two backend endpoints (app/api/clusters.py) that don't exist yet —
// build them to return this shape:
//
//   GET /clusters/overview
//     -> {
//          total_queries: number,                // ALL QueryLog rows, not just clustered ones
//          query_growth_percent: number | null,   // null/omitted hides the trend line
//          sentiment: { positive: number, neutral: number, urgent: number } | null,
//          last_run_status: "RUNNING" | "COMPLETED" | "INSUFFICIENT"
//                            | "FAILED_EXTRACTION" | "FAILED_ML" | null,
//          clusters: [
//            { cluster_id, cluster_label, cluster_status, cluster_percentage,
//              query_count, keywords: string[] },
//            ...
//          ]
//        }
//     Before any successful run: clusters: [], sentiment/growth may be null,
//     total_queries still reflects logged queries.
//
//   POST /clusters/run   (body: {})
//     -> same shape as GET /clusters/overview, reflecting the just-finished run.
//     Triggers app.services.clustering.pipeline.run_clustering_pipeline()
//     server-side. This runs synchronously for now (fine at low volume) —
//     worth moving to a background task + polling once embedding batches
//     start taking a while.
//
// Depends on api.js (apiGet/apiPost) and auth.js (requireAdmin) being loaded
// beforehand.
// ──────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", async () => {
    // const user = await requireAdmin();
    // if (!user) return;

    await loadClusterOverview();
    wireRunClusteringButton();
    wireClusterSearch();
    wireModalLogic();
});

let topicChart = null;

// Latest clusters from the server, plus the current header-search term. The
// search box filters this list (by label + keywords) into what the chart and
// cards actually render, without re-fetching.
let allClusters = [];
let clusterSearchTerm = "";

// Raw-queries modal state. Loaded once per "View Raw Queries" click and kept
// around so the All / Low Confidence toggle can re-filter without re-fetching.
let currentClusterQueries = [];
let currentQueryFilter = "all";

async function loadClusterOverview() {
    try {
        const data = await apiGet("/clusters/overview");
        renderOverview(data);
    } catch (err) {
        console.error("Could not load cluster overview:", err);
        renderOverview(null); // fall back to the zeroed/empty state, not a blank page
    }
}

function renderOverview(data) {
    allClusters = (data && Array.isArray(data.clusters)) ? data.clusters : [];

    renderTotalQueries(data?.total_queries ?? 0, data?.query_growth_percent);
    renderSentiment(data?.sentiment);
    applyClusterFilter();
    renderClusteringStatus(data?.last_run_status);
}

// Filter allClusters by the header search term, matching against the cluster
// label and its keywords, then re-render the chart + cards from the result.
function getFilteredClusters() {
    const term = clusterSearchTerm.trim().toLowerCase();
    if (!term) return allClusters;
    return allClusters.filter(c => {
        const label = (c.cluster_label || "").toLowerCase();
        const keywords = Array.isArray(c.keywords) ? c.keywords.join(" ").toLowerCase() : "";
        return label.includes(term) || keywords.includes(term);
    });
}

function applyClusterFilter() {
    const filtered = getFilteredClusters();
    const term = clusterSearchTerm.trim();

    // When a search hides every cluster (but clusters do exist), say "no
    // matches" instead of the default "no clusters yet — run clustering" copy.
    const cardEmpty = document.getElementById("cluster-empty-state");
    const chartEmpty = document.getElementById("chart-empty-state");
    if (term && allClusters.length && !filtered.length) {
        if (cardEmpty) cardEmpty.textContent = `No clusters match “${term}”.`;
        if (chartEmpty) chartEmpty.textContent = "No matches.";
    } else {
        if (cardEmpty) cardEmpty.innerHTML =
            'No clusters yet. Click <strong>Run Clustering</strong> once there are enough student queries logged.';
        if (chartEmpty) chartEmpty.textContent = "No clusters yet.";
    }

    renderChart(filtered);
    renderClusterCards(filtered);
}

function wireClusterSearch() {
    const input = document.querySelector(".search-bar input");
    if (!input) return;
    input.addEventListener("input", (e) => {
        clusterSearchTerm = e.target.value || "";
        applyClusterFilter();
    });
}

function renderTotalQueries(total, growthPercent) {
    const valueEl = document.getElementById("total-queries-value");
    const trendEl = document.getElementById("total-queries-trend");
    const trendText = document.getElementById("total-queries-trend-text");

    if (valueEl) valueEl.textContent = total.toLocaleString();

    if (trendEl && trendText) {
        if (typeof growthPercent === "number") {
            trendText.textContent = `${growthPercent >= 0 ? "+" : ""}${growthPercent}% from last week`;
            trendEl.classList.remove("hidden");
        } else {
            trendEl.classList.add("hidden");
        }
    }
}

function renderSentiment(sentiment) {
    const rows = [
        { key: "positive", pctId: "sentiment-positive-pct", fillId: "sentiment-positive-fill" },
        { key: "neutral", pctId: "sentiment-neutral-pct", fillId: "sentiment-neutral-fill" },
        { key: "urgent", pctId: "sentiment-urgent-pct", fillId: "sentiment-urgent-fill" },
    ];

    rows.forEach(row => {
        const pct = sentiment && typeof sentiment[row.key] === "number" ? sentiment[row.key] : 0;
        const pctEl = document.getElementById(row.pctId);
        const fillEl = document.getElementById(row.fillId);
        if (pctEl) pctEl.textContent = `${pct}%`;
        if (fillEl) fillEl.style.width = `${pct}%`;
    });
}

function renderChart(clusters) {
    const canvas = document.getElementById("topicChart");
    const emptyState = document.getElementById("chart-empty-state");
    if (!canvas) return;

    if (topicChart) {
        topicChart.destroy();
        topicChart = null;
    }

    if (!clusters.length) {
        canvas.classList.add("hidden");
        if (emptyState) emptyState.classList.remove("hidden");
        return;
    }

    canvas.classList.remove("hidden");
    if (emptyState) emptyState.classList.add("hidden");

    if (typeof Chart === "undefined") return;

    topicChart = new Chart(canvas.getContext("2d"), {
        type: "bar",
        data: {
            labels: clusters.map(c => c.cluster_label),
            datasets: [{
                label: "Query Volume",
                data: clusters.map(c => c.query_count),
                backgroundColor: ["#152e51", "#0ea5e9", "#7dd3fc", "#e0f2fe", "#bae6fd", "#38bdf8"],
                borderRadius: 4,
                barThickness: 50
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: { color: "#94a3b8", font: { size: 11 } },
                    grid: { color: "#f1f5f9" }
                },
                x: {
                    ticks: { color: "#64748b", font: { size: 11 } },
                    grid: { display: false }
                }
            }
        }
    });
}

// Cycled per card purely for visual variety -- not tied to any real category.
const CARD_STYLE_ROTATION = [
    { iconClass: "blue", badgeClass: "green", svg: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 10v6M2 10l10-5 10 5-10 5z"></path><path d="M6 12v5c3 3 9 3 12 0v-5"></path></svg>' },
    { iconClass: "purple", badgeClass: "blue", svg: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>' },
    { iconClass: "pink", badgeClass: "yellow", svg: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>' },
];

function renderClusterCards(clusters) {
    const grid = document.getElementById("cluster-cards-grid");
    const emptyState = document.getElementById("cluster-empty-state");
    if (!grid) return;

    grid.innerHTML = "";

    if (!clusters.length) {
        grid.classList.add("hidden");
        if (emptyState) emptyState.classList.remove("hidden");
        return;
    }

    grid.classList.remove("hidden");
    if (emptyState) emptyState.classList.add("hidden");

    clusters.forEach((cluster, i) => {
        const style = CARD_STYLE_ROTATION[i % CARD_STYLE_ROTATION.length];
        const keywords = Array.isArray(cluster.keywords) ? cluster.keywords : [];
        const tagsHtml = keywords.length
            ? keywords.map(kw => `<span class="kw-tag">${escapeHtml(kw)}</span>`).join("")
            : `<span class="kw-tag">No keywords yet</span>`;

        const card = document.createElement("div");
        card.className = "cluster-card";
        card.dataset.clusterId = cluster.cluster_id;
        card.innerHTML = `
            <div class="cluster-card-header">
                <div class="card-icon ${style.iconClass}">${style.svg}</div>
                <span class="status-badge ${style.badgeClass}">${escapeHtml(cluster.cluster_status || "ACTIVE")}</span>
            </div>
            <h3>${escapeHtml(cluster.cluster_label)}</h3>
            <div class="cluster-vol">
                <span class="pct">${cluster.cluster_percentage ?? 0}%</span>
                <span class="lbl">of total volume</span>
            </div>
            <p class="card-sm-title" style="margin-bottom: 8px;">TOP CLUSTER KEYWORDS</p>
            <div class="tag-container">${tagsHtml}</div>
            <button class="view-raw-btn" data-cluster-id="${cluster.cluster_id}" data-cluster-label="${escapeHtml(cluster.cluster_label)}">
                View Raw Queries
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>
            </button>
        `;
        grid.appendChild(card);
    });
}

function renderClusteringStatus(status) {
    const dot = document.getElementById("clustering-status-dot");
    const text = document.getElementById("clustering-status-text");
    if (!dot || !text) return;

    const STATUS_LABELS = {
        RUNNING: { dot: "yellow", text: "CLUSTERING SERVICE: RUNNING" },
        COMPLETED: { dot: "green", text: "CLUSTERING SERVICE: LIVE" },
        INSUFFICIENT: { dot: "grey", text: "CLUSTERING SERVICE: WAITING FOR DATA" },
        FAILED_EXTRACTION: { dot: "red", text: "CLUSTERING SERVICE: ERROR" },
        FAILED_ML: { dot: "red", text: "CLUSTERING SERVICE: ERROR" },
    };

    const info = STATUS_LABELS[status] || { dot: "grey", text: "CLUSTERING SERVICE: IDLE" };
    dot.className = `status-dot ${info.dot}`;
    text.textContent = info.text;
}

// Raise a header-bell notification summarising a just-finished run, keyed off
// the run status the server reports back.
function notifyClusteringRun(data) {
    const status = data?.last_run_status;
    const count = Array.isArray(data?.clusters) ? data.clusters.length : 0;

    const MESSAGES = {
        COMPLETED: {
            type: "clustering",
            title: "Clustering run complete",
            message: count
                ? `${count} ${count === 1 ? "cluster" : "clusters"} identified from student queries.`
                : "The run finished successfully.",
        },
        INSUFFICIENT: {
            type: "info",
            title: "Clustering run skipped",
            message: "Not enough student queries logged yet to form clusters.",
        },
        FAILED_EXTRACTION: {
            type: "error",
            title: "Clustering run failed",
            message: "Could not extract query data for clustering.",
        },
        FAILED_ML: {
            type: "error",
            title: "Clustering run failed",
            message: "The clustering algorithm could not complete.",
        },
    };

    const note = MESSAGES[status] || {
        type: "clustering",
        title: "Clustering run finished",
        message: "The clustering service has finished running.",
    };
    window.pushNotification?.(note);
}

function wireRunClusteringButton() {
    const btn = document.getElementById("run-clustering-btn");
    if (!btn) return;

    btn.addEventListener("click", async () => {
        btn.disabled = true;
        const originalText = btn.textContent;
        btn.textContent = "Running...";

        try {
            const data = await apiPost("/clusters/run", {});
            renderOverview(data);
            notifyClusteringRun(data);
        } catch (err) {
            console.error("Clustering run failed:", err);
            alert(err.message || "Clustering run failed. Please try again.");
            window.pushNotification?.({
                type: "error",
                title: "Clustering run failed",
                message: err.message || "The clustering run could not be completed.",
            });
        } finally {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    });
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.appendChild(document.createTextNode(String(text ?? "")));
    return div.innerHTML;
}

async function loadClusterQueries(clusterId) {
    const body = document.getElementById("queries-modal-body");
    if (body) body.innerHTML = `<p class="placeholder-note">Loading queries…</p>`;
    currentClusterQueries = [];

    try {
        const data = await apiGet(`/clusters/${clusterId}/queries`);
        currentClusterQueries = Array.isArray(data?.queries) ? data.queries : [];
    } catch (err) {
        console.error("Could not load cluster queries:", err);
        if (body) body.innerHTML = `<p class="placeholder-note">Could not load queries. Please try again.</p>`;
        return;
    }

    renderClusterQueries();
}

function renderClusterQueries() {
    const body = document.getElementById("queries-modal-body");
    if (!body) return;

    const rows = currentQueryFilter === "low"
        ? currentClusterQueries.filter(q => q.low_confidence)
        : currentClusterQueries;

    if (!rows.length) {
        const msg = currentQueryFilter === "low"
            ? "No low-confidence queries in this cluster."
            : "No queries found for this cluster.";
        body.innerHTML = `<p class="placeholder-note">${msg}</p>`;
        return;
    }

    body.innerHTML = rows.map(q => {
        const conf = typeof q.confidence === "number" ? `${Math.round(q.confidence * 100)}%` : "—";
        const confClass = q.low_confidence ? "qrow-conf low" : "qrow-conf";
        const intent = q.detected_intent ? `<span class="qrow-tag">${escapeHtml(q.detected_intent)}</span>` : "";
        const sentiment = q.sentiment ? `<span class="qrow-tag">${escapeHtml(q.sentiment)}</span>` : "";
        return `
            <div class="qrow">
                <p class="qrow-text">${escapeHtml(q.query_text)}</p>
                <div class="qrow-meta">
                    ${intent}
                    ${sentiment}
                    <span class="${confClass}">Confidence: ${conf}</span>
                </div>
            </div>`;
    }).join("");
}

async function loadSentimentQueries(bucket) {
    const modal = document.getElementById("sentiment-modal");
    const body = document.getElementById("sentiment-modal-body");
    const title = document.getElementById("sentiment-modal-title");
    if (!modal || !body) return;

    if (title) title.textContent = "Sentiment Queries";
    body.innerHTML = `<p class="placeholder-note">Loading queries…</p>`;
    modal.classList.remove("hidden");

    let data;
    try {
        data = await apiGet(`/clusters/sentiment/${bucket}/queries`);
    } catch (err) {
        console.error("Could not load sentiment queries:", err);
        body.innerHTML = `<p class="placeholder-note">Could not load queries. Please try again.</p>`;
        return;
    }

    if (title) title.textContent = `${data.title || "Sentiment"} (${data.query_count || 0})`;

    const rows = Array.isArray(data.queries) ? data.queries : [];
    if (!rows.length) {
        body.innerHTML = `<p class="placeholder-note">No queries in this sentiment bucket.</p>`;
        return;
    }

    body.innerHTML = rows.map(q => {
        const intent = q.detected_intent ? `<span class="qrow-tag">${escapeHtml(q.detected_intent)}</span>` : "";
        const sentiment = q.sentiment ? `<span class="qrow-tag">${escapeHtml(q.sentiment)}</span>` : "";
        return `
            <div class="qrow">
                <p class="qrow-text">${escapeHtml(q.query_text)}</p>
                <div class="qrow-meta">
                    ${intent}
                    ${sentiment}
                </div>
            </div>`;
    }).join("");
}

function wireModalLogic() {
    try {
        const queriesModal = document.getElementById('queries-modal');
        const queriesModalTitle = document.getElementById('queries-modal-title');

        // Sentiment distribution rows: clicking one lists the queries in that
        // sentiment bucket.
        document.querySelectorAll('.sentiment-row.clickable-row').forEach(row => {
            row.addEventListener('click', () => loadSentimentQueries(row.dataset.sentiment));
        });

        // Cluster cards are rendered dynamically, so this listens on the
        // document instead of attaching to buttons that don't exist yet.
        document.body.addEventListener('click', async (e) => {
            const btn = e.target.closest('.view-raw-btn');
            if (!btn || !queriesModal) return;

            if (queriesModalTitle) {
                queriesModalTitle.textContent = `Raw Queries: ${btn.dataset.clusterLabel || ''}`;
            }

            // Always reopen on the "All Queries" view.
            currentQueryFilter = "all";
            document.querySelectorAll('.toggle-btn').forEach(b => {
                b.classList.toggle('active', b.dataset.filter === 'all');
            });

            queriesModal.classList.remove('hidden');
            await loadClusterQueries(btn.dataset.clusterId);
        });

        const toggleBtns = document.querySelectorAll('.toggle-btn');
        toggleBtns.forEach(btn => {
            btn.addEventListener('click', (e) => {
                const target = e.currentTarget;
                toggleBtns.forEach(b => b.classList.remove('active'));
                target.classList.add('active');
                currentQueryFilter = target.dataset.filter || "all";
                renderClusterQueries();
            });
        });

        document.querySelectorAll('.close-ui-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                btn.closest('.ui-overlay')?.classList.add('hidden');
            });
        });

        document.querySelectorAll('.ui-overlay').forEach(overlay => {
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) overlay.classList.add('hidden');
            });
        });
    } catch (error) {
        console.error("Modal logic failed:", error);
    }
}
