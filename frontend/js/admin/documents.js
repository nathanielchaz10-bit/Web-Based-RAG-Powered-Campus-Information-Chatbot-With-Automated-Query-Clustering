document.addEventListener("DOMContentLoaded", () => {

    // --- 1. MODAL LOGIC ---
    const modal = document.getElementById("upload-modal");
    const openBtn = document.getElementById("open-upload-btn");
    const closeBtn = document.getElementById("close-modal-btn");
    const cancelBtn = document.getElementById("cancel-upload");

    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("file-input");
    const startBtn = document.getElementById("start-upload-btn");
    const pipeline = document.getElementById("upload-pipeline");

    function openModal() {
        modal.classList.remove("hidden");
        dropZone.style.display = "block";
        pipeline.classList.add("hidden");
        startBtn.disabled = true;
        startBtn.textContent = "Start Processing";
    }

    function closeModal() { modal.classList.add("hidden"); }

    openBtn.addEventListener("click", openModal);
    closeBtn.addEventListener("click", closeModal);
    cancelBtn.addEventListener("click", closeModal);

    dropZone.addEventListener("click", () => fileInput.click());

    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("dragover");
    });

    dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));

    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("dragover");
        if (e.dataTransfer.files.length > 0) {
            handleFileSelect(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener("change", (e) => {
        if (e.target.files.length > 0) {
            handleFileSelect(e.target.files[0]);
        }
    });

    function handleFileSelect(file) {
        dropZone.innerHTML = `
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2" style="margin-bottom:8px;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
            <p style="color:#0f172a; font-weight:600;">${file.name}</p>
            <span class="file-limits">${(file.size / 1024 / 1024).toFixed(2)} MB</span>
        `;
        startBtn.disabled = false;
    }

    // --- 3. MOCK PROCESSING PIPELINE ---
    startBtn.addEventListener("click", () => {
        startBtn.disabled = true;
        dropZone.style.display = "none";
        pipeline.classList.remove("hidden");

        const steps = [
            document.getElementById("step-extract"),
            document.getElementById("step-chunk"),
            document.getElementById("step-embed")
        ];

        setTimeout(() => {
            steps[0].classList.replace("active", "done");
            steps[0].innerHTML = "1. Extraction Complete ✓";
            steps[1].classList.replace("pending", "active");
        }, 1500);

        setTimeout(() => {
            steps[1].classList.replace("active", "done");
            steps[1].innerHTML = "2. Chunks Generated ✓";
            steps[2].classList.replace("pending", "active");
        }, 3500);

        setTimeout(() => {
            steps[2].classList.replace("active", "done");
            steps[2].innerHTML = "3. Indexed in Vector Database ✓";
            startBtn.textContent = "Done";
            startBtn.disabled = false;
            startBtn.addEventListener("click", closeModal, { once: true });
        }, 6000);
    });

    // --- 4. CRUD ACTION MENUS ---
    document.querySelectorAll(".action-toggle").forEach(btn => {
        btn.addEventListener("click", (e) => {
            document.querySelectorAll(".action-dropdown").forEach(menu => menu.remove());

            if(btn.disabled) return;

            const menu = document.createElement("div");
            menu.className = "action-dropdown";
            menu.innerHTML = `
                <button class="action-item"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg> Replace Version</button>
                <button class="action-item"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg> Temporarily Hide</button>
                <button class="action-item danger"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg> Delete from DB</button>
            `;

            e.currentTarget.parentElement.appendChild(menu);
            e.stopPropagation();
        });
    });

    document.addEventListener("click", () => {
        document.querySelectorAll(".action-dropdown").forEach(menu => menu.remove());
    });
});