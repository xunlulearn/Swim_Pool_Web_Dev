import json
import logging
import math
import os
import copy
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import Lock

import requests
from flask import current_app, has_app_context
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import load_only

# Legacy toggle kept for backward compatibility; runtime selection uses
# `USE_SAMPLE_WEATHER_DATA` in app config.
USE_SAMPLE_DATA = False
SAMPLE_LIGHTNING_PATH = os.path.join(
    os.path.dirname(__file__), '..', '..', 'tests', 'sample_nea_lightning_data.json'
)
SAMPLE_RAINFALL_PATH = os.path.join(
    os.path.dirname(__file__), '..', '..', 'tests', 'sample_nea_rainfall_data.json'
)

logger = logging.getLogger(__name__)


class PoolStatus(Enum):
    """Pool state shown on the homepage."""

    GREEN = "Open"
    AMBER = "Warning"
    RED = "Closed"


class WeatherEngine:
    """Resolve pool open/closed status from weather + operating rules.

    Decision summary:
    - During non-operating hours -> RED.
    - If recent community consensus is strong -> use community status.
    - If weather data unavailable -> AMBER.
    - Lightning within warning radius triggers 45-min closure window.
    - Heavy rain above threshold triggers 30-min closure window.
    - Otherwise -> GREEN.
    """

    # NTU Sports and Recreation Centre coordinates.
    SRC_LAT = 1.349383588
    SRC_LON = 103.6877553

    # Thresholds used by backend closure logic.
    LIGHTNING_CLOSE_THRESHOLD = 8.0
    LIGHTNING_WARN_THRESHOLD = 15.0
    RAINFALL_WARN_THRESHOLD = 5.0
    SGT = timezone(timedelta(hours=8))

    # NEA APIs.
    LIGHTNING_API_BASE_URL = "https://api-open.data.gov.sg/v2/real-time/api/weather"
    LIGHTNING_API_URL = f"{LIGHTNING_API_BASE_URL}?api=lightning"
    RAINFALL_API_URL = "https://api-open.data.gov.sg/v2/real-time/api/rainfall"
    LIGHTNING_HISTORY_RETENTION = timedelta(hours=24)

    def __init__(self):
        self.last_lightning_alert_time = None
        self.last_rain_alert_time = None
        self.last_rainfall_error = None

        self._status_cache = None
        self._status_cache_at = None
        self._status_cache_lock = Lock()
        self._status_refresh_lock = Lock()
        self._lightning_history_cache = None
        self._lightning_history_cache_at = None
        self._lightning_history_cache_lock = Lock()
        self._lightning_history_refresh_lock = Lock()
        self._lightning_snapshot_cache = None
        self._lightning_snapshot_cache_at = None
        self._lightning_snapshot_cache_lock = Lock()
        self._lightning_snapshot_refresh_lock = Lock()

        # 2026 Singapore public holidays (YYYY-MM-DD).
        self.PUBLIC_HOLIDAYS_2026 = {
            "2026-01-01",  # New Year's Day
            "2026-02-17",
            "2026-02-18",  # Chinese New Year
            "2026-03-21",  # Hari Raya Puasa
            "2026-04-03",  # Good Friday
            "2026-05-01",  # Labour Day
            "2026-05-27",  # Hari Raya Haji
            "2026-05-31",
            "2026-06-01",  # Vesak Day + observed
            "2026-08-09",
            "2026-08-10",  # National Day + observed
            "2026-11-08",
            "2026-11-09",  # Deepavali + observed
            "2026-12-25",  # Christmas
        }

    def _get_status_cache_ttl_seconds(self):
        if has_app_context():
            return int(current_app.config.get('WEATHER_STATUS_CACHE_SECONDS', 30))
        return 30

    def _get_weather_api_timeout_seconds(self):
        default_timeout = 4.0
        if has_app_context():
            raw_timeout = current_app.config.get('WEATHER_API_TIMEOUT_SECONDS', default_timeout)
        else:
            raw_timeout = default_timeout

        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError):
            return default_timeout
        return max(1.0, timeout)

    def _get_cached_overall_status(self):
        ttl_seconds = self._get_status_cache_ttl_seconds()
        if ttl_seconds <= 0:
            return None

        with self._status_cache_lock:
            if self._status_cache is None or self._status_cache_at is None:
                return None

            age = (datetime.now(timezone.utc) - self._status_cache_at).total_seconds()
            if age > ttl_seconds:
                return None

            state, message, details = self._status_cache
            return state, message, dict(details)

    def _set_cached_overall_status(self, state, message, details):
        with self._status_cache_lock:
            self._status_cache = (state, message, dict(details))
            self._status_cache_at = datetime.now(timezone.utc)

    def _get_stale_cached_overall_status(self):
        with self._status_cache_lock:
            if self._status_cache is None:
                return None
            state, message, details = self._status_cache
            return state, message, dict(details)

    def _get_lightning_history_cache_ttl_seconds(self):
        if has_app_context():
            return int(current_app.config.get('LIGHTNING_HISTORY_CACHE_SECONDS', 60))
        return 60

    def _get_lightning_history_max_pages(self):
        default_pages = 40
        if has_app_context() and not current_app.config.get('NEA_API_KEY'):
            # Without API key, the public quota throttles quickly.
            default_pages = 5

        if has_app_context():
            raw_value = current_app.config.get('LIGHTNING_HISTORY_MAX_PAGES', default_pages)
            try:
                parsed_value = int(raw_value)
            except (TypeError, ValueError):
                return default_pages
            if parsed_value <= 0:
                return default_pages
            return parsed_value

        return default_pages

    def _get_cached_lightning_history(self):
        ttl_seconds = self._get_lightning_history_cache_ttl_seconds()
        if ttl_seconds <= 0:
            return None

        with self._lightning_history_cache_lock:
            if self._lightning_history_cache is None or self._lightning_history_cache_at is None:
                return None

            age = (datetime.now(timezone.utc) - self._lightning_history_cache_at).total_seconds()
            if age > ttl_seconds:
                return None

            return copy.deepcopy(self._lightning_history_cache)

    def _set_cached_lightning_history(self, payload):
        with self._lightning_history_cache_lock:
            self._lightning_history_cache = copy.deepcopy(payload)
            self._lightning_history_cache_at = datetime.now(timezone.utc)

    def _get_stale_cached_lightning_history(self):
        with self._lightning_history_cache_lock:
            if self._lightning_history_cache is None:
                return None
            return copy.deepcopy(self._lightning_history_cache)

    def _get_lightning_snapshot_cache_ttl_seconds(self):
        if has_app_context():
            return int(
                current_app.config.get(
                    'LIGHTNING_SNAPSHOT_CACHE_SECONDS',
                    current_app.config.get('WEATHER_STATUS_CACHE_SECONDS', 30),
                )
            )
        return 30

    def _get_cached_lightning_snapshot(self):
        ttl_seconds = self._get_lightning_snapshot_cache_ttl_seconds()
        if ttl_seconds <= 0:
            return None

        with self._lightning_snapshot_cache_lock:
            if self._lightning_snapshot_cache is None or self._lightning_snapshot_cache_at is None:
                return None

            age = (datetime.now(timezone.utc) - self._lightning_snapshot_cache_at).total_seconds()
            if age > ttl_seconds:
                return None

            return copy.deepcopy(self._lightning_snapshot_cache)

    def _set_cached_lightning_snapshot(self, payload):
        with self._lightning_snapshot_cache_lock:
            self._lightning_snapshot_cache = copy.deepcopy(payload)
            self._lightning_snapshot_cache_at = datetime.now(timezone.utc)

    def _get_stale_cached_lightning_snapshot(self):
        with self._lightning_snapshot_cache_lock:
            if self._lightning_snapshot_cache is None:
                return None
            return copy.deepcopy(self._lightning_snapshot_cache)

    @staticmethod
    def _build_degraded_details(reason):
        return {
            "lightning_dist": None,
            "rainfall_rate": None,
            "lightning_count": None,
            "min_distance_km": None,
            "data_source": "degraded",
            "reason": reason,
        }

    def _use_sample_data(self):
        """Allow sample weather data only in DEBUG/TESTING mode."""
        if not has_app_context():
            return False

        if bool(current_app.config.get('FORCE_SAMPLE_WEATHER_DATA', False)):
            return True

        enabled = bool(current_app.config.get('USE_SAMPLE_WEATHER_DATA', False))
        if not enabled:
            return False

        if not (current_app.config.get('DEBUG') or current_app.config.get('TESTING')):
            logger.warning(
                "USE_SAMPLE_WEATHER_DATA is enabled but ignored outside DEBUG/TESTING."
            )
            return False

        return True

    def _is_operating_hours(self):
        """Return whether the pool is within opening hours (Singapore time)."""
        sgt_now = datetime.now(timezone(timedelta(hours=8)))

        date_str = sgt_now.strftime("%Y-%m-%d")
        is_weekend = sgt_now.weekday() >= 5  # 5=Sat, 6=Sun
        is_holiday = date_str in self.PUBLIC_HOLIDAYS_2026

        current_time = sgt_now.time()

        if is_weekend or is_holiday:
            start_time = datetime.strptime("08:00", "%H:%M").time()
            end_time = datetime.strptime("20:00", "%H:%M").time()
            day_type = "Weekend/Public Holiday"
        else:
            start_time = datetime.strptime("07:00", "%H:%M").time()
            end_time = datetime.strptime("21:30", "%H:%M").time()
            day_type = "Weekday"

        if start_time <= current_time <= end_time:
            return True, None

        msg = (
            f"Pool Closed - Outside Operating Hours "
            f"({day_type} {start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')})"
        )
        return False, msg

    def _get_community_consensus(self):
        """Return community consensus status ('Open' or 'Closed') when strong enough."""
        try:
            from app.models.report import PoolReport

            cutoff_time = datetime.utcnow() - timedelta(minutes=30)
            recent_reports = (
                PoolReport.query.filter(PoolReport.created_at >= cutoff_time)
                .order_by(PoolReport.created_at.desc())
                .limit(10)
                .all()
            )

            if len(recent_reports) < 5:
                return None

            latest_5 = recent_reports[:5]
            first_status = latest_5[0].status

            # All latest five must agree.
            if not all(r.status == first_status for r in latest_5):
                return None

            # Five unique users are required.
            user_ids = {r.user_id for r in latest_5}
            if len(user_ids) < 5:
                return None

            # Consensus must be fresh.
            latest_report_time = latest_5[0].created_at
            if (datetime.utcnow() - latest_report_time) > timedelta(minutes=10):
                return None

            return first_status

        except Exception:
            logger.exception("Failed to evaluate community consensus.")
            return None

    @staticmethod
    def _ensure_utc_aware(dt_value):
        if dt_value is None:
            return None
        if dt_value.tzinfo is None:
            return dt_value.replace(tzinfo=timezone.utc)
        return dt_value.astimezone(timezone.utc)

    def _get_recent_lightning_alert_time(self, now_utc):
        cutoff_utc = now_utc - timedelta(minutes=45)
        memory_alert = self._ensure_utc_aware(self.last_lightning_alert_time)
        if memory_alert is not None and memory_alert < cutoff_utc:
            memory_alert = None

        persisted_alert = None
        if has_app_context():
            try:
                from app.models.lightning_history import LightningHistorySnapshot

                row = (
                    LightningHistorySnapshot.query.options(
                        load_only(LightningHistorySnapshot.observed_at_utc)
                    )
                    .filter(
                        LightningHistorySnapshot.observed_at_utc
                        >= cutoff_utc.replace(tzinfo=None),
                        LightningHistorySnapshot.within_15km_count > 0,
                    )
                    .order_by(LightningHistorySnapshot.observed_at_utc.desc())
                    .first()
                )
                if row is not None:
                    persisted_alert = self._ensure_utc_aware(row.observed_at_utc)
            except Exception:
                try:
                    from app.extensions import db
                    db.session.rollback()
                except Exception:
                    pass
                logger.exception("Failed to resolve recent lightning alert time from persisted store.")

        candidates = [item for item in [memory_alert, persisted_alert] if item is not None]
        if not candidates:
            return None
        return max(candidates)

    def get_overall_status(self):
        """Main status resolver with short cache to reduce upstream pressure."""
        cached = self._get_cached_overall_status()
        if cached is not None:
            return cached

        # Prevent a thundering-herd when upstream weather APIs stall.
        # If another request is already refreshing status, serve stale cache
        # or a fast degraded response instead of blocking every worker thread.
        if not self._status_refresh_lock.acquire(blocking=False):
            stale = self._get_stale_cached_overall_status()
            if stale is not None:
                state, message, details = stale
                degraded_details = dict(details)
                degraded_details["stale_cache"] = True
                degraded_details.setdefault("reason", "stale_cache")
                return state, message, degraded_details

            is_open_hours, hours_msg = self._is_operating_hours()
            if not is_open_hours:
                return (
                    PoolStatus.RED,
                    hours_msg,
                    self._build_degraded_details("operating_hours"),
                )
            return (
                PoolStatus.AMBER,
                "Weather data temporarily unavailable",
                self._build_degraded_details("refresh_in_progress"),
            )

        try:
            return self._compute_overall_status()
        finally:
            self._status_refresh_lock.release()

    def _compute_overall_status(self):
        """Compute weather status once; callers should apply concurrency guards."""

        is_open_hours, hours_msg = self._is_operating_hours()
        if not is_open_hours:
            details = self._build_degraded_details("operating_hours")
            self._set_cached_overall_status(PoolStatus.RED, hours_msg, details)
            return PoolStatus.RED, hours_msg, details

        _, _, lightning_details = self.get_lightning_status()
        rainfall_rate, _, _ = self.get_rainfall_status()
        now = datetime.now(timezone.utc)

        lightning_dist = lightning_details.get("min_distance_km")
        has_lightning = (
            lightning_dist is not None and lightning_dist <= self.LIGHTNING_WARN_THRESHOLD
        )

        base_metrics = {
            "lightning_dist": lightning_dist,
            "rainfall_rate": rainfall_rate,
            "lightning_count": lightning_details.get("lightning_count"),
            "min_distance_km": lightning_dist,  # Frontend compatibility
            "data_source": lightning_details.get("data_source", "live_api"),
            "observation_time_sgt": lightning_details.get("observation_time_sgt"),
            "lightning_count_basis": lightning_details.get("lightning_count_basis"),
            "lightning_stale_cache": bool(lightning_details.get("stale_cache", False)),
            "lightning_source_error": lightning_details.get("source_error"),
            "lightning_warning": lightning_details.get("warning"),
        }

        community_status = self._get_community_consensus()
        if community_status:
            status = PoolStatus.GREEN if community_status == "Open" else PoolStatus.RED
            color_en = "OPEN" if status == PoolStatus.GREEN else "CLOSED"
            message = f"Manual report consensus: Pool {color_en}"
            details = {
                **base_metrics,
                "reason": "community_consensus",
                "reported_status": community_status,
            }
            self._set_cached_overall_status(status, message, details)
            return status, message, details

        if lightning_details.get("error") or self.last_rainfall_error:
            message = "Weather data temporarily unavailable"
            details = {
                **base_metrics,
                "reason": "weather_data_unavailable",
                "lightning_error": lightning_details.get("error"),
                "rainfall_error": self.last_rainfall_error,
            }
            self._set_cached_overall_status(PoolStatus.AMBER, message, details)
            return PoolStatus.AMBER, message, details

        recent_lightning_alert = self._get_recent_lightning_alert_time(now)
        if has_lightning:
            recent_lightning_alert = now
            self.last_lightning_alert_time = now
        elif recent_lightning_alert is not None:
            self.last_lightning_alert_time = recent_lightning_alert
        else:
            self.last_lightning_alert_time = None

        if recent_lightning_alert:
            time_since_alert = (now - recent_lightning_alert).total_seconds() / 60
            if time_since_alert <= 45:
                remaining = 45 - int(time_since_alert)
                if has_lightning:
                    message = (
                        f"Pool Closed due to Lightning Alert "
                        f"(Nearest {lightning_dist}km)"
                    )
                else:
                    message = (
                        "Pool Closed due to Lightning Alert "
                        f"(Estimated {remaining} min to reopen)"
                    )
                details = {
                    **base_metrics,
                    "reason": "lightning",
                    "distance": lightning_dist,
                    "last_alert": recent_lightning_alert.isoformat(),
                }
                self._set_cached_overall_status(PoolStatus.RED, message, details)
                return PoolStatus.RED, message, details

            self.last_lightning_alert_time = None

        has_heavy_rain = rainfall_rate is not None and rainfall_rate > self.RAINFALL_WARN_THRESHOLD
        if has_heavy_rain:
            self.last_rain_alert_time = now

        if self.last_rain_alert_time:
            time_since_alert = (now - self.last_rain_alert_time).total_seconds() / 60
            if time_since_alert <= 30:
                remaining = 30 - int(time_since_alert)
                if has_heavy_rain:
                    message = f"Pool Closed due to Heavy Rain ({rainfall_rate:.1f}mm/h)"
                else:
                    message = (
                        "Pool Closed due to Heavy Rain "
                        f"(Estimated {remaining} min to reopen)"
                    )
                details = {
                    **base_metrics,
                    "reason": "heavy_rain",
                    "rainfall_rate": rainfall_rate,
                    "last_alert": self.last_rain_alert_time.isoformat(),
                }
                self._set_cached_overall_status(PoolStatus.RED, message, details)
                return PoolStatus.RED, message, details

            self.last_rain_alert_time = None

        message = "Pool is Open"
        self._set_cached_overall_status(PoolStatus.GREEN, message, base_metrics)
        return PoolStatus.GREEN, message, base_metrics

    @staticmethod
    def haversine(lat1, lon1, lat2, lon2):
        """Return great-circle distance in kilometers."""
        earth_radius_km = 6371

        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)

        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return earth_radius_km * c

    @staticmethod
    def _parse_nea_datetime(value):
        if not value:
            return None

        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None

        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=WeatherEngine.SGT)
        return parsed.astimezone(WeatherEngine.SGT)

    @staticmethod
    def _extract_oldest_record_time(records):
        oldest = None
        for record in records:
            record_time = WeatherEngine._parse_nea_datetime(record.get('datetime'))
            if record_time is None:
                continue
            if oldest is None or record_time < oldest:
                oldest = record_time
        return oldest

    @staticmethod
    def _format_lightning_history_warning(error_code, truncated, rate_limited):
        if error_code == 'rate_limited' or rate_limited:
            return "Lightning history is partially loaded due to NEA API rate limits."
        if error_code == 'max_pages_reached' or truncated:
            return "Lightning history is partially loaded due to page fetch limits."
        if error_code == 'timeout':
            return "Lightning history request timed out; data may be incomplete."
        if error_code == 'network_error':
            return "Lightning history request failed due to network error."
        if error_code == 'invalid_response':
            return "Lightning history source returned an invalid response."
        if error_code == 'api_error_payload':
            return "Lightning history source returned an API error."
        if error_code == 'missing_or_invalid_api_key':
            return "Lightning history requires a valid NEA API key for extended paging."
        if error_code and error_code.startswith('http_'):
            return f"Lightning history request failed ({error_code})."
        return None

    def _fetch_lightning_records_for_history(self, now_sgt, cutoff_sgt):
        use_sample_data = self._use_sample_data()
        if use_sample_data:
            with open(SAMPLE_LIGHTNING_PATH, 'r', encoding='utf-8') as file:
                payload = json.load(file)
            records = payload.get('data', {}).get('records', [])
            return records, {
                "data_source": "sample_data",
                "request_count": 0,
                "truncated": False,
                "rate_limited": False,
                "error": None,
                "coverage_start": self._extract_oldest_record_time(records),
            }

        api_key = current_app.config.get('NEA_API_KEY')
        headers = {'x-api-key': api_key} if api_key else {}
        date_filter = now_sgt.strftime("%Y-%m-%dT%H:%M:%S")

        records = []
        pagination_token = None
        request_count = 0
        truncated = False
        rate_limited = False
        error = None
        coverage_start = None
        max_pages = self._get_lightning_history_max_pages()

        while True:
            if request_count >= max_pages:
                truncated = True
                error = error or 'max_pages_reached'
                break

            params = {
                "api": "lightning",
                "date": date_filter,
            }
            if pagination_token:
                params["paginationToken"] = pagination_token

            try:
                response = requests.get(
                    self.LIGHTNING_API_BASE_URL,
                    headers=headers,
                    params=params,
                    timeout=self._get_weather_api_timeout_seconds(),
                )
            except requests.exceptions.Timeout:
                error = 'timeout'
                break
            except requests.exceptions.RequestException:
                logger.exception("Lightning history request error.")
                error = 'network_error'
                break

            request_count += 1

            if response.status_code == 429:
                rate_limited = True
                error = 'rate_limited'
                break

            if response.status_code == 403:
                error = 'missing_or_invalid_api_key'
                break

            if response.status_code != 200:
                error = f'http_{response.status_code}'
                break

            try:
                payload = response.json()
            except ValueError:
                error = 'invalid_response'
                break

            if payload.get('code') != 0:
                error = 'api_error_payload'
                break

            data = payload.get('data') or {}
            page_records = data.get('records') or []
            if not page_records:
                break

            records.extend(page_records)
            page_oldest = self._extract_oldest_record_time(page_records)
            if page_oldest and (coverage_start is None or page_oldest < coverage_start):
                coverage_start = page_oldest

            if page_oldest and page_oldest <= cutoff_sgt:
                break

            pagination_token = data.get('paginationToken')
            if not pagination_token:
                break

        return records, {
            "data_source": "live_api",
            "request_count": request_count,
            "truncated": truncated,
            "rate_limited": rate_limited,
            "error": error,
            "coverage_start": coverage_start,
        }

    @staticmethod
    def _aggregate_points_to_fixed_bins(points, window_start, window_duration, target_bins):
        bin_seconds = window_duration.total_seconds() / max(1, target_bins)
        counts_15km = [0] * target_bins
        counts_30km = [0] * target_bins

        for point in points:
            offset_seconds = (point["time"] - window_start).total_seconds()
            if offset_seconds < 0:
                continue
            bin_index = int(offset_seconds // bin_seconds)
            if bin_index >= target_bins:
                bin_index = target_bins - 1
            counts_15km[bin_index] += int(point["counts_15km"])
            counts_30km[bin_index] += int(point["counts_30km"])

        return counts_15km, counts_30km, int(bin_seconds)

    @staticmethod
    def _pad_window_boundaries(points, window_start, window_end):
        padded = list(points or [])
        has_start = any(point.get("time") == window_start for point in padded)
        has_end = any(point.get("time") == window_end for point in padded)

        if not has_start:
            padded.append(
                {
                    "time": window_start,
                    "counts_15km": 0,
                    "counts_30km": 0,
                }
            )
        if not has_end:
            padded.append(
                {
                    "time": window_end,
                    "counts_15km": 0,
                    "counts_30km": 0,
                }
            )

        padded.sort(key=lambda point: point["time"])
        return padded

    def _extract_snapshot_points_from_records(self, records, now_sgt=None, cutoff_sgt=None):
        snapshot_points = []

        for record in records:
            record_time = self._parse_nea_datetime(record.get('datetime'))
            if record_time is None:
                continue
            if now_sgt and record_time > now_sgt:
                continue
            if cutoff_sgt and record_time < cutoff_sgt:
                continue

            readings = (record.get('item') or {}).get('readings') or []
            summary = self._summarize_lightning_readings(readings)
            snapshot_points.append(
                {
                    "time": record_time,
                    "counts_15km": int(summary["within_15km_count"]),
                    "counts_30km": int(summary["within_30km_count"]),
                    "total_valid_count": int(summary["total_valid_count"]),
                    "nearest_distance_km": summary["nearest_distance_km"],
                    "points_30km_json": json.dumps(
                        summary.get("points_within_30km") or [],
                        ensure_ascii=False,
                    ),
                    "source_record_json": json.dumps(record, ensure_ascii=False),
                }
            )

        snapshot_points.sort(key=lambda point: point["time"])
        return snapshot_points

    @staticmethod
    def _to_utc_naive(dt_value):
        if dt_value is None:
            return None
        if dt_value.tzinfo is None:
            return dt_value
        return dt_value.astimezone(timezone.utc).replace(tzinfo=None)

    def _prune_old_lightning_history_rows(self, anchor_utc):
        if anchor_utc is None:
            return 0

        from app.models.lightning_history import LightningHistorySnapshot

        cutoff_utc = anchor_utc - self.LIGHTNING_HISTORY_RETENTION
        return (
            LightningHistorySnapshot.query
            .filter(LightningHistorySnapshot.observed_at_utc < cutoff_utc)
            .delete(synchronize_session=False)
        )

    def _persist_lightning_snapshot_points(self, snapshot_points, data_source="live_api"):
        if not has_app_context() or not snapshot_points:
            return 0

        try:
            from app.extensions import db
            from app.models.lightning_history import LightningHistorySnapshot

            normalized = {}
            for point in snapshot_points:
                point_time = point.get("time")
                point_time_utc = self._to_utc_naive(point_time)
                if point_time_utc is None:
                    continue

                if point_time is not None and point_time.tzinfo is not None:
                    point_time_sgt = point_time.astimezone(self.SGT)
                else:
                    point_time_sgt = point_time

                normalized[point_time_utc] = {
                    "observed_at_sgt": (
                        point_time_sgt.isoformat()
                        if point_time_sgt is not None
                        else point_time_utc.isoformat()
                    ),
                    "within_15km_count": int(point.get("counts_15km") or 0),
                    "within_30km_count": int(point.get("counts_30km") or 0),
                    "total_valid_count": int(point.get("total_valid_count") or 0),
                    "nearest_distance_km": self._to_float(point.get("nearest_distance_km")),
                    "data_source": str(data_source or "live_api"),
                    "points_30km_json": point.get("points_30km_json"),
                    "source_record_json": point.get("source_record_json"),
                }

            if not normalized:
                return 0

            observed_keys = list(normalized.keys())
            retention_anchor_utc = max(observed_keys)
            existing_rows = (
                LightningHistorySnapshot.query.options(
                    load_only(
                        LightningHistorySnapshot.id,
                        LightningHistorySnapshot.observed_at_utc,
                    )
                )
                .filter(
                    LightningHistorySnapshot.observed_at_utc.in_(observed_keys)
                ).all()
            )
            existing_map = {row.observed_at_utc: row for row in existing_rows}

            written_count = 0
            for observed_at_utc, payload in normalized.items():
                row = existing_map.get(observed_at_utc)
                if row is None:
                    row = LightningHistorySnapshot(observed_at_utc=observed_at_utc)
                    db.session.add(row)

                row.observed_at_sgt = payload["observed_at_sgt"]
                row.within_15km_count = payload["within_15km_count"]
                row.within_30km_count = payload["within_30km_count"]
                row.total_valid_count = payload["total_valid_count"]
                row.nearest_distance_km = payload["nearest_distance_km"]
                row.data_source = payload["data_source"]
                if payload["points_30km_json"] is not None:
                    row.points_30km_json = payload["points_30km_json"]
                if payload["source_record_json"] is not None:
                    row.source_record_json = payload["source_record_json"]
                written_count += 1

            self._prune_old_lightning_history_rows(retention_anchor_utc)
            try:
                db.session.commit()
                return written_count
            except IntegrityError:
                db.session.rollback()
                existing_rows = (
                    LightningHistorySnapshot.query.options(
                        load_only(
                            LightningHistorySnapshot.id,
                            LightningHistorySnapshot.observed_at_utc,
                        )
                    )
                    .filter(
                        LightningHistorySnapshot.observed_at_utc.in_(observed_keys)
                    ).all()
                )
                existing_map = {row.observed_at_utc: row for row in existing_rows}
                for observed_at_utc, payload in normalized.items():
                    row = existing_map.get(observed_at_utc)
                    if row is None:
                        row = LightningHistorySnapshot(observed_at_utc=observed_at_utc)
                        db.session.add(row)
                    row.observed_at_sgt = payload["observed_at_sgt"]
                    row.within_15km_count = payload["within_15km_count"]
                    row.within_30km_count = payload["within_30km_count"]
                    row.total_valid_count = payload["total_valid_count"]
                    row.nearest_distance_km = payload["nearest_distance_km"]
                    row.data_source = payload["data_source"]
                    if payload["points_30km_json"] is not None:
                        row.points_30km_json = payload["points_30km_json"]
                    if payload["source_record_json"] is not None:
                        row.source_record_json = payload["source_record_json"]
                self._prune_old_lightning_history_rows(retention_anchor_utc)
                db.session.commit()
                return written_count
        except Exception:
            try:
                from app.extensions import db
                db.session.rollback()
            except Exception:
                pass
            logger.exception("Failed to persist lightning snapshot points.")
            return 0

    def _persist_lightning_snapshot_metrics(self, snapshot):
        if not snapshot or snapshot.get("error"):
            return 0

        observed_at = self._parse_nea_datetime(snapshot.get("observation_time_sgt"))
        if observed_at is None:
            return 0

        metrics = snapshot.get("metrics") or {}
        points_within_30km = [
            point
            for point in (snapshot.get("points") or [])
            if self._to_float((point or {}).get("distance_km")) is not None
            and float(point.get("distance_km")) <= 30
        ]
        point = {
            "time": observed_at,
            "counts_15km": int(metrics.get("within_15km_count") or 0),
            "counts_30km": int(metrics.get("within_30km_count") or 0),
            "total_valid_count": int(metrics.get("total_valid_count") or 0),
            "nearest_distance_km": self._to_float(metrics.get("nearest_distance_km")),
            "points_30km_json": json.dumps(points_within_30km, ensure_ascii=False),
        }
        return self._persist_lightning_snapshot_points(
            [point],
            data_source=snapshot.get("data_source", "live_api"),
        )

    def _load_persisted_lightning_snapshot_points(self, now_sgt, cutoff_sgt):
        if not has_app_context():
            return []

        try:
            from app.models.lightning_history import LightningHistorySnapshot

            cutoff_utc = self._to_utc_naive(cutoff_sgt)
            now_utc = self._to_utc_naive(now_sgt)

            rows = (
                LightningHistorySnapshot.query.options(
                    load_only(
                        LightningHistorySnapshot.observed_at_utc,
                        LightningHistorySnapshot.within_15km_count,
                        LightningHistorySnapshot.within_30km_count,
                        LightningHistorySnapshot.total_valid_count,
                        LightningHistorySnapshot.nearest_distance_km,
                    )
                )
                .filter(
                    LightningHistorySnapshot.observed_at_utc >= cutoff_utc,
                    LightningHistorySnapshot.observed_at_utc <= now_utc,
                )
                .order_by(LightningHistorySnapshot.observed_at_utc.asc())
                .all()
            )

            points = []
            for row in rows:
                observed_at_utc = row.observed_at_utc
                if observed_at_utc.tzinfo is None:
                    observed_at_utc = observed_at_utc.replace(tzinfo=timezone.utc)
                else:
                    observed_at_utc = observed_at_utc.astimezone(timezone.utc)

                point_time = observed_at_utc.astimezone(self.SGT)
                points.append(
                    {
                        "time": point_time,
                        "counts_15km": int(row.within_15km_count or 0),
                        "counts_30km": int(row.within_30km_count or 0),
                        "total_valid_count": int(row.total_valid_count or 0),
                        "nearest_distance_km": self._to_float(row.nearest_distance_km),
                    }
                )

            return points
        except Exception:
            try:
                from app.extensions import db
                db.session.rollback()
            except Exception:
                pass
            logger.exception("Failed to load persisted lightning snapshot points.")
            return []

    @staticmethod
    def _parse_json_list(raw_value):
        if not raw_value:
            return []
        try:
            parsed = json.loads(raw_value)
        except (TypeError, ValueError):
            return []
        if not isinstance(parsed, list):
            return []
        return parsed

    def _build_lightning_snapshot_from_persisted_row(self, row):
        if row is None:
            return None

        points_30km = self._parse_json_list(getattr(row, "points_30km_json", None))
        expected_points_30km = int(getattr(row, "within_30km_count", 0) or 0)
        if not points_30km and expected_points_30km > 0:
            source_record = getattr(row, "source_record_json", None)
            if source_record:
                try:
                    parsed_record = json.loads(source_record)
                    readings = (parsed_record.get("item") or {}).get("readings") or []
                    points_30km = self._summarize_lightning_readings(readings)[
                        "points_within_30km"
                    ]
                except (TypeError, ValueError):
                    points_30km = []

        nearest_value = self._to_float(getattr(row, "nearest_distance_km", None))
        if nearest_value is None:
            risk_level = "clear"
        elif nearest_value <= self.LIGHTNING_CLOSE_THRESHOLD:
            risk_level = "high"
        elif nearest_value <= self.LIGHTNING_WARN_THRESHOLD:
            risk_level = "warning"
        elif nearest_value <= 30:
            risk_level = "watch"
        else:
            risk_level = "clear"

        observed_at_utc = getattr(row, "observed_at_utc", None)
        generated_at = None
        if observed_at_utc is not None:
            if observed_at_utc.tzinfo is None:
                observed_at_utc = observed_at_utc.replace(tzinfo=timezone.utc)
            generated_at = observed_at_utc.isoformat()

        return {
            "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
            "observation_time_sgt": getattr(row, "observed_at_sgt", None),
            "data_source": "persisted_store",
            "error": None,
            "source_error": None,
            "warning": None,
            "stale_cache": False,
            "metrics": {
                "nearest_distance_km": nearest_value,
                "within_15km_count": int(getattr(row, "within_15km_count", 0) or 0),
                "within_30km_count": int(getattr(row, "within_30km_count", 0) or 0),
                "total_valid_count": int(getattr(row, "total_valid_count", 0) or 0),
                "risk_level": risk_level,
                "close_threshold_km": self.LIGHTNING_CLOSE_THRESHOLD,
                "warn_threshold_km": self.LIGHTNING_WARN_THRESHOLD,
            },
            "points": points_30km,
        }

    def _load_latest_persisted_lightning_snapshot(self):
        if not has_app_context():
            return None

        try:
            from app.models.lightning_history import LightningHistorySnapshot

            row = (
                LightningHistorySnapshot.query.options(
                    load_only(
                        LightningHistorySnapshot.observed_at_utc,
                        LightningHistorySnapshot.observed_at_sgt,
                        LightningHistorySnapshot.within_15km_count,
                        LightningHistorySnapshot.within_30km_count,
                        LightningHistorySnapshot.total_valid_count,
                        LightningHistorySnapshot.nearest_distance_km,
                        LightningHistorySnapshot.points_30km_json,
                    )
                )
                .order_by(
                    LightningHistorySnapshot.observed_at_utc.desc()
                ).first()
            )
            return self._build_lightning_snapshot_from_persisted_row(row)
        except Exception:
            try:
                from app.extensions import db
                db.session.rollback()
            except Exception:
                pass
            logger.exception("Failed to load latest persisted lightning snapshot.")
            return None

    def _build_lightning_history_charts_from_points(
        self,
        snapshot_points,
        now_sgt,
        latest_snapshot=None,
    ):
        window_specs = {
            "20m": {
                "duration": timedelta(minutes=20),
                "label_format": "%H:%M",
                "display_label": "Last 20 Minutes",
            },
            "1h": {
                "duration": timedelta(hours=1),
                "label_format": "%H:%M",
                "display_label": "Last 1 Hour",
            },
            "12h": {
                "duration": timedelta(hours=12),
                "label_format": "%m/%d %H:%M",
                "display_label": "Last 12 Hours",
                "target_bins": 60,
            },
        }

        cutoff_sgt = now_sgt - timedelta(hours=12)
        normalized_points = []
        oldest_counted_point = None

        for point in snapshot_points or []:
            point_time = point.get("time")
            if point_time is None:
                continue

            if point_time.tzinfo is None:
                point_time = point_time.replace(tzinfo=self.SGT)
            else:
                point_time = point_time.astimezone(self.SGT)

            if point_time > now_sgt or point_time < cutoff_sgt:
                continue

            normalized_points.append(
                {
                    "time": point_time,
                    "counts_15km": int(point.get("counts_15km") or 0),
                    "counts_30km": int(point.get("counts_30km") or 0),
                }
            )

        normalized_points.sort(key=lambda item: item["time"])

        latest_metrics = (latest_snapshot or {}).get("metrics") or {}
        latest_observed_at = self._parse_nea_datetime(
            (latest_snapshot or {}).get("observation_time_sgt")
        )
        if latest_observed_at and cutoff_sgt <= latest_observed_at <= now_sgt:
            override_point = {
                "time": latest_observed_at,
                "counts_15km": int(latest_metrics.get("within_15km_count") or 0),
                "counts_30km": int(latest_metrics.get("within_30km_count") or 0),
            }

            merged = False
            for index, point in enumerate(normalized_points):
                if point["time"] == latest_observed_at:
                    normalized_points[index] = override_point
                    merged = True
                    break
            if not merged:
                normalized_points.append(override_point)
                normalized_points.sort(key=lambda point: point["time"])

        for point in normalized_points:
            if int(point.get("counts_30km") or 0) <= 0:
                continue
            point_time = point.get("time")
            if oldest_counted_point is None or point_time < oldest_counted_point:
                oldest_counted_point = point_time

        charts = {}
        for window_key, spec in window_specs.items():
            window_start = now_sgt - spec["duration"]
            window_points = [
                point for point in normalized_points if point["time"] >= window_start
            ]
            raw_snapshot_count = len(window_points)
            if "target_bins" in spec:
                target_bins = int(spec["target_bins"])
                counts_15km, counts_30km, bin_seconds = self._aggregate_points_to_fixed_bins(
                    window_points,
                    window_start,
                    spec["duration"],
                    target_bins,
                )
                labels = [
                    (window_start + timedelta(seconds=bin_seconds * (index + 1))).strftime(
                        spec["label_format"]
                    )
                    for index in range(target_bins)
                ]
                counts_15km = [0] + counts_15km
                counts_30km = [0] + counts_30km
                labels = [window_start.strftime(spec["label_format"])] + labels
            else:
                points = self._pad_window_boundaries(window_points, window_start, now_sgt)
                counts_15km = [int(point["counts_15km"]) for point in points]
                counts_30km = [int(point["counts_30km"]) for point in points]
                labels = [point["time"].strftime(spec["label_format"]) for point in points]

            charts[window_key] = {
                "display_label": spec["display_label"],
                "labels": labels,
                "counts_15km": counts_15km,
                "counts_30km": counts_30km,
                "totals": {
                    "15km": int(sum(counts_15km)),
                    "30km": int(sum(counts_30km)),
                },
                "snapshot_count": raw_snapshot_count,
                "bar_count": len(labels),
            }

        return charts, oldest_counted_point

    def _build_lightning_history_charts(self, records, now_sgt, latest_snapshot=None):
        cutoff_sgt = now_sgt - timedelta(hours=12)
        snapshot_points = self._extract_snapshot_points_from_records(
            records,
            now_sgt=now_sgt,
            cutoff_sgt=cutoff_sgt,
        )
        return self._build_lightning_history_charts_from_points(
            snapshot_points,
            now_sgt,
            latest_snapshot=latest_snapshot,
        )

    def get_lightning_history(self):
        cached = self._get_cached_lightning_history()
        if cached is not None:
            return cached

        lightning_snapshot = self.get_lightning_snapshot()

        if not self._lightning_history_refresh_lock.acquire(blocking=False):
            now_sgt = datetime.now(self.SGT).replace(microsecond=0)
            cutoff_sgt = now_sgt - timedelta(hours=12)
            persisted_points = self._load_persisted_lightning_snapshot_points(now_sgt, cutoff_sgt)
            charts, oldest_counted_point = self._build_lightning_history_charts_from_points(
                persisted_points,
                now_sgt,
                latest_snapshot=lightning_snapshot,
            )
            return {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "observation_time_sgt": (
                    lightning_snapshot.get("observation_time_sgt") or now_sgt.isoformat()
                ),
                "distance_options_km": [15, 30],
                "window_options": ["20m", "1h", "12h"],
                "charts": charts,
                "metadata": {
                    "data_source": lightning_snapshot.get("data_source", "degraded"),
                    "requests_made": 0,
                    "records_loaded": len(persisted_points),
                    "coverage_start_sgt": (
                        persisted_points[0]["time"].isoformat() if persisted_points else None
                    ),
                    "coverage_end_sgt": now_sgt.isoformat(),
                    "oldest_counted_point_sgt": (
                        oldest_counted_point.isoformat() if oldest_counted_point else None
                    ),
                    "full_12h_coverage": bool(
                        persisted_points and persisted_points[0]["time"] <= cutoff_sgt
                    ),
                    "truncated": False,
                    "rate_limited": False,
                    "error": "refresh_in_progress",
                    "warning": "Lightning history refresh is in progress.",
                    "stale_cache": False,
                    "snapshot_stale_cache": bool(lightning_snapshot.get("stale_cache", False)),
                    "snapshot_source_error": lightning_snapshot.get("source_error"),
                    "history_basis": "persisted_store",
                    "persisted_records_loaded": len(persisted_points),
                    "persisted_records_written": 0,
                },
            }

        try:
            now_sgt = datetime.now(self.SGT).replace(microsecond=0)
            cutoff_sgt = now_sgt - timedelta(hours=12)
            persisted_points = self._load_persisted_lightning_snapshot_points(now_sgt, cutoff_sgt)
            persisted_written = 0
            backfill_fetch_meta = None

            if has_app_context():
                required_20m_start = now_sgt - timedelta(minutes=20)
                recent_points = [
                    point for point in persisted_points if point["time"] >= required_20m_start
                ]
                recent_first_time = recent_points[0]["time"] if recent_points else None
                recent_last_time = recent_points[-1]["time"] if recent_points else None
                needs_20m_backfill = (
                    not recent_points
                    or recent_first_time > (required_20m_start + timedelta(minutes=3))
                    or recent_last_time < (now_sgt - timedelta(minutes=3))
                )
                if needs_20m_backfill:
                    records, backfill_fetch_meta = self._fetch_lightning_records_for_history(
                        now_sgt,
                        cutoff_sgt,
                    )
                    api_points = self._extract_snapshot_points_from_records(
                        records,
                        now_sgt=now_sgt,
                        cutoff_sgt=cutoff_sgt,
                    )
                    persisted_written += self._persist_lightning_snapshot_points(
                        api_points,
                        data_source=(backfill_fetch_meta or {}).get("data_source", "live_api"),
                    )
                    persisted_written += self._persist_lightning_snapshot_metrics(lightning_snapshot)
                    persisted_points = self._load_persisted_lightning_snapshot_points(
                        now_sgt,
                        cutoff_sgt,
                    )

            charts, oldest_counted_point = self._build_lightning_history_charts_from_points(
                persisted_points,
                now_sgt,
                latest_snapshot=lightning_snapshot,
            )

            coverage_start = persisted_points[0]["time"] if persisted_points else None
            full_12h_coverage = bool(coverage_start and coverage_start <= cutoff_sgt)
            warning = None
            error = None
            requests_made = 0
            truncated = False
            rate_limited = False

            if backfill_fetch_meta:
                requests_made = int(backfill_fetch_meta.get("request_count") or 0)
                truncated = bool(backfill_fetch_meta.get("truncated", False))
                rate_limited = bool(backfill_fetch_meta.get("rate_limited", False))
                error = backfill_fetch_meta.get("error")
                warning = self._format_lightning_history_warning(
                    backfill_fetch_meta.get("error"),
                    truncated,
                    rate_limited,
                )

            if not persisted_points:
                error = "no_persisted_data"
                warning = "Lightning history is warming up. Background collector has not stored data yet."

            payload = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "observation_time_sgt": (
                    lightning_snapshot.get("observation_time_sgt") or now_sgt.isoformat()
                ),
                "distance_options_km": [15, 30],
                "window_options": ["20m", "1h", "12h"],
                "charts": charts,
                "metadata": {
                    "data_source": (
                        "persisted_store"
                        if persisted_points
                        else (backfill_fetch_meta or {}).get("data_source", "persisted_store")
                    ),
                    "requests_made": requests_made,
                    "records_loaded": len(persisted_points),
                    "coverage_start_sgt": coverage_start.isoformat() if coverage_start else None,
                    "coverage_end_sgt": now_sgt.isoformat(),
                    "oldest_counted_point_sgt": (
                        oldest_counted_point.isoformat() if oldest_counted_point else None
                    ),
                    "full_12h_coverage": full_12h_coverage,
                    "truncated": truncated,
                    "rate_limited": rate_limited,
                    "error": error,
                    "warning": warning,
                    "stale_cache": False,
                    "snapshot_stale_cache": bool(lightning_snapshot.get("stale_cache", False)),
                    "snapshot_source_error": lightning_snapshot.get("source_error"),
                    "history_basis": "persisted_store",
                    "persisted_records_loaded": len(persisted_points),
                    "persisted_records_written": persisted_written,
                },
            }

            self._set_cached_lightning_history(payload)
            return payload
        finally:
            self._lightning_history_refresh_lock.release()

    def _fetch_lightning_payload(self):
        """Fetch raw lightning payload from NEA or local sample data."""
        use_sample_data = self._use_sample_data()
        if use_sample_data:
            with open(SAMPLE_LIGHTNING_PATH, 'r', encoding='utf-8') as file:
                return json.load(file), "sample_data", None

        api_key = current_app.config.get('NEA_API_KEY')
        headers = {'x-api-key': api_key} if api_key else {}
        response = requests.get(
            self.LIGHTNING_API_URL,
            headers=headers,
            timeout=self._get_weather_api_timeout_seconds(),
        )

        if response.status_code == 403:
            return None, "live_api", "missing_or_invalid_api_key"
        if response.status_code != 200:
            logger.warning(
                "Lightning API request failed with HTTP %s.",
                response.status_code,
            )
            return None, "live_api", "api_unavailable"

        try:
            payload = response.json()
        except ValueError:
            logger.warning("Lightning API response is not valid JSON.")
            return None, "live_api", "invalid_response"

        if payload.get('code') != 0:
            logger.warning(
                "Lightning API returned error code payload: %s",
                payload.get('errorMsg'),
            )
            return None, "live_api", "api_error_payload"

        return payload, "live_api", None

    @staticmethod
    def _extract_latest_lightning_readings(payload):
        records = (payload or {}).get('data', {}).get('records', [])
        if not records:
            return [], None

        latest_record = records[0]
        latest_item = latest_record.get('item') or {}
        readings = latest_item.get('readings') or []
        observed_at = latest_record.get('datetime') or latest_record.get('updatedTimestamp')
        return readings, observed_at

    @staticmethod
    def _lightning_unavailable_message(error_code):
        if error_code == "missing_or_invalid_api_key":
            return "NEA API key missing or invalid."
        return "Weather data temporarily unavailable."

    def _build_unavailable_lightning_snapshot(self, data_source, error_code, warning=None):
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "observation_time_sgt": None,
            "data_source": data_source,
            "error": error_code,
            "source_error": None,
            "warning": warning or self._lightning_unavailable_message(error_code),
            "stale_cache": False,
            "metrics": {
                "nearest_distance_km": None,
                "within_15km_count": 0,
                "within_30km_count": 0,
                "total_valid_count": 0,
                "risk_level": "unknown",
                "close_threshold_km": self.LIGHTNING_CLOSE_THRESHOLD,
                "warn_threshold_km": self.LIGHTNING_WARN_THRESHOLD,
            },
            "points": [],
        }

    @staticmethod
    def _to_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _summarize_lightning_readings(self, readings):
        points = []
        points_within_30km = []
        nearest_distance = None
        within_15km_count = 0
        within_30km_count = 0
        total_valid_count = 0

        for reading in readings:
            location = reading.get('location') or {}
            lat = self._to_float(location.get('latitude'))
            lon = self._to_float(location.get('longitude'))
            if lat is None or lon is None:
                continue

            total_valid_count += 1
            distance_km = self.haversine(self.SRC_LAT, self.SRC_LON, lat, lon)
            distance_value = round(distance_km, 2)

            if nearest_distance is None or distance_km < nearest_distance:
                nearest_distance = distance_km
            if distance_km <= self.LIGHTNING_WARN_THRESHOLD:
                within_15km_count += 1
            if distance_km <= 30:
                within_30km_count += 1

            point_payload = {
                "lat": lat,
                "lng": lon,
                "distance_km": distance_value,
                "type": reading.get('type'),
                "datetime": reading.get('datetime'),
            }
            points.append(point_payload)
            if distance_km <= 30:
                points_within_30km.append(point_payload)

        points.sort(key=lambda point: point["distance_km"])
        points_within_30km.sort(key=lambda point: point["distance_km"])

        return {
            "points": points,
            "points_within_30km": points_within_30km,
            "nearest_distance_km": (
                round(nearest_distance, 2) if nearest_distance is not None else None
            ),
            "within_15km_count": int(within_15km_count),
            "within_30km_count": int(within_30km_count),
            "total_valid_count": int(total_valid_count),
        }

    def _build_stale_lightning_snapshot(self, stale_snapshot, warning, source_error):
        stale = copy.deepcopy(stale_snapshot)
        stale["stale_cache"] = True
        stale["error"] = None
        stale["source_error"] = source_error
        stale["warning"] = warning
        return stale

    def _build_lightning_snapshot_from_payload(self, payload, data_source):
        readings, observed_at = self._extract_latest_lightning_readings(payload)
        summary = self._summarize_lightning_readings(readings)
        points = summary["points"]
        nearest_value = summary["nearest_distance_km"]
        within_15km_count = summary["within_15km_count"]
        within_30km_count = summary["within_30km_count"]
        total_valid_count = summary["total_valid_count"]

        if nearest_value is None:
            risk_level = "clear"
        elif nearest_value <= self.LIGHTNING_CLOSE_THRESHOLD:
            risk_level = "high"
        elif nearest_value <= self.LIGHTNING_WARN_THRESHOLD:
            risk_level = "warning"
        elif nearest_value <= 30:
            risk_level = "watch"
        else:
            risk_level = "clear"

        warning = None
        if not readings:
            warning = "No lightning readings are available in the latest snapshot."
        elif not points:
            warning = "No valid lightning coordinates are available in the latest snapshot."

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "observation_time_sgt": observed_at,
            "data_source": data_source,
            "error": None,
            "source_error": None,
            "warning": warning,
            "stale_cache": False,
            "metrics": {
                "nearest_distance_km": nearest_value,
                "within_15km_count": within_15km_count,
                "within_30km_count": within_30km_count,
                "total_valid_count": total_valid_count,
                "risk_level": risk_level,
                "close_threshold_km": self.LIGHTNING_CLOSE_THRESHOLD,
                "warn_threshold_km": self.LIGHTNING_WARN_THRESHOLD,
            },
            "points": points,
        }

    def _fetch_lightning_snapshot_live(self):
        try:
            payload, data_source, error_code = self._fetch_lightning_payload()
        except requests.exceptions.Timeout:
            logger.warning("Lightning snapshot request timeout.")
            return self._build_unavailable_lightning_snapshot(
                "degraded",
                "timeout",
                "Lightning snapshot request timed out.",
            )
        except requests.exceptions.RequestException:
            logger.exception("Lightning snapshot request error.")
            return self._build_unavailable_lightning_snapshot(
                "degraded",
                "network_error",
                "Lightning snapshot request failed due to network error.",
            )

        if error_code:
            warning = self._lightning_unavailable_message(error_code)
            return self._build_unavailable_lightning_snapshot(data_source, error_code, warning)

        snapshot = self._build_lightning_snapshot_from_payload(payload, data_source)
        self._persist_lightning_snapshot_metrics(snapshot)

        persisted_snapshot = self._load_latest_persisted_lightning_snapshot()
        if persisted_snapshot is not None:
            self._set_cached_lightning_snapshot(persisted_snapshot)
            return persisted_snapshot

        self._set_cached_lightning_snapshot(snapshot)
        return snapshot

    def collect_and_store_latest_lightning_snapshot(self):
        if not self._lightning_snapshot_refresh_lock.acquire(blocking=False):
            return {"ok": False, "reason": "refresh_in_progress"}

        try:
            snapshot = self._fetch_lightning_snapshot_live()
            if snapshot.get("error"):
                return {"ok": False, "reason": snapshot.get("error"), "snapshot": snapshot}
            return {"ok": True, "snapshot": snapshot}
        finally:
            self._lightning_snapshot_refresh_lock.release()

    def get_lightning_snapshot(self):
        cached = self._get_cached_lightning_snapshot()
        if cached is not None:
            return cached

        persisted_snapshot = self._load_latest_persisted_lightning_snapshot()
        if persisted_snapshot is not None:
            self._set_cached_lightning_snapshot(persisted_snapshot)
            return persisted_snapshot

        if not self._lightning_snapshot_refresh_lock.acquire(blocking=False):
            stale = self._get_stale_cached_lightning_snapshot()
            if stale is not None:
                return self._build_stale_lightning_snapshot(
                    stale,
                    "Using cached lightning snapshot while refresh is in progress.",
                    "refresh_in_progress",
                )
            persisted_snapshot = self._load_latest_persisted_lightning_snapshot()
            if persisted_snapshot is not None:
                return persisted_snapshot
            return self._build_unavailable_lightning_snapshot(
                "degraded",
                "refresh_in_progress",
                "Lightning snapshot refresh is in progress.",
            )

        try:
            persisted_snapshot = self._load_latest_persisted_lightning_snapshot()
            if persisted_snapshot is not None:
                self._set_cached_lightning_snapshot(persisted_snapshot)
                return persisted_snapshot

            snapshot = self._fetch_lightning_snapshot_live()
            if snapshot.get("error"):
                stale = self._get_stale_cached_lightning_snapshot()
                if stale is not None:
                    return self._build_stale_lightning_snapshot(
                        stale,
                        f"Using cached lightning snapshot ({snapshot.get('warning')})",
                        snapshot.get("error"),
                    )
            return snapshot
        except Exception:
            logger.exception("Unexpected weather engine error when building lightning snapshot.")
            stale = self._get_stale_cached_lightning_snapshot()
            if stale is not None:
                return self._build_stale_lightning_snapshot(
                    stale,
                    "Using cached lightning snapshot due to system error.",
                    "system_error",
                )
            return self._build_unavailable_lightning_snapshot(
                "degraded",
                "system_error",
                "Lightning snapshot is temporarily unavailable.",
            )
        finally:
            self._lightning_snapshot_refresh_lock.release()

    def get_lightning_radar_data(self, radius_km=30):
        """Return radar visualization points from the shared lightning snapshot."""
        snapshot = self.get_lightning_snapshot()
        metrics = snapshot.get("metrics") or {}

        radius_value = self._to_float(radius_km)
        if radius_value is None or radius_value <= 0:
            radius_value = 30.0

        all_points = snapshot.get("points") or []
        radius_points = [
            {
                "lat": point.get("lat"),
                "lng": point.get("lng"),
                "distance_km": point.get("distance_km"),
                "type": point.get("type"),
                "datetime": point.get("datetime"),
            }
            for point in all_points
            if self._to_float(point.get("distance_km")) is not None
            and float(point.get("distance_km")) <= radius_value
        ]

        nearest_value = metrics.get("nearest_distance_km")
        if snapshot.get("error"):
            risk_level = "unknown"
        elif nearest_value is None:
            risk_level = "clear"
        elif nearest_value <= self.LIGHTNING_CLOSE_THRESHOLD:
            risk_level = "high"
        elif nearest_value <= self.LIGHTNING_WARN_THRESHOLD:
            risk_level = "warning"
        elif nearest_value <= radius_value:
            risk_level = "watch"
        else:
            risk_level = "clear"

        return {
            "generated_at": snapshot.get("generated_at") or datetime.now(timezone.utc).isoformat(),
            "observation_time_sgt": snapshot.get("observation_time_sgt"),
            "center": {
                "lat": self.SRC_LAT,
                "lng": self.SRC_LON,
                "label": "NTU SRC",
            },
            "radius_km": float(radius_value),
            "points": radius_points,
            "metrics": {
                "nearest_distance_km": nearest_value,
                "within_radius_count": len(radius_points),
                "total_valid_count": int(metrics.get("total_valid_count") or 0),
                "risk_level": risk_level,
                "close_threshold_km": self.LIGHTNING_CLOSE_THRESHOLD,
                "warn_threshold_km": self.LIGHTNING_WARN_THRESHOLD,
            },
            "meta": {
                "data_source": snapshot.get("data_source", "degraded"),
                "error": snapshot.get("error"),
                "source_error": snapshot.get("source_error"),
                "warning": snapshot.get("warning"),
                "stale_cache": bool(snapshot.get("stale_cache", False)),
            },
        }

    def get_lightning_status(self):
        """Fetch nearest lightning metrics from the shared latest snapshot."""
        snapshot = self.get_lightning_snapshot()
        error_code = snapshot.get("error")
        if error_code:
            return (
                PoolStatus.AMBER,
                self._lightning_unavailable_message(error_code),
                {
                    "error": error_code,
                    "data_source": snapshot.get("data_source", "degraded"),
                    "warning": snapshot.get("warning"),
                },
            )

        metrics = snapshot.get("metrics") or {}
        min_distance = metrics.get("nearest_distance_km")
        within_30km_count = int(metrics.get("within_30km_count") or 0)

        if min_distance is not None and min_distance <= self.LIGHTNING_WARN_THRESHOLD:
            status = PoolStatus.RED
            message = f"Lightning detected nearby ({min_distance:.1f}km) - Pool Closed"
        else:
            status = PoolStatus.GREEN
            message = "No lightning nearby - Pool is Open"

        details = {
            "min_distance_km": round(min_distance, 2)
            if min_distance is not None
            else 999.0,
            "lightning_count": within_30km_count,
            "lightning_count_basis": "within_30km_latest_snapshot",
            "timestamp": snapshot.get("generated_at") or datetime.now(timezone.utc).isoformat(),
            "observation_time_sgt": snapshot.get("observation_time_sgt"),
            "data_source": snapshot.get("data_source", "live_api"),
        }
        if snapshot.get("stale_cache"):
            details["stale_cache"] = True
        if snapshot.get("source_error"):
            details["source_error"] = snapshot.get("source_error")
        if snapshot.get("warning"):
            details["warning"] = snapshot.get("warning")

        return status, message, details

    def get_rainfall_status(self):
        """Fetch NTU-nearest station rainfall and normalize to mm/h."""
        try:
            use_sample_data = self._use_sample_data()
            self.last_rainfall_error = None

            if use_sample_data:
                with open(SAMPLE_RAINFALL_PATH, 'r', encoding='utf-8') as file:
                    data = json.load(file)
            else:
                api_key = current_app.config.get('NEA_API_KEY')
                headers = {'x-api-key': api_key} if api_key else {}

                response = requests.get(
                    self.RAINFALL_API_URL,
                    headers=headers,
                    timeout=self._get_weather_api_timeout_seconds(),
                )

                if response.status_code != 200:
                    self.last_rainfall_error = f"http_{response.status_code}"
                    logger.warning(
                        "Rainfall API request failed with HTTP %s.",
                        response.status_code,
                    )
                    return None, None, None

                data = response.json()

            if data.get('code') != 0:
                self.last_rainfall_error = 'api_error_payload'
                logger.warning(
                    "Rainfall API returned error code payload: %s",
                    data.get('errorMsg'),
                )
                return None, None, None

            stations = data.get('data', {}).get('stations', [])
            station_map = {}
            for station in stations:
                station_id = station.get('id')
                location = station.get('location', {})
                lat = location.get('latitude')
                lon = location.get('longitude')
                name = station.get('name')

                if station_id and lat is not None and lon is not None:
                    station_map[station_id] = {
                        'name': name,
                        'lat': float(lat),
                        'lon': float(lon),
                    }

            nearest_station_id = None
            nearest_station_name = None
            min_distance = float('inf')

            for station_id, info in station_map.items():
                distance = self.haversine(self.SRC_LAT, self.SRC_LON, info['lat'], info['lon'])
                if distance < min_distance:
                    min_distance = distance
                    nearest_station_id = station_id
                    nearest_station_name = info['name']

            if nearest_station_id is None:
                self.last_rainfall_error = 'station_not_found'
                return None, None, None

            readings = data.get('data', {}).get('readings', [])
            rainfall_5min = None

            if readings:
                latest_reading = readings[-1]
                reading_data = latest_reading.get('data', [])
                for item in reading_data:
                    if item.get('stationId') == nearest_station_id:
                        rainfall_5min = float(item.get('value', 0))
                        break

            if rainfall_5min is None:
                self.last_rainfall_error = 'station_value_not_found'
                return None, nearest_station_name, round(min_distance, 2)

            # NEA rainfall is in mm per 5 minutes; convert to mm/h.
            rainfall_per_hour = rainfall_5min * 12
            return rainfall_per_hour, nearest_station_name, round(min_distance, 2)

        except Exception:
            self.last_rainfall_error = 'exception'
            logger.exception("Unexpected weather engine error when fetching rainfall status.")
            return None, None, None


weather_engine = WeatherEngine()

