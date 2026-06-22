// ──────────────────────────────────────────────
// settings.js
// Logic for the Portal Settings page (admin).
// Depends on api.js (apiPut) and auth.js (requireAdmin, logout)
// being loaded beforehand.
// ──────────────────────────────────────────────

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

        setVal('rate-limit-input', s.rate_limit_max_requests);
        setText('rate-limit-val', s.rate_limit_max_requests);

        setVal('rate-window-input', s.rate_limit_window_seconds);
        setText('rate-window-val', s.rate_limit_window_seconds);

        setVal('rate-global-input', s.rate_limit_global_max_requests);
        setText('rate-global-val', s.rate_limit_global_max_requests);
    } catch (err) {
        console.error('Failed to load settings:', err);
    }
}

// ── Save settings ──
async function saveSettings() {
    const payload = {
        rate_limit_max_requests: parseInt(document.getElementById('rate-limit-input').value),
        rate_limit_window_seconds: parseInt(document.getElementById('rate-window-input').value),
        rate_limit_global_max_requests: parseInt(document.getElementById('rate-global-input').value)
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
// search hides rows whose name/email/role don't match.
function wireSettingsSearch() {
    const input = document.querySelector('.search-bar input');
    const tbody = document.getElementById('admins-tbody');
    if (!input || !tbody) return;

    input.addEventListener('input', () => {
        const term = input.value.trim().toLowerCase();
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
