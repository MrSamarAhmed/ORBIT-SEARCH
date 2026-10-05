import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.errors import APIError

# `starts_at_local` is bare wall clock: no offset, no `Z`, no seconds.
LOCAL_MINUTE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")


def zone_for(tz_name):
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return timezone.utc


def utc_iso(dt: datetime) -> str:
    """Stored form of an instant. Fixed width and always `+00:00`, so the lexicographic
    comparisons in the occupancy queries are chronological."""
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def from_utc_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def local_iso(utc_dt: datetime, tz) -> str:
    """RFC 3339 rendered in the restaurant's zone with its explicit offset."""
    return utc_dt.astimezone(tz).replace(microsecond=0).isoformat()


def local_label(utc_dt: datetime, tz) -> str:
    return utc_dt.astimezone(tz).strftime("%Y-%m-%dT%H:%M")


def parse_rfc3339(ts_str) -> datetime:
    if not isinstance(ts_str, str) or not ts_str.strip():
        raise APIError(422, "validation_failed", "Timestamp is missing or invalid")
    cleaned = ts_str.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        raise APIError(422, "validation_failed", f"Invalid RFC3339 timestamp: {ts_str}")
    if dt.tzinfo is None:
        raise APIError(422, "validation_failed", f"Timestamp needs an explicit offset: {ts_str}")
    return dt


def format_rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def parse_local(value):
    if not isinstance(value, str):
        raise APIError(400, "malformed_request", "starts_at_local must be a string")
    if not LOCAL_MINUTE.match(value):
        raise APIError(422, "validation_failed",
                       f"starts_at_local must be a bare local YYYY-MM-DDTHH:MM: {value}")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except ValueError:
        raise APIError(422, "validation_failed", f"starts_at_local is not a real date and time: {value}")


def resolve_local(naive: datetime, tz) -> datetime:
    """Wall clock to instant. fold=0, so a repeated hour resolves to its first
    occurrence; a skipped hour does not survive the round trip and is rejected."""
    utc_dt = naive.replace(tzinfo=tz).astimezone(timezone.utc)
    if utc_dt.astimezone(tz).replace(tzinfo=None) != naive:
        raise APIError(422, "invalid_local_time",
                       f"{naive:%Y-%m-%dT%H:%M} does not exist in this timezone")
    return utc_dt


def _minutes(hhmm) -> int:
    hours, _, rest = str(hhmm).partition(":")
    return int(hours) * 60 + int(rest or 0)


def opening_windows(conn, restaurant_id: str, weekday: int):
    rows = conn.execute(
        "SELECT opens, closes FROM opening_hours WHERE restaurant_id = ? AND weekday = ? ORDER BY opens",
        (restaurant_id, weekday)
    ).fetchall()
    return [(_minutes(r["opens"]), _minutes(r["closes"])) for r in rows]


def check_slot(conn, restaurant_id: str, naive_local: datetime, duration_minutes: int,
               slot_minutes: int) -> None:
    windows = opening_windows(conn, restaurant_id, naive_local.weekday())
    start = naive_local.hour * 60 + naive_local.minute
    containing = [w for w in windows if w[0] <= start < w[1]]
    if not containing:
        raise APIError(422, "outside_opening_hours", "Restaurant is closed at that local time")
    if all((start - w[0]) % slot_minutes for w in containing):
        raise APIError(422, "not_on_slot_grid",
                       f"Bookings start every {slot_minutes} minutes from opening time")
    if not any(w[0] <= start and start + duration_minutes <= w[1] for w in windows):
        raise APIError(422, "outside_opening_hours", "The reservation would end after closing")


def resolve_reservation_slot(conn, restaurant, starts_at_local):
    """`(starts_at_utc, ends_at_utc, tz)` for a restaurant row and a local label.
    The duration is the restaurant's own absolute-time policy, never wall clock."""
    naive = parse_local(starts_at_local)
    tz = zone_for(restaurant["timezone"])
    duration = int(restaurant["reservation_duration_minutes"])
    starts_utc = resolve_local(naive, tz)
    check_slot(conn, restaurant["id"], naive, duration, int(restaurant["slot_minutes"]))
    return starts_utc, starts_utc + timedelta(minutes=duration), tz
