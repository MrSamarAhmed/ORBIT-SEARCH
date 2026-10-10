# ORBIT Search

**ORBIT Search is an AI-powered research workspace that decomposes complex
questions into focused web searches, gathers evidence through SerpApi, and uses
Gemini to synthesize cited research answers.**

It is a small, self-contained FastAPI application with a dependency-free
browser interface. Ask a research question, and ORBIT Search plans several
searches, runs them against the live web, collects and deduplicates the
evidence, and returns a structured answer in which every citation is a URL the
run actually retrieved.

## Problem

A single web search answers simple lookup questions, but real research
questions ("Which approach should we use for X, and why?") need several
searches, cross-checking between sources, and a written answer that can be
traced back to where each claim came from. Doing that by hand is slow; asking a
plain LLM gives fluent text with no verifiable grounding.

ORBIT Search treats research as a pipeline — plan, search, collect, synthesize —
so the output is inspectable instead of a black box, and so partial failures
degrade honestly instead of discarding real evidence.

## Key features

- **Query planning** — the question is decomposed into focused search queries
  covering complementary angles; reworded near-duplicates are collapsed so no
  search is wasted on the same angle.
- **Live web search** — every planned query runs against SerpApi; one failed
  query does not discard the evidence of the others.
- **Evidence collection** — results are deduplicated by normalized URL and the
  strongest sources are selected across queries.
- **Cited synthesis** — an answer written from the collected evidence only,
  with citation URLs checked against the retrieved sources.
- **Research coverage transparency** — the workspace shows which queries ran,
  how many sources each produced, and which sources the answer cited.
- **Citation inspector** — clicking a citation in the answer locates the
  matching source card in the evidence list.
- **Graceful degradation** — when Gemini planning or synthesis fails or times
  out, the service returns the real collected evidence with an explicit
  warning instead of an invented answer.

## How a research run works

1. `POST /research` receives `{question}`.
2. Gemini plans a set of sub-queries (with a deterministic fallback if the
   planner is unavailable or times out).
3. Each query is searched via SerpApi sequentially; per-query failures are
   isolated and named in the response warning.
4. Results are deduplicated by normalized URL and a balanced cross-query
   selection is kept as evidence.
5. Gemini synthesizes an answer from the evidence only.
6. Malformed citations are repaired; inline URLs not present in the evidence
   are flagged in a warning.
7. The response carries `{question, queries, sources, answer, citations}`,
   plus `"status": "degraded"` and a `"warning"` when anything upstream was
   limited.

## Architecture

```text
app/
├── main.py       FastAPI application: app factory, /health, workspace
│                 hosting at /, whitelisted /static/{asset} serving
├── search.py     SerpApi client: query execution and normalization into
│                 {title, url, snippet, source, query} records
├── research.py   Research pipeline: Gemini planning (+ deterministic
│                 fallback), per-query search loop, evidence dedup and
│                 selection, Gemini synthesis, citation repair and
│                 provenance checks, degraded-response handling
├── errors.py     Shared APIError exception and the
│                 {"error": {"code", "message"}} envelope handlers
└── static/       Browser workspace: index.html, styles.css, app.js
tests/           Focused regression suite (all upstream HTTP mocked)
```

The pipeline is intentionally split into planning, retrieval, and synthesis
stages so each stage's inputs and outputs are visible in the API response:
which queries ran, which sources each produced, and which sources the answer
cited.

## Technology stack

| Layer | Technology |
|---|---|
| HTTP service | Python 3.12, FastAPI, Uvicorn |
| Live web search | SerpApi (Google search results API) |
| Query planning & synthesis | Google Gemini (`gemini-3.8-flash`) |
| Outbound HTTP | httpx (async, with timeouts and bounded retries) |
| Frontend | Vanilla HTML/CSS/JavaScript — no build step, no framework |
| Tests | pytest (+ a Node.js sandbox for the frontend script) |

## Installation (macOS / Linux)

Requires Python 3.12 or later.

```bash
git clone https://github.com/MrSamarAhmed/ORBIT-SEARCH.git
cd ORBIT-SEARCH
```

### Virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If you use [uv](https://docs.astral.sh/uv/), the equivalent is:

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
```

## Environment variables

ORBIT Search reads its credentials from the process environment; it does not
auto-load `.env` files. Copy `.env.example`, fill in your keys, and export the
variables — or pass them with `docker run -e`.

| Variable | Required | Default |
|---|---|---|
| `SERPAPI_API_KEY` | yes — used by `/search` and `/research` | — |
| `GEMINI_API_KEY` | yes — used by `/research` | — |
| `GEMINI_MODEL` | no | `gemini-3.8-flash` |

`GEMINI_MODEL` is read at application import time, so changing it requires
restarting the application. Never put real API keys in `.env.example`.

```bash
export SERPAPI_API_KEY=...
export GEMINI_API_KEY=...
```

## Starting the application

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
```

Then:

```bash
curl http://localhost:8080/health
# {"status":"ok"}

# Browser workspace
open http://localhost:8080/

# Search (GET with a query parameter)
curl "http://localhost:8080/search?q=predictive+maintenance+ai"

# Research (POST with a JSON request body)
curl -X POST http://localhost:8080/research \
  -H "Content-Type: application/json" \
  -d '{"question": "Best AI for predictive maintenance?"}'
```

