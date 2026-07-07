// Starter FAQ questions shown on the empty chat screen so users have somewhere
// to begin without typing. NOTE: these are hand-picked common questions, NOT
// derived from institutional query data — keep them answerable from the indexed
// documents so a click doesn't dead-end in a "couldn't find that" reply.

// These map to the "Frequently Asked Questions" knowledge doc (uploads/txt/,
// type DIRECTORY) so a click is grounded and answered formally by the bot —
// and so the same facts are available when a student types the question or
// asks a follow-up. Re-ingest that doc after editing it (see database/ingest_file.py).
const STUDENT_FAQS = [
    "What are the school's office hours?",
    "How can I contact the school?",
    "How do I request my Form 137?",
    "How do I contact the Registrar's Office?",
    "How do I contact the Alumni Office?",
];

// Guests can only reach the enrollment + scholarship documents, so their
// starters stay within that scope.
const GUEST_FAQS = [
    "What are the enrollment requirements?",
    "When does enrollment start?",
    "What is the enrollment process?",
    "What scholarships are available?",
    "How do I apply for a scholarship?",
];

// Render clickable FAQ chips into `container`; clicking one calls onPick(text).
// Removes any previously-rendered set first so it's safe to call repeatedly.
function renderFaqChips(container, questions, onPick) {
    if (!container) return;
    const existing = container.querySelector(".faq-chips");
    if (existing) existing.remove();

    const wrap = document.createElement("div");
    wrap.className = "suggested-chips faq-chips";
    questions.forEach((q) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "suggestion-chip";
        btn.textContent = q;
        btn.addEventListener("click", () => onPick(q));
        wrap.appendChild(btn);
    });
    container.appendChild(wrap);
    return wrap;
}
