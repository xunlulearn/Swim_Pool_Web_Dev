(function () {
    const REFRESH_INTERVAL_MS = 120000;

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
        if (timerId !== null || document.hidden) {
            return;
        }

        timerId = window.setInterval(invokeAllCallbacks, REFRESH_INTERVAL_MS);
        window.setTimeout(invokeAllCallbacks, 0);
    }

    function stopTicker() {
        if (timerId === null) {
            return;
        }

        window.clearInterval(timerId);
        timerId = null;
    }

    function handleVisibilityChange() {
        if (document.hidden) {
            stopTicker();
            return;
        }

        ensureTickerStarted();
        invokeAllCallbacks();
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

    document.addEventListener('visibilitychange', handleVisibilityChange);

    window.addEventListener(
        'beforeunload',
        () => {
            stopTicker();
            document.removeEventListener('visibilitychange', handleVisibilityChange);
            callbacks.clear();
        },
        { once: true }
    );
})();
