document.addEventListener('DOMContentLoaded', () => {
    const STATUS_ENDPOINT = '/weather/status';
    const POLL_INTERVAL = 60000; // 60 seconds

    const ui = {
        card: document.getElementById('status-card'),
        bgGradient: document.getElementById('status-bg-gradient'),
        ring: document.getElementById('status-ring'),
        iconContainer: document.getElementById('status-icon-container'),
        text: document.getElementById('status-text'),
        message: document.getElementById('status-message'),
        dist: document.getElementById('metric-distance'),
        count: document.getElementById('metric-count'),
        rainfall: document.getElementById('metric-rainfall'),
        updated: document.getElementById('last-updated')
    };

    const definitions = {
        'GREEN': {
            text: 'OPEN',
            colorClass: 'text-green-600',
            bgClass: 'from-green-100 to-emerald-50',
            ringClass: 'bg-green-100 text-green-600 ring-green-50',
            icon: `<svg class="w-12 h-12" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"></path></svg>`
        },
        'AMBER': {
            text: 'WARNING',
            colorClass: 'text-amber-600',
            bgClass: 'from-amber-100 to-orange-50',
            ringClass: 'bg-amber-100 text-amber-600 ring-amber-50',
            icon: `<svg class="w-12 h-12" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>`
        },
        'RED': {
            text: 'CLOSED',
            colorClass: 'text-red-600',
            bgClass: 'from-red-100 to-rose-50',
            ringClass: 'bg-red-100 text-red-600 ring-red-50',
            icon: `<svg class="w-12 h-12" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>`
        }
    };

    async function updateWeather() {
        try {
            // Add loading pulse if needed, or subtle indication
            
            const response = await fetch(STATUS_ENDPOINT);
            if (!response.ok) throw new Error('Network response was not ok');
            
            const data = await response.json();
            const config = definitions[data.status] || definitions['GREEN']; // Fallback
            
            // 1. Update State Text & Colors
            ui.text.textContent = config.text;
            ui.text.className = `font-black tracking-wider ${config.colorClass} transition-colors duration-500`;
            
            // 2. Update Message
            ui.message.innerHTML = data.message;
            
            // 3. Update Metrics
            const details = data.details || {};
            // Handle different field names from backend versions
            const dist = details.distance || details.lightning_dist || details.min_distance_km;
            const count = details.lightning_count;
            const rain = details.rainfall_rate;
            
            ui.dist.textContent = (dist !== null && dist !== undefined) ? `${dist} km` : '> 15 km';
            ui.count.textContent = (count !== null && count !== undefined) ? count : '--';
            ui.rainfall.textContent = (rain !== null && rain !== undefined) ? `${rain.toFixed(1)} mm/h` : '-- mm/h';
            
            // 4. Update Visuals (Icon, Ring, Background)
            ui.ring.className = `flex items-center justify-center w-24 h-24 rounded-full ring-4 transition-all duration-500 ${config.ringClass}`;
            ui.ring.innerHTML = config.icon;
            
            ui.bgGradient.className = `absolute inset-0 opacity-20 transition-all duration-1000 bg-gradient-to-br ${config.bgClass}`;

            // 5. Update Time
            const now = new Date();
            ui.updated.textContent = now.toLocaleTimeString();

        } catch (error) {
            console.error('Weather fetch error:', error);
            ui.message.textContent = "Unable to reach weather service.";
            ui.text.textContent = "OFFLINE";
            ui.text.className = "text-gray-400";
        }
    }

    // Initial load
    updateWeather();

    // Poll
    setInterval(updateWeather, POLL_INTERVAL);
});
