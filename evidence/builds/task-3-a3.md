BUILD_REPORT:
SUMMARY: Fixed the test defect in `tests/test_tablekeeper.py::test_idempotency_behavior` by anchoring `future_dt` to 17:30 UTC explicitly with `.replace(hour=17, minute=30, second=0, microsecond=0)`, ensuring the 90-minute reservation window falls fully within r-berlin's opening hours (18:00-23:00 local) under both CEST and CET.
FILES: stage-1/tests/test_tablekeeper.py
TESTS: Ran `cd stage-1 && .venv/bin/python -m pytest tests/` twice consecutively; both runs reported 19 passed successfully.