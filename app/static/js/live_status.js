document.addEventListener('DOMContentLoaded', () => {
    const feedContainer = document.getElementById('live-feed-list');
    const reportBtn = document.getElementById('report-status-btn');
    const reportOptions = document.getElementById('report-options');

    const API_URL = '/api/live-status/';
    const CSRF_ERROR_TEXT = 'invalid or missing csrf token';

    function getCsrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? String(meta.getAttribute('content') || '').trim() : '';
    }

    function setCsrfToken(token) {
        const normalized = String(token || '').trim();
        if (!normalized) return;

        let meta = document.querySelector('meta[name="csrf-token"]');
        if (!meta) {
            meta = document.createElement('meta');
            meta.setAttribute('name', 'csrf-token');
            document.head.appendChild(meta);
        }
        meta.setAttribute('content', normalized);

        document.querySelectorAll('input[name="csrf_token"]').forEach((inputEl) => {
            inputEl.value = normalized;
        });
    }

    function isCsrfErrorResponse(response, payload) {
        if (!response || response.status !== 400) return false;
        const errorText = String(payload?.error || '').trim().toLowerCase();
        return errorText === CSRF_ERROR_TEXT;
    }

    async function refreshCsrfToken() {
        try {
            const res = await fetch('/api/csrf-token', {
                method: 'GET',
                headers: { Accept: 'application/json' },
                credentials: 'same-origin',
                cache: 'no-store',
            });
            if (!res.ok) return '';
            const data = await res.json().catch(() => ({}));
            const token = String(data?.csrf_token || '').trim();
            if (!token) return '';
            setCsrfToken(token);
            return token;
        } catch (_error) {
            return '';
        }
    }

    async function resolveCsrfToken() {
        const token = getCsrfToken();
        if (token) return token;
        return refreshCsrfToken();
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

        const latestReports = Array.isArray(reports) ? reports.slice(0, 10) : [];

        if (latestReports.length === 0) {
            const emptyItem = document.createElement('div');
            emptyItem.className = 'rounded-xl border border-dashed border-slate-200 bg-white/80 px-4 py-5 text-center text-sm text-slate-500';
            emptyItem.textContent = 'No recent reports yet.';
            feedContainer.appendChild(emptyItem);
            return;
        }

        latestReports.forEach((report, index) => {
            const isOld = (new Date() - new Date(report.timestamp + 'Z')) > 2 * 60 * 60 * 1000;
            const ageClass = isOld ? 'opacity-60 saturate-50' : '';
            const isNewest = index === 0;
            const isOpen = report.status === 'Open';

            const statusColor = isOpen
                ? 'border border-emerald-200 bg-emerald-50 text-emerald-700'
                : 'border border-rose-200 bg-rose-50 text-rose-700';
            const rowTone = isOpen
                ? 'from-emerald-50/65 to-white border-emerald-100'
                : 'from-rose-50/65 to-white border-rose-100';

            const row = document.createElement('div');
            row.className = `mb-2 flex items-center justify-between rounded-xl border bg-gradient-to-r px-3 py-2 ${rowTone} ${ageClass} ${isNewest ? 'ring-1 ring-slate-200 shadow-sm' : ''}`;

            const left = document.createElement('div');
            left.className = 'flex items-center gap-3';

            const statusBadge = document.createElement('span');
            statusBadge.className = `rounded-full px-2 py-1 text-xs font-semibold ${statusColor}`;
            statusBadge.textContent = report.status.toUpperCase();

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
                    const sendRequest = (token) =>
                        fetch(API_URL, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-CSRFToken': token,
                            },
                            credentials: 'same-origin',
                            body: JSON.stringify({ status }),
                        });

                    const csrfToken = await resolveCsrfToken();
                    if (!csrfToken) {
                        alert('Error: CSRF token missing, please refresh and retry.');
                        return;
                    }

                    let res = await sendRequest(csrfToken);
                    let err = null;
                    if (!res.ok) {
                        err = await res.json().catch(() => ({}));
                        if (isCsrfErrorResponse(res, err)) {
                            const refreshedToken = await refreshCsrfToken();
                            if (refreshedToken) {
                                res = await sendRequest(refreshedToken);
                                if (!res.ok) {
                                    err = await res.json().catch(() => ({}));
                                } else {
                                    err = null;
                                }
                            }
                        }
                    }

                    if (res.ok) {
                        alert('Thanks for your report!');
                        reportOptions.classList.add('hidden');
                        fetchReports();
                    } else {
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
