"""Shared pool operating-hours rules (single source of truth).

Used by both the weather status engine and the community bot scheduler so
that "is the pool open right now" is always answered the same way.

All rules are defined in Singapore time (SGT, UTC+8).
"""

from datetime import date, datetime, time, timedelta, timezone


SGT = timezone(timedelta(hours=8))

WEEKDAY_OPEN = time(7, 0)
WEEKDAY_CLOSE = time(21, 30)
WEEKEND_OPEN = time(8, 0)
WEEKEND_CLOSE = time(20, 0)

# Singapore gazetted public holidays (weekend schedule applies).
# Source: MOM via data.gov.sg. Extend this map before each new year begins.
PUBLIC_HOLIDAYS = {
    # 2026
    "2026-01-01",  # New Year's Day
    "2026-02-17",  # Chinese New Year Day 1
    "2026-02-18",  # Chinese New Year Day 2
    "2026-03-21",  # Hari Raya Puasa
    "2026-04-03",  # Good Friday
    "2026-05-01",  # Labour Day
    "2026-05-27",  # Hari Raya Haji
    "2026-05-31",  # Vesak Day
    "2026-06-01",  # Vesak Day (observed)
    "2026-08-09",  # National Day
    "2026-08-10",  # National Day (observed)
    "2026-11-08",  # Deepavali
    "2026-11-09",  # Deepavali (observed)
    "2026-12-25",  # Christmas Day
    # 2027
    "2027-01-01",  # New Year's Day
    "2027-02-06",  # Chinese New Year Day 1
    "2027-02-07",  # Chinese New Year Day 2
    "2027-02-08",  # Chinese New Year (observed)
    "2027-03-10",  # Hari Raya Puasa
    "2027-03-26",  # Good Friday
    "2027-05-01",  # Labour Day
    "2027-05-17",  # Hari Raya Haji
    "2027-05-20",  # Vesak Day
    "2027-08-09",  # National Day
    "2027-10-29",  # Deepavali
    "2027-12-25",  # Christmas Day
}

LAST_MAINTAINED_HOLIDAY_YEAR = 2027


def to_sgt(dt_value):
    """Convert a datetime (naive values are assumed UTC) to aware SGT."""
    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=timezone.utc)
    return dt_value.astimezone(SGT)


def is_public_holiday(sgt_date: date) -> bool:
    """Return whether the given SGT calendar date is a Singapore public holiday."""
    return sgt_date.isoformat() in PUBLIC_HOLIDAYS


def day_schedule(sgt_date: date):
    """Return (open_time, close_time, day_type_label) for an SGT calendar date."""
    is_weekend = sgt_date.weekday() >= 5  # 5=Sat, 6=Sun
    if is_weekend or is_public_holiday(sgt_date):
        return WEEKEND_OPEN, WEEKEND_CLOSE, "Weekend/Public Holiday"
    return WEEKDAY_OPEN, WEEKDAY_CLOSE, "Weekday"


def is_within_operating_hours(now=None):
    """Return (is_open, closed_message) for a UTC/naive-UTC/aware datetime.

    closed_message is None while the pool is open, matching the historical
    WeatherEngine._is_operating_hours contract.
    """
    sgt_now = to_sgt(now) if now is not None else datetime.now(SGT)
    open_time, close_time, day_type = day_schedule(sgt_now.date())

    if open_time <= sgt_now.time() <= close_time:
        return True, None

    msg = (
        f"Pool Closed - Outside Operating Hours "
        f"({day_type} {open_time.strftime('%H:%M')}-{close_time.strftime('%H:%M')})"
    )
    return False, msg


def operating_window_utc_naive(now=None, *, edge_buffer=timedelta(0)):
    """Return today's (SGT) operating window as naive-UTC datetimes.

    Returns (window_start_utc, window_end_utc) shrunk inward by ``edge_buffer``
    on both sides, or None when the buffered window is empty. The window is the
    one for the SGT calendar day that ``now`` falls in.
    """
    sgt_now = to_sgt(now) if now is not None else datetime.now(SGT)
    open_time, close_time, _ = day_schedule(sgt_now.date())

    start_sgt = datetime.combine(sgt_now.date(), open_time, tzinfo=SGT) + edge_buffer
    end_sgt = datetime.combine(sgt_now.date(), close_time, tzinfo=SGT) - edge_buffer
    if start_sgt >= end_sgt:
        return None

    start_utc = start_sgt.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_sgt.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc
