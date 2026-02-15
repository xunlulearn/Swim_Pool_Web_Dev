document.addEventListener('DOMContentLoaded', () => {
    const feedContainer = document.getElementById('live-feed-list');
    const reportBtn = document.getElementById('report-status-btn');
    const reportOptions = document.getElementById('report-options');

    const API_URL = '/api/live-status/';

    function getCsrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    function timeAgo(dateString) {
        const date = new Date(dateString + 'Z');
        const now = new Date();
        const seconds = Math.floor((now - date) / 1000);

        let interval = seconds / 3600;
        if (interval > 24) return Math.floor(interval / 24) + ' days ago';
        if (interval > 1) return Math.floor(interval) + ' hours ago';
        interval = seconds / 60;
        if (interval > 1) return Math.floor(interval) + ' mins ago';
        return 'Just now';
    }

    async function fetchReports() {
        try {
            const res = await fetch(API_URL);
            const data = await res.json();
            renderFeed(data);
        } catch (err) {
            console.error('Error fetching live status:', err);
        }
    }

    function renderFeed(reports) {
        if (!feedContainer) return;
        feedContainer.textContent = '';

        if (!Array.isArray(reports) || reports.length === 0) {
            const emptyItem = document.createElement('li');
            emptyItem.className = 'text-sm text-gray-400 text-center py-2';
            emptyItem.textContent = 'No recent reports.';
            feedContainer.appendChild(emptyItem);
            return;
        }

        reports.forEach((report) => {
            const isOld = (new Date() - new Date(report.timestamp + 'Z')) > 2 * 60 * 60 * 1000;
            const opacityClass = isOld ? 'opacity-40' : '';
            const statusColor = report.status === 'Open' ? 'text-green-600 bg-green-50' : 'text-red-600 bg-red-50';
            const icon = report.status === 'Open' ? '[OPEN]' : '[CLOSED]';

            const row = document.createElement('div');
            row.className = `flex items-center justify-between p-3 rounded-lg border border-gray-50 mb-2 ${opacityClass}`;

            const left = document.createElement('div');
            left.className = 'flex items-center gap-3';

            const statusBadge = document.createElement('span');
            statusBadge.className = `text-xs font-semibold px-2 py-1 rounded-full ${statusColor}`;
            statusBadge.textContent = `${icon} ${report.status}`;

            const userName = document.createElement('span');
            userName.className = 'text-sm font-medium text-slate-700';
            userName.textContent = report.user || 'Unknown';

            const right = document.createElement('span');
            right.className = 'text-xs text-gray-400 font-mono';
            right.textContent = timeAgo(report.timestamp);

            left.appendChild(statusBadge);
            left.appendChild(userName);
            row.appendChild(left);
            row.appendChild(right);
            feedContainer.appendChild(row);
        });
    }

    if (reportBtn && reportOptions) {
        reportBtn.addEventListener('click', () => {
            reportOptions.classList.toggle('hidden');
        });

        document.querySelectorAll('.submit-report-action').forEach((btn) => {
            btn.addEventListener('click', async (e) => {
                const status = e.currentTarget.dataset.status;

                try {
                    const res = await fetch(API_URL, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCsrfToken(),
                        },
                        body: JSON.stringify({ status }),
                    });

                    if (res.ok) {
                        alert('Thanks for your report!');
                        reportOptions.classList.add('hidden');
                        fetchReports();
                    } else {
                        const err = await res.json().catch(() => ({}));
                        alert('Error: ' + (err.error || 'Failed to submit'));
                    }
                } catch (err) {
                    alert('Network error');
                }
            });
        });
    }

    fetchReports();
    setInterval(fetchReports, 60000);
});
