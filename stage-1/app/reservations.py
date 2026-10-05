import json
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Header, Request, Response

from app.auth import get_current_user_id
from app.db import get_connection, transaction
from app.errors import APIError, json_object_body
from app.idempotency import (
    check_idempotency,
    require_idempotency_key,
    store_idempotency_receipt,
)
from app.timeutil import (
    from_utc_iso,
    local_iso,
    local_label,
    resolve_reservation_slot,
    utc_iso,
    zone_for,
)

router = APIRouter(tags=["reservations"])

CREATE_SCOPE = "POST /reservations"
MOVES_SCOPE = "POST /reservation-moves"

# §8: `reference` is 6..12 characters of A-Z0-9, unique across every reservation.
REFERENCE_ALPHABET = string.ascii_uppercase + string.digits
REFERENCE_LENGTH = 8

RESERVATION_SELECT = """
    SELECT r.reference, r.reservation_id, r.restaurant_id, r.table_id, r.starts_at,
           r.ends_at, r.party_size, r.status, r.created_at, r.user_id,
           rest.timezone AS timezone,
           rest.cancellation_cutoff_minutes AS cutoff_minutes
    FROM reservations r JOIN restaurants rest ON rest.id = r.restaurant_id
"""


def generate_reference(conn) -> str:
    for _ in range(64):
        candidate = "".join(
            secrets.choice(REFERENCE_ALPHABET) for _ in range(REFERENCE_LENGTH)
        )
        if not conn.execute(
            "SELECT 1 FROM reservations WHERE reference = ?", (candidate,)
        ).fetchone():
            return candidate
    raise APIError(500, "internal", "Could not generate a unique reservation reference")


def generate_reservation_id(conn) -> str:
    for _ in range(64):
        candidate = f"res_{uuid.uuid4().hex}"
        if not conn.execute(
            "SELECT 1 FROM reservations WHERE reservation_id = ?", (candidate,)
        ).fetchone():
            return candidate
    raise APIError(500, "internal", "Could not generate a unique reservation id")


def load_restaurant(conn, restaurant_id: str):
    row = conn.execute(
        "SELECT * FROM restaurants WHERE id = ?", (restaurant_id,)
    ).fetchone()
    if not row:
        raise APIError(404, "not_found", f"No such restaurant: {restaurant_id}")
    return row


def load_table(conn, restaurant_id: str, table_id: str):
    """A table only exists for this endpoint if it belongs to this restaurant."""
    row = conn.execute(
        "SELECT id, max_seats FROM tables WHERE id = ? AND restaurant_id = ?",
        (table_id, restaurant_id),
    ).fetchone()
    if not row:
        raise APIError(404, "not_found", f"No such table: {table_id}")
    return row


def require_string(body: dict, field: str) -> str:
    if field not in body or body[field] is None or body[field] == "":
        raise APIError(422, "validation_failed", f"{field} is required")
    if not isinstance(body[field], str):
        raise APIError(400, "malformed_request", f"{field} must be a string")
    return body[field]


def optional_string(body: dict, field: str, default: str) -> str:
    if field not in body:
        return default
    return require_string(body, field)


def validate_party_size(value) -> int:
    # §5 names booleans and strings explicitly: both are 422, never a 500.
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise APIError(422, "validation_failed", "party_size must be a positive integer")
    return value


def optional_party_size(body: dict, default: int) -> int:
    if "party_size" not in body:
        return default
    return validate_party_size(body["party_size"])


def overlaps(conn, restaurant_id: str, table_id: str, starts_at: datetime,
             ends_at: datetime, exclude: Optional[list] = None) -> bool:
    """Half-open interval overlap `[starts_at, ends_at)` against confirmed bookings.

    Both sides are stored as fixed-width `+00:00` strings, so the comparison is
    chronological rather than merely lexicographic.
    """
    query = """
        SELECT 1 FROM reservations
        WHERE restaurant_id = ? AND table_id = ? AND status = 'confirmed'
          AND starts_at < ? AND ends_at > ?
    """
    params = [restaurant_id, table_id, utc_iso(ends_at), utc_iso(starts_at)]
    if exclude:
        query += f" AND reference NOT IN ({','.join('?' * len(exclude))})"
        params.extend(exclude)
    return conn.execute(query, params).fetchone() is not None


def reservation_payload(row) -> dict:
    """The one shape every reservation endpoint returns (§8).

    `starts_at_local` is rendered back from the stored instant rather than kept in
    its own column: a skipped local time can never be stored, and a repeated one is
    always resolved to its first occurrence, so the round trip is lossless.
    """
    tz = zone_for(row["timezone"])
    starts_at = from_utc_iso(row["starts_at"])
    return {
        "reservation_id": row["reservation_id"],
        "reference": row["reference"],
        "restaurant_id": row["restaurant_id"],
        "table_id": row["table_id"],
        "party_size": row["party_size"],
        "status": row["status"],
        "starts_at_local": local_label(starts_at, tz),
        "starts_at": local_iso(starts_at, tz),
        "ends_at": local_iso(from_utc_iso(row["ends_at"]), tz),
        "created_at": row["created_at"],
    }


def json_response(payload, status_code: int) -> Response:
    return Response(
        content=json.dumps(payload), status_code=status_code,
        media_type="application/json",
    )


def fetch_owned(conn, reference: str, user_id: str):
    """Someone else's booking is indistinguishable from one that never existed."""
    row = conn.execute(
        RESERVATION_SELECT + " WHERE r.reference = ?", (reference,)
    ).fetchone()
    if not row or row["user_id"] != user_id:
        raise APIError(404, "not_found", f"No such reservation: {reference}")
    return row


