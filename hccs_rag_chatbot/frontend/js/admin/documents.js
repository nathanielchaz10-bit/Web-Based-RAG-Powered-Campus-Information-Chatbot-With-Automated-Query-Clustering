// Document Directory — wired to the real /documents API (api.js helpers).
document.addEventListener("DOMContentLoaded", () => {

    // --- Elements ---
    const modal = document.getElementById("upload-modal");
    const openBtn = document.getElementById("open-upload-btn");
    const closeBtn = document.getElementById("close-modal-btn");
    const cancelBtn = document.getElementById("cancel-upload");

    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("file-input");
    const startBtn = document.getElementById("start-upload-btn");
    const docTypeSelect = document.getElementById("doc-type-select");
    const forceOcrCheck = document.getElementById("force-ocr-check");
    const docList = document.getElementById("doc-list");

    let selectedFile = null;
    let stageTimer = null;

    // ---- In-list "processing" card (the minimized form of an upload) ----
    // Starting an upload auto-minimizes the modal and drops a card into the
    // document list showing live status (like the mockup). The upload is one
    // synchronous request with no server-side progress feed, so rather than a
    // fake %, we cycle the known stages on a timer to show work is happening;
    // loadDocuments() swaps the card for the real document once it resolves.
    const PROCESSING_STAGES = [
        "Uploading & extracting text…",
        "Generating semantic chunks…",
        "Generating vector embeddings…",
    ];

    function processingCardHTML(name) {
        return `
            <div class="doc-card processing" id="processing-card">
                <div class="doc-card-header">
                    <div class="doc-title-area">${FILE_ICON}<h4>${escapeHtml(name)}</h4></div>
                </div>
                <div class="doc-metrics-grid">
                    <div class="metric-col" style="grid-column: 1 / -1;">
                        <span class="metric-label">PROCESSING STATUS</span>
                        <div class="processing-bar-container">
                            <span class="processing-spinner"></span>
                            <span class="metric-val blue-text" id="processing-status-text">${escapeHtml(PROCESSING_STAGES[0])}</span>
                        </div>
                    </div>
                </div>
            </div>`;
    }

    function showProcessingCard(name) {
        removeProcessingCard();
        docList.insertAdjacentHTML("afterbegin", processingCardHTML(name));
        let i = 0;
        stageTimer = setInterval(() => {
            i += 1;
            const el = document.getElementById("processing-status-text");
            if (el && i < PROCESSING_STAGES.length) el.textContent = PROCESSING_STAGES[i];
            if (i >= PROCESSING_STAGES.length - 1) { clearInterval(stageTimer); stageTimer = null; }
        }, 3000);
    }

    function removeProcessingCard() {
        if (stageTimer) { clearInterval(stageTimer); stageTimer = null; }
        const el = document.getElementById("processing-card");
        if (el) el.remove();
    }

    const FILE_ICON = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#1e293b" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>`;
    const DOTS_ICON = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="1"></circle><circle cx="12" cy="5" r="1"></circle><circle cx="12" cy="19" r="1"></circle></svg>`;

    function escapeHtml(s) {
        return String(s ?? "").replace(/[&<>"']/g, c => (
            { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
        ));
    }

    // ============================ DOCUMENT LIST ============================

    async function loadDocuments() {
        docList.innerHTML = `<p class="loading-text" style="color:#64748b; padding:16px;">Loading documents…</p>`;
        try {
            const docs = await apiGet("/documents");
            renderDocuments(docs || []);
        } catch (err) {
            docList.innerHTML = `<p style="color:#dc2626; padding:16px;">Failed to load documents: ${escapeHtml(err.message)}</p>`;
        }
    }

    function statusBadge(d) {
        if (d.needs_review) {
            return `<span class="status-indicator yellow">⚠ Held for Review</span>`;
        }
        if (d.is_active) {
            return `<span class="status-indicator green">✓ Active / Indexed</span>`;
        }
        return `<span class="status-indicator">Inactive</span>`;
    }

    function activityCol(d) {
        // ACTIVITY (indexed docs): retrievals logged this month + trend vs last.
        const n = d.retrievals_this_month || 0;
        const prev = d.retrievals_last_month || 0;
        let cls = "", text;
        if (!prev) {
            cls = n > 0 ? "green" : "";
            text = n > 0 ? "▲ new activity" : "no activity yet";
        } else {
            const pct = Math.round(((n - prev) / prev) * 100);
            if (pct > 0) { cls = "green"; text = `+${pct}% usage vs last month`; }
            else if (pct < 0) { cls = "red"; text = `${pct}% usage vs last month`; }
            else { text = "no change vs last month"; }
        }
        return `
            <div class="metric-col">
                <span class="metric-label">ACTIVITY</span>
                <span class="metric-val">${n} retrieval${n === 1 ? "" : "s"} this month</span>
                <span class="trend ${cls}">${escapeHtml(text)}</span>
            </div>`;
    }

    function typeCol(d) {
        return `
            <div class="metric-col">
                <span class="metric-label">TYPE</span>
                <span class="metric-val">${escapeHtml(d.document_type || "—")}</span>
            </div>`;
    }

    function docCardHTML(d) {
        const conf = d.extraction_confidence ? d.extraction_confidence.toUpperCase() : "—";
        const method = d.extraction_method || "—";
        // Indexed docs show how often the chatbot used them; others show their type.
        const firstCol = d.is_active ? activityCol(d) : typeCol(d);
        return `
            <div class="doc-card" data-id="${d.document_id}">
                <div class="doc-card-header">
                    <div class="doc-title-area">
                        ${FILE_ICON}
                        <h4>${escapeHtml(d.document_name)}</h4>
                    </div>
                    <div class="action-menu-container">
                        <button class="icon-btn action-toggle" data-id="${d.document_id}" data-review="${d.needs_review}">${DOTS_ICON}</button>
                    </div>
                </div>
                <div class="doc-metrics-grid">
                    ${firstCol}
                    <div class="metric-col">
                        <span class="metric-label">EXTRACTION</span>
                        <span class="metric-val">${escapeHtml(method)}</span>
                        <span class="trend">${conf} confidence · ${d.chunk_count} chunks</span>
                    </div>
                    <div class="metric-col">
                        <span class="metric-label">HEALTH &amp; STATUS</span>
                        ${statusBadge(d)}
                    </div>
                </div>
            </div>`;
    }

    function renderDocuments(docs) {
        if (!docs.length) {
            docList.innerHTML = `<p style="color:#64748b; padding:16px;">No documents yet. Click “Upload Document” to add one.</p>`;
            return;
        }
        docList.innerHTML = docs
            .map((d, i) => docCardHTML(d) + (i < docs.length - 1 ? `<div class="doc-divider"></div>` : ""))
            .join("");
    }

    // ============================ ROW ACTIONS ============================

    function closeDropdowns() {
        document.querySelectorAll(".action-dropdown").forEach(m => m.remove());
    }

    docList.addEventListener("click", async (e) => {
        const toggle = e.target.closest(".action-toggle");
        if (toggle) {
            e.stopPropagation();
            const wasOpen = toggle.parentElement.querySelector(".action-dropdown");
            closeDropdowns();
            if (wasOpen) return;
            const id = toggle.dataset.id;
            const needsReview = toggle.dataset.review === "true";
            const menu = document.createElement("div");
            menu.className = "action-dropdown";
            menu.innerHTML = `
                ${needsReview ? `<button class="action-item" data-action="approve" data-id="${id}">✓ Approve &amp; Index</button>` : ``}
                <button class="action-item danger" data-action="delete" data-id="${id}">🗑 Delete from DB</button>`;
            toggle.parentElement.appendChild(menu);
            return;
        }

        const action = e.target.closest("[data-action]");
        if (!action) return;
        e.stopPropagation();
        const id = action.dataset.id;
        closeDropdowns();

        if (action.dataset.action === "approve") {
            action.disabled = true;
            try {
                await apiPost(`/documents/${id}/approve`, {});
                await loadDocuments();
            } catch (err) {
                alert(`Approve failed: ${err.message}`);
            }
        } else if (action.dataset.action === "delete") {
            if (!confirm("Delete this document, its chunks, and its file? This cannot be undone.")) return;
            try {
                await apiDelete(`/documents/${id}`);
                await loadDocuments();
            } catch (err) {
                alert(`Delete failed: ${err.message}`);
            }
        }
    });

    document.addEventListener("click", closeDropdowns);

    // ============================ UPLOAD MODAL ============================

    function resetDropZone() {
        dropZone.innerHTML = `
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
            <p>Drag and drop files here or <strong>Browse</strong></p>
            <span class="file-limits">Supported: PDF, DOCX, TXT (Max 15MB)</span>`;
    }

    function openModal() {
        selectedFile = null;
        modal.classList.remove("hidden");
        dropZone.style.display = "block";
        resetDropZone();
        if (forceOcrCheck) forceOcrCheck.checked = false;
        startBtn.disabled = true;
    }
    function closeModal() { modal.classList.add("hidden"); }

    openBtn.addEventListener("click", openModal);
    closeBtn.addEventListener("click", closeModal);
    cancelBtn.addEventListener("click", closeModal);

    dropZone.addEventListener("click", () => fileInput.click());
    dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("dragover"); });
    dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("dragover");
        if (e.dataTransfer.files.length) handleFileSelect(e.dataTransfer.files[0]);
    });
    fileInput.addEventListener("change", (e) => {
        if (e.target.files.length) handleFileSelect(e.target.files[0]);
    });

    function handleFileSelect(file) {
        selectedFile = file;
        dropZone.innerHTML = `
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2" style="margin-bottom:8px;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
            <p style="color:#0f172a; font-weight:600;">${escapeHtml(file.name)}</p>
            <span class="file-limits">${(file.size / 1024 / 1024).toFixed(2)} MB</span>`;
        startBtn.disabled = false;
    }

    startBtn.addEventListener("click", async () => {
        if (!selectedFile) return;
        const name = selectedFile.name;
        const fd = new FormData();
        fd.append("file", selectedFile);
        fd.append("document_type", docTypeSelect.value);
        fd.append("force_ocr", forceOcrCheck && forceOcrCheck.checked ? "true" : "false");

        // Auto-minimize: close the modal and show a live processing card in the
        // list. Block a second upload until this one resolves.
        closeModal();
        openBtn.disabled = true;
        showProcessingCard(name);

        try {
            const res = await apiUpload("/documents/upload", fd);
            // Saved but held (low confidence / indexing error) -> surface why;
            // the refreshed list will show it as "Held for Review".
            if (!res.indexed) {
                if (res.index_error) console.warn("[upload] indexing error:", res.index_error);
                alert(res.message || "Saved, but held for review.");
            }
        } catch (err) {
            alert(`Upload failed: ${err.message}`);
        } finally {
            removeProcessingCard();
            openBtn.disabled = false;
            await loadDocuments();   // replace the card with the real document
        }
    });

    // Initial load.
    loadDocuments();
});
