document.addEventListener('DOMContentLoaded', () => {
    const STATUS_ENDPOINT = '/weather/status';
    const POLL_INTERVAL = 60000; // 60 seconds
    const FETCH_TIMEOUT_MS = 12000;

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
        distCard: document.getElementById('metric-distance-card'),
        countCard: document.getElementById('metric-count-card'),
        rainfallCard: document.getElementById('metric-rainfall-card'),
        legendDistancePointer: document.getElementById('legend-distance-pointer'),
        legendRainfallPointer: document.getElementById('legend-rainfall-pointer'),
        legendCountPointer: document.getElementById('legend-count-pointer'),
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

    const metricCardRiskClasses = {
        safe: ['border-emerald-200', 'from-emerald-50', 'to-green-100'],
        caution: ['border-amber-200', 'from-amber-50', 'to-yellow-100'],
        danger: ['border-rose-200', 'from-rose-50', 'to-red-100'],
        unknown: ['border-slate-200', 'from-slate-50', 'to-slate-100']
    };

    const metricValueRiskClasses = {
        safe: 'text-emerald-800',
        caution: 'text-amber-800',
        danger: 'text-rose-700',
        unknown: 'text-slate-700'
    };

    const allMetricCardRiskClasses = Object.values(metricCardRiskClasses).flat();
    const allMetricValueRiskClasses = Object.values(metricValueRiskClasses);

    function toPlainMessage(message) {
        let text = String(message || '');
        text = text.split('<br />').join('\n');
        text = text.split('<br/>').join('\n');
        text = text.split('<br>').join('\n');
        return text;
    }

    function normalizeForMatch(input) {
        return String(input || '')
            .replace(/[–—]/g, '-')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function translateMessageToChinese(englishMessage) {
        if (!englishMessage) {
            return '';
        }

        const msg = normalizeForMatch(englishMessage);
        if (!msg) {
            return '';
        }

        let match = msg.match(/^Pool Closed - Outside Operating Hours \((.+)\)$/);
        if (match) {
            const timePart = match[1]
                .replace('Weekend/Public Holiday', '周末/公共假日')
                .replace('Weekday', '工作日');
            return `泳池关闭 - 非运营时间（${timePart}）`;
        }
        if (msg.includes('Outside Operating Hours')) {
            return '泳池关闭 - 非运营时间';
        }

        match = msg.match(/^Manual report consensus: Pool (OPEN|CLOSED)$/);
        if (match) {
            const statusText = match[1] === 'OPEN' ? '开放' : '关闭';
            return `人工汇报共识：泳池${statusText}`;
        }
        if (msg.includes('Manual report consensus')) {
            return '人工汇报共识';
        }

        match = msg.match(/^Pool Closed due to Lightning Alert \(Nearest (.+)\)$/);
        if (match) {
            return `泳池因雷电警报关闭（最近雷电距离 ${match[1]}）`;
        }

        match = msg.match(/^Pool Closed due to Lightning Alert \(Estimated (\d+) min to reopen\)$/);
        if (match) {
            return `泳池因雷电警报关闭（预计 ${match[1]} 分钟后重开）`;
        }

        match = msg.match(/^Pool Closed due to Heavy Rain \((.+)\)$/);
        if (match) {
            return `泳池因强降雨关闭（${match[1]}）`;
        }

        match = msg.match(/^Pool Closed due to Heavy Rain \(Estimated (\d+) min to reopen\)$/);
        if (match) {
            return `泳池因强降雨关闭（预计 ${match[1]} 分钟后重开）`;
        }

        if (msg === 'Pool is Open') {
            return '泳池开放';
        }
        if (msg.includes('Pool is Open')) {
            return '泳池开放';
        }
        if (msg === 'Weather data temporarily unavailable') {
            return '天气数据暂时不可用';
        }
        if (msg.includes('Weather data temporarily unavailable')) {
            return '天气数据暂时不可用';
        }
        if (msg === 'Unable to reach weather service.') {
            return '无法连接天气服务。';
        }
        if (msg === 'Weather request timeout.') {
            return '天气服务请求超时。';
        }

        return '';
    }

    function toBilingualMessage(message) {
        const raw = toPlainMessage(message).trim();
        if (!raw) {
            return '';
        }

        const lines = raw
            .split('\n')
            .map((line) => line.trim())
            .filter(Boolean);

        const existingChinese = lines.find((line) => /[\u4e00-\u9fff]/.test(line));
        const englishMessage = lines.find((line) => /[A-Za-z]/.test(line)) || raw;
        const chineseMessage = existingChinese || translateMessageToChinese(englishMessage);

        if (!chineseMessage) {
            return englishMessage;
        }
        return `${englishMessage}\n${chineseMessage}`;
    }

    function toNumeric(value) {
        if (value === null || value === undefined || value === '') {
            return null;
        }
        const num = Number(value);
        return Number.isFinite(num) ? num : null;
    }

    function clamp(value, min, max) {
        return Math.max(min, Math.min(max, value));
    }

    function formatDistance(distanceKm) {
        if (distanceKm === null) {
            return '-- km';
        }
        if (distanceKm >= 15) {
            return '>15km';
        }
        const rounded = Math.round(distanceKm * 10) / 10;
        return `${rounded.toFixed(1)} km`;
    }

    function classifyLightningDistance(distanceKm) {
        if (distanceKm === null) {
            return 'unknown';
        }
        if (distanceKm <= 8) {
            return 'danger';
        }
        if (distanceKm <= 15) {
            return 'caution';
        }
        return 'safe';
    }

    function classifyRainfall(rainfallRate) {
        if (rainfallRate === null) {
            return 'unknown';
        }
        if (rainfallRate > 5) {
            return 'danger';
        }
        if (rainfallRate > 2) {
            return 'caution';
        }
        return 'safe';
    }

    function classifyLightningCount(lightningCount) {
        if (lightningCount === null) {
            return 'unknown';
        }
        if (lightningCount === 0) {
            return 'safe';
        }
        if (lightningCount <= 30) {
            return 'caution';
        }
        return 'danger';
    }

    function getDistancePointerPercent(distanceKm) {
        if (distanceKm === null) {
            return 50;
        }
        const normalizedRisk = 1 - clamp(distanceKm, 0, 20) / 20;
        return clamp(normalizedRisk * 100, 0, 100);
    }

    function getRainfallPointerPercent(rainfallRate) {
        if (rainfallRate === null) {
            return 50;
        }
        const normalizedRisk = clamp(rainfallRate, 0, 10) / 10;
        return clamp(normalizedRisk * 100, 0, 100);
    }

    function getLightningCountPointerPercent(lightningCount) {
        if (lightningCount === null) {
            return 50;
        }
        const normalizedRisk = clamp(lightningCount, 0, 120) / 120;
        return clamp(normalizedRisk * 100, 0, 100);
    }

    function setLegendPointer(pointerEl, percent, isUnknown = false) {
        if (!pointerEl) {
            return;
        }
        pointerEl.style.left = `${percent}%`;
        pointerEl.classList.toggle('opacity-40', isUnknown);
    }

    function applyLegendPointers(distanceKm, lightningCount, rainfallRate) {
        setLegendPointer(
            ui.legendDistancePointer,
            getDistancePointerPercent(distanceKm),
            distanceKm === null
        );
        setLegendPointer(
            ui.legendCountPointer,
            getLightningCountPointerPercent(lightningCount),
            lightningCount === null
        );
        setLegendPointer(
            ui.legendRainfallPointer,
            getRainfallPointerPercent(rainfallRate),
            rainfallRate === null
        );
    }

    function applyMetricRisk(cardEl, valueEl, risk) {
        if (!cardEl || !valueEl) {
            return;
        }

        allMetricCardRiskClasses.forEach((cls) => cardEl.classList.remove(cls));
        allMetricValueRiskClasses.forEach((cls) => valueEl.classList.remove(cls));

        metricCardRiskClasses[risk].forEach((cls) => cardEl.classList.add(cls));
        valueEl.classList.add(metricValueRiskClasses[risk]);
    }

    function applyUnknownMetricStyles() {
        applyMetricRisk(ui.distCard, ui.dist, 'unknown');
        applyMetricRisk(ui.countCard, ui.count, 'unknown');
        applyMetricRisk(ui.rainfallCard, ui.rainfall, 'unknown');
        applyLegendPointers(null, null, null);
    }

    async function fetchWithTimeout(url, timeoutMs) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        try {
            return await fetch(url, {
                cache: 'no-store',
                signal: controller.signal
            });
        } finally {
            clearTimeout(timer);
        }
    }

    async function updateWeather() {
        try {
            // Add loading pulse if needed, or subtle indication
            
            const response = await fetchWithTimeout(STATUS_ENDPOINT, FETCH_TIMEOUT_MS);
            if (!response.ok) throw new Error('Network response was not ok');
            
            const data = await response.json();
            const config = definitions[data.status] || definitions['GREEN']; // Fallback
            
            // 1. Update State Text & Colors
            ui.text.textContent = config.text;
            ui.text.className = `font-black tracking-wider ${config.colorClass} transition-colors duration-500`;
            
            // 2. Update Message
            ui.message.classList.add('whitespace-pre-line');
            ui.message.textContent = toBilingualMessage(data.message);
            
            // 3. Update Metrics
            const details = data.details || {};
            // Handle different field names from backend versions
            const dist = toNumeric(details.distance ?? details.lightning_dist ?? details.min_distance_km);
            const count = toNumeric(details.lightning_count);
            const rain = toNumeric(details.rainfall_rate);
            
            ui.dist.textContent = formatDistance(dist);
            ui.count.textContent = (count !== null) ? String(Math.round(count)) : '--';
            ui.rainfall.textContent = (rain !== null) ? `${rain.toFixed(1)} mm/h` : '-- mm/h';

            applyMetricRisk(ui.distCard, ui.dist, classifyLightningDistance(dist));
            applyMetricRisk(ui.countCard, ui.count, classifyLightningCount(count));
            applyMetricRisk(ui.rainfallCard, ui.rainfall, classifyRainfall(rain));
            applyLegendPointers(dist, count, rain);
            
            // 4. Update Visuals (Icon, Ring, Background)
            ui.ring.className = `flex items-center justify-center w-24 h-24 rounded-full ring-4 transition-all duration-500 ${config.ringClass}`;
            ui.ring.innerHTML = config.icon;
            
            ui.bgGradient.className = `absolute inset-0 opacity-20 transition-all duration-1000 bg-gradient-to-br ${config.bgClass}`;

            // 5. Update Time
            const now = new Date();
            ui.updated.textContent = now.toLocaleTimeString();

        } catch (error) {
            console.error('Weather fetch error:', error);
            ui.message.textContent = toBilingualMessage('Unable to reach weather service.');
            ui.text.textContent = "OFFLINE";
            ui.text.className = "text-gray-400";
            ui.dist.textContent = '-- km';
            ui.count.textContent = '--';
            ui.rainfall.textContent = '-- mm/h';
            applyUnknownMetricStyles();
        }
    }

    // Initial load
    updateWeather();

    // Poll
    setInterval(updateWeather, POLL_INTERVAL);
});
