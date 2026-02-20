(function () {
    const REFRESH_INTERVAL_MS = 60000;

    if (typeof window.registerWeatherRefreshHandler === 'function') {
        return;
    }

    const callbacks = new Set();
    let timerId = null;

    function invokeAllCallbacks() {
        callbacks.forEach((callback) => {
            try {
                callback();
            } catch (error) {
                console.error('Weather refresh callback failed:', error);
            }
        });
    }

    function ensureTickerStarted() {
        if (timerId !== null) {
            return;
        }

        timerId = window.setInterval(invokeAllCallbacks, REFRESH_INTERVAL_MS);
        window.setTimeout(invokeAllCallbacks, 0);
    }

    window.registerWeatherRefreshHandler = function registerWeatherRefreshHandler(callback) {
        if (typeof callback !== 'function') {
            return function noop() {};
        }

        callbacks.add(callback);
        ensureTickerStarted();

        return function unregisterWeatherRefreshHandler() {
            callbacks.delete(callback);
        };
    };

    window.addEventListener(
        'beforeunload',
        () => {
            if (timerId !== null) {
                window.clearInterval(timerId);
                timerId = null;
            }
            callbacks.clear();
        },
        { once: true }
    );
})();