def enforce_cutoff(row) -> None:
    """§8: nothing may be cancelled or changed within the cutoff of its start, or later."""
    deadline = from_utc_iso(row["starts_at"]) - timedelta(minutes=int(row["cutoff_minutes"]))
    if datetime.now(timezone.utc) >= deadline:
        raise APIError(409, "cutoff_passed",
                       "This reservation is inside its cancellation cutoff")


def place(conn, restaurant_id: str, table_id: str, party_size: int,
          starts_at_local: str, exclude: Optional[list] = None):
    """Shared validation for create, amend and move. Returns the resolved instants."""
    restaurant = load_restaurant(conn, restaurant_id)
    table = load_table(conn, restaurant_id, table_id)
    starts_at, ends_at, _ = resolve_reservation_slot(conn, restaurant, starts_at_local)
    if int(table["max_seats"]) < party_size:
        raise APIError(422, "party_exceeds_capacity",
                       f"Table {table_id} seats {table['max_seats']}, party is {party_size}")
    if overlaps(conn, restaurant_id, table_id, starts_at, ends_at, exclude=exclude):
        raise APIError(409, "table_unavailable",
                       f"Table {table_id} is already booked over that interval")
    return restaurant, starts_at, ends_at


@router.post("/reservations")
async def create_reservation(
    request: Request,
    authorization: Optional[str] = Header(None),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    body = await json_object_body(request)
    user_id = get_current_user_id(authorization)
    key = require_idempotency_key(idempotency_key)

    with transaction() as conn:
        # §7: the key is resolved before field validation, so a replay of a request
        # that would now fail still returns its original response.
        replayed = check_idempotency(conn, CREATE_SCOPE, user_id, key, body)
        if replayed is not None:
            return replayed

        restaurant_id = require_string(body, "restaurant_id")
        table_id = require_string(body, "table_id")
        starts_at_local = require_string(body, "starts_at_local")
        party_size = validate_party_size(body.get("party_size"))

        restaurant, starts_at, ends_at = place(conn, restaurant_id, table_id, party_size,
                                               starts_at_local)

        reference = generate_reference(conn)
        reservation_id = generate_reservation_id(conn)
        conn.execute(
            """INSERT INTO reservations (reference, reservation_id, restaurant_id, user_id,
                                         table_id, starts_at, ends_at, party_size,
                                         duration_minutes, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?)""",
            (reference, reservation_id, restaurant_id, user_id, table_id,
             utc_iso(starts_at), utc_iso(ends_at), party_size,
             int(restaurant["reservation_duration_minutes"]),
             utc_iso(datetime.now(timezone.utc))),
        )

        payload = reservation_payload(fetch_owned(conn, reference, user_id))
        store_idempotency_receipt(conn, CREATE_SCOPE, user_id, key, body, 201, payload)
        return json_response(payload, 201)


@router.get("/reservations")
def list_reservations(authorization: Optional[str] = Header(None)):
    user_id = get_current_user_id(authorization)
    with get_connection() as conn:
        rows = conn.execute(
            RESERVATION_SELECT + " WHERE r.user_id = ? ORDER BY r.starts_at DESC, r.reference DESC",
            (user_id,),
        ).fetchall()
        return {"reservations": [reservation_payload(row) for row in rows]}


@router.get("/reservations/{reference}")
def get_reservation(reference: str, authorization: Optional[str] = Header(None)):
    user_id = get_current_user_id(authorization)
    with get_connection() as conn:
        return reservation_payload(fetch_owned(conn, reference, user_id))


@router.post("/reservations/{reference}/cancel")
async def cancel_reservation(reference: str, authorization: Optional[str] = Header(None)):
    user_id = get_current_user_id(authorization)
    with transaction() as conn:
        row = fetch_owned(conn, reference, user_id)
        if row["status"] != "cancelled":
            enforce_cutoff(row)
            conn.execute(
                "UPDATE reservations SET status = 'cancelled', cancelled_at = ? WHERE reference = ?",
                (utc_iso(datetime.now(timezone.utc)), reference),
            )
        return json_response(reservation_payload(fetch_owned(conn, reference, user_id)), 200)


@router.patch("/reservations/{reference}")
async def patch_reservation(
    reference: str,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    body = await json_object_body(request)
    user_id = get_current_user_id(authorization)

    with transaction() as conn:
        row = fetch_owned(conn, reference, user_id)
        if row["status"] == "cancelled":
            raise APIError(409, "reservation_cancelled",
                           f"Reservation {reference} is cancelled")
        enforce_cutoff(row)

        table_id = optional_string(body, "table_id", row["table_id"])
        party_size = optional_party_size(body, row["party_size"])
        if "starts_at_local" in body:
            starts_at_local = require_string(body, "starts_at_local")
        else:
            starts_at_local = local_label(from_utc_iso(row["starts_at"]),
                                          zone_for(row["timezone"]))

        restaurant, starts_at, ends_at = place(conn, row["restaurant_id"], table_id,
                                               party_size, starts_at_local,
                                               exclude=[reference])
        conn.execute(
            """UPDATE reservations
               SET table_id = ?, starts_at = ?, ends_at = ?, party_size = ?, duration_minutes = ?
               WHERE reference = ?""",
            (table_id, utc_iso(starts_at), utc_iso(ends_at), party_size,
             int(restaurant["reservation_duration_minutes"]), reference),
        )
        return json_response(reservation_payload(fetch_owned(conn, reference, user_id)), 200)
