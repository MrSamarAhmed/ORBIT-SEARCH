import asyncio
import importlib
import json

import httpx

from app import research as research_module
from app import search as search_module

GEMINI_KEY = "test-gemini-key"
SERPAPI_KEY = "test-serpapi-key"

PLAN = ["predictive maintenance ai", "predictive maintenance manufacturing"]
ANSWER = "Answer citing https://example.org/pdm."


def mock_gemini(monkeypatch, handler):
    def make_client():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(research_module, "gemini_client", make_client)


def mock_serpapi(monkeypatch, handler):
    def make_client():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(search_module, "serpapi_client", make_client)


def plan_response(*queries):
    text = json.dumps({"queries": list(queries)})
    return httpx.Response(
        200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]}
    )


def answer_response(text):
    return httpx.Response(
        200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]}
    )


def gemini_ok(plan=PLAN, answer=ANSWER):
    def handler(request):
        body = json.loads(request.content)
        if body.get("generationConfig"):
            return plan_response(*plan)
        return answer_response(answer)

    return handler


def serpapi_ok(default=None, results_by_query=None):
    def handler(request):
        query = request.url.params["q"]
        results = (results_by_query or {}).get(query, default or [])
        return httpx.Response(200, json={"organic_results": results})

    return handler


def forbid(request):
    raise AssertionError("unexpected upstream request")


def mock_sleep(monkeypatch, sleeps):
    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(research_module, "sleep", fake_sleep)


def serp_result(title, url, snippet, source):
    return {"title": title, "link": url, "snippet": snippet, "source": source}


