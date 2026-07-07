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

        setVal('rate-user-daily-input', s.rate_limit_user_daily_max);
        setText('rate-user-daily-val', s.rate_limit_user_daily_max);

        setVal('rate-global-daily-input', s.rate_limit_global_daily_max);
        setText('rate-global-daily-val', s.rate_limit_global_daily_max);

        // Kill switch: reflect the boolean as a checkbox + label.
        const chatToggle = document.getElementById('chat-enabled-input');
        const chatLabel = document.getElementById('chat-enabled-label');
        if (chatToggle && s.chat_enabled != null) {
            chatToggle.checked = !!s.chat_enabled;
            if (chatLabel) chatLabel.textContent = chatToggle.checked ? 'Enabled' : 'Disabled';
            chatToggle.onchange = () => {
                if (chatLabel) chatLabel.textContent = chatToggle.checked ? 'Enabled' : 'Disabled';
            };
        }
    } catch (err) {
        console.error('Failed to load settings:', err);
    }
}

// ── Save settings ──
async function saveSettings() {
    const payload = {
        rate_limit_max_requests: parseInt(document.getElementById('rate-limit-input').value),
        rate_limit_window_seconds: parseInt(document.getElementById('rate-window-input').value),
        rate_limit_global_max_requests: parseInt(document.getElementById('rate-global-input').value),
        rate_limit_user_daily_max: parseInt(document.getElementById('rate-user-daily-input').value),
        rate_limit_global_daily_max: parseInt(document.getElementById('rate-global-daily-input').value),
        chat_enabled: document.getElementById('chat-enabled-input').checked
    };
    try {
        await apiPut('/settings', payload);
        showToast('✓ Settings saved successfully');
    } catch (err) {
        showToast('⚠ ' + err.message);
    }
}

// ── Admin Management ──
let _currentUser = null;      // set on load; gates Head-Admin-only actions
let _editingAdminId = null;   // null = add mode; otherwise the user_id being edited
let _admins = [];             // last-loaded admin list (for edit prefill)

const ROLE_PILL = { 'Head Admin': 'head', 'Registrar': 'reg', 'Finance Officer': 'fin' };
const AVATAR_COLORS = ['av-dark', 'av-slate', 'av-amber'];

const ICON_EDIT = '<svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>';
const ICON_DEACTIVATE = '<svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>';
const ICON_REACTIVATE = '<svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>';

function isHeadAdmin() {
    return !!_currentUser && _currentUser.role === 'Head Admin';
}

// Escape DB-sourced strings before injecting into innerHTML.
function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, ch =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

function adminInitials(name) {
    return (name || '?').trim().split(/\s+/).map(w => w[0] || '').join('').toUpperCase().slice(0, 2) || '?';
}

