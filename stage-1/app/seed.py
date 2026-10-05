from app.auth import hash_password
from app.errors import APIError
from app.reservations import generate_reference
from app.timeutil import parse_rfc3339, resolve_local, utc_iso

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import re


WEEKDAY_INDEX = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# §4/§8: a seeded reference is a create-style reference.
REFERENCE_RE = re.compile(r"^[A-Z0-9]{6,12}$")


# ---------------------------------------------------------------------------
# DATABASE RESET / DEFAULT SEED
# ---------------------------------------------------------------------------

def clear_database(conn) -> None:
    conn.execute("DELETE FROM idempotency_receipts;")
    conn.execute("DELETE FROM reservations;")
    conn.execute("DELETE FROM auth_tokens;")
    conn.execute("DELETE FROM users;")
    conn.execute("DELETE FROM opening_hours;")
    conn.execute("DELETE FROM tables;")
    conn.execute("DELETE FROM restaurants;")


def seed_database(conn) -> None:
    """
    Load the application's normal/default seed data.
    """

    clear_database(conn)

    # ------------------------------------------------------------------
    # 1. Berlin
    # ------------------------------------------------------------------

    conn.execute(
        """
        INSERT INTO restaurants
            (id, name, city, timezone)
        VALUES (?, ?, ?, ?)
        """,
        (
            "r-berlin",
            "Speisekammer Mitte",
            "Berlin",
            "Europe/Berlin",
        ),
    )

    for position, (t_name, max_seats) in enumerate([
        ("A", 2),
        ("B", 2),
        ("C", 4),
        ("D", 6),
    ]):
        t_id = f"t-berlin-{t_name.lower()}"

        conn.execute(
            """
            INSERT INTO tables
                (id, restaurant_id, name, max_seats, position)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                t_id,
                "r-berlin",
                t_name,
                max_seats,
                position,
            ),
        )

    for wd in range(7):
        conn.execute(
            """
            INSERT INTO opening_hours
                (restaurant_id, weekday, opens, closes)
            VALUES (?, ?, ?, ?)
            """,
            (
                "r-berlin",
                wd,
                "11:00",
                "14:30",
            ),
        )

        conn.execute(
            """
            INSERT INTO opening_hours
                (restaurant_id, weekday, opens, closes)
            VALUES (?, ?, ?, ?)
            """,
            (
                "r-berlin",
                wd,
                "18:00",
                "23:00",
            ),
        )

    # ------------------------------------------------------------------
    # 2. Kolkata
    # ------------------------------------------------------------------

    conn.execute(
        """
        INSERT INTO restaurants
            (id, name, city, timezone)
        VALUES (?, ?, ?, ?)
        """,
        (
            "r-kolkata",
            "Howrah Bistro",
            "Kolkata",
            "Asia/Kolkata",
        ),
    )

    for position, (t_name, max_seats) in enumerate([
        ("A", 4),
        ("B", 4),
        ("C", 8),
    ]):
        t_id = f"t-kolkata-{t_name.lower()}"

        conn.execute(
            """
            INSERT INTO tables
                (id, restaurant_id, name, max_seats, position)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                t_id,
                "r-kolkata",
                t_name,
                max_seats,
                position,
            ),
        )

    for wd in range(7):
        conn.execute(
            """
            INSERT INTO opening_hours
                (restaurant_id, weekday, opens, closes)
            VALUES (?, ?, ?, ?)
            """,
            (
                "r-kolkata",
                wd,
                "12:00",
                "22:30",
            ),
        )

    # ------------------------------------------------------------------
    # 3. Denver
    # ------------------------------------------------------------------

    conn.execute(
        """
        INSERT INTO restaurants
            (id, name, city, timezone)
        VALUES (?, ?, ?, ?)
        """,
        (
            "r-denver",
            "Mile High Kitchen",
            "Denver",
            "America/Denver",
        ),
    )

    for position, (t_name, max_seats) in enumerate([
        ("A", 2),
        ("B", 4),
        ("C", 4),
        ("D", 8),
    ]):
        t_id = f"t-denver-{t_name.lower()}"

        conn.execute(
            """
            INSERT INTO tables
                (id, restaurant_id, name, max_seats, position)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                t_id,
                "r-denver",
                t_name,
                max_seats,
                position,
            ),
        )

    for wd in range(7):
        conn.execute(
            """
            INSERT INTO opening_hours
                (restaurant_id, weekday, opens, closes)
            VALUES (?, ?, ?, ?)
            """,
            (
                "r-denver",
                wd,
                "08:00",
                "22:00",
            ),
        )

    # ------------------------------------------------------------------
    # 4. Default test user
    # ------------------------------------------------------------------

    conn.execute(
        """
        INSERT INTO users
            (user_id, email, password_hash, name, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "usr-ada",
            "ada@example.com",
            hash_password("correct horse"),
            "Ada Lovelace",
            datetime.now(timezone.utc).isoformat(),
        ),
    )

    conn.commit()


