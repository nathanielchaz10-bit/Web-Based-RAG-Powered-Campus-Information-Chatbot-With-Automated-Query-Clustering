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
    const pipeline = document.getElementById("upload-pipeline");
    const docTypeSelect = document.getElementById("doc-type-select");
    const forceOcrCheck = document.getElementById("force-ocr-check");
    const docList = document.getElementById("doc-list");

    const stepExtract = document.getElementById("step-extract");
    const stepChunk = document.getElementById("step-chunk");
    const stepEmbed = document.getElementById("step-embed");

    const minimizeBtn = document.getElementById("minimize-modal-btn");
    const minChip = document.getElementById("upload-min-chip");
    const minChipText = document.getElementById("upload-min-text");
    const forceOcrRow = forceOcrCheck ? forceOcrCheck.closest(".force-ocr-row") : null;

    let selectedFile = null;
    let uploadDone = false;

    // While an upload is in flight we lock the choices (type + Force OCR) so they
    // can't change mid-process, and lock the dismiss buttons (Cancel/×) so the
    // run can't be abandoned -- Minimize is offered instead. Both are released
    // when the modal is reset for the next upload.
    function lockChoices(on) {
        docTypeSelect.disabled = on;
        if (forceOcrCheck) forceOcrCheck.disabled = on;
        if (forceOcrRow) forceOcrRow.classList.toggle("disabled", on);
    }
    function lockDismiss(on) {
        cancelBtn.disabled = on;
        closeBtn.disabled = on;
        minimizeBtn.classList.toggle("hidden", !on);  // show Minimize only while locked
    }
    function setMinimized(on) {
        modal.classList.toggle("hidden", on);          // hide dialog; processing continues
        minChip.classList.toggle("hidden", !on);
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

    function docCardHTML(d) {
        const conf = d.extraction_confidence ? d.extraction_confidence.toUpperCase() : "—";
        const method = d.extraction_method || "—";
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
                    <div class="metric-col">
                        <span class="metric-label">TYPE</span>
                        <span class="metric-val">${escapeHtml(d.document_type || "—")}</span>
                    </div>
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
        uploadDone = false;
        modal.classList.remove("hidden");
        dropZone.style.display = "block";
        resetDropZone();
        pipeline.classList.add("hidden");
        if (forceOcrCheck) forceOcrCheck.checked = false;
        startBtn.disabled = true;
        startBtn.textContent = "Start Processing";
        // Release any locks/minimize state left over from a previous upload.
        lockChoices(false);
        lockDismiss(false);
        minChip.classList.add("hidden");
        minChip.classList.remove("done");
    }
    function closeModal() {
        modal.classList.add("hidden");
        minChip.classList.add("hidden");
    }

    openBtn.addEventListener("click", openModal);
    closeBtn.addEventListener("click", closeModal);
    cancelBtn.addEventListener("click", closeModal);
    minimizeBtn.addEventListener("click", () => setMinimized(true));
    minChip.addEventListener("click", () => setMinimized(false));

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

    function setStep(el, state, text) {
        el.className = `step ${state}`;
        el.innerHTML = text;
    }

    startBtn.addEventListener("click", async () => {
        if (uploadDone) { closeModal(); return; }
        if (!selectedFile) return;

        startBtn.disabled = true;
        lockChoices(true);   // freeze type + Force OCR for this run
        lockDismiss(true);   // no Cancel/× mid-process; offer Minimize instead
        minChip.classList.remove("done");
        if (minChipText) minChipText.textContent = "Processing upload…";
        dropZone.style.display = "none";
        pipeline.classList.remove("hidden");
        setStep(stepExtract, "active", "Uploading &amp; extracting text…");
        setStep(stepChunk, "pending", "2. Generating semantic chunks…");
        setStep(stepEmbed, "pending", "3. Vectorizing &amp; indexing…");

        try {
            const fd = new FormData();
            fd.append("file", selectedFile);
            fd.append("document_type", docTypeSelect.value);
            fd.append("force_ocr", forceOcrCheck && forceOcrCheck.checked ? "true" : "false");

            const res = await apiUpload("/documents/upload", fd);

            setStep(stepExtract, "done", `1. Extracted via ${escapeHtml(res.extraction_method)} ✓`);
            setStep(stepChunk, "done", "2. Chunks generated ✓");
            if (res.indexed) {
                setStep(stepEmbed, "done", `3. Indexed ${res.chunk_count} chunks (${escapeHtml(res.confidence)} confidence) ✓`);
            } else {
                // Held: show the backend's actual reason (low confidence vs. an
                // indexing error such as a missing API key / exhausted quota),
                // plus the raw cause as a muted detail when present.
                const reason = res.message || "Held for review.";
                const detail = res.index_error
                    ? `<div class="step-detail">${escapeHtml(res.index_error)}</div>`
                    : "";
                setStep(stepEmbed, "active", `3. ⚠ ${escapeHtml(reason)}${detail}`);
                if (res.index_error) console.warn("[upload] indexing error:", res.index_error);
            }
            await loadDocuments();
        } catch (err) {
            setStep(stepExtract, "active", `Upload failed: ${escapeHtml(err.message)}`);
            setStep(stepChunk, "pending", "2. Generating semantic chunks…");
            setStep(stepEmbed, "pending", "3. Vectorizing &amp; indexing…");
        } finally {
            uploadDone = true;
            startBtn.textContent = "Done";
            startBtn.disabled = false;
            lockDismiss(false);            // allow closing now; hide Minimize
            minChip.classList.add("done");
            if (minChipText) minChipText.textContent = "Upload finished — tap to view";
        }
    });

    // Initial load.
    loadDocuments();
});
