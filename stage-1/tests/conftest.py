import pytest
import os
import tempfile
from fastapi.testclient import TestClient

@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    db_file = tmp_path / "test_tablekeeper.db"
    monkeypatch.setenv("TABLEKEEPER_DB_PATH", str(db_file))
    from app.db import init_db
    init_db(str(db_file))
    with open(db_file, "a"):
        pass
    yield str(db_file)

@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as c:
        # Reset DB on test start
        c.post("/_test/reset")
        yield c
