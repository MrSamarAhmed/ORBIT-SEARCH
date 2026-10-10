import os

import httpx
from fastapi import APIRouter

from app.errors import APIError

router = APIRouter(tags=["search"])

SERPAPI_URL = "https://serpapi.com/search.json"
SERPAPI_TIMEOUT_SECONDS = 20.0


def serpapi_client() -> httpx.AsyncClient:
    # Factory so tests can inject an httpx.MockTransport-backed client.
    return httpx.AsyncClient(timeout=SERPAPI_TIMEOUT_SECONDS)


def normalize_payload(payload: dict, query: str) -> dict:
    organic = payload.get("organic_results", [])
    if not isinstance(organic, list):
        raise APIError(
            502,
            "upstream_error",
            "SerpApi returned an unexpected response shape",
        )

    results = []
    for fallback_position, item in enumerate(organic, start=1):
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "position": item.get("position", fallback_position),
                "title": item.get("title"),
                "url": item.get("link"),
                "snippet": item.get("snippet"),
                "source": item.get("source") or item.get("displayed_link"),
            }
        )

    return {"query": query, "results": results}


async def run_search(query: str) -> dict:
    api_key = os.environ.get("SERPAPI_API_KEY")
    if not api_key:
        raise APIError(
            500,
            "configuration_error",
            "SERPAPI_API_KEY is not configured",
        )

    try:
        async with serpapi_client() as client:
            response = await client.get(
                SERPAPI_URL,
                params={
                    "engine": "google",
                    "q": query,
                    "api_key": api_key,
                },
            )
    except httpx.TimeoutException:
        raise APIError(504, "upstream_timeout", "SerpApi request timed out")
    except httpx.HTTPError:
        raise APIError(502, "upstream_error", "Failed to reach SerpApi")

    if response.status_code != 200:
        raise APIError(
            502,
            "upstream_error",
            f"SerpApi request failed with status {response.status_code}",
        )

    try:
        payload = response.json()
    except ValueError:
        raise APIError(502, "upstream_error", "SerpApi returned a malformed response")

    if not isinstance(payload, dict):
        raise APIError(
            502,
            "upstream_error",
            "SerpApi returned an unexpected response shape",
        )

    if payload.get("error"):
        raise APIError(502, "upstream_error", f"SerpApi error: {payload['error']}")

    return normalize_payload(payload, query)


@router.get("/search")
async def search(q: str | None = None):
    query = (q or "").strip()
    if not query:
        raise APIError(
            400,
            "validation_failed",
            "Query parameter 'q' must be a non-empty string",
        )

    return await run_search(query)
