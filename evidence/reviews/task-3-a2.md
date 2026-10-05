Concrete Evidence:
- **Files Inspected:**
  - `stage-1/app/idempotency.py`: Verified idempotency check, body hash computation, replay response generation with `Idempotency-Replayed` header, receipt storage, and `IDEMPOTENCY_KEY_REUSED` handling.
  - `stage-1/app/moves.py`: Verified `POST /reservation-moves` atomic multi-reservation moves, swaps, validation, and idempotency integration.
  - `stage-1/app/reservations.py`: Verified `POST /reservations`, `PATCH /reservations/{ref}`, cancellation, and concurrency/occupancy safety via `BEGIN IMMEDIATE`.
  - `stage-1/app/exportimport.py`: Verified export and import persistence including tokens and idempotency receipts.
  - `stage-1/app/schema.sql`: Verified database schema with WAL-ready indexes and idempotency receipts table.
  - `stage-1/tests/test_tablekeeper.py`: Verified comprehensive test coverage for concurrency, idempotency, export/import, moves, DST, opening hours, and edge cases.
- **Commands Run:**
  - `cd stage-1 && .venv/bin/python -m pytest`
- **Test Output Summary:**
  - 19 passed, 0 failed (100% green status).

VERDICT: APPROVED