def test_research_end_to_end(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    searched = []

    def serpapi(request):
        query = request.url.params["q"]
        searched.append(query)
        if query == "predictive maintenance manufacturing":
            return httpx.Response(
                200,
                json={
                    "organic_results": [
                        {
                            "position": 1,
                            "title": "AI in manufacturing",
                            "link": "https://example.com/ai-manufacturing",
                            "snippet": "How AI is used on factory floors.",
                            "source": "Example",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "organic_results": [
                    {
                        "position": 1,
                        "title": "Predictive maintenance overview",
                        "link": "https://example.org/pdm",
                        "snippet": "A guide to predictive maintenance.",
                        "displayed_link": "example.org",
                    }
                ]
            },
        )

    mock_serpapi(monkeypatch, serpapi)

    gemini_calls = []

    def gemini(request):
        body = json.loads(request.content)
        gemini_calls.append(body)
        if body.get("generationConfig"):
            return plan_response(*PLAN)
        return answer_response(ANSWER)

    mock_gemini(monkeypatch, gemini)

    res = client.post(
        "/research", json={"question": "  Best AI for predictive maintenance?  "}
    )

    assert res.status_code == 200
    data = res.json()

    assert data["question"] == "Best AI for predictive maintenance?"
    assert data["queries"] == PLAN
    assert searched == PLAN

    assert data["sources"] == [
        {
            "title": "Predictive maintenance overview",
            "url": "https://example.org/pdm",
            "snippet": "A guide to predictive maintenance.",
            "source": "example.org",
            "query": "predictive maintenance ai",
        },
        {
            "title": "AI in manufacturing",
            "url": "https://example.com/ai-manufacturing",
            "snippet": "How AI is used on factory floors.",
            "source": "Example",
            "query": "predictive maintenance manufacturing",
        },
    ]
    assert data["citations"] == [
        "https://example.org/pdm",
        "https://example.com/ai-manufacturing",
    ]
    assert data["answer"] == ANSWER
    # Successful responses keep the original schema: no degraded markers.
    assert "status" not in data
    assert "warning" not in data

    # Planning asked Gemini for structured JSON; synthesis received the evidence.
    planning = gemini_calls[0]
    assert planning["generationConfig"]["responseMimeType"] == "application/json"
    assert planning["generationConfig"]["responseSchema"]["properties"]["queries"]
    synthesis_text = gemini_calls[1]["contents"][0]["parts"][0]["text"]
    assert "A guide to predictive maintenance." in synthesis_text
    assert "https://example.org/pdm" in synthesis_text

    # Neither API key appears anywhere in the response.
    assert GEMINI_KEY not in res.text
    assert SERPAPI_KEY not in res.text


def test_research_multiple_queries_are_searched_capped_and_deduped(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    plan = ["q1", "q2", "q1", "q3", "q4", "q5"]
    mock_gemini(
        monkeypatch,
        gemini_ok(plan=plan, answer="Answer citing https://example.com/q1."),
    )

    searched = []

    def serpapi(request):
        query = request.url.params["q"]
        searched.append(query)
        return httpx.Response(
            200,
            json={
                "organic_results": [
                    serp_result(
                        query,
                        f"https://example.com/{query}",
                        f"Snippet for {query}",
                        "example.com",
                    )
                ]
            },
        )

    mock_serpapi(monkeypatch, serpapi)

    res = client.post("/research", json={"question": "Compare the options"})

    assert res.status_code == 200
    data = res.json()
    assert data["queries"] == ["q1", "q2", "q3", "q4"]
    assert searched == ["q1", "q2", "q3", "q4"]
    assert [source["url"] for source in data["sources"]] == [
        "https://example.com/q1",
        "https://example.com/q2",
        "https://example.com/q3",
        "https://example.com/q4",
    ]
    assert data["citations"] == [source["url"] for source in data["sources"]]


def test_research_serpapi_failure(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)
    mock_gemini(monkeypatch, gemini_ok(plan=["q1"]))
    mock_serpapi(monkeypatch, lambda request: httpx.Response(500, text="server error"))

    res = client.post("/research", json={"question": "Any question"})

    assert res.status_code == 502
    assert res.json()["error"]["code"] == "upstream_error"
    assert SERPAPI_KEY not in res.text
    assert GEMINI_KEY not in res.text


def test_research_gemini_planning_failure(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)
    mock_gemini(monkeypatch, lambda request: httpx.Response(500, text="boom"))
    mock_serpapi(monkeypatch, forbid)

    res = client.post("/research", json={"question": "Any question"})

    assert res.status_code == 502
    assert res.json()["error"]["code"] == "upstream_error"
    assert GEMINI_KEY not in res.text


def test_research_gemini_synthesis_failure(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    def gemini(request):
        body = json.loads(request.content)
        if body.get("generationConfig"):
            return plan_response("q1")
        return httpx.Response(500, text="quota exceeded")

    mock_gemini(monkeypatch, gemini)
    mock_serpapi(
        monkeypatch,
        serpapi_ok(default=[serp_result("T", "https://example.com/x", "S", "example.com")]),
    )

    res = client.post("/research", json={"question": "Any question"})

    assert res.status_code == 502
    assert res.json()["error"]["code"] == "upstream_error"


def test_research_unusable_plan(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)
    mock_gemini(monkeypatch, lambda request: answer_response("not a plan object"))
    mock_serpapi(monkeypatch, forbid)

    res = client.post("/research", json={"question": "Any question"})

    assert res.status_code == 502
    assert res.json()["error"]["code"] == "upstream_error"


def test_research_empty_search_results(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    gemini_calls = []

    def gemini(request):
        body = json.loads(request.content)
        gemini_calls.append(body)
        if body.get("generationConfig"):
            return plan_response("q1", "q2")
        return answer_response("The evidence is insufficient to answer.")

    mock_gemini(monkeypatch, gemini)
    mock_serpapi(monkeypatch, serpapi_ok())

    res = client.post("/research", json={"question": "An obscure question"})

    assert res.status_code == 200
    data = res.json()
    assert data["sources"] == []
    assert data["citations"] == []
    assert data["answer"] == "The evidence is insufficient to answer."

    # Synthesis still ran, over an explicit "no results" placeholder.
    synthesis_text = gemini_calls[-1]["contents"][0]["parts"][0]["text"]
    assert "no search results were found" in synthesis_text


def test_research_missing_gemini_key(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)
    mock_gemini(monkeypatch, forbid)
    mock_serpapi(monkeypatch, forbid)

    res = client.post("/research", json={"question": "Any question"})

    assert res.status_code == 500
    assert res.json()["error"]["code"] == "configuration_error"


def test_research_missing_question(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)
    mock_gemini(monkeypatch, forbid)
    mock_serpapi(monkeypatch, forbid)

    res = client.post("/research", json={})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_failed"

    res = client.post("/research", json={"question": "   "})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_failed"

    res = client.post("/research", json={"question": 42})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "malformed_request"

    res = client.post(
        "/research",
        content="not valid json",
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "malformed_request"


def test_research_gemini_model_default_and_env_override(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    importlib.reload(research_module)
    assert research_module.GEMINI_MODEL == "gemini-3.8-flash"

    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash-preview")
    importlib.reload(research_module)
    assert research_module.GEMINI_MODEL == "gemini-3.8-flash-preview"

    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    importlib.reload(research_module)
    assert research_module.GEMINI_MODEL == "gemini-3.8-flash"


def test_research_gemini_request_targets_configured_model(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)
    monkeypatch.setattr(research_module, "GEMINI_MODEL", "gemini-3.8-flash")

    requests_seen = []

    def gemini(request):
        requests_seen.append(request)
        body = json.loads(request.content)
        if body.get("generationConfig"):
            return plan_response("q1")
        return answer_response("Answer citing https://example.com/x.")

    mock_gemini(monkeypatch, gemini)
    mock_serpapi(
        monkeypatch,
        serpapi_ok(
            default=[serp_result("T", "https://example.com/x", "S", "example.com")]
        ),
    )

    res = client.post("/research", json={"question": "Any question"})

    assert res.status_code == 200
    assert len(requests_seen) == 2  # planning + synthesis

    for request in requests_seen:
        assert request.url.path == "/v1beta/models/gemini-3.8-flash:generateContent"
        assert str(request.url).startswith("https://generativelanguage.googleapis.com")
        # The key travels in the header, never in the URL or request body.
        assert request.headers["x-goog-api-key"] == GEMINI_KEY
        assert GEMINI_KEY not in str(request.url)
        assert GEMINI_KEY not in request.content.decode()

    assert GEMINI_KEY not in res.text


def test_research_gemini_timeout_configuration():
    assert research_module.GEMINI_TIMEOUT_SECONDS == 60.0

    async def read_timeout():
        async with research_module.gemini_client() as client:
            return client.timeout.read

    assert asyncio.run(read_timeout()) == 60.0


def test_research_synthesis_receives_at_most_eight_evidence_items(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    plan = ["q1", "q2", "q3", "q4"]

    gemini_calls = []

    def gemini(request):
        body = json.loads(request.content)
        gemini_calls.append(body)
        if body.get("generationConfig"):
            return plan_response(*plan)
        return answer_response("Answer citing https://example.com/q4/2.")

    mock_gemini(monkeypatch, gemini)

    def serpapi(request):
        query = request.url.params["q"]
        return httpx.Response(
            200,
            json={
                "organic_results": [
                    serp_result(
                        f"{query} result {rank}",
                        f"https://example.com/{query}/{rank}",
                        f"Snippet {rank} for {query}",
                        "example.com",
                    )
                    for rank in range(1, 6)
                ]
            },
        )

    mock_serpapi(monkeypatch, serpapi)

    res = client.post("/research", json={"question": "Compare the options"})

    assert res.status_code == 200
    data = res.json()

    # The response contract is unchanged: all 20 collected sources are returned.
    assert len(data["sources"]) == 20

    # Citations are scoped to the evidence actually supplied to synthesis:
    # the best 8, never the full collected set.
    assert data["citations"] == [
        "https://example.com/q1/1",
        "https://example.com/q2/1",
        "https://example.com/q3/1",
        "https://example.com/q4/1",
        "https://example.com/q1/2",
        "https://example.com/q2/2",
        "https://example.com/q3/2",
        "https://example.com/q4/2",
    ]
    source_urls = [source["url"] for source in data["sources"]]
    assert "https://example.com/q1/3" in source_urls
    assert "https://example.com/q1/3" not in data["citations"]

    # Synthesis only receives the best 8: every query contributes its top
    # results first, lower-ranked results are dropped.
    synthesis_text = gemini_calls[-1]["contents"][0]["parts"][0]["text"]
    assert synthesis_text.count("Found via query: ") == 8
    for query in plan:
        assert f"Found via query: {query}" in synthesis_text
    assert "https://example.com/q4/2" in synthesis_text
    assert "/q1/3" not in synthesis_text

    # The answer cites an evidence URL, so no degraded markers appear.
    assert "status" not in data
    assert "warning" not in data


def test_research_retries_once_after_gemini_503(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    sleeps = []
    mock_sleep(monkeypatch, sleeps)

    gemini_calls = []

    def gemini(request):
        body = json.loads(request.content)
        gemini_calls.append(body)
        if len(gemini_calls) == 1:
            return httpx.Response(503, text="high demand")
        if body.get("generationConfig"):
            return plan_response("q1")
        return answer_response("Answer citing https://example.com/x.")

    mock_gemini(monkeypatch, gemini)
    mock_serpapi(
        monkeypatch,
        serpapi_ok(
            default=[serp_result("T", "https://example.com/x", "S", "example.com")]
        ),
    )

    res = client.post("/research", json={"question": "Any question"})

    assert res.status_code == 200
    assert len(gemini_calls) == 3  # 503, retried planning, synthesis
    assert sleeps == [2.0]


def test_research_retries_twice_after_two_gemini_503(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    sleeps = []
    mock_sleep(monkeypatch, sleeps)

    gemini_calls = []

    def gemini(request):
        body = json.loads(request.content)
        gemini_calls.append(body)
        if len(gemini_calls) <= 2:
            return httpx.Response(503, text="high demand")
        if body.get("generationConfig"):
            return plan_response("q1")
        return answer_response("Answer citing https://example.com/x.")

    mock_gemini(monkeypatch, gemini)
    mock_serpapi(
        monkeypatch,
        serpapi_ok(
            default=[serp_result("T", "https://example.com/x", "S", "example.com")]
        ),
    )

    res = client.post("/research", json={"question": "Any question"})

    assert res.status_code == 200
    assert len(gemini_calls) == 4  # 503, 503, retried planning, synthesis
    assert sleeps == [2.0, 4.0]


def test_research_planner_503_falls_back_to_deterministic_queries(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    sleeps = []
    mock_sleep(monkeypatch, sleeps)

    planning_attempts = []
    gemini_calls = []

    def gemini(request):
        body = json.loads(request.content)
        gemini_calls.append(body)
        if body.get("generationConfig"):
            planning_attempts.append(body)
            return httpx.Response(503, text="high demand")
        return answer_response("Answer citing https://example.com/result-1.")

    mock_gemini(monkeypatch, gemini)

    searched = []

    def serpapi(request):
        query = request.url.params["q"]
        searched.append(query)
        return httpx.Response(
            200,
            json={
                "organic_results": [
                    serp_result(
                        query,
                        f"https://example.com/result-{len(searched)}",
                        f"Snippet for {query}",
                        "example.com",
                    )
                ]
            },
        )

    mock_serpapi(monkeypatch, serpapi)

    res = client.post(
        "/research", json={"question": "Best AI for predictive maintenance?"}
    )

    # Planning gave up after the bounded retries and fell back deterministically.
    assert len(planning_attempts) == 3
    assert sleeps == [2.0, 4.0]

    assert res.status_code == 200
    data = res.json()

    expected_queries = [
        "Best AI for predictive maintenance",
        "Best AI predictive maintenance",
        "predictive maintenance",
    ]
    assert data["queries"] == expected_queries
    assert searched == expected_queries
    assert len(gemini_calls) == 4  # 3 planning attempts + 1 synthesis
    assert data["answer"] == "Answer citing https://example.com/result-1."
    assert [source["url"] for source in data["sources"]] == [
        "https://example.com/result-1",
        "https://example.com/result-2",
        "https://example.com/result-3",
    ]
    assert data["citations"] == [source["url"] for source in data["sources"]]
    assert "status" not in data


def test_research_planner_timeout_falls_back_to_deterministic_queries(
    client, monkeypatch
):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    sleeps = []
    mock_sleep(monkeypatch, sleeps)

    planning_attempts = []
    gemini_calls = []

    def gemini(request):
        body = json.loads(request.content)
        gemini_calls.append(body)
        if body.get("generationConfig"):
            planning_attempts.append(body)
            raise httpx.ReadTimeout("timed out")
        return answer_response("Answer citing https://example.com/result-1.")

    mock_gemini(monkeypatch, gemini)

    searched = []

    def serpapi(request):
        query = request.url.params["q"]
        searched.append(query)
        return httpx.Response(
            200,
            json={
                "organic_results": [
                    serp_result(
                        query,
                        f"https://example.com/result-{len(searched)}",
                        f"Snippet for {query}",
                        "example.com",
                    )
                ]
            },
        )

    mock_serpapi(monkeypatch, serpapi)

    res = client.post(
        "/research", json={"question": "Best AI for predictive maintenance?"}
    )

    # The timeout failed immediately: no retry, no sleep, one planning attempt.
    assert len(planning_attempts) == 1
    assert sleeps == []

    assert res.status_code == 200
    data = res.json()

    # The search still ran on the deterministic fallback plan.
    expected_queries = [
        "Best AI for predictive maintenance",
        "Best AI predictive maintenance",
        "predictive maintenance",
    ]
    assert data["queries"] == expected_queries
    assert searched == expected_queries
    assert len(gemini_calls) == 2  # 1 planning attempt + 1 synthesis
    assert data["answer"] == "Answer citing https://example.com/result-1."
    assert [source["url"] for source in data["sources"]] == [
        "https://example.com/result-1",
        "https://example.com/result-2",
        "https://example.com/result-3",
    ]
    assert "status" not in data


def test_research_reworded_planned_queries_are_collapsed(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    # Observed in a real run: Gemini reworded one angle into three queries.
    mock_gemini(
        monkeypatch,
        gemini_ok(
            plan=[
                "How is agentic AI used in enterprises",
                "agentic AI used enterprises",
                "agentic AI used",
                "measured outcomes of agentic AI in enterprises",
            ],
            answer="Answer citing https://example.com/result-1.",
        ),
    )

    searched = []

    def serpapi(request):
        query = request.url.params["q"]
        searched.append(query)
        return httpx.Response(
            200,
            json={
                "organic_results": [
                    serp_result(
                        query,
                        f"https://example.com/result-{len(searched)}",
                        f"Snippet for {query}",
                        "example.com",
                    )
                ]
            },
        )

    mock_serpapi(monkeypatch, serpapi)

    res = client.post(
        "/research",
        json={"question": "How is agentic AI used in enterprises?"},
    )

    assert res.status_code == 200
    data = res.json()

    # The rewordings collapse into the first query; the complementary
    # outcomes query survives. No redundant SerpApi calls are made.
    expected_queries = [
        "How is agentic AI used in enterprises",
        "measured outcomes of agentic AI in enterprises",
    ]
    assert data["queries"] == expected_queries
    assert searched == expected_queries
    assert [source["query"] for source in data["sources"]] == expected_queries
    assert data["answer"] == "Answer citing https://example.com/result-1."
    assert "status" not in data
    assert GEMINI_KEY not in res.text
    assert SERPAPI_KEY not in res.text


def test_research_does_not_retry_non_503_gemini_errors(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    sleeps = []
    mock_sleep(monkeypatch, sleeps)

    gemini_calls = []

    def gemini(request):
        gemini_calls.append(json.loads(request.content))
        return httpx.Response(404, text="not found")

    mock_gemini(monkeypatch, gemini)
    mock_serpapi(monkeypatch, forbid)

    res = client.post("/research", json={"question": "Any question"})

    assert res.status_code == 502
    assert res.json()["error"]["code"] == "upstream_error"
    assert res.json()["error"]["message"] == "Gemini request failed with status 404"
    assert len(gemini_calls) == 1
    assert sleeps == []


def test_research_synthesis_503_returns_degraded_response(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    sleeps = []
    mock_sleep(monkeypatch, sleeps)

    gemini_calls = []

    def gemini(request):
        body = json.loads(request.content)
        gemini_calls.append(body)
        if body.get("generationConfig"):
            return plan_response("q1", "q2")
        return httpx.Response(503, text="high demand")

    mock_gemini(monkeypatch, gemini)

    results_by_query = {
        "q1": [
            serp_result(
                "Predictive maintenance overview",
                "https://example.org/pdm",
                "A guide to predictive maintenance.",
                "example.org",
            )
        ],
        "q2": [
            serp_result(
                "AI in manufacturing",
                "https://example.com/ai-manufacturing",
                "How AI is used on factory floors.",
                "Example",
            )
        ],
    }
    mock_serpapi(monkeypatch, serpapi_ok(results_by_query=results_by_query))

    res = client.post(
        "/research", json={"question": "Best AI for predictive maintenance?"}
    )

    # Synthesis was attempted with bounded retries, then the response degraded.
    assert len(gemini_calls) == 4  # 1 planning + 3 synthesis attempts
    assert sleeps == [2.0, 4.0]

    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "degraded"
    assert "unavailable" in data["warning"]
    # The upstream status code is surfaced for diagnosis.
    assert "status 503" in data["warning"]
    # No AI-generated answer was fabricated.
    assert data["answer"] is None

    # The real collected evidence is returned, with actual titles and URLs.
    assert data["question"] == "Best AI for predictive maintenance?"
    assert data["queries"] == ["q1", "q2"]
    assert data["sources"] == [
        {
            "title": "Predictive maintenance overview",
            "url": "https://example.org/pdm",
            "snippet": "A guide to predictive maintenance.",
            "source": "example.org",
            "query": "q1",
        },
        {
            "title": "AI in manufacturing",
            "url": "https://example.com/ai-manufacturing",
            "snippet": "How AI is used on factory floors.",
            "source": "Example",
            "query": "q2",
        },
    ]
    assert data["citations"] == [
        "https://example.org/pdm",
        "https://example.com/ai-manufacturing",
    ]
    assert GEMINI_KEY not in res.text


def test_research_synthesis_429_returns_degraded_response_without_retry(
    client, monkeypatch
):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    sleeps = []
    mock_sleep(monkeypatch, sleeps)

    gemini_calls = []

    def gemini(request):
        body = json.loads(request.content)
        gemini_calls.append(body)
        if body.get("generationConfig"):
            return plan_response("q1", "q2")
        return httpx.Response(429, text="resource exhausted")

    mock_gemini(monkeypatch, gemini)

    results_by_query = {
        "q1": [
            serp_result(
                "Predictive maintenance overview",
                "https://example.org/pdm",
                "A guide to predictive maintenance.",
                "example.org",
            )
        ],
        "q2": [
            serp_result(
                "AI in manufacturing",
                "https://example.com/ai-manufacturing",
                "How AI is used on factory floors.",
                "Example",
            )
        ],
    }
    mock_serpapi(monkeypatch, serpapi_ok(results_by_query=results_by_query))

    res = client.post(
        "/research", json={"question": "Best AI for predictive maintenance?"}
    )

    # 429 is transient, but unlike 503 it is never retried: one planning call
    # plus a single synthesis attempt, with no sleeps.
    assert len(gemini_calls) == 2
    assert sleeps == []

    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "degraded"
    assert "unavailable" in data["warning"]
    # The upstream status code is surfaced for diagnosis.
    assert "status 429" in data["warning"]
    # No AI-generated answer was fabricated.
    assert data["answer"] is None

    # The real collected evidence is returned, with actual titles and URLs.
    assert data["question"] == "Best AI for predictive maintenance?"
    assert data["queries"] == ["q1", "q2"]
    assert [source["url"] for source in data["sources"]] == [
        "https://example.org/pdm",
        "https://example.com/ai-manufacturing",
    ]
    assert data["citations"] == [
        "https://example.org/pdm",
        "https://example.com/ai-manufacturing",
    ]
    assert SERPAPI_KEY not in res.text
    assert GEMINI_KEY not in res.text


def test_research_planner_429_falls_back_without_retry_keeping_variants(
    client, monkeypatch
):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    sleeps = []
    mock_sleep(monkeypatch, sleeps)

    def gemini(request):
        body = json.loads(request.content)
        if body.get("generationConfig"):
            return httpx.Response(429, text="resource exhausted")
        return answer_response("Answer citing https://example.com/result-1.")

    mock_gemini(monkeypatch, gemini)

    searched = []

    def serpapi(request):
        query = request.url.params["q"]
        searched.append(query)
        return httpx.Response(
            200,
            json={
                "organic_results": [
                    serp_result(
                        query,
                        f"https://example.com/result-{len(searched)}",
                        f"Snippet for {query}",
                        "example.com",
                    )
                ]
            },
        )

    mock_serpapi(monkeypatch, serpapi)

    res = client.post(
        "/research",
        json={"question": "How is agentic AI used in enterprises?"},
    )

    # 429 is never retried: the deterministic fallback runs immediately.
    assert sleeps == []

    assert res.status_code == 200
    data = res.json()

    # Fallback behavior is unchanged: its keyword variants are all searched
    # even though the similarity filter would collapse planned queries.
    expected_queries = [
        "How is agentic AI used in enterprises",
        "agentic AI used enterprises",
        "agentic AI used",
    ]
    assert data["queries"] == expected_queries
    assert searched == expected_queries
    assert data["answer"] == "Answer citing https://example.com/result-1."
    assert "status" not in data
    assert GEMINI_KEY not in res.text
    assert SERPAPI_KEY not in res.text


def test_research_synthesis_timeout_returns_degraded_response_with_sources(
    client, monkeypatch
):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    sleeps = []
    mock_sleep(monkeypatch, sleeps)

    gemini_calls = []

    def gemini(request):
        body = json.loads(request.content)
        gemini_calls.append(body)
        if body.get("generationConfig"):
            return plan_response("q1", "q2")
        raise httpx.ReadTimeout("timed out")

    mock_gemini(monkeypatch, gemini)

    results_by_query = {
        "q1": [
            serp_result(
                "Predictive maintenance overview",
                "https://example.org/pdm",
                "A guide to predictive maintenance.",
                "example.org",
            )
        ],
        "q2": [
            serp_result(
                "AI in manufacturing",
                "https://example.com/ai-manufacturing",
                "How AI is used on factory floors.",
                "Example",
            )
        ],
    }
    mock_serpapi(monkeypatch, serpapi_ok(results_by_query=results_by_query))

    res = client.post(
        "/research", json={"question": "Best AI for predictive maintenance?"}
    )

    # The synthesis timeout failed immediately: no retry, no sleep.
    assert len(gemini_calls) == 2  # 1 planning + 1 synthesis attempt
    assert sleeps == []

    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "degraded"
    assert "synthesis timed out" in data["warning"]
    assert "Gemini request timed out" in data["warning"]
    assert data["answer"] is None

    # The collected evidence survives the synthesis timeout.
    assert data["question"] == "Best AI for predictive maintenance?"
    assert data["queries"] == ["q1", "q2"]
    assert data["sources"] == [
        {
            "title": "Predictive maintenance overview",
            "url": "https://example.org/pdm",
            "snippet": "A guide to predictive maintenance.",
            "source": "example.org",
            "query": "q1",
        },
        {
            "title": "AI in manufacturing",
            "url": "https://example.com/ai-manufacturing",
            "snippet": "How AI is used on factory floors.",
            "source": "Example",
            "query": "q2",
        },
    ]
    assert data["citations"] == [
        "https://example.org/pdm",
        "https://example.com/ai-manufacturing",
    ]
    assert GEMINI_KEY not in res.text
    assert SERPAPI_KEY not in res.text


def test_research_search_failure_after_planner_fallback_is_not_hidden(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    sleeps = []
    mock_sleep(monkeypatch, sleeps)

    mock_gemini(monkeypatch, lambda request: httpx.Response(503, text="high demand"))
    mock_serpapi(monkeypatch, lambda request: httpx.Response(500, text="server error"))

    res = client.post("/research", json={"question": "Any question"})

    # A genuine SerpApi failure stays a failure even on the fallback path.
    assert res.status_code == 502
    assert res.json()["error"]["code"] == "upstream_error"
    assert sleeps == [2.0, 4.0]  # planning still retried before falling back


def test_research_partial_search_timeout_keeps_successful_results(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    mock_gemini(
        monkeypatch,
        gemini_ok(plan=["q1", "q2"], answer="Answer citing https://example.com/q1."),
    )

    def serpapi(request):
        if request.url.params["q"] == "q2":
            raise httpx.ReadTimeout("timed out")
        return httpx.Response(
            200,
            json={
                "organic_results": [
                    serp_result(
                        "Q1 result",
                        "https://example.com/q1",
                        "Snippet for q1",
                        "example.com",
                    )
                ]
            },
        )

    mock_serpapi(monkeypatch, serpapi)

    res = client.post("/research", json={"question": "Any question"})

    assert res.status_code == 200
    data = res.json()

    # The surviving query's real evidence is preserved.
    assert data["queries"] == ["q1", "q2"]
    assert data["sources"] == [
        {
            "title": "Q1 result",
            "url": "https://example.com/q1",
            "snippet": "Snippet for q1",
            "source": "example.com",
            "query": "q1",
        }
    ]
    assert data["citations"] == ["https://example.com/q1"]
    assert data["answer"] == "Answer citing https://example.com/q1."

    # The failed query is surfaced, not hidden; the answer cites the evidence,
    # so search failure is the only warning.
    assert data["status"] == "degraded"
    assert "1 of 2 search queries failed" in data["warning"]
    assert "'q2'" in data["warning"]
    assert "upstream_timeout" in data["warning"]
    assert "SerpApi request timed out" in data["warning"]
    assert "provenance" not in data["warning"]

    assert SERPAPI_KEY not in res.text
    assert GEMINI_KEY not in res.text


def test_research_all_search_queries_failing_returns_honest_error(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    mock_gemini(monkeypatch, gemini_ok(plan=["q1", "q2"]))

    def serpapi(request):
        raise httpx.ReadTimeout("timed out")

    mock_serpapi(monkeypatch, serpapi)

    res = client.post("/research", json={"question": "Any question"})

    # No evidence could be collected: an honest error, never a fake success.
    assert res.status_code == 504
    data = res.json()
    assert data["error"]["code"] == "upstream_timeout"
    assert data["error"]["message"] == "SerpApi request timed out"
    assert "sources" not in data
    assert "answer" not in data
    assert SERPAPI_KEY not in res.text
    assert GEMINI_KEY not in res.text


def test_research_partial_failure_and_synthesis_unavailable(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    sleeps = []
    mock_sleep(monkeypatch, sleeps)

    def gemini(request):
        body = json.loads(request.content)
        if body.get("generationConfig"):
            return plan_response("q1", "q2")
        return httpx.Response(503, text="high demand")

    mock_gemini(monkeypatch, gemini)

    def serpapi(request):
        if request.url.params["q"] == "q2":
            raise httpx.ReadTimeout("timed out")
        return httpx.Response(
            200,
            json={
                "organic_results": [
                    serp_result("T", "https://example.com/q1", "S", "example.com")
                ]
            },
        )

    mock_serpapi(monkeypatch, serpapi)

    res = client.post("/research", json={"question": "Any question"})

    assert res.status_code == 200
    data = res.json()

    # Both degradations are reported; neither is hidden.
    assert data["status"] == "degraded"
    assert data["answer"] is None
    assert "1 of 2 search queries failed" in data["warning"]
    assert "synthesis was unavailable" in data["warning"]
    # The Gemini status is surfaced alongside the search-failure warning.
    assert "status 503" in data["warning"]
    assert [source["url"] for source in data["sources"]] == ["https://example.com/q1"]
    assert data["citations"] == ["https://example.com/q1"]
    assert sleeps == [2.0, 4.0]  # synthesis still retried before degrading


def test_research_fallback_queries_are_distinct_keyword_variants():
    assert research_module.fallback_queries("Best AI for predictive maintenance?") == [
        "Best AI for predictive maintenance",
        "Best AI predictive maintenance",
        "predictive maintenance",
    ]
    assert research_module.fallback_queries(
        "How do interest rates affect inflation?"
    ) == [
        "How do interest rates affect inflation",
        "interest rates affect inflation",
    ]
    assert research_module.fallback_queries("chai") == ["chai", "chai comparison"]


def test_research_fallback_queries_hold_for_diverse_topics():
    questions = [
        "Best AI for predictive maintenance?",
        "How do interest rates affect inflation?",
        "Which electric car is best for long road trips?",
        "What are the health benefits of green tea?",
        "chai",
    ]

    for question in questions:
        queries = research_module.fallback_queries(question)

        assert 2 <= len(queries) <= research_module.MAX_QUERIES
        assert len({query.lower() for query in queries}) == len(queries)
        # The user's original question leads the fallback plan.
        assert queries[0] == question.rstrip("?!. ")


def test_research_dedupe_similar_queries_collapses_rewordings():
    dedupe = research_module.dedupe_similar_queries

    # Rewordings of one angle (only stop words differ) collapse into the first.
    assert dedupe(
        [
            "How is agentic AI used in enterprises",
            "agentic AI used enterprises",
            "agentic AI used",
        ]
    ) == ["How is agentic AI used in enterprises"]

    # Queries adding new keywords — distinct angles — are kept, in order.
    assert dedupe(["a b", "a", "c d", "a b c"]) == ["a b", "c d", "a b c"]

    assert dedupe([]) == []
    # The first query is always kept, even with no usable keywords.
    assert dedupe(["how is it"]) == ["how is it"]


def test_research_normalize_url_deduplication_key():
    normalize = research_module.normalize_url

    assert normalize("https://example.com/ai") == "https://example.com/ai"
    assert normalize("https://example.com/ai/") == "https://example.com/ai"
    assert normalize("https://EXAMPLE.com/ai#results") == "https://example.com/ai"
    assert normalize("  https://example.com/ai  ") == "https://example.com/ai"
    assert (
        normalize("https://example.com/search?q=ai")
        == "https://example.com/search?q=ai"
    )
    assert normalize("") == ""
    assert normalize("not a url") == ""
    assert normalize(None) == ""


def test_research_deduplicates_sources_by_normalized_url(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    mock_gemini(
        monkeypatch,
        gemini_ok(plan=["q1", "q2"], answer="Answer citing https://example.com/ai."),
    )

    results_by_query = {
        "q1": [
            serp_result("Guide", "https://example.com/ai", "First copy", "Example"),
            serp_result(
                "Guide", "https://example.com/ai/", "Trailing slash", "Example"
            ),
        ],
        "q2": [
            serp_result(
                "Guide", "https://EXAMPLE.com/ai#section", "Fragment copy", "Example"
            ),
            serp_result(
                "Other", "https://other.example/c", "Unique page", "other.example"
            ),
        ],
    }
    mock_serpapi(monkeypatch, serpapi_ok(results_by_query=results_by_query))

    res = client.post("/research", json={"question": "Any question"})

    assert res.status_code == 200
    data = res.json()

    # Only the first occurrence of each normalized URL survives, keeping its
    # original URL text and the query that discovered it.
    assert data["sources"] == [
        {
            "title": "Guide",
            "url": "https://example.com/ai",
            "snippet": "First copy",
            "source": "Example",
            "query": "q1",
        },
        {
            "title": "Other",
            "url": "https://other.example/c",
            "snippet": "Unique page",
            "source": "other.example",
            "query": "q2",
        },
    ]
    assert data["citations"] == ["https://example.com/ai", "https://other.example/c"]
    # Nothing was degraded: this is a clean, successful response.
    assert "status" not in data
    assert "warning" not in data
    assert SERPAPI_KEY not in res.text
    assert GEMINI_KEY not in res.text


def test_research_partial_results_survive_failure_with_dedup(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    mock_gemini(
        monkeypatch,
        gemini_ok(plan=["q1", "q2", "q3"], answer="Answer citing https://example.com/ai."),
    )

    searched = []

    def serpapi(request):
        query = request.url.params["q"]
        searched.append(query)
        if query == "q2":
            raise httpx.ReadTimeout("timed out")
        results = {
            "q1": [
                serp_result("A", "https://example.com/ai", "From q1", "example.com")
            ],
            "q3": [
                serp_result("A", "https://example.com/ai/", "From q3", "example.com"),
                serp_result("B", "https://other.example/b", "From q3", "other.example"),
            ],
        }[query]
        return httpx.Response(200, json={"organic_results": results})

    mock_serpapi(monkeypatch, serpapi)

    res = client.post("/research", json={"question": "Any question"})

    assert res.status_code == 200
    data = res.json()

    assert searched == ["q1", "q2", "q3"]
    assert data["queries"] == ["q1", "q2", "q3"]
    assert [source["url"] for source in data["sources"]] == [
        "https://example.com/ai",
        "https://other.example/b",
    ]
    assert [source["query"] for source in data["sources"]] == ["q1", "q3"]
    assert data["citations"] == ["https://example.com/ai", "https://other.example/b"]
    assert data["answer"] == "Answer citing https://example.com/ai."

    # The failed query is still reported; dedup never hides a failure.
    assert data["status"] == "degraded"
    assert "1 of 3 search queries failed" in data["warning"]
    assert "'q2'" in data["warning"]
    assert "provenance" not in data["warning"]
    assert SERPAPI_KEY not in res.text
    assert GEMINI_KEY not in res.text


def test_research_inline_urls_not_in_evidence_normalization():
    check = research_module.inline_urls_not_in_evidence

    evidence = [
        {"url": "https://example.com/a"},
        {"url": "https://example.com/b/"},
        {"url": None},
    ]

    # Matching follows normalize_url: case, trailing slashes and fragments are
    # ignored, and trailing punctuation after a URL is stripped first. Repeated
    # unsupported URLs are reported once.
    answer = (
        "See https://EXAMPLE.com/a/ and (https://example.com/b#top). "
        "Unverified: https://example.com/missing, and again "
        "https://example.com/missing. Also https://example.com/c/page)."
    )
    assert check(answer, evidence) == [
        "https://example.com/missing",
        "https://example.com/c/page",
    ]

    # An answer without any URLs never flags anything.
    assert check("No links here.", evidence) == []


def test_research_accepts_inline_urls_from_evidence(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    answer = (
        "Compare https://EXAMPLE.com/a/ and (https://example.com/b#top); "
        "the first is the stronger match."
    )
    mock_gemini(monkeypatch, gemini_ok(plan=["q1"], answer=answer))
    mock_serpapi(
        monkeypatch,
        serpapi_ok(
            default=[
                serp_result("A", "https://example.com/a", "Snippet A", "example.com"),
                serp_result("B", "https://example.com/b/", "Snippet B", "example.com"),
            ]
        ),
    )

    res = client.post("/research", json={"question": "Any question"})

    assert res.status_code == 200
    data = res.json()

    # Case, trailing slash, and fragment differences all normalize to evidence
    # URLs, so this stays a clean success with the original response schema.
    assert data["answer"] == answer
    assert data["citations"] == ["https://example.com/a", "https://example.com/b/"]
    assert set(data) == {"question", "queries", "sources", "answer", "citations"}
    assert len(data["sources"]) == 2
    assert SERPAPI_KEY not in res.text
    assert GEMINI_KEY not in res.text


def test_research_flags_inline_urls_not_in_evidence(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    answer = (
        "According to https://example.com/a the trend is clear. "
        "A second report (https://evil.example.com/fake) claims otherwise."
    )
    mock_gemini(monkeypatch, gemini_ok(plan=["q1"], answer=answer))
    mock_serpapi(
        monkeypatch,
        serpapi_ok(
            default=[
                serp_result("A", "https://example.com/a", "Snippet A", "example.com")
            ]
        ),
    )

    res = client.post("/research", json={"question": "Any question"})

    assert res.status_code == 200
    data = res.json()

    # The answer is returned unchanged, but no longer presented as a fully
    # successful synthesis: the unsupported URL is flagged.
    assert data["answer"] == answer
    assert data["status"] == "degraded"
    assert "https://evil.example.com/fake" in data["warning"]
    assert "not part of the evidence supplied to synthesis" in data["warning"]
    assert "provenance" in data["warning"]
    assert "does not verify whether any source supports" in data["warning"]

    # Real retrieved sources and citations are preserved; nothing is fabricated
    # or substituted for the flagged URL.
    assert [source["url"] for source in data["sources"]] == ["https://example.com/a"]
    assert data["citations"] == ["https://example.com/a"]
    assert "https://evil.example.com/fake" not in data["citations"]
    assert SERPAPI_KEY not in res.text
    assert GEMINI_KEY not in res.text


def test_research_synthesis_instruction_requires_numeric_attribution():
    instruction = research_module.SYNTHESIS_INSTRUCTION

    assert "Attribute every numerical claim to the source that reports it" in instruction
    assert "source-reported estimates" in instruction
    assert "your own inference" in instruction
    assert "say so explicitly" in instruction
    assert "independently verified facts" in instruction
    assert "never cite URLs from outside the evidence" in instruction
    assert "untrusted external data" in instruction


def test_research_planner_instruction_requires_complementary_angles():
    instruction = research_module.PLANNER_INSTRUCTION

    assert "complementary angles" in instruction
    assert "distinct aspect" in instruction
    assert "never be a rewording of another query" in instruction


def test_research_citations_are_scoped_to_synthesis_evidence(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    plan = ["q1", "q2", "q3"]
    collected = 12

    mock_gemini(
        monkeypatch,
        gemini_ok(plan=plan, answer="Answer citing https://example.com/q1/1."),
    )

    def serpapi(request):
        query = request.url.params["q"]
        return httpx.Response(
            200,
            json={
                "organic_results": [
                    serp_result(
                        f"{query} result {rank}",
                        f"https://example.com/{query}/{rank}",
                        f"Snippet {rank} for {query}",
                        "example.com",
                    )
                    for rank in range(1, 5)
                ]
            },
        )

    mock_serpapi(monkeypatch, serpapi)

    res = client.post("/research", json={"question": "Compare the options"})

    assert res.status_code == 200
    data = res.json()

    # All 12 collected sources are returned, but citations contain only the 8
    # actual retrieved URLs that were supplied to synthesis.
    assert len(data["sources"]) == collected
    assert data["citations"] == [
        "https://example.com/q1/1",
        "https://example.com/q2/1",
        "https://example.com/q3/1",
        "https://example.com/q1/2",
        "https://example.com/q2/2",
        "https://example.com/q3/2",
        "https://example.com/q1/3",
        "https://example.com/q2/3",
    ]
    source_urls = {source["url"] for source in data["sources"]}
    assert set(data["citations"]) <= source_urls
    assert "https://example.com/q3/3" in source_urls
    assert "https://example.com/q3/3" not in data["citations"]

    # The answer cites evidence, so this remains an undegraded response.
    assert "status" not in data
    assert "warning" not in data


def test_research_repairs_malformed_citation_links(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    answer = (
        "Per the [IBM report]([https://example.com/a](https://example.com/a)), "
        "downtime drops sharply. See also [Vendor B](https://example.com/b)."
    )
    repaired = (
        "Per the [IBM report](https://example.com/a), "
        "downtime drops sharply. See also [Vendor B](https://example.com/b)."
    )
    mock_gemini(monkeypatch, gemini_ok(plan=["q1"], answer=answer))
    mock_serpapi(
        monkeypatch,
        serpapi_ok(
            default=[
                serp_result("A", "https://example.com/a", "Snippet A", "example.com"),
                serp_result("B", "https://example.com/b", "Snippet B", "example.com"),
            ]
        ),
    )

    res = client.post("/research", json={"question": "Any question"})

    assert res.status_code == 200
    data = res.json()

    # The nested `[text]([url](url))` link is repaired because the URL is part
    # of the evidence; the valid link is left alone and nothing is degraded.
    assert data["answer"] == repaired
    assert "]([" not in data["answer"]
    assert "status" not in data
    assert data["citations"] == ["https://example.com/a", "https://example.com/b"]
    assert SERPAPI_KEY not in res.text
    assert GEMINI_KEY not in res.text


def test_research_keeps_valid_citation_links(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    answer = (
        "Per the [IBM report](https://example.com/a), downtime drops sharply. "
        "Raw URL https://example.com/b agrees."
    )
    mock_gemini(monkeypatch, gemini_ok(plan=["q1"], answer=answer))
    mock_serpapi(
        monkeypatch,
        serpapi_ok(
            default=[
                serp_result("A", "https://example.com/a", "Snippet A", "example.com"),
                serp_result("B", "https://example.com/b", "Snippet B", "example.com"),
            ]
        ),
    )

    res = client.post("/research", json={"question": "Any question"})

    assert res.status_code == 200
    data = res.json()

    # Valid Markdown links pass through byte-for-byte, undegraded.
    assert data["answer"] == answer
    assert "status" not in data
    assert data["citations"] == ["https://example.com/a", "https://example.com/b"]
    assert SERPAPI_KEY not in res.text
    assert GEMINI_KEY not in res.text


def test_research_does_not_repair_unsupported_malformed_links(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    monkeypatch.setenv("SERPAPI_API_KEY", SERPAPI_KEY)

    answer = (
        "Per the [IBM report]([https://evil.example.com/fake](https://evil.example.com/fake)), "
        "downtime drops sharply."
    )
    mock_gemini(monkeypatch, gemini_ok(plan=["q1"], answer=answer))
    mock_serpapi(
        monkeypatch,
        serpapi_ok(
            default=[
                serp_result("A", "https://example.com/a", "Snippet A", "example.com")
            ]
        ),
    )

    res = client.post("/research", json={"question": "Any question"})

    assert res.status_code == 200
    data = res.json()

    # The unsupported URL is neither repaired, substituted, nor approved: the
    # malformed link is returned unchanged and the provenance check degrades
    # the response with the URL flagged.
    assert data["answer"] == answer
    assert data["status"] == "degraded"
    assert "https://evil.example.com/fake" in data["warning"]
    assert "not part of the evidence supplied to synthesis" in data["warning"]
    assert "provenance" in data["warning"]
    assert [source["url"] for source in data["sources"]] == ["https://example.com/a"]
    assert data["citations"] == ["https://example.com/a"]
    assert "https://evil.example.com/fake" not in data["citations"]
    assert SERPAPI_KEY not in res.text
    assert GEMINI_KEY not in res.text