function formatLastActive(a) {
    if (a.pending) return 'Pending sign-in';
    if (!a.last_active) return '—';
    const d = new Date(a.last_active);
    return isNaN(d.getTime()) ? '—'
        : d.toLocaleString([], { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

async function loadAdmins() {
    const tbody = document.getElementById('admins-tbody');
    if (!tbody) return;
    try {
        _admins = (await apiGet('/admins')) || [];
        if (!_admins.length) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#94a3b8;padding:20px;">No administrators yet.</td></tr>';
            return;
        }
        tbody.innerHTML = '';
        _admins.forEach((a, i) => tbody.appendChild(renderAdminRow(a, i)));
    } catch (err) {
        console.error('Failed to load admins:', err);
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#b91c1c;padding:20px;">Could not load administrators.</td></tr>';
    }
}

function renderAdminRow(a, i) {
    const tr = document.createElement('tr');
    if (!a.is_active) tr.style.opacity = '0.55';

    const pill = ROLE_PILL[a.role] || 'fin';
    const avatar = AVATAR_COLORS[i % AVATAR_COLORS.length];

    // Prefer the Google profile photo; fall back to coloured initials.
    // referrerpolicy=no-referrer: Google's lh3.googleusercontent.com avatars
    // often 403 when a Referer is sent, which would show a broken image.
    const avatarInner = a.picture
        ? `<img src="${escapeHtml(a.picture)}" alt="" referrerpolicy="no-referrer" style="width:100%;height:100%;border-radius:50%;object-fit:cover;">`
        : escapeHtml(adminInitials(a.display_name));
    const deactivatedBadge = a.is_active ? ''
        : ' <span class="role-pill" style="background:#fee2e2;color:#b91c1c;">Deactivated</span>';

    // Actions are Head-Admin-only. Don't offer self-deactivation.
    let actions = '<span style="color:#cbd5e1;">—</span>';
    if (isHeadAdmin()) {
        const isSelf = _currentUser && a.user_id === _currentUser.user_id;
        let toggle = '';
        if (!isSelf) {
            toggle = a.is_active
                ? `<button class="action-icon-btn danger" title="Deactivate" onclick="toggleAdminStatus(${a.user_id}, false)">${ICON_DEACTIVATE}</button>`
                : `<button class="action-icon-btn" title="Reactivate" onclick="toggleAdminStatus(${a.user_id}, true)">${ICON_REACTIVATE}</button>`;
        }
        actions = `<button class="action-icon-btn" title="Edit" onclick="editAdmin(${a.user_id})">${ICON_EDIT}</button>${toggle}`;
    }

    tr.innerHTML = `
        <td>
            <div class="admin-name-cell">
                <div class="admin-avatar ${avatar}">${avatarInner}</div>
                <div class="admin-name-info">
                    <strong>${escapeHtml(a.display_name)}${deactivatedBadge}</strong>
                    <span>${escapeHtml(a.email)}</span>
                </div>
            </div>
        </td>
        <td><span class="role-pill ${pill}">${escapeHtml(a.role)}</span></td>
        <td>${formatLastActive(a)}</td>
        <td>${actions}</td>`;
    return tr;
}

// ── Add / Edit Admin Modal ──
function openAddAdminModal() {
    _editingAdminId = null;
    document.getElementById('admin-modal-title').textContent = 'Add New Administrator';
    document.getElementById('admin-modal-submit').textContent = 'Add Administrator';
    document.getElementById('new-admin-name').value = '';
    const emailEl = document.getElementById('new-admin-email');
    emailEl.value = '';
    emailEl.disabled = false;
    document.getElementById('new-admin-role').value = 'Registrar';
    document.getElementById('add-admin-modal').classList.remove('hidden');
}

function editAdmin(id) {
    const a = _admins.find(x => x.user_id === id);
    if (!a) return;
    _editingAdminId = id;
    document.getElementById('admin-modal-title').textContent = 'Edit Administrator';
    document.getElementById('admin-modal-submit').textContent = 'Save Changes';
    document.getElementById('new-admin-name').value = a.display_name;
    const emailEl = document.getElementById('new-admin-email');
    emailEl.value = a.email;
    emailEl.disabled = true;   // email is the account identity; not editable here
    document.getElementById('new-admin-role').value = a.role;
    document.getElementById('add-admin-modal').classList.remove('hidden');
}

function closeAddAdminModal() {
    document.getElementById('add-admin-modal').classList.add('hidden');
    _editingAdminId = null;
}

async function saveAdmin() {
    const name  = document.getElementById('new-admin-name').value.trim();
    const email = document.getElementById('new-admin-email').value.trim();
    const role  = document.getElementById('new-admin-role').value;
    if (!name || (!_editingAdminId && !email)) {
        showToast('Please fill in all fields.');
        return;
    }
    try {
        if (_editingAdminId) {
            await apiPut(`/admins/${_editingAdminId}`, { display_name: name, role });
            showToast('✓ Administrator updated');
        } else {
            await apiPost('/admins', { display_name: name, email, role });
            showToast(`✓ ${name} added as ${role}`);
        }
        closeAddAdminModal();
        await loadAdmins();
    } catch (err) {
        showToast('⚠ ' + err.message);
    }
}

async function toggleAdminStatus(id, makeActive) {
    if (!makeActive && !confirm('Deactivate this administrator? They will lose portal access until reactivated.')) {
        return;
    }
    try {
        await apiPost(`/admins/${id}/status`, { is_active: makeActive });
        showToast(makeActive ? '✓ Administrator reactivated' : '✓ Administrator deactivated');
        await loadAdmins();
    } catch (err) {
        showToast('⚠ ' + err.message);
    }
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
        _currentUser = user;
    }
    // Admin Management is the Head Admin's panel: hide "Add" for other admins
    // (the row actions are already gated in renderAdminRow, and the backend
    // enforces it regardless).
    if (!isHeadAdmin()) {
        const addBtn = document.querySelector('.add-admin-btn');
        if (addBtn) addBtn.style.display = 'none';
    }
    loadSettings();
    loadAdmins();
});
