import logging
import os
import threading
import time


logger = logging.getLogger(__name__)

_start_lock = threading.Lock()
_collector_thread = None


def _run_collector_loop(app):
    from app.services.weather_engine import weather_engine

    startup_delay = int(app.config.get("LIGHTNING_COLLECTOR_STARTUP_DELAY_SECONDS", 5))
    interval_seconds = max(30, int(app.config.get("LIGHTNING_COLLECTOR_INTERVAL_SECONDS", 120)))

    if startup_delay > 0:
        time.sleep(startup_delay)

    while True:
        try:
            with app.app_context():
                if not bool(app.config.get("LIGHTNING_COLLECTOR_ENABLED", True)):
                    return

                result = weather_engine.collect_and_store_latest_lightning_snapshot()
                if not result.get("ok"):
                    logger.warning(
                        "Lightning collector tick did not persist snapshot: %s",
                        result.get("reason"),
                    )
        except Exception:
            logger.exception("Lightning collector tick failed.")

        time.sleep(interval_seconds)


def maybe_start_lightning_collector(app):
    global _collector_thread

    if app.config.get("TESTING"):
        return
    if not bool(app.config.get("LIGHTNING_COLLECTOR_ENABLED", True)):
        app.logger.info("Lightning collector is disabled by config.")
        return
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    with _start_lock:
        if _collector_thread is not None and _collector_thread.is_alive():
            return

        _collector_thread = threading.Thread(
            target=_run_collector_loop,
            args=(app,),
            name="lightning-collector",
            daemon=True,
        )
        _collector_thread.start()
        app.logger.info(
            "Started lightning collector thread (interval=%ss).",
            max(30, int(app.config.get("LIGHTNING_COLLECTOR_INTERVAL_SECONDS", 120))),
        )
