// Admin Query Clusters — wired to GET /clusters and POST /clusters/run.
// Requires api.js + auth.js to be loaded first.

const CLUSTER_PALETTE = ["#152e51", "#0ea5e9", "#7dd3fc", "#e0f2fe", "#1d4ed8",
                         "#38bdf8", "#93c5fd", "#bae6fd"];

document.addEventListener("DOMContentLoaded", async () => {
    if (typeof requireAdmin === "function") {
        const user = await requireAdmin();
        if (!user) return;
    }
    wireRunButton();
    await loadClusters();
    wireModals();
});

async function loadClusters() {
    const container = document.getElementById("cluster-cards-container");
    let data;
    try {
        data = await apiGet("/clusters");
    } catch (err) {
        if (container) container.innerHTML = `<p>Could not load clusters: ${err.message}</p>`;
        return;
    }

    renderChart(data.clusters);
    renderCards(data.clusters, container);
}

function renderChart(clusters) {
    const ctx = document.getElementById("topicChart");
    if (!ctx || typeof Chart === "undefined") return;

    const labels = clusters.map(c => c.label);
    const values = clusters.map(c => c.query_count);
    const colors = clusters.map((_, i) => CLUSTER_PALETTE[i % CLUSTER_PALETTE.length]);

    new Chart(ctx.getContext("2d"), {
        type: "bar",
        data: {
            labels: labels.length ? labels : ["No clusters yet"],
            datasets: [{
                label: "Query Volume",
                data: values.length ? values : [0],
                backgroundColor: colors.length ? colors : ["#e0f2fe"],
                borderRadius: 4,
                barThickness: 50
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { beginAtZero: true, grid: { color: "#f1f5f9" } },
                x: { grid: { display: false } }
            }
        }
    });
}

function renderCards(clusters, container) {
    if (!container) return;
    container.innerHTML = "";

    if (!clusters.length) {
        container.innerHTML =
            "<p style='grid-column:1/-1;color:#64748b;'>No clusters yet. " +
            "Click <strong>Run Clustering</strong> once there are enough student " +
            "queries logged.</p>";
        return;
    }

    clusters.forEach((c, i) => {
        const tags = (c.keywords || [])
            .map(kw => `<span class="kw-tag">${escapeHtml(kw)}</span>`)
            .join("");
        const color = CLUSTER_PALETTE[i % CLUSTER_PALETTE.length];
        container.innerHTML += `
            <div class="cluster-card">
                <div class="cluster-card-header">
                    <div class="card-icon" style="background:${color}1a;color:${color};">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"></circle><path d="M12 1v6m0 6v6"></path></svg>
                    </div>
                    <span class="status-badge blue">${c.query_count} QUERIES</span>
                </div>
                <h3>${escapeHtml(c.label)}</h3>
                <div class="cluster-vol">
                    <span class="pct">${c.percentage != null ? c.percentage + "%" : "—"}</span>
                    <span class="lbl">of total volume</span>
                </div>
                <p class="card-sm-title" style="margin-bottom: 8px;">TOP CLUSTER KEYWORDS</p>
                <div class="tag-container">${tags || "<span class='lbl'>—</span>"}</div>
            </div>
        `;
    });
}

function wireRunButton() {
    const container = document.getElementById("cluster-cards-container");
    if (!container || !container.parentElement) return;

    const btn = document.createElement("button");
    btn.textContent = "Run Clustering";
    btn.className = "run-clustering-btn";
    btn.style.cssText =
        "margin:0 0 16px;padding:10px 18px;background:#152e51;color:#fff;border:none;" +
        "border-radius:8px;cursor:pointer;font-weight:600;";
    btn.addEventListener("click", async () => {
        btn.disabled = true;
        btn.textContent = "Clustering… (this can take a moment)";
        try {
            const res = await apiPost("/clusters/run", {});
            btn.textContent = `Done — ${res.num_clusters} clusters from ${res.total_queries} queries`;
            await loadClusters();
        } catch (err) {
            btn.textContent = "Run Clustering";
            alert("Clustering failed: " + err.message);
        } finally {
            btn.disabled = false;
            setTimeout(() => (btn.textContent = "Run Clustering"), 4000);
        }
    });
    container.parentElement.insertBefore(btn, container);
}

function wireModals() {
    try {
        document.querySelectorAll(".close-ui-btn").forEach(b =>
            b.addEventListener("click", () =>
                document.querySelectorAll(".ui-overlay").forEach(o => o.classList.add("hidden"))));
        document.querySelectorAll(".ui-overlay").forEach(overlay =>
            overlay.addEventListener("click", e => {
                if (e.target === overlay) overlay.classList.add("hidden");
            }));
    } catch (e) {
        console.error("Modal wiring failed:", e);
    }
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.appendChild(document.createTextNode(text == null ? "" : String(text)));
    return div.innerHTML;
}
