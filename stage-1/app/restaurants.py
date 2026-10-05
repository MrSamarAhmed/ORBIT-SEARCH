from fastapi import APIRouter

from app.db import get_connection
from app.errors import APIError

router = APIRouter(tags=["restaurants"])

WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@router.get("/restaurants")
def get_restaurants():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, timezone FROM restaurants ORDER BY rowid"
        ).fetchall()
        return {"restaurants": [dict(r) for r in rows]}


@router.get("/restaurants/{restaurant_id}")
def get_restaurant_detail(restaurant_id: str):
    with get_connection() as conn:
        r = conn.execute(
            """
            SELECT id, name, timezone,
                   slot_minutes, reservation_duration_minutes,
                   cancellation_cutoff_minutes
            FROM restaurants
            WHERE id = ?
            """,
            (restaurant_id,),
        ).fetchone()
        if not r:
            raise APIError(404, "not_found", f"Restaurant not found: {restaurant_id}")

        # The fixture's own shape: tables as {id,label,capacity} in fixture
        # order, opening hours as one flat entry per window.
        tables = [
            {"id": t["id"], "label": t["name"], "capacity": t["max_seats"]}
            for t in conn.execute(
                """SELECT id, name, max_seats FROM tables
                   WHERE restaurant_id = ? ORDER BY position, rowid""",
                (restaurant_id,),
            ).fetchall()
        ]

        opening_hours = [
            {
                "weekday": WEEKDAY_NAMES[oh["weekday"]],
                "opens": oh["opens"],
                "closes": oh["closes"],
            }
            for oh in conn.execute(
                """SELECT weekday, opens, closes FROM opening_hours
                   WHERE restaurant_id = ? ORDER BY rowid""",
                (restaurant_id,),
            ).fetchall()
        ]

        result = dict(r)
        result["tables"] = tables
        result["opening_hours"] = opening_hours
        return result
