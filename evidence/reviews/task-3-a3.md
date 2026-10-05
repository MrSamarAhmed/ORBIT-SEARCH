I have independently inspected the codebase, reviewed the implementation of task-3, and executed the test suite.

### Concrete Evidence

1. **Files Inspected:**
   - `stage-1/app/idempotency.py`: Implements request body hashing, receipt storage, replayed response generation with `Idempotency-Replayed: true`, and `IDEMPOTENCY_KEY_REUSED` conflict handling.
   - `stage-1/app/moves.py`: Implements `POST /reservation-moves` with atomic multi-reservation validation, table swap support, and rollback on failure.
   - `stage-1/app/reservations.py` & `stage-1/app/exportimport.py`: Implements reservation management, patch logic, and export/import persistence of tokens, reservations, and idempotency receipts.
   - `stage-1/tests/test_tablekeeper.py`: Comprehensive test suite covering health, reset, export/import round-trip, auth, availability, reservation creation/cancellation/patching, idempotency (replay, reuse conflict, export/import persistence), reservation moves and atomic failures, opening hours constraints, and concurrency threads.

2. **Commands Run:**
   - `cd stage-1 && .venv/bin/python -m pytest`

3. **Output Summary:**
   - Pytest collected and executed 19 tests successfully (`19 passed, 1 warning in 0.58s`), covering all acceptance criteria including concurrency threads, idempotency semantics, export/import persistence, and reservation moves.

VERDICT: APPROVED