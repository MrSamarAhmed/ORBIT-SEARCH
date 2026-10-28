# ORBIT Search — Execution Guide

## Environment Variables

ORBIT Search (`/search`, `/research`) reads its credentials from the process
environment:

| Variable | Required | Default |
|---|---|---|
| `SERPAPI_API_KEY` | yes — SerpApi key used by `/search` and `/research` | — |
| `GEMINI_API_KEY` | yes — Gemini API key used by `/research` | — |
| `GEMINI_MODEL` | no | `gemini-3.8-flash` |

The application reads `GEMINI_MODEL` at import time, so changing it requires
restarting the application.

The app does not auto-load `.env` files; export the variables or pass them with
`docker run -e`. See `.env.example` for a template (variable names only, no
keys).

## Local Toolchain & Execution

```bash
export PATH="$HOME/.local/bin:$PATH"
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt

# Required for /search and /research
export SERPAPI_API_KEY=...
export GEMINI_API_KEY=...
# Optional; default gemini-3.8-flash, applied at import time
export GEMINI_MODEL=gemini-3.8-flash

# Run server
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
```

## ORBIT Search Endpoints

### GET /

Dependency-free research workspace (HTML/CSS/vanilla JS) that calls
`POST /research` and renders the answer, research coverage (queries executed,
sources collected vs. cited, per-query source titles), the full source list,
and degraded-mode warnings. Requires no browser-side credentials.

Open `http://localhost:8080/` after starting the server.

### GET /search?q=<query>

Web search via SerpApi. A missing `SERPAPI_API_KEY` returns
`500 configuration_error`.

```bash
curl "http://localhost:8080/search?q=predictive+maintenance+ai"
```

Response:

```json
{
  "query": "predictive maintenance ai",
  "results": [
    {
      "position": 1,
      "title": "...",
      "url": "https://...",
      "snippet": "...",
      "source": "..."
    }
  ]
}
```

### POST /research

JSON request body with a single `question` string:

```bash
curl -X POST http://localhost:8080/research \
  -H "Content-Type: application/json" \
  -d '{"question": "Best AI for predictive maintenance?"}'
```

Response (success):

```json
{
  "question": "Best AI for predictive maintenance?",
  "queries": ["...", "..."],
  "sources": [
    {
      "title": "...",
      "url": "https://...",
      "snippet": "...",
      "source": "...",
      "query": "..."
    }
  ],
  "answer": "...",
  "citations": ["https://..."]
}
```

Degraded responses keep the same fields and add `"status": "degraded"` plus a
`"warning"` string — for example when one search query failed, when synthesis
was unavailable (`answer` is then `null`), or when the answer cited a URL
outside the synthesis evidence. Success responses carry no extra fields.

Validation: a missing or blank `question` returns `422 validation_failed`; a
non-string `question`, invalid JSON, or a non-object body returns
`400 malformed_request`. Errors use the shared envelope
`{"error": {"code": "...", "message": "..."}}`.

## Docker Build & Run

```bash
docker build -t orbit-search .

# API keys are passed at runtime; never baked into the image.
docker run --rm -p 8080:8080 \
  -e PORT=8080 \
  -e SERPAPI_API_KEY=... \
  -e GEMINI_API_KEY=... \
  orbit-search

# Optional model override (read at container start, i.e. app import time):
#   -e GEMINI_MODEL=gemini-3.8-flash
```

## Health Check

```bash
curl http://localhost:8080/health
```

## Tests

```bash
# Full regression suite, including provider-boundary checks (81 tests)
.venv/bin/python -m pytest -q
```

`tests/test_app_js_logic.py` exercises `app/static/app.js` (including the
degraded HTTP 200 / `answer: null` response) in a fake-DOM sandbox under
Node.js with mocked fetch. It needs Node on `PATH` and fails without it, so a
run that silently skipped the frontend cannot look green; use
`ORBITSEARCH_ALLOW_NO_NODE=1` only to skip those 9 tests deliberately.

Verified 2026-10-28 in an isolated Linux container, Python 3.12.16 + Node
20.20.2: 81 passed, 0 skipped, one Starlette/httpx deprecation warning. Missing
Node produced 9 errors; explicit opt-in produced 9 skips. The same day, a real
browser loaded the unmodified `index.html` + `app.js` against a stub that
returned synthetic `/research` payloads (no SerpApi or Gemini access) for
degraded, cited and uncited answers, including queries named `constructor` and
`__proto__`; all three rendered as expected — degraded showed the banner and the
empty-answer state with the answer panel hidden, and the cited/uncited cases
reported 2/3 and 0/5 in `stat-cited`/`stat-uncited`.
These checks do not validate live SerpApi/Gemini access or model availability.

The API `citations` field lists selected evidence, not necessarily URLs cited
in the answer. The UI counts selected URLs mentioned in answer text; this is
a heuristic, not claim verification. Avoid verbose HTTP client logging:
SerpApi credentials are sent as query parameters and can appear in request logs.

All upstream HTTP is mocked in the test suite — no real SerpApi or Gemini
calls are made and no quota is consumed.
