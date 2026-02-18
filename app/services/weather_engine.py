import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import Lock

import requests
from flask import current_app, has_app_context

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

    # NEA APIs.
    LIGHTNING_API_URL = "https://api-open.data.gov.sg/v2/real-time/api/weather?api=lightning"
    RAINFALL_API_URL = "https://api-open.data.gov.sg/v2/real-time/api/rainfall"

    def __init__(self):
        self.last_lightning_alert_time = None
        self.last_rain_alert_time = None
        self.last_rainfall_error = None

        self._status_cache = None
        self._status_cache_at = None
        self._status_cache_lock = Lock()
        self._status_refresh_lock = Lock()

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
        }

        is_open_hours, hours_msg = self._is_operating_hours()
        if not is_open_hours:
            details = {**base_metrics, "reason": "operating_hours"}
            self._set_cached_overall_status(PoolStatus.RED, hours_msg, details)
            return PoolStatus.RED, hours_msg, details

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

        if has_lightning:
            self.last_lightning_alert_time = now

        if self.last_lightning_alert_time:
            time_since_alert = (now - self.last_lightning_alert_time).total_seconds() / 60
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
                    "last_alert": self.last_lightning_alert_time.isoformat(),
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

    def get_lightning_status(self):
        """Fetch lightning points and return nearest distance + count."""
        try:
            use_sample_data = self._use_sample_data()

            if use_sample_data:
                with open(SAMPLE_LIGHTNING_PATH, 'r', encoding='utf-8') as file:
                    data = json.load(file)
            else:
                api_key = current_app.config.get('NEA_API_KEY')
                headers = {'x-api-key': api_key} if api_key else {}

                response = requests.get(
                    self.LIGHTNING_API_URL,
                    headers=headers,
                    timeout=10,
                )

                if response.status_code == 403:
                    return (
                        PoolStatus.AMBER,
                        "NEA API key missing or invalid.",
                        {"error": "missing_or_invalid_api_key"},
                    )

                if response.status_code != 200:
                    logger.warning(
                        "Lightning API request failed with HTTP %s.",
                        response.status_code,
                    )
                    return (
                        PoolStatus.AMBER,
                        "Weather data temporarily unavailable.",
                        {"error": "api_unavailable"},
                    )

                data = response.json()

            if data.get('code') != 0:
                logger.warning(
                    "Lightning API returned error code payload: %s",
                    data.get('errorMsg'),
                )
                return (
                    PoolStatus.AMBER,
                    "Weather data temporarily unavailable.",
                    {"error": "api_error_payload"},
                )

            records = data.get('data', {}).get('records', [])
            all_readings = []
            for record in records:
                item = record.get('item', {})
                readings = item.get('readings', [])
                all_readings.extend(readings)

            min_distance = float('inf')
            lightning_count = len(all_readings)

            for reading in all_readings:
                location = reading.get('location', {})
                lat_str = location.get('latitude')
                lon_str = location.get('longitude')
                if lat_str is None or lon_str is None:
                    continue

                try:
                    lat = float(lat_str)
                    lon = float(lon_str)
                except (ValueError, TypeError):
                    continue

                distance = self.haversine(self.SRC_LAT, self.SRC_LON, lat, lon)
                if distance < min_distance:
                    min_distance = distance

            if min_distance <= self.LIGHTNING_WARN_THRESHOLD:
                status = PoolStatus.RED
                message = (
                    f"Lightning detected nearby ({min_distance:.1f}km) - Pool Closed"
                )
            else:
                status = PoolStatus.GREEN
                message = "No lightning nearby - Pool is Open"

            details = {
                # If no lightning point exists, return a large safe distance so UI
                # can consistently display '>15km' and safe color state.
                "min_distance_km": round(min_distance, 2)
                if min_distance != float('inf')
                else 999.0,
                "lightning_count": lightning_count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data_source": "sample_data" if use_sample_data else "live_api",
            }

            return status, message, details

        except requests.exceptions.Timeout:
            logger.warning("Lightning API request timeout.")
            return PoolStatus.AMBER, "Weather request timeout.", {"error": "timeout"}
        except requests.exceptions.RequestException:
            logger.exception("Lightning API request error.")
            return PoolStatus.AMBER, "Weather network error.", {"error": "network_error"}
        except Exception:
            logger.exception("Unexpected weather engine error when fetching lightning status.")
            return PoolStatus.AMBER, "Weather system error.", {"error": "system_error"}

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
                    timeout=10,
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