### Docker

```bash
docker build -t orbit-search .

# API keys are passed at runtime; never baked into the image.
docker run --rm -p 8080:8080 \
  -e PORT=8080 \
  -e SERPAPI_API_KEY=... \
  -e GEMINI_API_KEY=... \
  orbit-search
```

## Running the tests

All upstream HTTP is mocked — the suite makes no real SerpApi or Gemini calls
and consumes no quota.

```bash
.venv/bin/python -m pytest -q tests/test_search.py tests/test_research.py tests/test_frontend.py tests/test_app_js_logic.py
```

That is 64 tests: search 8, research 42, frontend 6, and 8 app.js behavior
tests. The app.js tests run the real frontend script with mocked fetch in a
Node.js sandbox and skip automatically when Node.js is not installed.

## API endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Research workspace (dependency-free HTML/CSS/JS) |
| `GET /search?q=...` | Live web search normalized to JSON |
| `POST /research` | Full research pipeline: plan → search → evidence → cited answer |
| `GET /health` | Liveness check |
| `GET /docs` | Auto-generated OpenAPI UI |
| `GET /openapi.json` | OpenAPI schema |

### `GET /search?q=<query>`

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

A missing `SERPAPI_API_KEY` returns `500 configuration_error`; a SerpApi
timeout returns `504 upstream_timeout`.

### `POST /research`

Request body: `{"question": "..."}`. A missing or blank question returns
`422 validation_failed`; a non-string question, invalid JSON, or a non-object
body returns `400 malformed_request`. Errors use the shared envelope
`{"error": {"code", "message"}}`.

Success response:

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

## Graceful degradation

The application never trades honesty for a confident-looking answer:

- **One or more failed search queries** → `200` with the real evidence from
  the remaining queries and a warning naming the failed queries.
- **Gemini planning unavailable or timed out** → the run continues with a
  deterministic keyword-based query plan; the evidence and answer are
  unaffected.
- **Gemini synthesis unavailable or timed out** → `200` with
  `"status": "degraded"`, `answer: null`, and the full collected evidence
  (sources, citations, queries) preserved, plus a warning explaining what
  failed. **The retrieved evidence is never discarded when synthesis fails.**
- **Answer cites a URL outside the evidence** → the response is still
  returned, with a warning flagging the unproven citation.

Degraded responses keep the same fields as success responses and add
`"status": "degraded"` plus a `"warning"` string; success responses carry no
extra fields.

## Citations — and their limits

A citation in the answer means the URL was **retrieved as part of this run's
evidence** — the pipeline checks provenance, not truth. It does not verify
that a source actually supports every claim attached to it. Answer text is
synthesized by a model from search snippets and must be reviewed against the
linked sources; the workspace states this explicitly.

## Known limitations

- **No caching** — identical questions re-run the full pipeline (cost and
  latency are paid each time).
- **Sequential searches** — queries run one at a time, not in parallel.
- **Evidence is snippet-level** — pages are not fetched or fully read.
- **Citations are provenance-checked, not claim-verified** (see above).
- **Synthesis depends on Gemini quota** — when quota is exhausted the service
  returns a degraded, evidence-only response with `answer: null`.
- **Local, single-process service** — designed for local and demo use, not
  for multi-user production deployment; there is no authentication.
- **No persistence** — research runs are stateless; nothing is stored
  between requests.

## Security notes

- API keys are read from environment variables only; they are never
  hard-coded, logged, or sent to the frontend.
- `.env` is gitignored; `.env.example` contains variable names only.
- Static file serving is restricted to an allowlist (`styles.css`, `app.js`)
  plus the `index.html` workspace — arbitrary path traversal is rejected.
- Search evidence returned by SerpApi is treated as untrusted external data;
  synthesis instructions tell the model to ignore any instructions embedded
  inside it.
- Upstream errors are reported with fixed-format messages and status codes;
  response headers and bodies are never echoed into warnings.

## Demo

A timed three-minute demonstration script — including the honest fallback path
for when Gemini quota is exhausted — is in [`DEMO.md`](DEMO.md). To follow it,
start the server locally (`uvicorn app.main:app --port 8080`), open
`http://localhost:8080/` in a browser, and walk the script. The workspace is
served by the same process, so no separate frontend setup is needed.

## Project layout

```text
ORBIT-SEARCH/
├── README.md
├── RUN.md              # detailed execution guide
├── DEMO.md             # timed demo script
├── .env.example        # environment variable template (no values)
├── .gitignore
├── requirements.txt
├── Dockerfile
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── search.py
│   ├── research.py
│   ├── errors.py
│   └── static/
│       ├── index.html
│       ├── styles.css
│       └── app.js
└── tests/
    ├── conftest.py
    ├── test_search.py
    ├── test_research.py
    ├── test_frontend.py
    └── test_app_js_logic.py
```

## Status

ORBIT Search runs locally from this repository (or via Docker). It has not
been deployed to any hosted environment.