# ---------------------------------------------------------------------------
# FIXTURE VALIDATION HELPERS
# ---------------------------------------------------------------------------

def weekday_index(value) -> int:
    """
    Convert an exact 3-letter weekday name to SQLite's weekday index.

    The official fixture contract uses:
        mon tue wed thu fri sat sun
    """

    if not isinstance(value, str):
        raise APIError(
            422,
            "validation_failed",
            "weekday must be a 3-letter weekday name",
        )

    if value not in WEEKDAY_INDEX:
        raise APIError(
            422,
            "validation_failed",
            "weekday must be one of mon, tue, wed, thu, fri, sat, sun",
        )

    return WEEKDAY_INDEX[value]


def validate_id(value, field_name: str) -> None:
    """
    Fixture IDs are opaque strings with a maximum length of 64.
    """

    if isinstance(value, bool) or not isinstance(value, str):
        raise APIError(
            422,
            "validation_failed",
            f"{field_name} must be a string",
        )

    if len(value) > 64:
        raise APIError(
            422,
            "validation_failed",
            f"{field_name} must be at most 64 characters",
        )


def validate_string(value, field_name: str) -> None:
    if not isinstance(value, str):
        raise APIError(
            422,
            "validation_failed",
            f"{field_name} must be a string",
        )


def validate_integer(
    value,
    field_name: str,
    minimum=None,
) -> None:
    """
    Strict integer validation.

    Important:
    bool, float and numeric strings must NOT be accepted as integers.
    """

    if isinstance(value, bool) or not isinstance(value, int):
        raise APIError(
            422,
            "validation_failed",
            f"{field_name} must be an integer",
        )

    if minimum is not None and value < minimum:
        raise APIError(
            422,
            "validation_failed",
            f"{field_name} must be >= {minimum}",
        )


def validate_time(value, field_name: str) -> None:
    """
    Validate local opening-hours times as exact HH:MM.
    """

    if not isinstance(value, str):
        raise APIError(
            422,
            "validation_failed",
            f"{field_name} must be HH:MM",
        )

    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError:
        raise APIError(
            422,
            "validation_failed",
            f"{field_name} must be HH:MM",
        )

    if parsed.strftime("%H:%M") != value:
        raise APIError(
            422,
            "validation_failed",
            f"{field_name} must be HH:MM",
        )


def validate_timezone(value) -> None:
    if not isinstance(value, str):
        raise APIError(
            422,
            "validation_failed",
            "timezone must be a string",
        )

    try:
        ZoneInfo(value)
    except Exception:
        raise APIError(
            422,
            "validation_failed",
            f"invalid timezone: {value}",
        )


def validate_email(value, field_name: str) -> None:
    if not isinstance(value, str) or not EMAIL_RE.fullmatch(value):
        raise APIError(
            422,
            "validation_failed",
            f"{field_name} must be a valid email address",
        )


# ---------------------------------------------------------------------------
# FIXTURE TIMESTAMP
# ---------------------------------------------------------------------------

