document.addEventListener('DOMContentLoaded', () => {
    const HISTORY_ENDPOINT = '/weather/lightning-history';
    const REFRESH_INTERVAL_MS = 60000;
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const ui = {
        canvas: document.getElementById('lightning-trend-chart'),
        summary: document.getElementById('lightning-trend-summary'),
        meta: document.getElementById('lightning-trend-meta'),
        distanceButtons: Array.from(document.querySelectorAll('[data-distance-filter]')),
        windowButtons: Array.from(document.querySelectorAll('[data-window-filter]')),
    };

    if (!ui.canvas || !ui.summary) {
        return;
    }

    if (typeof Chart === 'undefined') {
        ui.summary.textContent = 'Unable to load chart library.';
        return;
    }

    const chartAreaBackgroundPlugin = {
        id: 'chartAreaBackground',
        beforeDraw(chart, _args, options) {
            const { ctx, chartArea } = chart;
            if (!chartArea) {
                return;
            }

            ctx.save();
            const gradient = ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
            gradient.addColorStop(0, options?.topColor || 'rgba(241, 245, 249, 0.58)');
            gradient.addColorStop(1, options?.bottomColor || 'rgba(224, 242, 254, 0.40)');
            ctx.fillStyle = gradient;
            ctx.fillRect(
                chartArea.left,
                chartArea.top,
                chartArea.right - chartArea.left,
                chartArea.bottom - chartArea.top
            );
            ctx.restore();
        },
    };

    const zeroLightningMessagePlugin = {
        id: 'zeroLightningMessage',
        afterDraw(chart, _args, options) {
            if (!options?.display || !options?.text) {
                return;
            }

            const { ctx, chartArea } = chart;
            if (!chartArea) {
                return;
            }

            ctx.save();
            ctx.fillStyle = options.color || '#475569';
            ctx.font = options.font || '600 13px system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(
                options.text,
                chartArea.left + ((chartArea.right - chartArea.left) / 2),
                chartArea.top + ((chartArea.bottom - chartArea.top) / 2)
            );
            ctx.restore();
        },
    };
    Chart.register(chartAreaBackgroundPlugin, zeroLightningMessagePlugin);

    const state = {
        distance: '15km',
        window: '20m',
        payload: null,
        chart: null,
    };

    function toNumberArray(values) {
        return (values || []).map((value) => {
            const num = Number(value);
            return Number.isFinite(num) ? num : 0;
        });
    }

    function formatIsoTime(isoText) {
        if (!isoText) {
            return '--';
        }

        const parsed = new Date(isoText);
        if (Number.isNaN(parsed.getTime())) {
            return '--';
        }

        return parsed.toLocaleString('en-SG', {
            hour12: false,
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
        });
    }

    function setFilterButtonState(button, isActive) {
        button.classList.toggle('bg-ntu-blue', isActive);
        button.classList.toggle('text-white', isActive);
        button.classList.toggle('bg-white', !isActive);
        button.classList.toggle('text-slate-700', !isActive);
    }

    function refreshFilterStyles() {
        ui.distanceButtons.forEach((button) => {
            setFilterButtonState(button, button.dataset.distanceFilter === state.distance);
        });
        ui.windowButtons.forEach((button) => {
            setFilterButtonState(button, button.dataset.windowFilter === state.window);
        });
    }

    function getActiveWindowData() {
        if (!state.payload || !state.payload.charts) {
            return null;
        }
        return state.payload.charts[state.window] || null;
    }

    function getActiveSeries(windowData) {
        if (!windowData) {
            return [];
        }
        if (state.distance === '15km') {
            return toNumberArray(windowData.counts_15km);
        }
        return toNumberArray(windowData.counts_30km);
    }

    function getDistanceLabel() {
        return state.distance === '15km' ? '<= 15 km' : '<= 30 km';
    }

    function getColorConfig() {
        if (state.distance === '15km') {
            return {
                border: '#EA580C',
                line: '#C2410C',
                fillStart: 'rgba(234, 88, 12, 0.92)',
                fillEnd: 'rgba(251, 146, 60, 0.68)',
            };
        }
        return {
            border: '#0369A1',
            line: '#075985',
            fillStart: 'rgba(3, 105, 161, 0.92)',
            fillEnd: 'rgba(56, 189, 248, 0.68)',
        };
    }

    function buildBarGradient(chart, fillStart, fillEnd) {
        const { ctx, chartArea } = chart;
        if (!chartArea) {
            return fillStart;
        }
        const gradient = ctx.createLinearGradient(0, chartArea.bottom, 0, chartArea.top);
        gradient.addColorStop(0, fillEnd);
        gradient.addColorStop(1, fillStart);
        return gradient;
    }

    function getXAxisTickStep(labelCount) {
        const safeCount = Number(labelCount) || 0;
        const maxVisible = state.window === '12h' ? 8 : 10;
        if (safeCount <= maxVisible) {
            return 1;
        }
        return Math.max(1, Math.ceil((safeCount - 1) / maxVisible));
    }

    function isXAxisTickTooCloseToEnd(index, lastIndex, tickStep) {
        if (state.window !== '12h' || tickStep <= 1 || index === lastIndex) {
            return false;
        }

        const endGuard = Math.max(2, Math.ceil(tickStep / 2));
        return index >= lastIndex - endGuard;
    }

    function getYAxisMax(series) {
        const values = Array.isArray(series) ? series : [];
        const maxValue = values.reduce((highest, value) => Math.max(highest, Number(value) || 0), 0);
        return maxValue < 10 ? 10 : undefined;
    }

    function hasZeroLightningData(labels, series) {
        if (!Array.isArray(labels) || labels.length === 0 || !Array.isArray(series) || series.length === 0) {
            return false;
        }

        const total = series.reduce((acc, value) => acc + (Number(value) || 0), 0);
        return total === 0;
    }

    function renderSummary(windowData, rawSeries) {
        if (!windowData) {
            ui.summary.textContent = 'No lightning trend data available.';
            return;
        }

        const totals = windowData.totals || {};
        const totalValue = state.distance === '15km'
            ? Number(totals['15km'] ?? rawSeries.reduce((acc, value) => acc + value, 0))
            : Number(totals['30km'] ?? rawSeries.reduce((acc, value) => acc + value, 0));
        const safeTotal = Number.isFinite(totalValue) ? Math.round(totalValue) : 0;
        const displayLabel = windowData.display_label || state.window;

        ui.summary.textContent = `${displayLabel} | ${getDistanceLabel()} total: ${safeTotal} strikes`;
    }

    function renderMeta() {
        if (!ui.meta) {
            return;
        }

        if (!state.payload || !state.payload.metadata) {
            ui.meta.textContent = '';
            return;
        }
        ui.meta.textContent = '';
    }

    function renderChart() {
        const windowData = getActiveWindowData();
        if (!windowData) {
            ui.summary.textContent = 'No lightning trend data available.';
            if (ui.meta) {
                ui.meta.textContent = '';
            }
            return;
        }

        const labels = Array.isArray(windowData.labels) ? windowData.labels : [];
        const rawSeries = getActiveSeries(windowData);
        const colorConfig = getColorConfig();
        const xTickStep = getXAxisTickStep(labels.length);
        const yAxisMax = getYAxisMax(rawSeries);
        const showZeroLightningMessage = hasZeroLightningData(labels, rawSeries);

        const chartConfig = {
            type: 'bar',
            data: {
                labels,
                datasets: [
                    {
                        label: `${getDistanceLabel()} bars`,
                        data: rawSeries,
                        borderColor: colorConfig.border,
                        borderWidth: 1.2,
                        borderRadius: 6,
                        borderSkipped: false,
                        categoryPercentage: state.window === '20m' ? 0.99 : 0.86,
                        barPercentage: state.window === '20m' ? 1 : 0.9,
                        maxBarThickness: state.window === '20m' ? 32 : 24,
                        backgroundColor: (context) => buildBarGradient(
                            context.chart,
                            colorConfig.fillStart,
                            colorConfig.fillEnd
                        ),
                    },
                ],
            },
            options: {
                maintainAspectRatio: false,
                responsive: true,
                animation: prefersReducedMotion
                    ? false
                    : {
                        duration: 260,
                        easing: 'easeOutCubic',
                    },
                plugins: {
                    chartAreaBackground: {
                        topColor: 'rgba(248, 250, 252, 0.65)',
                        bottomColor: 'rgba(224, 242, 254, 0.42)',
                    },
                    legend: {
                        display: false,
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        callbacks: {
                            label(context) {
                                const value = Math.round(Number(context.parsed.y || 0));
                                return `${context.dataset.label}: ${value}`;
                            },
                        },
                    },
                    zeroLightningMessage: {
                        display: showZeroLightningMessage,
                        text: 'No lightning detected',
                        color: '#475569',
                        font: '600 13px system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
                    },
                    title: {
                        display: true,
                        text: `${windowData.display_label || state.window} | ${getDistanceLabel()}`,
                        color: '#0F172A',
                        font: {
                            size: 12,
                            weight: '600',
                        },
                    },
                },
                scales: {
                    x: {
                        title: {
                            display: true,
                            text: 'Time',
                        },
                        ticks: {
                            maxRotation: 0,
                            autoSkip: false,
                            callback(value, index, ticks) {
                                const lastIndex = ticks.length - 1;
                                if (isXAxisTickTooCloseToEnd(index, lastIndex, xTickStep)) {
                                    return '';
                                }
                                if (index === 0 || index === lastIndex || index % xTickStep === 0) {
                                    return this.getLabelForValue(value);
                                }
                                return '';
                            },
                        },
                        grid: {
                            display: false,
                        },
                    },
                    y: {
                        beginAtZero: true,
                        max: yAxisMax,
                        title: {
                            display: true,
                            text: 'Lightning Count',
                        },
                        ticks: {
                            precision: 0,
                        },
                    },
                },
            },
        };

        if (state.chart) {
            state.chart.data = chartConfig.data;
            state.chart.options = chartConfig.options;
            state.chart.update();
        } else {
            const context = ui.canvas.getContext('2d');
            if (!context) {
                ui.summary.textContent = 'Unable to draw lightning chart.';
                return;
            }
            state.chart = new Chart(context, chartConfig);
        }

        renderSummary(windowData, rawSeries);
        renderMeta();
    }

    async function fetchHistory() {
        try {
            const response = await fetch(HISTORY_ENDPOINT, { cache: 'no-store' });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const payload = await response.json();
            if (!payload || !payload.charts) {
                throw new Error('Unexpected payload');
            }

            state.payload = payload;
            renderChart();
        } catch (error) {
            console.error('Lightning history fetch failed:', error);
            ui.summary.textContent = 'Unable to load lightning trend right now.';
            if (ui.meta) {
                ui.meta.textContent = '';
            }
        }
    }

    ui.distanceButtons.forEach((button) => {
        button.addEventListener('click', () => {
            state.distance = button.dataset.distanceFilter;
            refreshFilterStyles();
            renderChart();
        });
    });

    ui.windowButtons.forEach((button) => {
        button.addEventListener('click', () => {
            state.window = button.dataset.windowFilter;
            refreshFilterStyles();
            renderChart();
        });
    });

    refreshFilterStyles();
    const registerRefresh = window.registerWeatherRefreshHandler;
    if (typeof registerRefresh === 'function') {
        registerRefresh(fetchHistory);
    } else {
        fetchHistory();
        setInterval(fetchHistory, REFRESH_INTERVAL_MS);
    }
});
