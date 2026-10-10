"""Behavioral tests for app/static/app.js submission handling.

Runs the real app.js in a minimal fake-DOM sandbox under Node.js with
mocked fetch responses — no HTTP server and no live API calls. Covers the
degraded (HTTP 200, answer null) response shape and the distinct failure
classes: transport failure, HTTP error, unreadable JSON, rendering error.

Skips automatically when Node.js is not installed.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js not available")

DRIVER = r'''
"use strict";
const fs = require("fs");
const vm = require("vm");
const appJsPath = process.argv[2];
const src = fs.readFileSync(appJsPath, "utf8");

function makeElement(tag) {
  const classes = new Set();
  const el = {
    tagName: tag,
    hidden: false,
    className: "",
    textContent: "",
    title: "",
    id: "",
    value: "",
    disabled: false,
    children: [],
    handlers: {},
    appendChild(child) { el.children.push(child); return child; },
    remove() {},
    setAttribute(key, val) { el[key] = val; },
    addEventListener(type, fn) {
      (el.handlers[type] = el.handlers[type] || []).push(fn);
    },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    focus() {},
    scrollIntoView() {},
    classList: {
      add(c) { classes.add(c); },
      remove(c) { classes.delete(c); },
      contains(c) { return classes.has(c); }
    }
  };
  return el;
}

function bootstrap(fetchImpl) {
  const ids = [
    "ask-form", "question", "ask-button", "status-banner", "results",
    "empty-state", "loading-state", "error-state", "error-message",
    "answer-empty", "answer-empty-detail", "answer-panel", "answer-question",
    "answer-body", "coverage-panel", "queries-list", "stat-queries",
    "stat-collected", "stat-cited", "stat-uncited", "query-coverage",
    "sources-panel", "sources-list"
  ];
  const els = {};
  ids.forEach((id) => { els[id] = makeElement("div"); });
  const consoleErrors = [];
  const fakeConsole = {
    error(...a) { consoleErrors.push(a.map((x) => String(x)).join(" ")); }
  };
  const calls = [];
  const fetchWrapper = function (url, opts) {
    calls.push(url);
    return fetchImpl(url, opts);
  };
  const window = { setTimeout, clearTimeout, console: fakeConsole, fetch: fetchWrapper };
  const document = {
    readyState: "complete",
    getElementById(id) { return els[id] || null; },
    createElement(tag) { return makeElement(tag); },
    createTextNode(text) { return { textContent: String(text) }; },
    createDocumentFragment() { return makeElement("#document-fragment"); },
    addEventListener() {},
    querySelectorAll() { return []; }
  };
  vm.runInNewContext(
    src,
    { window, document, fetch: fetchWrapper, URL, setTimeout, clearTimeout, console: fakeConsole },
    { filename: "app.js" }
  );
  return { els, calls, consoleErrors };
}

function httpResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status: status,
    json() {
      if (body === "__THROW__") {
        return Promise.reject(new Error("Unexpected token in JSON"));
      }
      return Promise.resolve(typeof body === "string" ? JSON.parse(body) : body);
    }
  };
}

const QUESTION = "How is agentic AI used in enterprises?";
const QUERIES = [
  "agentic AI enterprise use cases",
  "agentic AI enterprise adoption 2026",
  "enterprise AI agent platforms"
];

function makeSources(count, queries) {
  const sources = [];
  for (let i = 0; i < count; i++) {
    sources.push({
      title: "Source " + (i + 1),
      url: "https://example.org/articles/" + (i + 1),
      snippet: "Snippet text " + (i + 1),
      source: "example.org",
      query: queries[i % queries.length]
    });
  }
  return sources;
}

function payloadWith(overrides) {
  const base = {
    question: QUESTION,
    queries: QUERIES,
    sources: makeSources(15, QUERIES),
    citations: [1, 2, 3, 4, 5].map((i) => "https://example.org/articles/" + i)
  };
  const merged = Object.assign({}, base);
  Object.keys(overrides).forEach((k) => { merged[k] = overrides[k]; });
  return merged;
}

const DEGRADED_PAYLOAD = payloadWith({
  answer: null,
  status: "degraded",
  warning: "AI synthesis was unavailable, so no AI-generated answer was produced. "
    + "The collected search evidence is returned instead. "
    + "(Gemini API returned HTTP 429.)"
});

const SUCCESS_PAYLOAD = payloadWith({
  answer: "Agentic AI is used for **support automation** and pipeline triage.\n\n"
    + "See https://example.org/articles/1 for a survey."
});

function onlyResearch(responder) {
  return function (url) {
    if (url === "/research") return responder();
    throw new Error("unexpected fetch: " + url);
  };
}

async function runScenario(fetchImpl, prepare) {
  const ctx = bootstrap(fetchImpl);
  ctx.els["question"].value = QUESTION;
  if (prepare) prepare(ctx);
  const handler = ctx.els["ask-form"].handlers.submit[0];
  await handler({ preventDefault() {} });
  const els = ctx.els;
  return {
    errorHidden: els["error-state"].hidden,
    errorMessage: els["error-message"].textContent,
    bannerText: els["status-banner"].hidden
      ? ""
      : els["status-banner"].children.map((c) => c.textContent).join(" "),
    answerPanelHidden: els["answer-panel"].hidden,
    answerQuestion: els["answer-question"].textContent,
    answerEmptyHidden: els["answer-empty"].hidden,
    answerEmptyDetail: els["answer-empty-detail"].textContent,
    coverageHidden: els["coverage-panel"].hidden,
    statQueries: els["stat-queries"].textContent,
    statCollected: els["stat-collected"].textContent,
    statCited: els["stat-cited"].textContent,
    statUncited: els["stat-uncited"].textContent,
    sourcesCount: els["sources-list"].children.length,
    buttonDisabled: els["ask-button"].disabled,
    calls: ctx.calls,
    consoleErrors: ctx.consoleErrors
  };
}

(async () => {
  const results = {};

  results.degraded = await runScenario(
    onlyResearch(() => httpResponse(200, DEGRADED_PAYLOAD))
  );

  results.success = await runScenario(
    onlyResearch(() => httpResponse(200, SUCCESS_PAYLOAD))
  );

  results.networkDown = await runScenario(() => {
    throw new TypeError("Failed to fetch");
  });

  results.stalePage = await runScenario((url) => {
    if (url === "/health") return httpResponse(200, { status: "ok" });
    throw new TypeError("Failed to fetch");
  });

  results.httpEnvelope = await runScenario(
    onlyResearch(() => httpResponse(503, {
      error: { code: "upstream_unavailable", message: "Research is temporarily unavailable." }
    }))
  );

  results.httpNoJson = await runScenario(
    onlyResearch(() => httpResponse(500, "__THROW__"))
  );

  results.okBadJson = await runScenario(
    onlyResearch(() => httpResponse(200, "__THROW__"))
  );

  results.renderError = await runScenario(
    onlyResearch(() => httpResponse(200, SUCCESS_PAYLOAD)),
    (ctx) => {
      ctx.els["answer-body"].appendChild = function () {
        throw new Error("boom");
      };
    }
  );

  process.stdout.write(JSON.stringify(results));
})().catch((err) => {
  process.stderr.write(String(err && err.stack ? err.stack : err) + "\n");
  process.exit(1);
});
'''


def run_driver(tmp_path: Path) -> dict:
    driver_path = tmp_path / "app_js_driver.js"
    driver_path.write_text(DRIVER, encoding="utf-8")
    proc = subprocess.run(
        [NODE, str(driver_path), str(APP_JS)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"app.js driver failed:\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_driver(tmp_path_factory.mktemp("appjs"))


def test_degraded_200_renders_evidence_not_error(results):
    r = results["degraded"]
    assert r["errorHidden"] is True
    assert "could not be reached" not in r["errorMessage"]
    assert r["answerEmptyHidden"] is False
    assert "AI synthesis was unavailable" in r["answerEmptyDetail"]
    assert "HTTP 429" in r["answerEmptyDetail"]
    assert r["bannerText"].startswith("Degraded result:")
    assert "HTTP 429" in r["bannerText"]
    assert r["answerPanelHidden"] is True
    assert r["coverageHidden"] is False
    assert r["statQueries"] == "3"
    assert r["statCollected"] == "15"
    assert r["statCited"] == "5"
    assert r["statUncited"] == "10"
    assert r["sourcesCount"] == 15
    assert r["buttonDisabled"] is False


def test_success_200_renders_answer(results):
    r = results["success"]
    assert r["errorHidden"] is True
    assert r["answerPanelHidden"] is False
    assert r["answerEmptyHidden"] is True
    assert r["answerQuestion"] == QUESTION
    assert r["bannerText"] == ""
    assert r["statCollected"] == "15"
    assert r["sourcesCount"] == 15
    assert r["buttonDisabled"] is False


def test_network_failure_server_unreachable(results):
    r = results["networkDown"]
    assert r["errorHidden"] is False
    assert "could not be reached" in r["errorMessage"]
    assert "/health" in r["calls"]
    assert r["buttonDisabled"] is False


def test_network_failure_with_reachable_server_suggests_reload(results):
    r = results["stalePage"]
    assert r["errorHidden"] is False
    assert "out of date" in r["errorMessage"]
    assert "could not be reached" not in r["errorMessage"]
    assert r["calls"] == ["/research", "/health"]
    assert r["buttonDisabled"] is False


def test_http_error_uses_service_error_message(results):
    r = results["httpEnvelope"]
    assert r["errorHidden"] is False
    assert r["errorMessage"] == "Research is temporarily unavailable."
    assert r["buttonDisabled"] is False


def test_http_error_without_json_body_reports_status(results):
    r = results["httpNoJson"]
    assert r["errorHidden"] is False
    assert "HTTP 500" in r["errorMessage"]
    assert "Network error" not in r["errorMessage"]
    assert r["buttonDisabled"] is False


def test_ok_response_with_invalid_json_is_not_network_error(results):
    r = results["okBadJson"]
    assert r["errorHidden"] is False
    assert "invalid JSON" in r["errorMessage"]
    assert "Network error" not in r["errorMessage"]
    assert r["buttonDisabled"] is False


def test_render_exception_is_distinct_from_network_error(results):
    r = results["renderError"]
    assert r["errorHidden"] is False
    assert "could not be displayed" in r["errorMessage"]
    assert "Network error" not in r["errorMessage"]
    assert len(r["consoleErrors"]) > 0
    assert r["buttonDisabled"] is False
