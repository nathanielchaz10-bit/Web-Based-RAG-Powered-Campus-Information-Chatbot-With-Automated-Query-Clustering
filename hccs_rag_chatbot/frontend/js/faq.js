// Starter FAQ questions shown on the empty chat screen so users have somewhere
// to begin without typing. NOTE: these are hand-picked common questions, NOT
// derived from institutional query data — keep them answerable from the indexed
// documents so a click doesn't dead-end in a "couldn't find that" reply.

const STUDENT_FAQS = [
    "What are the enrollment requirements?",
    "When does enrollment start?",
    "What scholarships are available?",
    "How do I apply for a scholarship?",
    "Where can I find the student handbook?",
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
