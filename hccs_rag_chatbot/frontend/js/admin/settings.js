// ──────────────────────────────────────────────
// settings.js
// Logic for the Portal Settings page (admin).
// Depends on api.js (apiPut) and auth.js (requireAdmin, logout)
// being loaded beforehand.
// ──────────────────────────────────────────────

// ── Tab switching ──
function switchTab(btn, tab) {
    document.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + tab).classList.add('active');
}

// ── Toast ──
function showToast(msg) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('visible');
    setTimeout(() => t.classList.remove('visible'), 3000);
}

// ── Load current settings into the form ──
// GET /settings (admin-only) returns the effective values; populate each field
// and its display label. Runs on page load after the admin guard passes.
async function loadSettings() {
    try {
        const s = await apiGet('/settings');
        if (!s) return;

        const setVal = (id, val) => {
            const el = document.getElementById(id);
            if (el && val != null) el.value = val;
        };
        const setText = (id, val) => {
            const el = document.getElementById(id);
            if (el && val != null) el.textContent = val;
        };

        setVal('school-name', s.school_name);
        setVal('contact-email', s.contact_email);

        setVal('temp-slider', s.rag_temperature);
        setText('temp-val', s.rag_temperature);

        setVal('token-input', s.max_context_tokens);
        setText('token-val', Number(s.max_context_tokens).toLocaleString());

        setVal('rel-slider', s.search_relevance_threshold);
        setText('rel-val', s.search_relevance_threshold + '%');

        setVal('rate-limit-input', s.rate_limit_max_requests);
        setText('rate-limit-val', s.rate_limit_max_requests);
    } catch (err) {
        console.error('Failed to load settings:', err);
    }
}

// ── Save settings ──
async function saveSettings() {
    const payload = {
        school_name: document.getElementById('school-name').value,
        contact_email: document.getElementById('contact-email').value,
        rag_temperature: parseFloat(document.getElementById('temp-slider').value),
        max_context_tokens: parseInt(document.getElementById('token-input').value),
        search_relevance_threshold: parseInt(document.getElementById('rel-slider').value),
        rate_limit_max_requests: parseInt(document.getElementById('rate-limit-input').value)
    };
    try {
        await apiPut('/settings', payload);
        showToast('✓ Settings saved successfully');
    } catch (err) {
        showToast('⚠ ' + err.message);
    }
}

// ── Add Admin Modal ──
function openAddAdminModal() {
    document.getElementById('add-admin-modal').classList.remove('hidden');
}

function closeAddAdminModal() {
    document.getElementById('add-admin-modal').classList.add('hidden');
}

async function addAdmin() {
    const name  = document.getElementById('new-admin-name').value.trim();
    const email = document.getElementById('new-admin-email').value.trim();
    const role  = document.getElementById('new-admin-role').value;
    if (!name || !email) { showToast('Please fill in all fields.'); return; }

    const initials = name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
    const colors = ['av-dark', 'av-slate', 'av-amber'];
    const colorClass = colors[document.querySelectorAll('#admins-tbody tr').length % colors.length];
    const rolePillClass = role === 'Head Admin' ? 'head' : role === 'Registrar' ? 'reg' : 'fin';

    const tr = document.createElement('tr');
    tr.innerHTML = `
        <td>
            <div class="admin-name-cell">
                <div class="admin-avatar ${colorClass}">${initials}</div>
                <div class="admin-name-info">
                    <strong>${name}</strong>
                    <span>${email}</span>
                </div>
            </div>
        </td>
        <td><span class="role-pill ${rolePillClass}">${role}</span></td>
        <td>Just now</td>
        <td>
            <button class="action-icon-btn" title="Edit">
                <svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
            </button>
            <button class="action-icon-btn danger" title="Delete" onclick="this.closest('tr').remove()">
                <svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>
            </button>
        </td>`;
    document.getElementById('admins-tbody').appendChild(tr);

    closeAddAdminModal();
    showToast(`✓ ${name} added as ${role}`);
    document.getElementById('new-admin-name').value = '';
    document.getElementById('new-admin-email').value = '';
}

// ── Header search: filter the Admin Management table ──
// The only list on this page is the admins table, so typing in the header
// search jumps to that tab and hides rows whose name/email/role don't match.
function wireSettingsSearch() {
    const input = document.querySelector('.search-bar input');
    const tbody = document.getElementById('admins-tbody');
    if (!input || !tbody) return;

    input.addEventListener('input', () => {
        const term = input.value.trim().toLowerCase();

        if (term) {
            const adminsTab = Array.from(document.querySelectorAll('.settings-tab'))
                .find(b => (b.getAttribute('onclick') || '').includes("'admins'"));
            if (adminsTab && !adminsTab.classList.contains('active')) {
                switchTab(adminsTab, 'admins');
            }
        }

        tbody.querySelectorAll('tr').forEach(tr => {
            tr.style.display = tr.textContent.toLowerCase().includes(term) ? '' : 'none';
        });
    });
}

document.addEventListener('DOMContentLoaded', wireSettingsSearch);

// ── Route guard on load ──
// Mirror the other admin pages (dashboard.js / clusters.js): an unauthenticated
// or non-admin visitor is redirected to login by requireAdmin(). Guarded with a
// typeof check so the page still renders if auth.js failed to load.
document.addEventListener('DOMContentLoaded', async () => {
    if (typeof requireAdmin === 'function') {
        const user = await requireAdmin();
        if (!user) return; // requireAdmin handles the redirect
    }
    loadSettings();
});
