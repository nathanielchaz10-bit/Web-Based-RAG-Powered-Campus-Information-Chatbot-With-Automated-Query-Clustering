document.addEventListener("DOMContentLoaded", () => {

    const ctx = document.getElementById('topicChart');
    if (ctx && typeof Chart !== 'undefined') {
        new Chart(ctx.getContext('2d'), {
            type: 'bar',
            data: {
                labels: ['Scholarship Guidelines', 'Enrollment Schedules', 'Uniform Policies', 'Clinic Hours'],
                datasets: [{
                    label: 'Query Volume',
                    data: [120, 85, 40, 15],
                    backgroundColor: ['#152e51', '#0ea5e9', '#7dd3fc', '#e0f2fe'],
                    borderRadius: 4,
                    barThickness: 50
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 140,
                        ticks: { color: '#94a3b8', font: { size: 11 }, stepSize: 20 },
                        border: { display: false },
                        grid: { color: '#f1f5f9' }
                    },
                    x: {
                        ticks: { color: '#64748b', font: { size: 11 } },
                        grid: { display: false },
                        border: { display: false }
                    }
                }
            }
        });
    }

    // ==========================================
    // 2. DYNAMIC CLUSTER CARDS INJECTION
    // ==========================================
    const clusterData = [
        {
            title: "Scholarship Guidelines",
            iconSvg: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 10v6M2 10l10-5 10 5-10 5z"></path><path d="M6 12v5c3 3 9 3 12 0v-5"></path></svg>',
            iconClass: "blue",
            badgeText: "HIGH TRENDING",
            badgeClass: "green",
            percent: "45%",
            keywords: ["GWA", "Form 138", "Deadline", "Requirements"]
        },
        {
            title: "Enrollment Schedules",
            iconSvg: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>',
            iconClass: "purple",
            badgeText: "ACTIVE PERIOD",
            badgeClass: "blue",
            percent: "30%",
            keywords: ["Dates", "Late Enrollment", "Cashier", "Registration"]
        },
        {
            title: "Uniform Policies",
            iconSvg: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.38 3.46L16 2a8 8 0 0 1-8 0L3.62 3.46a2 2 0 0 0-1.34 2.23l.58 3.47a1 1 0 0 0 .99.84H6v10c0 1.1.9 2 2 2h8a2 2 0 0 0 2-2V10h2.15a1 1 0 0 0 .99-.84l.58-3.47a2 2 0 0 0-1.34-2.23z"></path></svg>',
            iconClass: "pink",
            badgeText: "RECURRING",
            badgeClass: "yellow",
            percent: "15%",
            keywords: ["PE Uniform", "Haircut", "Shoes", "Wash day"]
        }
    ];

    const container = document.getElementById("cluster-cards-container");
    if (container) {
        clusterData.forEach(card => {
            const tagsHtml = card.keywords.map(kw => `<span class="kw-tag">${kw}</span>`).join('');
            container.innerHTML += `
                <div class="cluster-card">
                    <div class="cluster-card-header">
                        <div class="card-icon ${card.iconClass}">${card.iconSvg}</div>
                        <span class="status-badge ${card.badgeClass}">${card.badgeText}</span>
                    </div>
                    <h3>${card.title}</h3>
                    <div class="cluster-vol">
                        <span class="pct">${card.percent}</span>
                        <span class="lbl">of total volume</span>
                    </div>
                    <p class="card-sm-title" style="margin-bottom: 8px;">TOP CLUSTER KEYWORDS</p>
                    <div class="tag-container">${tagsHtml}</div>
                    <button class="view-raw-btn">View Raw Queries <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg></button>
                </div>
            `;
        });
    }

    // ==========================================
    // 3. UI OVERLAYS & MODALS LOGIC
    // ==========================================
    try {
        const sentimentModal = document.getElementById('sentiment-modal');
        const queriesModal = document.getElementById('queries-modal');

        // Open Sentiment Modal
        document.querySelectorAll('.sentiment-row.clickable-row').forEach(row => {
            row.addEventListener('click', () => {
                if(sentimentModal) sentimentModal.classList.remove('hidden');
            });
        });

        // Open Raw Queries Modal
        document.body.addEventListener('click', (e) => {
            if(e.target.closest('.view-raw-btn')) {
                if(queriesModal) queriesModal.classList.remove('hidden');
            }
        });

        // Filter Toggle Logic inside the Queries Modal
        const toggleBtns = document.querySelectorAll('.toggle-btn');
        const queryCards = document.querySelectorAll('.query-card');

        toggleBtns.forEach(btn => {
            btn.addEventListener('click', (e) => {
                toggleBtns.forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');

                const filterType = e.target.getAttribute('data-filter');
                queryCards.forEach(card => {
                    if (filterType === 'all') {
                        card.style.display = 'block';
                    } else if (filterType === 'low') {
                        card.style.display = card.classList.contains('filter-low') ? 'block' : 'none';
                    }
                });
            });
        });

        // Close logic (Clicking the X buttons)
        document.querySelectorAll('.close-ui-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                if(sentimentModal) sentimentModal.classList.add('hidden');
                if(queriesModal) queriesModal.classList.add('hidden');
            });
        });

        // Close logic (Clicking the blurred background)
        document.querySelectorAll('.ui-overlay').forEach(overlay => {
            overlay.addEventListener('click', (e) => {
                if(e.target === overlay) {
                    overlay.classList.add('hidden');
                }
            });
        });
    } catch (error) {
        console.error("Modal Logic Failed:", error);
    }
});