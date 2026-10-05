import sqlite3
import os
from contextlib import contextmanager

DEFAULT_DB_PATH = os.environ.get("TABLEKEEPER_DB_PATH", "data/tablekeeper.db")

def get_db_path() -> str:
    return DEFAULT_DB_PATH

# `CREATE TABLE IF NOT EXISTS` leaves an already-created database without new
# columns, so a database file from an earlier boot would fail every reservation query.
ADDED_COLUMNS = {
    "restaurants": (
        ("slot_minutes", "INTEGER NOT NULL DEFAULT 30"),
        ("reservation_duration_minutes", "INTEGER NOT NULL DEFAULT 90"),
        ("cancellation_cutoff_minutes", "INTEGER NOT NULL DEFAULT 0"),
    ),
    "reservations": (
        ("reservation_id", "TEXT"),
    ),
    "tables": (
        ("position", "INTEGER NOT NULL DEFAULT 0"),
    ),
}

def add_missing_columns(conn) -> None:
    for table, columns in ADDED_COLUMNS.items():
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, declaration in columns:
            if name not in present:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")

TABLES_PK = "PRIMARY KEY (restaurant_id, id)"

def rebuild_legacy_tables(conn) -> None:
    """Upgrade a database whose `tables` rows were globally unique.

    Older boots created `tables` with `id TEXT PRIMARY KEY`, which cannot store
    the official fixture contract's repeated table ids across restaurants. The
    table (and `reservations`, whose foreign key pointed at the old key) is
    rebuilt in place, preserving every row. A fresh database already matches and
    is left untouched, so this runs at most once per database file.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'tables'"
    ).fetchone()
    if row is None or TABLES_PK in " ".join(row[0].split()):
        return
    conn.execute("PRAGMA foreign_keys=OFF;")
    conn.execute("BEGIN IMMEDIATE;")
    try:
        conn.execute(
            """
            CREATE TABLE tables_rebuilt (
                id TEXT NOT NULL,
                restaurant_id TEXT NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                max_seats INTEGER NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (restaurant_id, id)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO tables_rebuilt (id, restaurant_id, name, max_seats, position)
            SELECT id, restaurant_id, name, max_seats, position FROM tables
            """
        )
        conn.execute("DROP TABLE tables;")
        conn.execute("ALTER TABLE tables_rebuilt RENAME TO tables;")

        conn.execute(
            """
            CREATE TABLE reservations_rebuilt (
                reference TEXT PRIMARY KEY,
                reservation_id TEXT UNIQUE,
                restaurant_id TEXT NOT NULL REFERENCES restaurants(id),
                user_id TEXT NOT NULL REFERENCES users(user_id),
                table_id TEXT NOT NULL,
                starts_at TEXT NOT NULL,
                ends_at TEXT NOT NULL,
                party_size INTEGER NOT NULL,
                duration_minutes INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                cancelled_at TEXT,
                FOREIGN KEY (restaurant_id, table_id) REFERENCES tables(restaurant_id, id)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO reservations_rebuilt (
                reference, reservation_id, restaurant_id, user_id, table_id,
                starts_at, ends_at, party_size, duration_minutes, status,
                created_at, cancelled_at
            )
            SELECT
                reference, reservation_id, restaurant_id, user_id, table_id,
                starts_at, ends_at, party_size, duration_minutes, status,
                created_at, cancelled_at
            FROM reservations
            """
        )
        conn.execute("DROP TABLE reservations;")
        conn.execute("ALTER TABLE reservations_rebuilt RENAME TO reservations;")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reservations_restaurant_starts "
            "ON reservations(restaurant_id, starts_at, ends_at);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reservations_user ON reservations(user_id);"
        )
    except Exception:
        conn.execute("ROLLBACK;")
        raise
    conn.execute("COMMIT;")
    conn.execute("PRAGMA foreign_keys=ON;")

def init_db(db_path: str = None) -> None:
    path = db_path or get_db_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=5000;")
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        with open(schema_path, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        add_missing_columns(conn)
        rebuild_legacy_tables(conn)
        conn.commit()
    finally:
        conn.close()

@contextmanager
def get_connection(db_path: str = None):
    path = db_path or get_db_path()
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=5000;")
        yield conn
    finally:
        conn.close()

@contextmanager
def transaction(db_path: str = None):
    path = db_path or get_db_path()
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("BEGIN IMMEDIATE;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
