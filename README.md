# ORBIT Search

**ORBIT Search is an evidence-oriented research workflow that combines live web
search, query planning, source collection, evidence selection, and AI-generated
synthesis with citations.**

It is a small, self-contained FastAPI application with a dependency-free
browser interface. Ask a research question, and ORBIT Search plans several
searches, runs them against the live web through SerpApi, collects and
deduplicates the evidence, and returns a structured answer in which every
citation is a URL the run actually retrieved.

## Demo

Watch the ORBIT Search demonstration:

[Watch the demo video](https://drive.google.com/file/d/1Dqts1IbtJBCVsi2bnr4z5Y0IWkfTvSvi/view?usp=drive_link)

> `https://drive.google.com/file/d/1Dqts1IbtJBCVsi2bnr4z5Y0IWkfTvSvi/view?usp=drive_link` is a placeholder. The recorded MP4 exists in this repository
> at `demo-video/ORBIT_Search_SerpApi_Hackathon_Demo.mp4` (2 minutes 1 second,
> 1920×1080, narrated and subtitled) and has **not** been uploaded to a public
> URL yet, so the link above does not resolve until it is hosted.

The demo walks one genuine research run end to end: entering a question, the
planned sub-queries and per-query source counts returned by SerpApi, the source
cards behind the answer, Gemini's synthesized answer with clickable inline
citations, and an honest degraded run in which Gemini synthesis was
rate-limited — the evidence is still returned and no answer is invented. It
then shows the application source and the actual pytest result for the suite.

## Problem

A single web search answers simple lookup questions, but real research
questions ("Which approach should we use for X, and why?") need several
searches, cross-checking between sources, and a written answer that can be
traced back to where each claim came from. Doing that by hand is slow; asking a
plain LLM gives fluent text with no verifiable grounding.

## Solution

ORBIT Search treats research as an inspectable pipeline — plan, search,
collect, select, synthesize — rather than a single prompt. Every stage's input
and output is returned in the API response, so a judge can see which queries
ran, which sources each query produced, which sources were kept as evidence,
and which of them the answer cited. When a stage fails, the run degrades
explicitly instead of pretending it succeeded:

```text
Research question
    -> Query planning
    -> SerpApi search
    -> Evidence collection and selection
    -> Gemini synthesis when available
    -> Answer and citations
```

If Gemini synthesis is unavailable, the application preserves the real search
evidence and returns a degraded response (`answer: null` plus a warning)
instead of generating an answer it cannot support.

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
- **Browser-based interface** — a dependency-free research workspace served by
  the same FastAPI process; no frontend build step.
- **Automated tests** — a focused pytest suite that mocks all upstream HTTP,
  so the suite runs without SerpApi or Gemini quota.

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

## Prerequisites

- Python 3.12 or later
- A [SerpApi](https://serpapi.com) API key
- A [Google Gemini](https://aistudio.google.com/apikey) API key
- Optional: Docker, and Node.js (the frontend behaviour tests run the real
  `app.js` in a Node sandbox and skip automatically when Node.js is absent)

## Installation (macOS / Linux)

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
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
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
- **Demo video not yet hosted** — the link in [Demo](#demo) is a placeholder
  until the recorded MP4 is published to a public URL.

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

## Live walkthrough script

Prefer driving the application yourself? A timed three-minute walkthrough —
including the honest fallback path for when Gemini quota is exhausted — is in
[`DEMO.md`](DEMO.md). To follow it, start the server locally
(`uvicorn app.main:app --port 8080`), open `http://localhost:8080/` in a
browser, and walk the script. The workspace is served by the same process, so
no separate frontend setup is needed.

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
├── tests/
│   ├── conftest.py
│   ├── test_search.py
│   ├── test_research.py
│   ├── test_frontend.py
│   └── test_app_js_logic.py
└── demo-video/
    ├── README.md       # how to regenerate the demo MP4
    ├── render/         # frame, narration and assembly scripts
    └── assets/         # text inputs the frame script renders
```

The rendered MP4 and every generated media file (narration audio, intermediate
clips, screenshot frames, caption files, the vendored FFmpeg binary) are
gitignored; only the scripts and their small text inputs are versioned. See
[`demo-video/README.md`](demo-video/README.md).

## Status

ORBIT Search runs locally from this repository (or via Docker). It has not
been deployed to any hosted environment.