def fixture_start_utc(
    seeded: dict,
    tz_name: str,
) -> datetime:
    """
    Convert a seeded reservation timestamp to UTC.

    starts_at_local:
      - naive local timestamp is interpreted in restaurant timezone
      - timezone-aware timestamp is converted to UTC

    starts_at:
      - parsed as RFC3339 and converted to UTC
    """

    local = seeded.get("starts_at_local")

    if local:
        if not isinstance(local, str):
            raise APIError(
                422,
                "validation_failed",
                "starts_at_local must be a string",
            )

        try:
            naive = datetime.fromisoformat(local)
        except (TypeError, ValueError):
            raise APIError(
                422,
                "validation_failed",
                "invalid starts_at_local",
            )

        if naive.tzinfo is not None:
            return naive.astimezone(timezone.utc)

        try:
            return resolve_local(naive, ZoneInfo(tz_name))
        except APIError:
            raise
        except Exception:
            raise APIError(
                422,
                "validation_failed",
                "invalid reservation timezone",
            )

    if seeded.get("starts_at"):
        if not isinstance(seeded["starts_at"], str):
            raise APIError(
                422,
                "validation_failed",
                "starts_at must be a string",
            )

        try:
            return parse_rfc3339(
                seeded["starts_at"]
            ).astimezone(timezone.utc)
        except Exception:
            raise APIError(
                422,
                "validation_failed",
                "invalid starts_at",
            )

    raise APIError(
        422,
        "validation_failed",
        "seeded reservation requires starts_at_local or starts_at",
    )


# ---------------------------------------------------------------------------
# COMPLETE FIXTURE VALIDATION
# ---------------------------------------------------------------------------

