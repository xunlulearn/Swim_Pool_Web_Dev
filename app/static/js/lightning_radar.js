document.addEventListener('DOMContentLoaded', () => {
    const RADAR_ENDPOINT = '/weather/lightning-radar';

    const CONFIG = {
        ntuLat: 1.349383588,
        ntuLng: 103.6877553,
        scale: 1484.27,
        radarSize: 800,
        scanSpeed: 1.5,
        refreshInterval: 60000,
    };

    const centerPx = CONFIG.radarSize / 2;

    const ui = {
        bgCanvas: document.getElementById('lightning-radar-bg'),
        sweepCanvas: document.getElementById('lightning-radar-sweep'),
        pointsLayer: document.getElementById('lightning-radar-points'),
        status: document.getElementById('lightning-radar-status'),
        count: document.getElementById('lightning-radar-count'),
        nearest: document.getElementById('lightning-radar-nearest'),
        risk: document.getElementById('lightning-radar-risk'),
        updated: document.getElementById('lightning-radar-updated'),
    };

    if (!ui.bgCanvas || !ui.sweepCanvas || !ui.pointsLayer || !ui.status) {
        return;
    }

    const ctxBg = ui.bgCanvas.getContext('2d');
    const ctxSweep = ui.sweepCanvas.getContext('2d');
    if (!ctxBg || !ctxSweep) {
        ui.status.textContent = 'Radar canvas is unavailable in this browser.';
        return;
    }

    let activeLightningPoints = [];
    let latestStrikes = [];
    let currentScanAngle = 0;
    let animationId = null;

    const riskTextClasses = ['text-slate-700', 'text-emerald-700', 'text-amber-700', 'text-rose-700'];

    function toNumber(value) {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : null;
    }

    function formatDistance(distanceKm) {
        if (distanceKm === null || distanceKm === undefined) {
            return '-- km';
        }

        const numeric = Number(distanceKm);
        if (!Number.isFinite(numeric)) {
            return '-- km';
        }

        if (numeric > 15) {
            return '>15km';
        }
        return `${numeric.toFixed(1)} km`;
    }

    function formatSnapshotTime(isoText) {
        if (!isoText) {
            return '--:--';
        }

        const parsed = new Date(isoText);
        if (Number.isNaN(parsed.getTime())) {
            return '--:--';
        }

        const hh = String(parsed.getHours()).padStart(2, '0');
        const mm = String(parsed.getMinutes()).padStart(2, '0');
        return `${hh}:${mm}`;
    }

    function applyRiskLevel(riskLevel) {
        const normalized = String(riskLevel || '').toLowerCase();
        ui.risk.classList.remove(...riskTextClasses);

        if (normalized === 'high') {
            ui.risk.classList.add('text-rose-700');
            ui.risk.textContent = 'High';
            return;
        }
        if (normalized === 'warning') {
            ui.risk.classList.add('text-amber-700');
            ui.risk.textContent = 'Warning';
            return;
        }
        if (normalized === 'watch') {
            ui.risk.classList.add('text-amber-700');
            ui.risk.textContent = 'Watch';
            return;
        }
        if (normalized === 'clear') {
            ui.risk.classList.add('text-emerald-700');
            ui.risk.textContent = 'Clear';
            return;
        }

        ui.risk.classList.add('text-slate-700');
        ui.risk.textContent = '--';
    }

    function latLngToXY(lat, lng) {
        const cosLat = Math.cos(CONFIG.ntuLat * Math.PI / 180);
        const dx = (lng - CONFIG.ntuLng) * cosLat * CONFIG.scale;
        const dy = (CONFIG.ntuLat - lat) * CONFIG.scale;

        return {
            x: centerPx + dx,
            y: centerPx + dy,
        };
    }

    function syncRadarGeometryFromPayload(payload) {
        const centerLat = toNumber(payload?.center?.lat);
        const centerLng = toNumber(payload?.center?.lng);
        const radiusKm = toNumber(payload?.radius_km);

        if (centerLat !== null) {
            CONFIG.ntuLat = centerLat;
        }
        if (centerLng !== null) {
            CONFIG.ntuLng = centerLng;
        }
        if (radiusKm !== null && radiusKm > 0) {
            CONFIG.scale = (centerPx * 111.32) / radiusKm;
        }
    }

    function getRenderScale() {
        const width = ui.pointsLayer.clientWidth || ui.bgCanvas.clientWidth || CONFIG.radarSize;
        if (!Number.isFinite(width) || width <= 0) {
            return 1;
        }
        return width / CONFIG.radarSize;
    }

    function drawRadarBackground() {
        ctxBg.clearRect(0, 0, CONFIG.radarSize, CONFIG.radarSize);
        ctxBg.lineWidth = 1;
        ctxBg.font = 'bold 14px Arial';
        ctxBg.textAlign = 'center';
        ctxBg.textBaseline = 'bottom';

        const kmPerDegree = 111.32;
        const rings = 4;
        const ringSpacing = (CONFIG.radarSize / 2) / rings;

        for (let i = 1; i <= rings; i += 1) {
            const radius = ringSpacing * i;

            if (i <= 2) {
                ctxBg.strokeStyle = 'rgba(239, 68, 68, 0.4)';
                ctxBg.fillStyle = '#ef4444';
            } else {
                ctxBg.strokeStyle = 'rgba(217, 119, 6, 0.4)';
                ctxBg.fillStyle = '#d97706';
            }

            ctxBg.beginPath();
            ctxBg.arc(centerPx, centerPx, radius, 0, Math.PI * 2);
            ctxBg.stroke();

            const distanceKm = (radius / CONFIG.scale) * kmPerDegree;
            ctxBg.fillText(`${distanceKm.toFixed(1)} km`, centerPx, centerPx - radius - 4);
        }

        ctxBg.strokeStyle = 'rgba(95, 134, 194, 0.2)';
        ctxBg.beginPath();
        ctxBg.moveTo(centerPx, 0);
        ctxBg.lineTo(centerPx, CONFIG.radarSize);
        ctxBg.moveTo(0, centerPx);
        ctxBg.lineTo(CONFIG.radarSize, centerPx);
        ctxBg.stroke();

        ctxBg.beginPath();
        ctxBg.strokeStyle = 'rgba(95, 134, 194, 0.15)';
        ctxBg.moveTo(0, 0);
        ctxBg.lineTo(CONFIG.radarSize, CONFIG.radarSize);
        ctxBg.moveTo(CONFIG.radarSize, 0);
        ctxBg.lineTo(0, CONFIG.radarSize);
        ctxBg.stroke();
    }

    function checkScanHighlight() {
        activeLightningPoints.forEach((point) => {
            const dx = point.x - centerPx;
            const dy = point.y - centerPx;
            let pointAngle = Math.atan2(dy, dx);

            if (pointAngle < 0) {
                pointAngle += Math.PI * 2;
            }

            const angleDiff = Math.abs(currentScanAngle - pointAngle);

            if (angleDiff < 0.15 || angleDiff > (Math.PI * 2 - 0.15)) {
                if (!point.el.classList.contains('scanned')) {
                    point.el.classList.add('scanned');
                    window.setTimeout(() => point.el.classList.remove('scanned'), 400);
                }
            }
        });
    }

    function animateScanner() {
        ctxSweep.clearRect(0, 0, CONFIG.radarSize, CONFIG.radarSize);

        ctxSweep.save();
        ctxSweep.translate(centerPx, centerPx);
        ctxSweep.rotate(currentScanAngle);

        let gradient;
        if (typeof ctxSweep.createConicGradient === 'function') {
            gradient = ctxSweep.createConicGradient(0, 0, 0);
            gradient.addColorStop(0, 'rgba(167, 139, 250, 0)');
            gradient.addColorStop(0.8, 'rgba(167, 139, 250, 0.1)');
            gradient.addColorStop(0.98, 'rgba(167, 139, 250, 0.5)');
            gradient.addColorStop(1, 'rgba(139, 92, 246, 0.8)');
        } else {
            gradient = ctxSweep.createRadialGradient(0, 0, 0, 0, 0, centerPx);
            gradient.addColorStop(0, 'rgba(167, 139, 250, 0.22)');
            gradient.addColorStop(1, 'rgba(167, 139, 250, 0)');
        }

        ctxSweep.beginPath();
        ctxSweep.moveTo(0, 0);
        ctxSweep.arc(0, 0, centerPx, 0, Math.PI * 2);
        ctxSweep.fillStyle = gradient;
        ctxSweep.fill();
        ctxSweep.restore();

        checkScanHighlight();

        currentScanAngle += (CONFIG.scanSpeed * Math.PI) / 180;
        if (currentScanAngle >= Math.PI * 2) {
            currentScanAngle = 0;
        }

        animationId = window.requestAnimationFrame(animateScanner);
    }

    function renderPoints(strikes) {
        const oldPoints = ui.pointsLayer.querySelectorAll('.lightning-point');
        oldPoints.forEach((el) => {
            el.classList.add('fade-out');
            window.setTimeout(() => el.remove(), 300);
        });

        activeLightningPoints = [];
        const renderScale = getRenderScale();

        strikes.forEach((strike) => {
            const lat = toNumber(strike?.lat);
            const lng = toNumber(strike?.lng);
            if (lat === null || lng === null) {
                return;
            }

            const pixel = latLngToXY(lat, lng);
            const distFromCenter = Math.sqrt(((pixel.x - centerPx) ** 2) + ((pixel.y - centerPx) ** 2));
            if (distFromCenter > centerPx) {
                return;
            }

            const pointEl = document.createElement('div');
            pointEl.className = 'lightning-point';
            pointEl.style.left = `${pixel.x * renderScale}px`;
            pointEl.style.top = `${pixel.y * renderScale}px`;
            pointEl.style.animationDelay = `${Math.random() * 1}s`;
            ui.pointsLayer.appendChild(pointEl);

            activeLightningPoints.push({ x: pixel.x, y: pixel.y, el: pointEl });
        });
        return activeLightningPoints.length;
    }

    async function fetchRadarData() {
        ui.status.textContent = 'System Status: Fetching Data...';

        try {
            const response = await fetch(RADAR_ENDPOINT, { cache: 'no-store' });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const payload = await response.json();
            syncRadarGeometryFromPayload(payload);
            const strikes = Array.isArray(payload?.points) ? payload.points : [];
            latestStrikes = strikes;
            const renderedCount = renderPoints(latestStrikes);
            const withinRadiusCount = toNumber(payload?.metrics?.within_radius_count);

            ui.status.textContent = 'System Status: Tracking Active';
            ui.count.textContent = withinRadiusCount !== null
                ? String(Math.round(withinRadiusCount))
                : String(renderedCount);
            ui.updated.textContent = `Snapshot time: ${formatSnapshotTime(payload?.observation_time_sgt)}`;
            ui.nearest.textContent = formatDistance(payload?.metrics?.nearest_distance_km);
            applyRiskLevel(payload?.metrics?.risk_level);
        } catch (error) {
            console.error('Lightning radar fetch failed:', error);
            ui.status.textContent = 'System Status: Connection Error';
            ui.updated.textContent = 'Snapshot time: --:--';
            ui.nearest.textContent = '-- km';
            ui.count.textContent = '--';
            applyRiskLevel('unknown');
        }
    }

    drawRadarBackground();
    if (animationId !== null) {
        window.cancelAnimationFrame(animationId);
    }
    animationId = window.requestAnimationFrame(animateScanner);

    const registerRefresh = window.registerWeatherRefreshHandler;
    if (typeof registerRefresh === 'function') {
        registerRefresh(fetchRadarData);
    } else {
        fetchRadarData();
        window.setInterval(fetchRadarData, CONFIG.refreshInterval);
    }

    window.addEventListener('resize', () => {
        drawRadarBackground();
        if (latestStrikes.length > 0) {
            renderPoints(latestStrikes);
        }
    });
    window.addEventListener('beforeunload', () => {
        if (animationId !== null) {
            window.cancelAnimationFrame(animationId);
        }
    });
});
