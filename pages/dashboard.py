import streamlit as st
import sqlite3
import os
import pandas as pd

st.set_page_config(page_title="HCCS Analytics Dashboard", page_icon="📊", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=Source+Sans+3:wght@400;500;600;700&display=swap');

:root {
    --navy:      #0d2a5e;
    --navy-mid:  #1a3a7a;
    --navy-pale: #f0f4fb;
    --gold:      #f5c100;
    --gold-dark: #c99a00;
    --gold-light:#fffbe6;
    --white:     #ffffff;
    --off-white: #f5f7fc;
    --text:      #1a1a2e;
    --muted:     #5a6a88;
    --border:    #d0d9ee;
}

/* ═══════════════════════════════════════════════
   FORCE ENTIRE APP TO LIGHT — all Streamlit layers
   ═══════════════════════════════════════════════ */
html, body,
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stAppViewBlockContainer"],
[data-testid="stMain"],
[data-testid="stMainBlockContainer"],
section[data-testid="stMain"],
.main, .main > div,
.block-container,
[data-testid="stVerticalBlock"],
[data-testid="stVerticalBlockBorderWrapper"],
div[data-testid="stDecoration"],
[class*="appview-container"],
[class*="main-content"],
[data-testid="stHorizontalBlock"],
[data-testid="column"],
[data-testid="stColumn"] {
    background-color: var(--off-white) !important;
    color: var(--text) !important;
}

/* ── Sidebar ── */
[data-testid="stSidebar"],
[data-testid="stSidebar"] > div,
[data-testid="stSidebarContent"],
[data-testid="stSidebarUserContent"],
section[data-testid="stSidebar"] > div {
    background-color: var(--white) !important;
    border-right: 1.5px solid var(--border) !important;
}
[data-testid="stSidebar"] * { color: var(--text) !important; }

/* ── Bottom bar ── */
[data-testid="stBottom"],
[data-testid="stBottom"] > div,
[data-testid="stBottomBlockContainer"],
.stBottom, .stBottom > div {
    background-color: var(--off-white) !important;
    border-top: 1px solid var(--border) !important;
}

/* ── Inputs ── */
input, input[type="text"], textarea,
.stTextInput input, .stTextArea textarea {
    background-color: var(--white) !important;
    color: var(--text) !important;
}

/* ── Typography ── */
html, body, p, span, div, label, [class*="css"] {
    font-family: 'Source Sans 3', sans-serif;
}

/* ── Streamlit chrome ── */
#MainMenu, footer { visibility: hidden; }
.block-container { padding: 1.5rem 2rem 3rem !important; }

/* ── Buttons ── */
[data-testid="stButton"] > button {
    background: var(--navy) !important;
    color: var(--white) !important;
    border: none !important;
    border-radius: 10px !important;
    font-family: 'Source Sans 3', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    padding: 0.55rem 1.2rem !important;
    transition: background 0.2s, transform 0.15s !important;
    box-shadow: 0 2px 8px rgba(13,42,94,0.15) !important;
}
[data-testid="stButton"] > button:hover {
    background: var(--navy-mid) !important;
    transform: translateY(-1px) !important;
}

/* ── DataTable ── */
[data-testid="stDataFrame"] {
    border-radius: 12px !important;
    overflow: hidden !important;
    border: 1.5px solid var(--border) !important;
    background: var(--white) !important;
}

/* ── Alert/info banners ── */
[data-testid="stAlert"] { border-radius: 10px !important; }

/* ── Spinner ── */
[data-testid="stSpinner"] > div { color: var(--navy) !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--off-white); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

/* ══════════════════════════════════
   CUSTOM COMPONENTS
   ══════════════════════════════════ */

.dash-header {
    background: linear-gradient(135deg, var(--navy) 0%, var(--navy-mid) 100%);
    border-radius: 16px;
    padding: 2rem 2.5rem;
    margin-bottom: 1.75rem;
    position: relative;
    overflow: hidden;
    box-shadow: 0 6px 28px rgba(13,42,94,0.20);
}
.dash-header::before {
    content: '';
    position: absolute; top: -40px; right: -40px;
    width: 200px; height: 200px;
    background: var(--gold); opacity: 0.09; border-radius: 50%;
}
.dash-header::after {
    content: '';
    position: absolute; bottom: -60px; left: 35%;
    width: 280px; height: 280px;
    background: var(--gold); opacity: 0.05; border-radius: 50%;
}
.dash-header-inner {
    position: relative; z-index: 2;
    display: flex; align-items: center;
    justify-content: space-between; flex-wrap: wrap; gap: 1rem;
}
.dash-header-left h1 {
    font-family: 'Playfair Display', serif;
    color: var(--white); font-size: 1.8rem; font-weight: 700;
    margin: 0 0 0.3rem 0; letter-spacing: -0.3px;
}
.dash-header-left p { color: rgba(255,255,255,0.55); font-size: 0.85rem; margin: 0; }
.dash-badge {
    background: var(--gold); color: var(--navy);
    font-size: 0.7rem; font-weight: 700; letter-spacing: 0.1em;
    text-transform: uppercase; padding: 0.35rem 1rem;
    border-radius: 20px; white-space: nowrap; align-self: flex-start; margin-top: 0.4rem;
}

.metric-card {
    background: var(--white);
    border: 1.5px solid var(--border);
    border-radius: 14px;
    padding: 1.4rem 1.6rem;
    text-align: center;
    box-shadow: 0 2px 10px rgba(13,42,94,0.06);
    position: relative; overflow: hidden;
}
.metric-card::before {
    content: '';
    position: absolute; top: 0; left: 0; right: 0;
    height: 4px;
    background: linear-gradient(90deg, var(--navy), var(--navy-mid));
    border-radius: 14px 14px 0 0;
}
.metric-card .value {
    font-family: 'Playfair Display', serif;
    font-size: 2.4rem; font-weight: 700; color: var(--navy);
    line-height: 1; margin-bottom: 0.4rem;
}
.metric-card .label {
    font-size: 0.72rem; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.1em; font-weight: 600;
}

.section-title {
    font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.12em; color: var(--muted);
    margin: 1.75rem 0 0.85rem 0;
    display: flex; align-items: center; gap: 0.5rem;
}
.section-title::after { content: ''; flex: 1; height: 1px; background: var(--border); }

.bar-wrap {
    display: flex; align-items: center; gap: 0.85rem;
    margin-bottom: 0.5rem; padding: 0.5rem 0.65rem;
    border-radius: 8px; transition: background 0.15s;
}
.bar-wrap:hover { background: var(--navy-pale); }
.bar-label {
    font-size: 0.84rem; color: var(--text); font-weight: 500;
    width: 190px; white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; flex-shrink: 0;
}
.bar-track { flex: 1; background: var(--navy-pale); border-radius: 6px; height: 11px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 6px; background: linear-gradient(90deg, var(--navy), var(--navy-mid)); }
.bar-count { font-size: 0.78rem; color: var(--muted); width: 28px; text-align: right; flex-shrink: 0; font-weight: 600; }

.cluster-card {
    background: var(--white);
    border: 1.5px solid var(--border);
    border-radius: 14px;
    padding: 1.4rem 1.6rem;
    margin-bottom: 1rem;
    box-shadow: 0 2px 10px rgba(13,42,94,0.05);
}
.cluster-header { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.6rem; }
.cluster-badge {
    background: var(--navy); color: var(--gold);
    border-radius: 8px; padding: 0.22rem 0.7rem;
    font-size: 0.7rem; font-weight: 700; letter-spacing: 0.05em; white-space: nowrap;
}
.cluster-name { font-size: 1rem; font-weight: 700; color: var(--navy); }
.cluster-summary { font-size: 0.8rem; color: var(--muted); margin-bottom: 0.85rem; font-style: italic; }
.query-pill {
    display: inline-block;
    background: var(--navy-pale); border: 1px solid var(--border);
    border-radius: 20px; padding: 0.3rem 0.85rem;
    font-size: 0.8rem; color: var(--navy-mid); font-weight: 500;
    margin: 0.2rem 0.2rem 0.2rem 0; line-height: 1.4;
}

.empty-state {
    text-align: center; padding: 3rem 2rem; color: var(--muted); font-size: 0.9rem;
    background: var(--white); border: 1.5px dashed var(--border); border-radius: 14px;
}
.empty-state .icon { font-size: 2.5rem; margin-bottom: 0.75rem; }

.dash-footer {
    text-align: center; color: var(--muted); font-size: 0.74rem;
    margin-top: 2.5rem; padding-top: 1rem; border-top: 1px solid var(--border);
}
.dash-footer span { color: var(--gold-dark); font-weight: 600; }
</style>
""", unsafe_allow_html=True)


# ── Data loading ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=30)
def load_dashboard_data():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, 'analytics.db')
    if not os.path.exists(db_path):
        return None, None
    conn = sqlite3.connect(db_path)
    clusters_df = pd.read_sql_query(
        "SELECT cluster_id, cluster_name, cluster_summary, created_at FROM query_clusters ORDER BY cluster_id",
        conn
    )
    queries_df = pd.read_sql_query(
        "SELECT query_id, query_text, answer_text, timestamp, cluster_id FROM user_queries ORDER BY timestamp DESC",
        conn
    )
    conn.close()
    return clusters_df, queries_df


# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="dash-header">
    <div class="dash-header-inner">
        <div class="dash-header-left">
            <h1>Student Query Analytics</h1>
            <p>Holy Child Catholic School · Automated clustering dashboard</p>
        </div>
        <div class="dash-badge">📊 Admin Portal</div>
    </div>
</div>
""", unsafe_allow_html=True)