def validate_fixture(fixture: dict) -> None:
    """
    Validate the complete /_test/reset fixture before touching the DB.

    This is deliberately performed before clear_database() so an invalid
    fixture cannot destroy the current database state.
    """

    if not isinstance(fixture, dict):
        raise APIError(
            422,
            "validation_failed",
            "fixture must be an object",
        )

    users = fixture.get("users", [])
    restaurants = fixture.get("restaurants", [])
    reservations = fixture.get("reservations", [])

    if not isinstance(users, list):
        raise APIError(
            422,
            "validation_failed",
            "users must be a list",
        )

    if not isinstance(restaurants, list):
        raise APIError(
            422,
            "validation_failed",
            "restaurants must be a list",
        )

    if not isinstance(reservations, list):
        raise APIError(
            422,
            "validation_failed",
            "reservations must be a list",
        )

    # ================================================================
    # USERS
    # ================================================================

    user_ids = set()
    user_emails = set()

    for user in users:
        if not isinstance(user, dict):
            raise APIError(
                422,
                "validation_failed",
                "each user must be an object",
            )

        for field in (
            "id",
            "email",
            "password",
        ):
            if field not in user:
                raise APIError(
                    422,
                    "validation_failed",
                    f"user.{field} is required",
                )

        validate_id(
            user["id"],
            "user.id",
        )

        if user["id"] in user_ids:
            raise APIError(
                422,
                "validation_failed",
                f"duplicate user id: {user['id']}",
            )

        user_ids.add(user["id"])

        validate_email(
            user["email"],
            "user.email",
        )

        email = user["email"].lower()

        if email in user_emails:
            raise APIError(
                422,
                "validation_failed",
                f"duplicate user email: {user['email']}",
            )

        user_emails.add(email)

        validate_string(
            user["password"],
            "user.password",
        )

        if len(user["password"]) < 8:
            raise APIError(
                422,
                "validation_failed",
                "user.password must be at least 8 characters",
            )

        if "display_name" in user:
            validate_string(
                user["display_name"],
                "user.display_name",
            )

        if "name" in user:
            validate_string(
                user["name"],
                "user.name",
            )

    # ================================================================
    # RESTAURANTS
    # ================================================================

    restaurant_ids = set()

    # Table ids are unique per restaurant, not globally: one fixture may give
    # several restaurants the same ids ("t_1", "t_2", ...).
    restaurant_tables = {}

    # Used later to validate seeded reservations.
    restaurant_timezone = {}

    for restaurant in restaurants:
        if not isinstance(restaurant, dict):
            raise APIError(
                422,
                "validation_failed",
                "each restaurant must be an object",
            )

        for field in (
            "id",
            "name",
            "timezone",
        ):
            if field not in restaurant:
                raise APIError(
                    422,
                    "validation_failed",
                    f"restaurant.{field} is required",
                )

        validate_id(
            restaurant["id"],
            "restaurant.id",
        )

        if restaurant["id"] in restaurant_ids:
            raise APIError(
                422,
                "validation_failed",
                f"duplicate restaurant id: {restaurant['id']}",
            )

        restaurant_ids.add(
            restaurant["id"]
        )

        validate_string(
            restaurant["name"],
            "restaurant.name",
        )

        validate_timezone(
            restaurant["timezone"]
        )

        restaurant_timezone[
            restaurant["id"]
        ] = restaurant["timezone"]

        if "city" in restaurant:
            validate_string(
                restaurant["city"],
                "restaurant.city",
            )

        # ------------------------------------------------------------
        # Restaurant configuration
        # ------------------------------------------------------------

        slot_minutes = restaurant.get(
            "slot_minutes",
            30,
        )

        reservation_duration_minutes = restaurant.get(
            "reservation_duration_minutes",
            90,
        )

        cancellation_cutoff_minutes = restaurant.get(
            "cancellation_cutoff_minutes",
            0,
        )

        validate_integer(
            slot_minutes,
            "slot_minutes",
            1,
        )

        validate_integer(
            reservation_duration_minutes,
            "reservation_duration_minutes",
            0,
        )

        validate_integer(
            cancellation_cutoff_minutes,
            "cancellation_cutoff_minutes",
            0,
        )

        # ------------------------------------------------------------
        # Opening hours
        # ------------------------------------------------------------

        opening_hours = restaurant.get(
            "opening_hours",
            [],
        )

        if not isinstance(opening_hours, list):
            raise APIError(
                422,
                "validation_failed",
                "opening_hours must be a list",
            )

        for window in opening_hours:
            if not isinstance(window, dict):
                raise APIError(
                    422,
                    "validation_failed",
                    "opening hour must be an object",
                )

            for field in (
                "weekday",
                "opens",
                "closes",
            ):
                if field not in window:
                    raise APIError(
                        422,
                        "validation_failed",
                        f"opening hour {field} is required",
                    )

            weekday_index(
                window["weekday"]
            )

            validate_time(
                window["opens"],
                "opens",
            )

            validate_time(
                window["closes"],
                "closes",
            )

            if window["opens"] >= window["closes"]:
                raise APIError(
                    422,
                    "validation_failed",
                    "opening hour opens must be before closes",
                )

        # ------------------------------------------------------------
        # Tables
        # ------------------------------------------------------------

        tables = restaurant.get(
            "tables",
            [],
        )

        if not isinstance(tables, list):
            raise APIError(
                422,
                "validation_failed",
                "tables must be a list",
            )

        for table in tables:
            if not isinstance(table, dict):
                raise APIError(
                    422,
                    "validation_failed",
                    "table must be an object",
                )

            for field in (
                "id",
                "label",
                "capacity",
            ):
                if field not in table:
                    raise APIError(
                        422,
                        "validation_failed",
                        f"table.{field} is required",
                    )

            validate_id(
                table["id"],
                "table.id",
            )

            if table["id"] in restaurant_tables.setdefault(
                restaurant["id"],
                set(),
            ):
                raise APIError(
                    422,
                    "validation_failed",
                    f"duplicate table id in restaurant "
                    f"{restaurant['id']}: {table['id']}",
                )

            restaurant_tables[
                restaurant["id"]
            ].add(
                table["id"]
            )

            validate_string(
                table["label"],
                "table.label",
            )

            validate_integer(
                table["capacity"],
                "table.capacity",
                1,
            )

    # ================================================================
    # SEEDED RESERVATIONS
    # ================================================================

    reservation_ids = set()
    reservation_references = set()

    for reservation in reservations:
        if not isinstance(reservation, dict):
            raise APIError(
                422,
                "validation_failed",
                "each reservation must be an object",
            )

        for field in (
            "restaurant_id",
            "user_id",
            "table_id",
            "party_size",
        ):
            if field not in reservation:
                raise APIError(
                    422,
                    "validation_failed",
                    f"reservation.{field} is required",
                )

        # ------------------------------------------------------------
        # Reservation ID
        # ------------------------------------------------------------

        if "id" in reservation:
            validate_id(
                reservation["id"],
                "reservation.id",
            )

            if reservation["id"] in reservation_ids:
                raise APIError(
                    422,
                    "validation_failed",
                    f"duplicate reservation id: {reservation['id']}",
                )

            reservation_ids.add(
                reservation["id"]
            )

        # ------------------------------------------------------------
        # Reservation reference
        # ------------------------------------------------------------

        if "reference" in reservation:
            validate_id(
                reservation["reference"],
                "reservation.reference",
            )

            if not REFERENCE_RE.match(
                reservation["reference"]
            ):
                raise APIError(
                    422,
                    "validation_failed",
                    "reservation.reference must match "
                    "^[A-Z0-9]{6,12}$",
                )

            if (
                reservation["reference"]
                in reservation_references
            ):
                raise APIError(
                    422,
                    "validation_failed",
                    f"duplicate reservation reference: "
                    f"{reservation['reference']}",
                )

            reservation_references.add(
                reservation["reference"]
            )

        # ------------------------------------------------------------
        # Foreign keys
        # ------------------------------------------------------------

        validate_id(
            reservation["restaurant_id"],
            "reservation.restaurant_id",
        )

        validate_id(
            reservation["user_id"],
            "reservation.user_id",
        )

        validate_id(
            reservation["table_id"],
            "reservation.table_id",
        )

        if reservation["restaurant_id"] not in restaurant_ids:
            raise APIError(
                422,
                "validation_failed",
                "reservation references unknown restaurant",
            )

        if reservation["user_id"] not in user_ids:
            raise APIError(
                422,
                "validation_failed",
                "reservation references unknown user",
            )

        if (
            reservation["table_id"]
            not in restaurant_tables.get(
                reservation["restaurant_id"],
                set(),
            )
        ):
            raise APIError(
                422,
                "validation_failed",
                "reservation references unknown table",
            )

        # ------------------------------------------------------------
        # Party size
        # ------------------------------------------------------------

        validate_integer(
            reservation["party_size"],
            "reservation.party_size",
            1,
        )

        # ------------------------------------------------------------
        # Duration
        # ------------------------------------------------------------

        if "duration_minutes" in reservation:
            validate_integer(
                reservation["duration_minutes"],
                "reservation.duration_minutes",
                0,
            )

        # ------------------------------------------------------------
        # Status
        # ------------------------------------------------------------

        if "status" in reservation:
            validate_string(
                reservation["status"],
                "reservation.status",
            )

        # ------------------------------------------------------------
        # Timestamp
        # ------------------------------------------------------------

        if (
            "starts_at_local" not in reservation
            and "starts_at" not in reservation
        ):
            raise APIError(
                422,
                "validation_failed",
                "seeded reservation requires "
                "starts_at_local or starts_at",
            )

        fixture_start_utc(
            reservation,
            restaurant_timezone[
                reservation["restaurant_id"]
            ],
        )


