# ORBIT — Autonomous Operations & Reliability Agent

**ORBIT** is a standalone, general-purpose autonomous operations and reliability
platform, operated here as a three-agent software factory (Architect → Builder
→ Reviewer) cooperating through BAND.

ORBIT decomposes a written specification into implementation tasks, dispatches
coding work, independently reviews builds, and supports rejection → revision →
approval cycles. The delivered Stage 1 artifact is a restaurant
table-reservation HTTP service in `stage-1/`; the factory run and supporting
artifacts are preserved under `evidence/`.

## Submission scope

This submission targets **Stage 1** of the Dark Factory Tablekeeper track.

The shipped Stage 1 artifact is contained in `stage-1/` and includes the Docker
configuration, execution guide, FastAPI service, database schema, and tests
required for Stage 1.

## Layout

```text
result/
├── README.md
├── FACTORY.md
├── mandates/
│   ├── architect.md
│   ├── builder.md
│   └── reviewer.md
├── room.json
├── stage-1/
│   ├── Dockerfile
│   ├── RUN.md
│   ├── DEMO.md
│   ├── requirements.txt
│   ├── app/
│   │   └── static/        # research workspace: index.html, styles.css, app.js
│   └── tests/
└── evidence/
    ├── state.json
    ├── events.jsonl
    ├── builds/
    └── reviews/
```

## Quick start

### Local

```bash
cd stage-1

uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt

.venv/bin/python -m pytest
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080
```

### Docker

```bash
cd stage-1

docker build -t orbit-search .
docker run --rm -p 8080:8080 -e PORT=8080 orbit-search

curl http://localhost:8080/health
```

## ORBIT Search

**ORBIT Search is an AI research agent that turns live web search into
structured, source-grounded research.** It layers query planning, evidence
collection, and cited answer synthesis on top of the Stage 1 service, and ships
with a dependency-free research workspace served at `GET /`.

### 1. Problem

A single web search answers simple lookup questions, but real research
questions ("Which approach should we use for X, and why?") need several
searches, cross-checking between sources, and a written answer that can be
traced back to where each claim came from. Doing that by hand is slow; asking a
plain LLM gives fluent text with no verifiable grounding.

### 2. Who it is for

Developers, analysts, and students who want a cited first draft of research on
a current topic — with the sources in hand so they can verify it — rather than
an unverifiable chatbot paragraph.

### 3. Why it is multi-step

One query rarely covers a real question. ORBIT Search treats research as a
pipeline: plan several focused queries, run each against the live web, collect
and deduplicate evidence, then synthesize an answer that is allowed to use only
what was actually retrieved. Splitting planning, retrieval, and synthesis is
what makes the output inspectable instead of a black box.

### 4. Core capabilities

- **Query planning** — the question is decomposed into focused search queries
  covering complementary angles; reworded near-duplicates are collapsed so no
  search is wasted on the same angle.
- **Live web search** — every planned query runs against SerpApi; one failed
  query does not discard the evidence of the others.
- **Evidence collection** — results are deduplicated by normalized URL and the
  strongest sources are selected across queries.
- **Cited synthesis** — an answer written from the collected evidence only,
  with citations checked against the retrieved sources.
- **Research coverage transparency** — the workspace shows which queries ran,
  how many sources each produced, and which sources the answer cited.
- **Citation inspector** — clicking a citation in the answer locates the
  matching source card in the evidence list.
- **Honest degradation** — partial or total upstream failures produce a
  degraded response with the real evidence and a warning, never a fabricated
  answer.

### 5. What SerpApi does

SerpApi is the live-search layer. Each planned query is executed via SerpApi
and normalized into `{title, url, snippet, source, query}` records attributed
to the query that found them. Without SerpApi there is no evidence layer at
all — every answer is anchored in these retrieved results.

### 6. What Gemini does

Gemini is used twice per research run: first as a **planner** that turns the
question into a set of search queries, then as a **synthesizer** that writes the
structured answer. Synthesis is constrained to the collected evidence; the
model is never asked to supply facts from memory, and citation URLs it emits
are repaired and checked against the evidence before the response is returned.

### 7. How a research run works

1. `POST /research` receives `{question}`.
2. Gemini plans a set of sub-queries.
3. Each query is searched via SerpApi sequentially; per-query failures are
   isolated and reported.
4. Results are deduplicated by normalized URL and a balanced cross-query
   selection is kept as evidence.
5. Gemini synthesizes an answer from the evidence.
6. Malformed citations are repaired; inline URLs not present in the evidence
   are flagged in a warning.
7. The response carries `{question, queries, sources, answer, citations}`, plus
   `"status": "degraded"` and a `"warning"` when anything upstream was limited.

The browser workspace at `GET /` renders this full response, including the
coverage view (queries executed, sources collected vs. cited, per-query source
titles) built only from fields the endpoint already returns.

### 8. Citations — and their limits

A citation in the answer means the URL was **retrieved as part of this run's
evidence** — the pipeline checks provenance, not truth. It does not verify that
the source supports every claim attached to it. Answer text is synthesized by a
model and must be reviewed against the linked sources; the UI states this
explicitly in the footer.

### 9. Errors and degraded responses

- One or more failed search queries → `200` with real evidence from the
  remaining queries and a warning naming the failed queries.
- Gemini unavailable (rate limit, upstream 5xx) → `200` with
  `"status": "degraded"`, `answer: null`, the collected evidence, and a warning
  that includes the upstream status code. No answer is invented.
