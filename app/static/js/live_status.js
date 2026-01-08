document.addEventListener('DOMContentLoaded', () => {
    const feedContainer = document.getElementById('live-feed-list');
    const reportBtn = document.getElementById('report-status-btn');
    const reportOptions = document.getElementById('report-options');
    
    // Config
    const API_URL = '/api/live-status/';
    
    // Time formatter
    function timeAgo(dateString) {
        const date = new Date(dateString + 'Z'); // Assume UTC
        const now = new Date();
        const seconds = Math.floor((now - date) / 1000);
        
        let interval = seconds / 3600;
        if (interval > 24) return Math.floor(interval/24) + " days ago";
        if (interval > 1) return Math.floor(interval) + " hours ago";
        interval = seconds / 60;
        if (interval > 1) return Math.floor(interval) + " mins ago";
        return "Just now";
    }

    // Fetch Reports
    async function fetchReports() {
        try {
            const res = await fetch(API_URL);
            const data = await res.json();
            renderFeed(data);
        } catch (err) {
            console.error('Error fetching live status:', err);
        }
    }

    // Render Feed
    function renderFeed(reports) {
        if (!feedContainer) return;
        feedContainer.innerHTML = '';
        
        if (reports.length === 0) {
            feedContainer.innerHTML = '<li class="text-sm text-gray-400 text-center py-2">No recent reports.</li>';
            return;
        }

        reports.forEach(report => {
            const isOld = (new Date() - new Date(report.timestamp + 'Z')) > 2 * 60 * 60 * 1000; // 2 hours
            const opacityClass = isOld ? 'opacity-40' : '';
            const statusColor = report.status === 'Open' ? 'text-green-600 bg-green-50' : 'text-red-600 bg-red-50';
            const icon = report.status === 'Open' ? '🟢' : '🔴';
            
            const li = document.createElement('div');
            li.className = `flex items-center justify-between p-3 rounded-lg border border-gray-50 mb-2 ${opacityClass}`;
            li.innerHTML = `
                <div class="flex items-center gap-3">
                    <span class="text-xs font-semibold px-2 py-1 rounded-full ${statusColor}">${icon} ${report.status}</span>
                    <span class="text-sm font-medium text-slate-700">${report.user}</span>
                </div>
                <span class="text-xs text-gray-400 font-mono">${timeAgo(report.timestamp)}</span>
            `;
            feedContainer.appendChild(li);
        });
    }

    // Report Action
    if (reportBtn) {
        reportBtn.addEventListener('click', () => {
            reportOptions.classList.toggle('hidden');
        });

        document.querySelectorAll('.submit-report-action').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const status = e.target.dataset.status;
                
                try {
                    const res = await fetch(API_URL, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({status})
                    });
                    
                    if (res.ok) {
                        alert('Thanks for your report!');
                        reportOptions.classList.add('hidden');
                        fetchReports();
                    } else {
                        const err = await res.json();
                        alert('Error: ' + (err.error || 'Failed to submit'));
                    }
                } catch (err) {
                    alert('Network error');
                }
            });
        });
    }

    // Init
    fetchReports();
    setInterval(fetchReports, 60000); // Poll every minute
});