# ---------------------------------------------------------------------------
# FIXTURE LOADER
# ---------------------------------------------------------------------------

def load_fixture(
    conn,
    fixture: dict,
) -> None:
    """
    Replace all state with a harness-supplied fixture.

    IMPORTANT:
    Validation happens BEFORE clear_database().
    Therefore an invalid fixture cannot destroy the current state.
    The caller owns the transaction/commit.
    """

    validate_fixture(fixture)

    clear_database(conn)

    now_str = datetime.now(
        timezone.utc
    ).isoformat()

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    for user in fixture.get(
        "users",
        [],
    ):
        email = user["email"].lower()

        conn.execute(
            """
            INSERT INTO users
                (
                    user_id,
                    email,
                    password_hash,
                    name,
                    created_at
                )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                email,
                hash_password(
                    user["password"]
                ),
                user.get("display_name")
                or user.get("name")
                or email,
                now_str,
            ),
        )

    # ------------------------------------------------------------------
    # Restaurants
    # ------------------------------------------------------------------

    timezones = {}
    durations = {}

    for restaurant in fixture.get(
        "restaurants",
        [],
    ):
        rid = restaurant["id"]

        timezones[rid] = restaurant["timezone"]

        durations[rid] = restaurant.get(
            "reservation_duration_minutes",
            90,
        )

        slot_minutes = restaurant.get(
            "slot_minutes",
            30,
        )

        reservation_duration_minutes = restaurant.get(
            "reservation_duration_minutes",
            90,
        )

        cancellation_cutoff_minutes = restaurant.get(
            "cancellation_cutoff_minutes",
            0,
        )

        conn.execute(
            """
            INSERT INTO restaurants (
                id,
                name,
                city,
                timezone,
                slot_minutes,
                reservation_duration_minutes,
                cancellation_cutoff_minutes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                restaurant["name"],
                restaurant.get("city", ""),
                restaurant["timezone"],
                slot_minutes,
                reservation_duration_minutes,
                cancellation_cutoff_minutes,
            ),
        )

        # Preserve fixture table order.
        for position, table in enumerate(
            restaurant.get("tables", [])
        ):
            conn.execute(
                """
                INSERT INTO tables
                    (
                        id,
                        restaurant_id,
                        name,
                        max_seats,
                        position
                    )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    table["id"],
                    rid,
                    table["label"],
                    table["capacity"],
                    position,
                ),
            )

        for window in restaurant.get(
            "opening_hours",
            [],
        ):
            conn.execute(
                """
                INSERT INTO opening_hours
                    (
                        restaurant_id,
                        weekday,
                        opens,
                        closes
                    )
                VALUES (?, ?, ?, ?)
                """,
                (
                    rid,
                    weekday_index(
                        window["weekday"]
                    ),
                    window["opens"],
                    window["closes"],
                ),
            )

    # ------------------------------------------------------------------
    # Seeded reservations
    # ------------------------------------------------------------------

    for seeded in fixture.get(
        "reservations",
        [],
    ):
        rid = seeded["restaurant_id"]

        starts_at = fixture_start_utc(
            seeded,
            timezones.get(
                rid,
                "UTC",
            ),
        )

        duration = seeded.get(
            "duration_minutes"
        )

        if duration is None:
            duration = durations.get(
                rid,
                90,
            )

        reference = seeded.get(
            "reference"
        )

        if not reference:
            reference = generate_reference(
                conn
            )

        reservation_id = seeded.get("id")

        conn.execute(
            """
            INSERT INTO reservations (
                reference,
                reservation_id,
                restaurant_id,
                user_id,
                table_id,
                starts_at,
                ends_at,
                party_size,
                duration_minutes,
                status,
                created_at,
                cancelled_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reference,
                reservation_id,
                rid,
                seeded["user_id"],
                seeded["table_id"],
                utc_iso(starts_at),
                utc_iso(
                    starts_at
                    + timedelta(
                        minutes=duration
                    )
                ),
                seeded["party_size"],
                duration,
                seeded.get(
                    "status"
                ) or "confirmed",
                seeded.get(
                    "created_at"
                ) or utc_iso(
                    datetime.now(timezone.utc)
                ),
                seeded.get(
                    "cancelled_at"
                ),
            ),
        )