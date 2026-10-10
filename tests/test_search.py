import httpx

from app import search as search_module

SERPAPI_KEY = "test-serpapi-key"


def mock_serpapi(monkeypatch, handler):
    def make_client():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(search_module, "serpapi_client", make_client)


def test_search_returns_normalized_results(client, monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "organic_results": [
                    {
                        "position": 1,
                        "title": "Chai Point",
                        "link": "https://example.com/chai",
                        "snippet": "Best chai in town",
                        "source": "Example",
                    },
                    {
                        "position": 2,
                        "title": "Filter Coffee House",
                        "link": "https://example.com/coffee",
                        "snippet": "Iconic since 1940",
                        "displayed_link": "example.com",
                    },
                ]
            },
        )

    mock_serpapi(monkeypatch, handler)

    res = client.get("/search", params={"q": "chai in bengaluru"})

    assert res.status_code == 200
    assert res.json() == {
        "query": "chai in bengaluru",
        "results": [
            {
                "position": 1,
                "title": "Chai Point",
                "url": "https://example.com/chai",
                "snippet": "Best chai in town",
                "source": "Example",
            },
            {
                "position": 2,
                "title": "Filter Coffee House",
                "url": "https://example.com/coffee",
                "snippet": "Iconic since 1940",
                "source": "example.com",
            },
        ],
    }

    # The real SerpApi endpoint was requested with the Google engine and the key.
    assert captured["url"].startswith("https://serpapi.com/search.json")
    assert captured["params"]["engine"] == "google"
    assert captured["params"]["q"] == "chai in bengaluru"
    assert captured["params"]["api_key"] == SERPAPI_KEY

    # The API key never appears in the response.
    assert SERPAPI_KEY not in res.text


def test_search_empty_or_missing_query_is_rejected(client, monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    res = client.get("/search", params={"q": "   "})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "validation_failed"

    res = client.get("/search")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "validation_failed"


def test_search_missing_api_key_is_configuration_error(client, monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)

    res = client.get("/search", params={"q": "chai"})

    assert res.status_code == 500
    assert res.json()["error"]["code"] == "configuration_error"


def test_search_upstream_failure(client, monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)
    mock_serpapi(monkeypatch, lambda request: httpx.Response(500, text="server error"))

    res = client.get("/search", params={"q": "chai"})

    assert res.status_code == 502
    assert res.json()["error"]["code"] == "upstream_error"
    assert SERPAPI_KEY not in res.text


def test_search_serpapi_error_payload(client, monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)
    mock_serpapi(
        monkeypatch,
        lambda request: httpx.Response(200, json={"error": "Invalid API key"}),
    )

    res = client.get("/search", params={"q": "chai"})

    assert res.status_code == 502
    assert res.json()["error"]["code"] == "upstream_error"
    assert SERPAPI_KEY not in res.text


def test_search_timeout(client, monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    def handler(request):
        raise httpx.ReadTimeout("timed out")

    mock_serpapi(monkeypatch, handler)

    res = client.get("/search", params={"q": "chai"})

    assert res.status_code == 504
    assert res.json()["error"]["code"] == "upstream_timeout"


def test_search_malformed_response(client, monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)
    mock_serpapi(
        monkeypatch,
        lambda request: httpx.Response(200, text="<html>not json</html>"),
    )

    res = client.get("/search", params={"q": "chai"})

    assert res.status_code == 502
    assert res.json()["error"]["code"] == "upstream_error"


def test_search_zero_results(client, monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)
    mock_serpapi(
        monkeypatch,
        lambda request: httpx.Response(200, json={"search_metadata": {}}),
    )

    res = client.get("/search", params={"q": "zzzz-no-results"})

    assert res.status_code == 200
    assert res.json() == {"query": "zzzz-no-results", "results": []}
