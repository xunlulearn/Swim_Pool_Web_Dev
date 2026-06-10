const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const chartScriptPath = path.resolve(__dirname, '../../app/static/js/lightning_chart.js');

function createButton(dataset) {
    const listeners = {};
    return {
        dataset,
        classList: {
            toggle() {},
        },
        addEventListener(eventName, handler) {
            listeners[eventName] = handler;
        },
        click() {
            listeners.click();
        },
    };
}

function createLightningChartHarness(payload) {
    const domListeners = {};
    const distanceButtons = [
        createButton({ distanceFilter: '15km' }),
        createButton({ distanceFilter: '30km' }),
    ];
    const windowButtons = [
        createButton({ windowFilter: '20m' }),
        createButton({ windowFilter: '1h' }),
        createButton({ windowFilter: '12h' }),
    ];
    const canvasContext = {
        createLinearGradient() {
            return {
                addColorStop() {},
            };
        },
        fillRect() {},
        restore() {},
        save() {},
    };
    const elementsById = {
        'lightning-trend-chart': {
            getContext() {
                return canvasContext;
            },
        },
        'lightning-trend-summary': {
            textContent: '',
        },
        'lightning-trend-meta': {
            textContent: '',
        },
    };

    class FakeChart {
        constructor(_context, config) {
            this.data = config.data;
            this.options = config.options;
            FakeChart.instances.push(this);
        }

        update() {}

        static register(plugin) {
            FakeChart.plugins.push(plugin);
        }
    }
    FakeChart.instances = [];
    FakeChart.plugins = [];

    const context = {
        Chart: FakeChart,
        console,
        document: {
            addEventListener(eventName, handler) {
                domListeners[eventName] = handler;
            },
            getElementById(id) {
                return elementsById[id] || null;
            },
            querySelectorAll(selector) {
                if (selector === '[data-distance-filter]') {
                    return distanceButtons;
                }
                if (selector === '[data-window-filter]') {
                    return windowButtons;
                }
                return [];
            },
        },
        fetch: async () => ({
            ok: true,
            json: async () => payload,
        }),
        setInterval() {},
        window: {
            matchMedia: () => ({
                matches: false,
            }),
        },
    };

    vm.createContext(context);
    vm.runInContext(readFileSync(chartScriptPath, 'utf8'), context);

    async function boot() {
        domListeners.DOMContentLoaded();
        await new Promise((resolve) => setImmediate(resolve));
    }

    async function selectWindow(windowName) {
        windowButtons.find((button) => button.dataset.windowFilter === windowName).click();
        await new Promise((resolve) => setImmediate(resolve));
    }

    return {
        FakeChart,
        elementsById,
        boot,
        selectWindow,
    };
}

function buildPayload({ labels, counts }) {
    const zeroes = labels.map(() => 0);
    return {
        charts: {
            '20m': {
                display_label: 'Last 20 Minutes',
                labels: ['start', 'end'],
                counts_15km: [0, 0],
                counts_30km: [0, 0],
                totals: { '15km': 0, '30km': 0 },
            },
            '1h': {
                display_label: 'Last 1 Hour',
                labels: ['start', 'end'],
                counts_15km: [0, 0],
                counts_30km: [0, 0],
                totals: { '15km': 0, '30km': 0 },
            },
            '12h': {
                display_label: 'Last 12 Hours',
                labels,
                counts_15km: counts,
                counts_30km: zeroes,
                totals: { '15km': counts.reduce((acc, value) => acc + value, 0), '30km': 0 },
            },
        },
        metadata: {},
    };
}

test('12h x-axis keeps the final label but hides sampled labels too close to it', async () => {
    const labels = Array.from({ length: 61 }, (_value, index) => `tick-${index}`);
    const harness = createLightningChartHarness(buildPayload({
        labels,
        counts: labels.map(() => 0),
    }));

    await harness.boot();
    await harness.selectWindow('12h');

    const chart = harness.FakeChart.instances[0];
    const callback = chart.options.scales.x.ticks.callback;
    const ticks = labels.map((_label, index) => ({ value: index }));
    const labelContext = {
        getLabelForValue(value) {
            return labels[value];
        },
    };

    assert.equal(callback.call(labelContext, 60, 60, ticks), 'tick-60');
    assert.equal(callback.call(labelContext, 56, 56, ticks), '');
});

test('low non-zero lightning counts use a 0-10 y-axis range', async () => {
    const labels = Array.from({ length: 61 }, (_value, index) => `tick-${index}`);
    const counts = labels.map((_label, index) => (index === 40 ? 1 : 0));
    const harness = createLightningChartHarness(buildPayload({ labels, counts }));

    await harness.boot();
    await harness.selectWindow('12h');

    const chart = harness.FakeChart.instances[0];
    assert.equal(chart.options.scales.y.max, 10);
});

test('zero lightning data shows an explicit no-lightning chart message', async () => {
    const labels = Array.from({ length: 61 }, (_value, index) => `tick-${index}`);
    const harness = createLightningChartHarness(buildPayload({
        labels,
        counts: labels.map(() => 0),
    }));

    await harness.boot();
    await harness.selectWindow('12h');

    const chart = harness.FakeChart.instances[0];
    assert.equal(chart.options.plugins.zeroLightningMessage.display, true);
    assert.equal(chart.options.plugins.zeroLightningMessage.text, 'No lightning detected');
});
