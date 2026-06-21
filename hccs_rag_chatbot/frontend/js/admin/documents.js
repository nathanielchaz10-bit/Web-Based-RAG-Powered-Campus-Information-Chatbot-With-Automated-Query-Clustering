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
    let replaceDocId = null;   // non-null => modal is replacing this document
    let currentDocs = [];      // last-rendered docs, for type/name lookup on replace

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

    function processingCardHTML(name, type) {
        return `
            <div class="doc-card processing" id="processing-card">
                <div class="doc-card-header">
                    <div class="doc-title-area">${typeIcon(type)}<h4>${escapeHtml(name)}</h4></div>
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

    function showProcessingCard(name, type) {
        removeProcessingCard();
        docList.insertAdjacentHTML("afterbegin", processingCardHTML(name, type));
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

    // Per-document-type glyphs, one for each option of the upload dropdown, so a
    // card carries an icon that matches its type. Used by both the processing
    // card (driven by the dropdown selection) and the finished document cards.
    function typeIcon(type) {
        const A = 'width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#1e293b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
        const icons = {
            POLICY: `<svg ${A}><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path></svg>`,
            DIRECTORY: `<svg ${A}><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle></svg>`,
            FINANCIAL: `<svg ${A}><line x1="12" y1="1" x2="12" y2="23"></line><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>`,
            CALENDAR: `<svg ${A}><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>`,
            ENROLLMENT: `<svg ${A}><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="8.5" cy="7" r="4"></circle><line x1="20" y1="8" x2="20" y2="14"></line><line x1="23" y1="11" x2="17" y2="11"></line></svg>`,
        };
        return icons[type] || FILE_ICON;  // OTHER (and anything unknown) -> generic file
    }

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

    // ---- Corpus stat cards (Total Tokens / Vector Index Space) ----
    // Live figures from /documents/stats: tokens estimated from the indexed
    // chunk text, vector space = real on-disk size of the Chroma store. Both
    // move as documents are added or removed.
    function compactNumber(n) {
        if (n >= 1e9) return (n / 1e9).toFixed(1).replace(/\.0$/, "") + "B";
        if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
        if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, "") + "K";
        return String(n);
    }

    function formatBytes(bytes) {
        if (!bytes) return "0 MB";
        const units = ["B", "KB", "MB", "GB", "TB"];
        let i = 0, v = bytes;
        while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
        return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
    }

    async function loadStats() {
        const tokensEl = document.getElementById("stat-total-tokens");
        const spaceEl = document.getElementById("stat-vector-space");
        try {
            const s = await apiGet("/documents/stats");
            if (tokensEl) tokensEl.textContent = compactNumber(s.total_tokens || 0);
            if (spaceEl) spaceEl.textContent = formatBytes(s.vector_index_bytes || 0);
        } catch (err) {
            console.warn("[stats] could not load corpus stats:", err.message);
            if (tokensEl && tokensEl.textContent === "—") tokensEl.textContent = "—";
            if (spaceEl && spaceEl.textContent === "—") spaceEl.textContent = "—";
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
                        ${typeIcon(d.document_type)}
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
        currentDocs = docs;
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
                <button class="action-item" data-action="replace" data-id="${id}">↻ Update / Replace</button>
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
                loadStats();
            } catch (err) {
                alert(`Approve failed: ${err.message}`);
            }
        } else if (action.dataset.action === "replace") {
            openReplaceModal(id);
        } else if (action.dataset.action === "delete") {
            if (!confirm("Delete this document, its chunks, and its file? This cannot be undone.")) return;
            try {
                await apiDelete(`/documents/${id}`);
                await loadDocuments();
                loadStats();
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

    // Retarget the shared modal between "ingest new" and "replace existing"
    // (the two flows differ only in copy + which endpoint Start hits).
    function setModalMode(mode, docName) {
        const title = modal.querySelector(".modal-header h3");
        const desc = modal.querySelector(".modal-desc");
        if (mode === "replace") {
            if (title) title.textContent = "Upload New Version";
            if (desc) desc.textContent =
                `Replace “${docName}” with a newer file. Its usage history is kept; ` +
                `the old text is removed and the new file is re-indexed.`;
            startBtn.textContent = "Replace Document";
        } else {
            if (title) title.textContent = "Ingest New Knowledge";
            if (desc) desc.textContent =
                "Upload a PDF, DOCX, or TXT file. Word tables are preserved as " +
                "structured text and scanned PDFs are read with vision OCR; the " +
                "text is then chunked and indexed into the vector database.";
            startBtn.textContent = "Start Processing";
        }
    }

    function openModal() {
        replaceDocId = null;
        selectedFile = null;
        modal.classList.remove("hidden");
        dropZone.style.display = "block";
        resetDropZone();
        if (forceOcrCheck) forceOcrCheck.checked = false;
        startBtn.disabled = true;
        setModalMode("upload");
    }

    function openReplaceModal(id) {
        const doc = currentDocs.find(d => String(d.document_id) === String(id));
        openModal();                 // reset to a clean slate first
        replaceDocId = id;
        if (doc && doc.document_type) docTypeSelect.value = doc.document_type;
        setModalMode("replace", doc ? doc.document_name : "this document");
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
        const isReplace = replaceDocId !== null;
        const docId = replaceDocId;          // capture before the modal resets it
        const fd = new FormData();
        fd.append("file", selectedFile);
        fd.append("document_type", docTypeSelect.value);
        fd.append("force_ocr", forceOcrCheck && forceOcrCheck.checked ? "true" : "false");

        // Auto-minimize: close the modal and show a live processing card in the
        // list. Block a second upload until this one resolves.
        closeModal();
        openBtn.disabled = true;
        showProcessingCard(name, docTypeSelect.value);

        try {
            const res = isReplace
                ? await apiUpload(`/documents/${docId}/replace`, fd)
                : await apiUpload("/documents/upload", fd);
            const verb = isReplace ? "updated" : "processed";
            // Saved but held (low confidence / indexing error) -> surface why;
            // the refreshed list will show it as "Held for Review".
            if (!res.indexed) {
                if (res.index_error) console.warn(`[${isReplace ? "replace" : "upload"}] indexing error:`, res.index_error);
                alert(res.message || "Saved, but held for review.");
                window.pushNotification?.({
                    type: "document",
                    title: "Document held for review",
                    message: `“${name}” was saved but needs review before it’s indexed.`,
                });
            } else {
                window.pushNotification?.({
                    type: "document",
                    title: `Document fully ${verb}`,
                    message: isReplace
                        ? `“${name}” replaced the previous version (v${res.version}) and was re-indexed.`
                        : `“${name}” has been extracted, chunked, and indexed.`,
                });
            }
        } catch (err) {
            alert(`${isReplace ? "Replace" : "Upload"} failed: ${err.message}`);
        } finally {
            removeProcessingCard();
            openBtn.disabled = false;
            await loadDocuments();   // replace the card with the real document
            loadStats();             // corpus changed — refresh the headline figures
        }
    });

    // Initial load.
    loadDocuments();
    loadStats();
});
