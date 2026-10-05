import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request

from app.db import get_connection
from app.errors import APIError
from app.timeutil import local_iso, resolve_local, utc_iso, zone_for

router = APIRouter(tags=["availability"])

DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
# §5: a query integer is plain ASCII decimal digits -- `4.0`, `+4`, ` 4`, `1e9`
# and `true` are all rejected however they would parse as a number.
PARTY_SIZE_RE = re.compile(r"^[0-9]+$")


def _minutes(hhmm: str) -> int:
    hours, _, rest = str(hhmm).partition(":")
    return int(hours) * 60 + int(rest)


@router.get("/availability")
def get_availability(request: Request):
    params = request.query_params
    restaurant_id = params.get("restaurant_id")
    date = params.get("date")
    party_raw = params.get("party_size")

    if restaurant_id is None or date is None or party_raw is None:
        raise APIError(
            422,
            "validation_failed",
            "restaurant_id, date and party_size are all required",
        )

    if not PARTY_SIZE_RE.match(party_raw):
        raise APIError(
            422,
            "validation_failed",
            f"party_size must be a plain decimal integer: {party_raw}",
        )

    party_size = int(party_raw)

    if party_size < 1:
        raise APIError(422, "validation_failed", "party_size must be at least 1")

    if not DATE_RE.match(date):
        raise APIError(
            422,
            "validation_failed",
            f"date must be YYYY-MM-DD: {date}",
        )

    try:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise APIError(
            422,
            "validation_failed",
            f"date is not a real calendar date: {date}",
        )

    with get_connection() as conn:
        restaurant = conn.execute(
            """
            SELECT id, timezone, slot_minutes, reservation_duration_minutes
            FROM restaurants
            WHERE id = ?
            """,
            (restaurant_id,),
        ).fetchone()

        if not restaurant:
            raise APIError(
                404,
                "not_found",
                f"Restaurant not found: {restaurant_id}",
            )

        tz = zone_for(restaurant["timezone"])
        slot_minutes = int(restaurant["slot_minutes"])
        duration = int(restaurant["reservation_duration_minutes"])

        tables = conn.execute(
            """
            SELECT id, max_seats
            FROM tables
            WHERE restaurant_id = ?
            ORDER BY position, rowid
            """,
            (restaurant_id,),
        ).fetchall()

        largest = max((int(t["max_seats"]) for t in tables), default=0)

        if party_size > largest:
            raise APIError(
                422,
                "validation_failed",
                f"Party size {party_size} exceeds the largest table ({largest})",
            )

        candidate_ids = [t["id"] for t in tables if int(t["max_seats"]) >= party_size]

        windows = conn.execute(
            """
            SELECT opens, closes
            FROM opening_hours
            WHERE restaurant_id = ? AND weekday = ?
            ORDER BY opens
            """,
            (restaurant_id, target_date.weekday()),
        ).fetchall()

        if not windows:
            return {
                "restaurant_id": restaurant_id,
                "date": date,
                "timezone": restaurant["timezone"],
                "slots": [],
            }

        # Confirmed bookings that could reach into this local day. The buffer
        # keeps zone skew and neighbouring-day bookings inside the window.
        day_start_local = datetime.combine(target_date, datetime.min.time(), tzinfo=tz)
        day_end_local = day_start_local + timedelta(days=1)
        bookings = []
        for b in conn.execute(
            """
            SELECT table_id, starts_at, ends_at
            FROM reservations
            WHERE restaurant_id = ?
              AND status = 'confirmed'
              AND starts_at < ?
              AND ends_at > ?
            """,
            (
                restaurant_id,
                utc_iso(day_end_local + timedelta(days=1)),
                utc_iso(day_start_local - timedelta(days=1)),
            ),
        ).fetchall():
            bookings.append(
                (
                    b["table_id"],
                    datetime.fromisoformat(b["starts_at"]).astimezone(timezone.utc),
                    datetime.fromisoformat(b["ends_at"]).astimezone(timezone.utc),
                )
            )

        duration_td = timedelta(minutes=duration)
        slots = []

        for window in windows:
            opens = _minutes(window["opens"])
            closes = _minutes(window["closes"])
            midnight = datetime.combine(target_date, datetime.min.time())

            t = opens
            while t + duration <= closes:
                naive = midnight + timedelta(minutes=t)

                # A wall-clock time skipped by a spring-forward transition is
                # not a slot; a repeated one appears once, at its first
                # occurrence, because the labels themselves are unique.
                try:
                    starts_utc = resolve_local(naive, tz)
                except APIError as exc:
                    if exc.code != "invalid_local_time":
                        raise
                    t += slot_minutes
                    continue

                ends_utc = starts_utc + duration_td

                available = []
                for table_id in candidate_ids:
                    booked = any(
                        table_id == b_table and b_start < ends_utc and starts_utc < b_end
                        for b_table, b_start, b_end in bookings
                    )
                    if not booked:
                        available.append(table_id)

                slots.append(
                    {
                        "starts_at_local": naive.strftime("%Y-%m-%dT%H:%M"),
                        "starts_at": local_iso(starts_utc, tz),
                        "available_table_ids": available,
                    }
                )

                t += slot_minutes

        return {
            "restaurant_id": restaurant_id,
            "date": date,
            "timezone": restaurant["timezone"],
            "slots": slots,
        }
