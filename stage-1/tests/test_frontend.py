"""Frontend serving tests for the ORBIT Search research workspace."""


def test_index_served_at_root(client):
    res = client.get("/")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")

    body = res.text
    assert "ORBIT Search" in body
    assert "/static/styles.css" in body
    assert "/static/app.js" in body


def test_styles_asset_served(client):
    res = client.get("/static/styles.css")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/css")
    assert ".answer-body" in res.text


def test_app_js_asset_served(client):
    res = client.get("/static/app.js")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/javascript")
    assert "buildCoverage" in res.text


def test_unknown_asset_returns_error_envelope(client):
    res = client.get("/static/missing.css")

    assert res.status_code == 404
    body = res.json()
    assert body["error"]["code"] == "not_found"


def test_asset_rejects_path_traversal(client):
    for asset in ("..%2Fmain.py", "%2e%2e/app/main.py", "..%2F..%2Frequirements.txt"):
        res = client.get(f"/static/{asset}")

        assert res.status_code == 404
        assert "def auth_signup" not in res.text
        assert "fastapi" not in res.text.lower()


def test_served_files_do_not_expose_secrets(client):
    combined = client.get("/").text
    combined += client.get("/static/app.js").text
    combined += client.get("/static/styles.css").text

    assert "SERPAPI_API_KEY" not in combined
    assert "GEMINI_API_KEY" not in combined
    assert "serpapi.com/search" not in combined
