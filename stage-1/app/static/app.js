/*
 * ORBIT Search frontend logic.
 *
 * All model-produced content (question echo, queries, titles, snippets, URLs,
 * answer text) is treated as untrusted: every dynamic string enters the DOM
 * via createElement/textContent only — no innerHTML — and every URL is
 * validated to http/https before it becomes a link.
 */
(function (root) {
  "use strict";

  /* ------------------------------------------------------------------ */
  /* Pure helpers (no DOM — unit-testable in Node)                       */
  /* ------------------------------------------------------------------ */

  function isPlainObject(value) {
    return (
      typeof value === "object" &&
      value !== null &&
      !Array.isArray(value)
    );
  }

  // Return the trimmed URL string only for http(s) URLs; anything else
  // (javascript:, data:, relative junk, unparsable input) -> null.
  function safeHttpUrl(value) {
    if (typeof value !== "string") return null;
    var trimmed = value.trim();
    if (!trimmed) return null;
    var parsed;
    try {
      parsed = new URL(trimmed);
    } catch (err) {
      return null;
    }
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return null;
    }
    return trimmed;
  }

  // Normalized key used to match citation URLs against source URLs.
  function urlKey(value) {
    var url = safeHttpUrl(value);
    if (url === null) return null;
    try {
      var parsed = new URL(url);
      var host = parsed.host.toLowerCase();
      var path = parsed.pathname.replace(/\/+$/, "");
      return parsed.protocol + "//" + host + path + parsed.search;
    } catch (err) {
      return null;
    }
  }

  function displayTitle(source) {
    if (isPlainObject(source) && typeof source.title === "string" && source.title.trim()) {
      return source.title.trim();
    }
    return "(untitled source)";
  }

  /*
   * Coverage model built exclusively from existing POST /research fields:
   *   queries[], sources[].query, sources[].url, citations[].
   * No counts are invented: a query with no attributed sources reports 0.
   */
  function buildCoverage(payload) {
    var empty = {
      queries: [],
      collected: 0,
      cited: 0,
      uncited: 0,
      perQuery: [],
      sourceIndexByKey: {},
      citedKeys: {}
    };
    if (!isPlainObject(payload)) return empty;

    var queries = Array.isArray(payload.queries)
      ? payload.queries.filter(function (q) { return typeof q === "string"; })
      : [];
    var sources = Array.isArray(payload.sources)
      ? payload.sources.filter(isPlainObject)
      : [];
    var rawCitations = Array.isArray(payload.citations)
      ? payload.citations.filter(function (c) { return typeof c === "string"; })
      : [];

    var citedKeys = {};
    rawCitations.forEach(function (c) {
      var key = urlKey(c);
      if (key !== null) citedKeys[key] = true;
    });

    var sourceIndexByKey = {};
    sources.forEach(function (source, index) {
      var key = urlKey(source.url);
      if (key !== null && !(key in sourceIndexByKey)) {
        sourceIndexByKey[key] = index;
      }
    });

    var citedCount = 0;
    sources.forEach(function (source) {
      var key = urlKey(source.url);
      if (key !== null && citedKeys[key]) citedCount += 1;
    });

    var byQuery = {};
    sources.forEach(function (source) {
      var q = typeof source.query === "string" ? source.query : "";
      if (!byQuery[q]) byQuery[q] = [];
      byQuery[q].push(source);
    });

    var perQuery = queries.map(function (q) {
      var list = byQuery[q] || [];
      return {
        query: q,
        count: list.length,
        titles: list.map(displayTitle)
      };
    });
    // Defensive: sources attributed to a query string not present in queries.
    Object.keys(byQuery).forEach(function (q) {
      if (q !== "" && queries.indexOf(q) === -1) {
        perQuery.push({
          query: q,
          count: byQuery[q].length,
          titles: byQuery[q].map(displayTitle)
        });
      }
    });

    return {
      queries: queries,
      collected: sources.length,
      cited: citedCount,
      uncited: sources.length - citedCount,
      perQuery: perQuery,
      sourceIndexByKey: sourceIndexByKey,
      citedKeys: citedKeys
    };
  }

  /* ------------------------------------------------------------------ */
  /* Minimal safe Markdown renderer (DOM nodes, never HTML strings)      */
  /* ------------------------------------------------------------------ */

  var INLINE_PATTERN =
    /(\[([^\]]*)\]\(([^)\s]+)\))|(\*\*([^*]+)\*\*)|(`([^`]+)`)|(https?:\/\/[^\s<>"')\]]+)/gi;

  function renderInline(doc, text, linkHook) {
    var frag = doc.createDocumentFragment();
    var re = new RegExp(INLINE_PATTERN.source, "gi");
    var last = 0;
    var match;
    while ((match = re.exec(text)) !== null) {
      if (match.index > last) {
        frag.appendChild(doc.createTextNode(text.slice(last, match.index)));
      }
      if (match[1] !== undefined) {
        // Markdown link [label](url)
        var label = match[2];
        var url = safeHttpUrl(match[3]);
        if (url !== null) {
          var anchor = doc.createElement("a");
          anchor.textContent = label || url;
          anchor.href = url;
          anchor.target = "_blank";
          anchor.rel = "noopener noreferrer";
          if (typeof linkHook === "function") linkHook(anchor, url);
          frag.appendChild(anchor);
        } else {
          // Unsafe scheme (javascript:, data:, ...) — show as inert text.
          var plain = doc.createElement("span");
          plain.className = "xss-plain";
          plain.textContent = match[1];
          frag.appendChild(plain);
        }
      } else if (match[4] !== undefined) {
        var strong = doc.createElement("strong");
        strong.textContent = match[5];
        frag.appendChild(strong);
      } else if (match[6] !== undefined) {
        var code = doc.createElement("code");
        code.textContent = match[7];
        frag.appendChild(code);
      } else if (match[8] !== undefined) {
        var bare = safeHttpUrl(match[8]);
        if (bare !== null) {
          var bareAnchor = doc.createElement("a");
          bareAnchor.textContent = match[8];
          bareAnchor.href = bare;
          bareAnchor.target = "_blank";
          bareAnchor.rel = "noopener noreferrer";
          if (typeof linkHook === "function") linkHook(bareAnchor, bare);
          frag.appendChild(bareAnchor);
        } else {
          frag.appendChild(doc.createTextNode(match[8]));
        }
      }
      last = re.lastIndex;
    }
    if (last < text.length) {
      frag.appendChild(doc.createTextNode(text.slice(last)));
    }
    return frag;
  }

  /*
   * Supported blocks: #/##/### headings, "-" bullet and "1." numbered
   * lists, paragraphs. Inline: **bold**, `code`, [label](http-url), and
   * bare http(s) URLs. Anything else — including HTML tags — is rendered
   * as literal text.
   */
  function renderMarkdown(doc, text, linkHook) {
    var frag = doc.createDocumentFragment();
    if (typeof text !== "string" || !text.trim()) return frag;

    var lines = text.split(/\r\n|\r|\n/);
    var list = null;

    function closeList() {
      if (list) {
        frag.appendChild(list.el);
        list = null;
      }
    }

    var i = 0;
    while (i < lines.length) {
      var trimmed = lines[i].trim();

      if (!trimmed) {
        closeList();
        i += 1;
        continue;
      }

      var heading = /^(#{1,3})\s+(.+)$/.exec(trimmed);
      if (heading) {
        closeList();
        var h = doc.createElement("h" + heading[1].length);
        h.appendChild(renderInline(doc, heading[2], linkHook));
        frag.appendChild(h);
        i += 1;
        continue;
      }

      var ul = /^[-*+]\s+(.+)$/.exec(trimmed);
      var ol = /^\d+[.)]\s+(.+)$/.exec(trimmed);
      if (ul || ol) {
        var type = ul ? "ul" : "ol";
        if (!list || list.type !== type) {
          closeList();
          list = { type: type, el: doc.createElement(type) };
        }
        var li = doc.createElement("li");
        li.appendChild(renderInline(doc, (ul || ol)[1], linkHook));
        list.el.appendChild(li);
        i += 1;
        continue;
      }

      closeList();
      var para = [trimmed];
      i += 1;
      while (i < lines.length) {
        var next = lines[i].trim();
        if (
          !next ||
          /^(#{1,3})\s+/.test(next) ||
          /^[-*+]\s+/.test(next) ||
          /^\d+[.)]\s+/.test(next)
        ) {
          break;
        }
        para.push(next);
        i += 1;
      }
      var p = doc.createElement("p");
      p.appendChild(renderInline(doc, para.join(" "), linkHook));
      frag.appendChild(p);
    }

    closeList();
    return frag;
  }

  /* ------------------------------------------------------------------ */
  /* DOM bootstrap                                                       */
  /* ------------------------------------------------------------------ */

  function init() {
    var form = document.getElementById("ask-form");
    var textarea = document.getElementById("question");
    var button = document.getElementById("ask-button");
    var banner = document.getElementById("status-banner");
    var results = document.getElementById("results");

    var emptyState = document.getElementById("empty-state");
    var loadingState = document.getElementById("loading-state");
    var errorState = document.getElementById("error-state");
    var errorMessage = document.getElementById("error-message");
    var answerEmpty = document.getElementById("answer-empty");
    var answerEmptyDetail = document.getElementById("answer-empty-detail");
    var answerPanel = document.getElementById("answer-panel");
    var answerQuestion = document.getElementById("answer-question");
    var answerBody = document.getElementById("answer-body");
    var coveragePanel = document.getElementById("coverage-panel");
    var queriesList = document.getElementById("queries-list");
    var statQueries = document.getElementById("stat-queries");
    var statCollected = document.getElementById("stat-collected");
    var statCited = document.getElementById("stat-cited");
    var statUncited = document.getElementById("stat-uncited");
    var queryCoverage = document.getElementById("query-coverage");
    var sourcesPanel = document.getElementById("sources-panel");
    var sourcesList = document.getElementById("sources-list");

    var requestSeq = 0;
    var highlightTimer = null;

    function setBusy(busy) {
      button.disabled = busy;
      button.textContent = busy ? "Researching…" : "Research";
    }

    function hideAllStates() {
      emptyState.hidden = true;
      loadingState.hidden = true;
      errorState.hidden = true;
      answerEmpty.hidden = true;
      answerPanel.hidden = true;
      coveragePanel.hidden = true;
      sourcesPanel.hidden = true;
      results.classList.remove("has-content");
    }

    function showBanner(kind, text) {
      if (!text) {
        banner.hidden = true;
        banner.className = "status-banner";
        banner.textContent = "";
        return;
      }
      banner.hidden = false;
      banner.className = "status-banner " + kind;
      var strong = document.createElement("strong");
      strong.textContent = kind === "warn" ? "Degraded result: " : "Notice: ";
      banner.appendChild(strong);
      banner.appendChild(document.createTextNode(text));
    }

    function queryBadgeLabel(index) {
      return "Q" + (index + 1);
    }

    function renderCoverage(coverage) {
      queriesList.textContent = "";
      coverage.queries.forEach(function (q) {
        var li = document.createElement("li");
        li.textContent = q;
        queriesList.appendChild(li);
      });

      statQueries.textContent = String(coverage.queries.length);
      statCollected.textContent = String(coverage.collected);
      statCited.textContent = String(coverage.cited);
      statUncited.textContent = String(coverage.uncited);

      queryCoverage.textContent = "";
      coverage.perQuery.forEach(function (item, index) {
        var box = document.createElement("div");
        box.className = "query-coverage-item";

        var head = document.createElement("div");
        head.className = "query-coverage-head";

        var q = document.createElement("p");
        q.className = "query-coverage-q";
        q.textContent = queryBadgeLabel(index) + " · " + item.query;

        var count = document.createElement("p");
        count.className = "query-coverage-count";
        count.textContent = item.count + (item.count === 1 ? " source" : " sources");

        head.appendChild(q);
        head.appendChild(count);
        box.appendChild(head);

        if (item.titles.length > 0) {
          var titles = document.createElement("ul");
          titles.className = "query-coverage-titles";
          item.titles.forEach(function (title) {
            var t = document.createElement("li");
            t.textContent = title;
            titles.appendChild(t);
          });
          box.appendChild(titles);
        } else {
          var none = document.createElement("p");
          none.className = "query-coverage-none";
          none.textContent = "No source records were attributed to this query.";
          box.appendChild(none);
        }

        queryCoverage.appendChild(box);
      });
    }

    function renderSources(coverage, sources) {
      sourcesList.textContent = "";

      sources.forEach(function (source, index) {
        var card = document.createElement("li");
        card.className = "source-card";
        card.id = "source-" + index;

        var head = document.createElement("div");
        head.className = "source-head";

        var url = safeHttpUrl(isPlainObject(source) ? source.url : null);
        var titleText = displayTitle(source);

        if (url !== null) {
          var titleLink = document.createElement("a");
          titleLink.className = "source-title";
          titleLink.textContent = titleText;
          titleLink.href = url;
          titleLink.target = "_blank";
          titleLink.rel = "noopener noreferrer";
          head.appendChild(titleLink);
          try {
            var host = document.createElement("span");
            host.className = "source-host";
            host.textContent = new URL(url).host;
            head.appendChild(host);
          } catch (err) { /* host omitted */ }
        } else {
          var titlePlain = document.createElement("p");
          titlePlain.className = "source-title";
          titlePlain.textContent = titleText;
          head.appendChild(titlePlain);
        }

        var badges = document.createElement("div");
        badges.className = "source-badges";

        var key = urlKey(isPlainObject(source) ? source.url : null);
        if (key !== null && coverage.citedKeys[key]) {
          var cited = document.createElement("span");
          cited.className = "badge cited";
          cited.textContent = "Cited in answer";
          badges.appendChild(cited);
        }

        if (
          isPlainObject(source) &&
          typeof source.query === "string" &&
          coverage.queries.indexOf(source.query) !== -1
        ) {
          var qBadge = document.createElement("span");
          qBadge.className = "badge query-badge";
          qBadge.textContent = queryBadgeLabel(coverage.queries.indexOf(source.query));
          qBadge.title = "Retrieved via: " + source.query;
          badges.appendChild(qBadge);
        }

        if (badges.childNodes.length > 0) head.appendChild(badges);
        card.appendChild(head);

        if (isPlainObject(source) && typeof source.query === "string" && source.query) {
          var qLine = document.createElement("p");
          qLine.className = "source-query-line";
          qLine.textContent = "Retrieved via: " + source.query;
          card.appendChild(qLine);
        }

        if (isPlainObject(source) && typeof source.snippet === "string" && source.snippet.trim()) {
          var snippet = document.createElement("p");
          snippet.className = "source-snippet";
          snippet.textContent = source.snippet;
          card.appendChild(snippet);
        }

        sourcesList.appendChild(card);
      });

      return sources.length > 0;
    }

    // Citation inspector: an answer link whose URL matches a retrieved
    // source scrolls to (and highlights) that source card instead of
    // navigating away. Unmatched URLs keep normal new-tab behavior.
    function citationHook(sourceIndexByKey) {
      return function (anchor, url) {
        var key = urlKey(url);
        if (key === null || !(key in sourceIndexByKey)) return;
        var index = sourceIndexByKey[key];
        anchor.title = "Locate this source in Sources & evidence below";
        anchor.addEventListener("click", function (event) {
          event.preventDefault();
          var card = document.getElementById("source-" + index);
          if (!card) return;
          card.scrollIntoView({ behavior: "smooth", block: "center" });
          card.classList.add("highlight");
          if (highlightTimer) root.clearTimeout(highlightTimer);
          highlightTimer = root.setTimeout(function () {
            card.classList.remove("highlight");
          }, 1800);
        });
      };
    }

    function renderResult(data) {
      hideAllStates();

      var coverage = buildCoverage(data);
      var degraded = data.status === "degraded" || typeof data.warning === "string";
      showBanner(degraded ? "warn" : "", degraded ? (data.warning || "The result is partially degraded.") : "");

      var hasAnswer = typeof data.answer === "string" && data.answer.trim().length > 0;
      if (hasAnswer) {
        answerQuestion.textContent = typeof data.question === "string" ? data.question : "";
        answerBody.textContent = "";
        answerBody.appendChild(renderMarkdown(document, data.answer, citationHook(coverage.sourceIndexByKey)));
        answerPanel.hidden = false;
      } else {
        answerEmptyDetail.textContent = degraded
          ? (data.warning || "AI synthesis was unavailable for this run; the collected evidence is shown below.")
          : "The service returned no synthesized answer for this run; the collected evidence is shown below.";
        answerEmpty.hidden = false;
      }

      renderCoverage(coverage);
      coveragePanel.hidden = false;

      var staleNote = sourcesPanel.querySelector("p.source-snippet[data-empty]");
      if (staleNote) staleNote.remove();
      var hasSources = renderSources(coverage, Array.isArray(data.sources) ? data.sources.filter(isPlainObject) : []);
      if (!hasSources) {
        var note = document.createElement("p");
        note.className = "source-snippet";
        note.setAttribute("data-empty", "true");
        note.textContent = "No sources were collected for this run.";
        sourcesPanel.appendChild(note);
      }
      sourcesPanel.hidden = false;

      results.classList.add("has-content");
      results.focus();
    }

    function renderFailure(message) {
      hideAllStates();
      showBanner("", "");
      errorMessage.textContent = message;
      errorState.hidden = false;
      results.classList.add("has-content");
      results.focus();
    }

    /*
     * A rejected fetch() means no HTTP response arrived at all. Probe
     * /health (local, no upstream calls) to distinguish a genuinely
     * unreachable service from a stale page whose pooled connection died
     * (e.g. the server restarted after this page was loaded) — the two
     * need different guidance.
     */
    async function reachabilityMessage() {
      try {
        await fetch("/health", { method: "GET" });
        return (
          "The research service is reachable, but this request could not be " +
          "completed. This page may be out of date — reload it and try again."
        );
      } catch (probeErr) {
        return (
          "Network error — the research service could not be reached. " +
          "Verify the server is running, then reload this page."
        );
      }
    }

    async function onSubmit(event) {
      event.preventDefault();
      var question = textarea.value.trim();
      if (!question) {
        textarea.focus();
        return;
      }

      var mySeq = ++requestSeq;
      setBusy(true);
      hideAllStates();
      showBanner("", "");
      loadingState.hidden = false;

      try {
        // Phase 1: transport. A rejection here means no HTTP response —
        // not an error status returned by the service.
        var response = null;
        try {
          response = await fetch("/research", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question: question })
          });
        } catch (transportErr) {
          if (mySeq !== requestSeq) return;
          renderFailure(await reachabilityMessage());
          return;
        }

        if (mySeq !== requestSeq) return;

        // Phase 2: response body. A JSON parse failure on a 200 is a
        // malformed response, not a network failure.
        var data = null;
        var unreadable = false;
        try {
          data = await response.json();
        } catch (parseErr) {
          unreadable = true;
        }

        if (mySeq !== requestSeq) return;

        // Phase 3: HTTP status. Prefer the service's own error message.
        if (!response.ok) {
          var message =
            data && isPlainObject(data.error) && typeof data.error.message === "string"
              ? data.error.message
              : "The research request failed (HTTP " + response.status + ").";
          renderFailure(message);
          return;
        }

        if (unreadable) {
          renderFailure(
            "The research service returned an unreadable response (invalid JSON)."
          );
          return;
        }

        // Phase 4: rendering. A rendering exception must not be reported
        // as a network error.
        try {
          renderResult(isPlainObject(data) ? data : {});
        } catch (renderErr) {
          if (mySeq !== requestSeq) return;
          if (root.console && typeof root.console.error === "function") {
            root.console.error(
              "ORBIT Search: result received but rendering failed",
              renderErr
            );
          }
          renderFailure(
            "The research result was received but could not be displayed. " +
              "Reload the page and try again."
          );
        }
      } finally {
        if (mySeq === requestSeq) setBusy(false);
      }
    }

    form.addEventListener("submit", onSubmit);

    Array.prototype.forEach.call(
      document.querySelectorAll(".example-chip"),
      function (chip) {
        chip.addEventListener("click", function () {
          textarea.value = chip.textContent;
          textarea.focus();
        });
      }
    );
  }

  /* ------------------------------------------------------------------ */
  /* Exports + bootstrap                                                 */
  /* ------------------------------------------------------------------ */

  var api = {
    safeHttpUrl: safeHttpUrl,
    urlKey: urlKey,
    buildCoverage: buildCoverage,
    renderMarkdown: renderMarkdown,
    displayTitle: displayTitle
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  }
})(typeof window !== "undefined" ? window : globalThis);
