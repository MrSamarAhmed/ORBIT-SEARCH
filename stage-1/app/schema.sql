CREATE TABLE IF NOT EXISTS restaurants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    timezone TEXT NOT NULL,
    slot_minutes INTEGER NOT NULL DEFAULT 30,
    reservation_duration_minutes INTEGER NOT NULL DEFAULT 90,
    cancellation_cutoff_minutes INTEGER NOT NULL DEFAULT 0
);

-- Table ids are scoped to their restaurant: the official fixture contract
-- reuses ids such as "t_1" across different restaurants in one database.
CREATE TABLE IF NOT EXISTS tables (
    id TEXT NOT NULL,
    restaurant_id TEXT NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    max_seats INTEGER NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (restaurant_id, id)
);

CREATE TABLE IF NOT EXISTS opening_hours (
    restaurant_id TEXT NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    weekday INTEGER NOT NULL,
    opens TEXT NOT NULL,
    closes TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reservations (
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
);

CREATE INDEX IF NOT EXISTS idx_reservations_restaurant_starts ON reservations(restaurant_id, starts_at, ends_at);
CREATE INDEX IF NOT EXISTS idx_reservations_user ON reservations(user_id);

CREATE TABLE IF NOT EXISTS idempotency_receipts (
    scope TEXT NOT NULL,
    key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    response_body TEXT NOT NULL,
    PRIMARY KEY (scope, key)
);