clusters_df, queries_df = load_dashboard_data()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding:1rem 0 0.75rem; border-bottom:1.5px solid #d0d9ee; margin-bottom:1.25rem;">
        <div style="font-family:'Playfair Display',serif;font-size:1.1rem;font-weight:700;color:#0d2a5e;">HCCS Admin</div>
        <div style="font-size:0.78rem;color:#5a6a88;margin-top:0.2rem;">Clustering Controls</div>
    </div>
    """, unsafe_allow_html=True)

    distance_threshold = st.slider(
        "Distance Threshold",
        min_value=0.10,
        max_value=0.50,
        value=0.22,
        step=0.01,
        help="Lower = tighter, more specific clusters. Higher = broader clusters that group more queries together."
    )

    if st.button("▶  Run Cluster Engine", width='stretch'):
        with st.spinner("Clustering queries… this may take a minute."):
            try:
                from src.cluster_engine import run_clustering
                run_clustering(distance_threshold=distance_threshold)
                st.cache_data.clear()
                st.success("Clustering complete! Dashboard refreshed.")
            except Exception as e:
                st.error(f"Clustering failed: {e}")

    st.markdown("""
    <div style="margin-top:1.25rem;font-size:0.78rem;color:#5a6a88;line-height:1.6;">
        Run the cluster engine after new student queries accumulate to group them into topic categories.
    </div>
    """, unsafe_allow_html=True)

if clusters_df is None:
    st.error("Could not find `analytics.db`. Run `python db_tools/init_db.py` from the project root to create it.")
    st.stop()

# ── Summary metrics ───────────────────────────────────────────────────────────
total_queries  = len(queries_df)
clustered      = int(queries_df['cluster_id'].notna().sum())
unclustered    = total_queries - clustered
total_clusters = len(clusters_df)

c1, c2, c3, c4 = st.columns(4)
for col, val, label in [
    (c1, total_queries,  "Total Queries"),
    (c2, total_clusters, "Clusters"),
    (c3, clustered,      "Clustered"),
    (c4, unclustered,    "Unclustered"),
]:
    with col:
        st.markdown(f"""
        <div class="metric-card">
            <div class="value">{val}</div>
            <div class="label">{label}</div>
        </div>""", unsafe_allow_html=True)

st.markdown("<div style='margin-top:0.25rem'></div>", unsafe_allow_html=True)

# ── Main layout ───────────────────────────────────────────────────────────────
left, right = st.columns([1, 1.6], gap="large")

with left:
    st.markdown('<div class="section-title">Queries per cluster</div>', unsafe_allow_html=True)

    if total_clusters == 0:
        st.markdown("""
        <div class="empty-state">
            <div class="icon">🗂️</div>
            <strong>No clusters yet.</strong><br>Run the cluster engine from the sidebar.
        </div>""", unsafe_allow_html=True)
    else:
        counts = (
            queries_df[queries_df['cluster_id'].notna()]
            .groupby('cluster_id').size().reset_index(name='count')
        )
        merged = clusters_df.merge(counts, on='cluster_id', how='left').fillna({'count': 0})
        merged['count'] = merged['count'].astype(int)
        merged = merged.sort_values('count', ascending=False)
        max_count = int(merged['count'].max()) or 1
        bars_html = ""
        for _, row in merged.iterrows():
            pct = int(row['count'] / max_count * 100)
            bars_html += f"""
            <div class="bar-wrap">
                <div class="bar-label" title="{row['cluster_name']}">{row['cluster_name']}</div>
                <div class="bar-track"><div class="bar-fill" style="width:{pct}%"></div></div>
                <div class="bar-count">{int(row['count'])}</div>
            </div>"""
        st.markdown(bars_html, unsafe_allow_html=True)

    if unclustered > 0:
        st.info(
            f"**{unclustered}** {'query' if unclustered == 1 else 'queries'} not yet clustered. "
            "Run the cluster engine to process them."
        )

with right:
    st.markdown('<div class="section-title">Cluster details</div>', unsafe_allow_html=True)

    if total_clusters == 0:
        st.markdown("""
        <div class="empty-state">
            <div class="icon">🔍</div>
            Cluster details will appear here after running the engine.
        </div>""", unsafe_allow_html=True)
    else:
        for _, cluster in clusters_df.iterrows():
            cid   = cluster['cluster_id']
            cname = cluster['cluster_name']
            csumm = cluster['cluster_summary'] or ""
            cluster_queries = queries_df[queries_df['cluster_id'] == cid]
            q_count = len(cluster_queries)
            pills_html = ""
            for _, q in cluster_queries.iterrows():
                text = q['query_text'] or ""
                if " | Context:" in text:
                    text = text.split(" | Context:")[0].replace("Question: ", "")
                display = text[:70] + "…" if len(text) > 70 else text
                pills_html += f'<span class="query-pill">{display}</span>'
            if not pills_html:
                pills_html = '<span style="color:#5a6a88;font-size:0.82rem">No queries assigned yet.</span>'
            st.markdown(f"""
            <div class="cluster-card">
                <div class="cluster-header">
                    <span class="cluster-badge">{q_count} {'query' if q_count == 1 else 'queries'}</span>
                    <span class="cluster-name">{cname}</span>
                </div>
                <div class="cluster-summary">{csumm}</div>
                {pills_html}
            </div>""", unsafe_allow_html=True)

# ── Recent queries table ──────────────────────────────────────────────────────
st.markdown('<div class="section-title">Recent queries</div>', unsafe_allow_html=True)

recent = queries_df.head(20).copy()

def clean_query(text):
    if not text: return ""
    if " | Context:" in text:
        text = text.split(" | Context:")[0].replace("Question: ", "")
    return text[:100] + "…" if len(text) > 100 else text

recent['question'] = recent['query_text'].apply(clean_query)
recent['answer preview'] = recent['answer_text'].apply(
    lambda x: (x[:80] + "…") if x and len(x) > 80 else (x or "—")
)
id_to_name = dict(zip(clusters_df['cluster_id'], clusters_df['cluster_name']))
recent['cluster'] = recent['cluster_id'].apply(
    lambda x: id_to_name.get(x, "Unclustered") if pd.notna(x) else "Unclustered"
)

st.dataframe(
    recent[['question', 'answer preview', 'cluster', 'timestamp']],
    width='stretch',
    hide_index=True,
    column_config={
        "question":       st.column_config.TextColumn("Question",       width="large"),
        "answer preview": st.column_config.TextColumn("Answer Preview", width="large"),
        "cluster":        st.column_config.TextColumn("Cluster",        width="medium"),
        "timestamp":      st.column_config.TextColumn("Timestamp",      width="medium"),
    }
)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="dash-footer">
    Data refreshes every <span>30 seconds</span> · Run cluster engine from the sidebar to update clusters
</div>
""", unsafe_allow_html=True)