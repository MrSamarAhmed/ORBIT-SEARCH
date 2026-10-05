# Tablekeeper — Stage 1 (Dark Factory submission)

A restaurant table-reservation HTTP service produced through **ORBIT**, a
three-agent software factory (Architect → Builder → Reviewer) operating through
BAND.

The factory decomposes the specification into implementation tasks, dispatches
coding work, independently reviews builds, and supports rejection → revision →
approval cycles. The factory run and supporting artifacts are preserved under
`evidence/`.

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
│   ├── requirements.txt
│   ├── app/
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

docker build -t tablekeeper-stage1 .
docker run --rm -p 8080:8080 -e PORT=8080 tablekeeper-stage1

curl http://localhost:8080/health
```

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