- Invalid request shape → the standard `{"error": {"code", "message"}}`
  envelope with `400`/`401`/`422` as appropriate.
- SerpApi timeout → a genuine `504` failure for `/search`; in `/research`,
  other queries may still produce evidence.

### 10. Setup

Required environment variables:

| Variable | Required | Default |
|---|---|---|
| `SERPAPI_API_KEY` | yes — used by `/search` and `/research` | — |
| `GEMINI_API_KEY` | yes — used by `/research` | — |
| `GEMINI_MODEL` | no | `gemini-3.8-flash` |

`GEMINI_MODEL` is read at application import time, so changing it requires
restarting the application. See `.env.example` for a template — never put real
API keys in it. Keys are read server-side only; the frontend never sees them.

```bash
export SERPAPI_API_KEY=...
export GEMINI_API_KEY=...

# Workspace (browser)
open http://localhost:8080/

# Search (GET with a query parameter)
curl "http://localhost:8080/search?q=predictive+maintenance+ai"

# Research (POST with a JSON request body)
curl -X POST http://localhost:8080/research \
  -H "Content-Type: application/json" \
  -d '{"question": "Best AI for predictive maintenance?"}'
```

Docker — pass the keys at runtime; never bake them into the image:

```bash
docker run --rm -p 8080:8080 \
  -e PORT=8080 \
  -e SERPAPI_API_KEY=... \
  -e GEMINI_API_KEY=... \
  orbit-search
```

### 11. Endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Research workspace (dependency-free HTML/CSS/JS) |
| `GET /search?q=...` | Live web search normalized to JSON |
| `POST /research` | Full research pipeline: plan → search → evidence → cited answer |
| `GET /docs` | Auto-generated OpenAPI UI |
| `GET /health` | Liveness check |

### 12. Testing

Focused regression tests (all upstream HTTP mocked — no real SerpApi or Gemini
calls, no quota consumed):

```bash
.venv/bin/python -m pytest -q tests/test_search.py tests/test_research.py tests/test_frontend.py tests/test_app_js_logic.py
```

The 64 focused tests (search 8, research 42, frontend 6, app.js behavior 8)
currently pass; the app.js tests run the real frontend script with mocked
fetch in a Node.js sandbox and skip automatically when Node.js is not
installed. The full `.venv/bin/python -m pytest` run also collects
`tests/test_tablekeeper.py`, which has 19 known historical failures due to
stale test expectations; those predate the search/research work and are not
regressions. Full execution details are in `stage-1/RUN.md`.

### 13. Known limitations

- **No caching** — identical questions re-run the full pipeline (cost and
  latency are paid each time).
- **Sequential searches** — queries run one at a time, not in parallel.
- **Evidence is snippet-level** — pages are not fetched or fully read.
- **Citations are provenance-checked, not claim-verified** (see §8).
- **Synthesis depends on Gemini quota** — when quota is exhausted the service
  returns a degraded, evidence-only response with `answer: null`.
- **Local, single-process service** — SQLite storage and an in-process rate
  limiter; not built for multi-user deployment.

### Demo

A three-minute demonstration script, including an honest fallback plan for when
Gemini quota is exhausted, is in `stage-1/DEMO.md`.

## Official Stage 1 verification

The final Stage 1 artifact was validated with the official Dark Factory
harness.

| Check | Result |
|---|---|
| Official Stage 1 test suite | **120/120 passed** |
| Official Stage 1 failures | **0** |
| Official Stage 1 errors | **0** |
| Official isolated Stage 1 harness run | **PASS** |
| Factory Gates 1 and 2 | **PASS** |
| Gate 4 mandate validation | **PASS** |
| Stage 1 Docker build / serve / health | **PASS** |

The official Stage 1 validation collected:

- `test_health_reset_auth.py` — 12/12
- `test_reservations.py` — 37/37
- `test_restaurants_availability.py` — 18/18
- `test_retries_time_input.py` — 20/20
- `test_sample.py` — 20/20
- `test_seeded_state.py` — 13/13

**Total: 120/120 passed.**

The factory's original development artifacts contain an earlier 19-test suite.
Those historical tests are preserved as part of the factory evidence and are
not the final official Stage 1 validation reported above.

## Factory evidence

The factory run recorded:

- 3 ordered tasks
- 5 build attempts/artifacts
- 5 review records
- rejection → revision → approval recovery cycles
- independent Reviewer verification

The detailed factory history is documented in `FACTORY.md`, with supporting
records in `evidence/`.

## Honesty and provenance

`room.json` is a faithful export of the BAND room's **metadata and
participants** via the BAND REST API. The API exposes no message-history
endpoint, so the factory protocol history is documented through `evidence/`
(`state.json`, `events.jsonl`, and the build and review artifacts). No
transcript has been synthesized.

The development history includes two **operator-injected** task-3 rejection
verdicts through the protocol's normal verdict message path. These were used to
exercise the rejection → revision → review workflow and to route a real,
independently-diagnosed test-timestamp defect through the factory. Both
injections are disclosed in `FACTORY.md`; the resulting repair was built and
independently reviewed by the agents.

This submission does not claim that every development action was autonomous.
The factory workflow, agent collaboration, recovery cycle, and independent
review are documented in the supplied evidence.

No API keys, tokens, or secrets are included in this package. Factory
credentials live in the factory's own gitignored `.env`.

## Reproducibility

The shipped artifact is contained in `stage-1/`.

See `stage-1/RUN.md` for the complete local and Docker execution instructions.
