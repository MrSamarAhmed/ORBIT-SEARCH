# ORBIT Search — Three-Minute Demo Script

A timed walkthrough of ORBIT Search for a live audience. Everything below
demonstrates functionality that exists today; the fallback plan (§6) covers the
case where Gemini quota is exhausted. **Never present a mocked or recorded
response as a live run.**

## Pre-flight (before the audience)

1. `curl http://localhost:8080/health` → `{"status": "ok"}`
2. Confirm `SERPAPI_API_KEY` and `GEMINI_API_KEY` are exported in the server
   environment (never display their values).
3. Open `http://localhost:8080/` in the browser you will share.
4. Run one quiet `POST /research` to confirm whether Gemini synthesis is
   available right now. This decides path A or path B in §3.

## Timing

### 1. Setup (0:00–0:20)

> "This is ORBIT Search — an AI research agent that turns live web search into
> structured, source-grounded research. It's built on SerpApi for live search
> and Gemini for query planning and synthesis, served by a small FastAPI
> service. This is the actual product, not a mockup."

Point at the empty-state pipeline diagram (Question → Plan → Search →
Evidence → Synthesis → Citations): each step is a real stage of the backend
pipeline.

### 2. Ask a question (0:20–0:50)

Pick one question relevant to the audience, e.g.:

- "How are Indian startups applying AI in agriculture?"
- "What is agentic AI and how is it used in enterprise software?"

Type it in, click **Research**, and let the honest loading state show:

> "While this runs: the planner turns my one question into several focused
> searches, each runs against the live web, and only then does synthesis
> start. No fake progress bar — it takes up to a minute because the work is
> real."

### 3. Walk the result (0:50–2:00)

**Path A — synthesis available** (live answer returned):

1. Answer: point out the structure (headings, bullets) and that it was written
   from retrieved evidence, not model memory.
2. Citations: click an inline citation → the matching source card in
   "Sources & evidence" is highlighted. "Every citation is a URL this run
   actually retrieved."
3. Research coverage: "On the right you can see exactly which queries ran,
   how many sources each produced, and how many the answer cited." Point out a
   query with zero sources if present — "failed or empty queries are shown
   honestly, not hidden."

**Path B — Gemini quota exhausted** (`answer: null`, degraded banner):

> "The AI synthesis layer is rate-limited right now. Notice what happens: the
> service does not invent an answer. It returns the planned queries and the
> real sources it retrieved, and says so explicitly in the warning banner."

Show the coverage panel and source cards — the retrieval half of the pipeline
is still fully demonstrated. This is an honest, supported demo path.

### 4. Prove the sources are live (2:00–2:30)

Open one source card's external link in a new tab and skim the page:

> "These are real, current web pages retrieved seconds ago — that's the
> SerpApi layer doing the work."

Optionally contrast with `curl "http://localhost:8080/search?q=..."` to show
the raw normalized search endpoint underneath.

### 5. Failure isolation (2:30–2:50) — optional if time is tight

> "One more property: if one search query fails, the rest still deliver."

Submit a question, and if the warning banner reports a failed query, point at
it. Do not fabricate a failure if none occurs.

### 6. Close (2:50–3:00)

> "ORBIT Search: planned queries, live SerpApi evidence, evidence-grounded
> synthesis, provenance-checked citations — and when anything upstream is
> limited, it degrades honestly instead of making things up. The workspace is
> served by the same FastAPI service at `GET /`, and the full pipeline is one
> `POST /research` call."

## Never do in the demo

- Do not display, type, or narrate API key values.
- Do not present cached, recorded, or hand-crafted JSON as a live response.
- Do not claim the pipeline verifies that sources support specific claims —
  it verifies provenance (the URL was retrieved), nothing more.
- Do not retry a rate-limited Gemini call on stage to "make it work"; use
  Path B as the demonstration of honest degradation.
