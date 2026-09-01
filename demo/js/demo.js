/* ==========================================================================
   RC Engine — read-only demo
   Reads the static snapshot in demo/data/ and renders it. No network calls
   beyond same-origin JSON; nothing here can trigger a generation run.
   ========================================================================== */
(function () {
  "use strict";

  var DATA = "data/";
  var state = { corpus: null, funnel: null, sets: [], detail: null, cache: {} };

  // ------------------------------------------------------------- helpers
  function $(sel, root) { return (root || document).querySelector(sel); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  function num(v, digits) {
    if (v == null || isNaN(v)) return "—";
    return Number(v).toFixed(digits == null ? 2 : digits);
  }
  function pct(v) { return v == null ? "—" : Math.round(v * 100) + "%"; }
  function titleCase(s) { return String(s || "").replace(/_/g, " "); }
  function dateOnly(s) { return String(s || "").slice(0, 10); }

  function fetchJSON(path) {
    return fetch(DATA + path, { cache: "no-cache" }).then(function (r) {
      if (!r.ok) throw new Error(path + " → HTTP " + r.status);
      return r.json();
    });
  }

  // --------------------------------------------------------------- hero
  function renderStats() {
    var c = state.corpus, f = state.funnel;
    var approved = (c.by_status && c.by_status.approved) || 0;
    var items = [
      [c.sets_total, "sets in the corpus", null],
      [approved, "cleared for delivery", null],
      [f.total_evaluations, "novelty audits run", null],
      [f.total_rejections, "candidates rejected", "var(--reject)"],
      [pct(f.rejection_rate), "of evaluations end in rejection", null],
      [c.fingerprint_corpus.total, "fingerprints compared against", null]
    ];
    var box = $("#stats");
    clear(box);
    items.forEach(function (it) {
      var s = el("div", "stat");
      var n = el("div", "stat__n", String(it[0]));
      if (it[2]) n.style.color = it[2];
      s.appendChild(n);
      s.appendChild(el("div", "stat__l", it[1]));
      box.appendChild(s);
    });

    $("#snapshot-line").textContent =
      "Static snapshot · corpus spans " + dateOnly(c.first_set) +
      " to " + dateOnly(c.last_set);

    $("#footer-stamp").textContent =
      "Snapshot: " + c.sets_total + " sets, " + f.total_evaluations +
      " audits, " + c.blueprints_drawn + " blueprints drawn. " +
      "Full text released for " + (c.published_full_text || []).length + " set(s).";
  }

  // ----------------------------------------------------------- overview
  function renderTables() {
    var tb = $("#tier-table tbody");
    clear(tb);
    (state.corpus.tier_stats || []).forEach(function (r) {
      var tr = el("tr");
      tr.appendChild(el("td", null, titleCase(r.tier)));
      [[r.n, 0], [r.avg_score, 2], [r.avg_compliance, 3], [r.avg_novelty, 3]]
        .forEach(function (p) { tr.appendChild(el("td", "num", num(p[0], p[1]))); });
      tb.appendChild(tr);
    });

    var ub = $("#usage-table tbody");
    clear(ub);
    (state.corpus.component_usage || []).forEach(function (r) {
      var tr = el("tr");
      tr.appendChild(el("td", null, titleCase(r.component_type)));
      tr.appendChild(el("td", "num", String(r.distinct_used)));
      tr.appendChild(el("td", "num", String(r.draws)));
      ub.appendChild(tr);
    });
  }

  // ------------------------------------------------------------- funnel
  function renderFunnel() {
    var list = $("#funnel-list");
    clear(list);
    var widest = Math.max.apply(null,
      state.funnel.gates.map(function (g) { return g.evaluated; }).concat([1]));

    state.funnel.gates.forEach(function (g) {
      var card = el("div", "gate");

      var head = el("div", "gate__head");
      head.appendChild(el("div", "gate__name", g.label));
      head.appendChild(el("div", "gate__count",
        g.evaluated + " evaluated · " + g.rejected + " rejected"));
      card.appendChild(head);
      card.appendChild(el("div", "gate__blurb", g.blurb));

      // Bar width is proportional to how many candidates reached this gate,
      // so the cascade narrows visually as work gets more expensive.
      var scale = g.evaluated / widest;
      var bar = el("div", "bar");
      bar.style.width = Math.max(scale * 100, 8) + "%";
      if (g.passed) {
        var p = el("div", "bar__seg bar__seg--pass", g.passed ? String(g.passed) : "");
        p.style.width = (g.passed / g.evaluated * 100) + "%";
        bar.appendChild(p);
      }
      if (g.rejected) {
        var r = el("div", "bar__seg bar__seg--reject", String(g.rejected));
        r.style.width = (g.rejected / g.evaluated * 100) + "%";
        bar.appendChild(r);
      }
      card.appendChild(bar);

      var reasons = Object.keys(g.reasons || {});
      if (reasons.length) {
        var box = el("div", "gate__reasons");
        reasons.forEach(function (k) {
          box.appendChild(el("span", "tag tag--reject",
            titleCase(k) + " × " + g.reasons[k]));
        });
        card.appendChild(box);
      }
      list.appendChild(card);
    });
  }

  // ----------------------------------------------------------- explorer
  function renderPicker() {
    var sel = $("#setpick");
    clear(sel);
    state.sets.forEach(function (s) {
      var o = el("option", null,
        s.rc_id + "  ·  " + titleCase(s.tier) +
        (s.published ? "  ·  full text" : ""));
      o.value = s.rc_id;
      sel.appendChild(o);
    });
    // Default to a set whose passage is published, so the first thing a
    // visitor sees is readable rather than locked.
    var first = state.sets.filter(function (s) { return s.published; })[0] || state.sets[0];
    if (first) sel.value = first.rc_id;
    sel.addEventListener("change", function () { loadSet(sel.value); });
    return first ? first.rc_id : null;
  }

  function renderMeta(d) {
    var box = $("#setmeta");
    clear(box);
    function chip(label, value, cls) {
      var c = el("span", "chip" + (cls ? " " + cls : ""));
      c.appendChild(document.createTextNode(label + " "));
      c.appendChild(el("b", null, value));
      box.appendChild(c);
    }
    var statusCls = d.status === "approved" ? "chip--pass"
      : d.status === "needs_review" ? "chip--warn" : "chip--reject";
    chip("Status", titleCase(d.status), statusCls);
    chip("Tier", titleCase(d.tier));
    if (d.average_score) chip("Rubric", num(d.average_score, 1) + " / 10");
    if (d.compliance_f1 != null) chip("Compliance F1", num(d.compliance_f1, 3));
    if (d.novelty_composite != null) chip("Novelty", num(d.novelty_composite, 3));
    if (d.word_count) chip("Passage", d.word_count + " words");
    if (d.question_count) chip("Questions", String(d.question_count));
    chip("Built", dateOnly(d.created_at));
  }

  // -------------------------------------------------------- tab: read
  function renderRead(d) {
    var p = $("#panel-read");
    clear(p);

    if (!d.passage) {
      var lock = el("div", "locked");
      lock.appendChild(el("b", null, "This passage is not published."));
      lock.appendChild(document.createTextNode(
        "Sets under the delivery contract stay unpublished; their structure, scores and " +
        "audit trail are shown in full on the other tabs. Choose a set marked " +
        "“full text” to read a complete passage with its answer key."));
      p.appendChild(lock);
      if (d.topic) {
        var t = el("p", "srcline", "Blueprint topic brief: " + d.topic);
        p.appendChild(t);
      }
      return;
    }

    var art = el("div", "passage");
    d.passage.forEach(function (para) { art.appendChild(el("p", null, para)); });
    p.appendChild(art);

    if (d.source) {
      var s = el("p", "srcline");
      s.appendChild(document.createTextNode("Composed from seed material: "));
      if (/^https?:/.test(d.source.url)) {
        var a = el("a", null, d.source.title);
        a.href = d.source.url;
        a.rel = "noopener noreferrer nofollow";
        a.target = "_blank";
        s.appendChild(a);
      } else {
        s.appendChild(document.createTextNode(d.source.title + " (" + d.source.url + ")"));
      }
      p.appendChild(s);
    }

    d.questions.forEach(function (q) { p.appendChild(renderQuestion(q)); });
  }

  function renderQuestion(q) {
    var wrap = el("div", "q");
    wrap.appendChild(el("div", "q__n", "Question " + q.n));
    wrap.appendChild(el("div", "q__stem", q.stem));

    var why = {};
    (q.rationale || []).forEach(function (r) { why[r.letter] = r; });

    var opts = el("div", "opts");
    q.options.forEach(function (o) {
      var btn = el("button", "opt");
      btn.type = "button";
      btn.setAttribute("aria-expanded", "false");
      btn.appendChild(el("span", "opt__l", "(" + o.letter + ")"));

      var body = el("span");
      body.appendChild(document.createTextNode(o.text));
      btn.appendChild(body);

      btn.addEventListener("click", function () {
        var open = btn.getAttribute("aria-expanded") === "true";
        if (open) {
          btn.setAttribute("aria-expanded", "false");
          btn.removeAttribute("data-state");
          var old = $(".opt__why", btn);
          if (old) body.removeChild(old);
          return;
        }
        btn.setAttribute("aria-expanded", "true");
        var correct = o.letter === q.answer;
        btn.setAttribute("data-state", correct ? "correct" : "trap");

        var r = why[o.letter];
        var note = el("span", "opt__why");
        var tag = el("span", "opt__tag", correct ? "CORRECT"
          : (r && r.tag ? titleCase(r.tag) : "distractor"));
        tag.style.color = correct ? "var(--pass)" : "var(--reject)";
        note.appendChild(tag);
        note.appendChild(el("span", null,
          (r && r.note) ? " " + r.note : " No recorded rationale for this option."));
        body.appendChild(note);
      });
      opts.appendChild(btn);
    });
    wrap.appendChild(opts);
    wrap.appendChild(el("div", "q__hint",
      "Click any option to reveal its trap type and the elimination logic recorded for it."));
    return wrap;
  }

  // ------------------------------------------------------- tab: audit
  function renderAudit(d) {
    var p = $("#panel-audit");
    clear(p);
    var n = d.novelty || {};

    if (!n.channels || !n.channels.length) {
      p.appendChild(el("div", "locked", "No full nine-channel audit was recorded for this set."));
      return;
    }

    var lede = el("p", "sec-lede");
    lede.textContent = "Novelty composite " + num(n.composite, 3) +
      " against the closest set in the corpus, " + (n.nearest || "—") + ". " +
      "The engine scores each channel as similarity, then reports novelty as one " +
      "minus their weighted mean — so a set is only as novel as its nearest " +
      "neighbour allows. Bars below show distinctness: longer is further away.";
    p.appendChild(lede);

    var box = el("div", "channels");
    n.channels.forEach(function (c) {
      var row = el("div", "chan");
      var name = el("div");
      name.appendChild(el("div", "chan__name", c.label));
      name.appendChild(el("div", "chan__w",
        "weight " + c.weight.toFixed(2) + " · similarity " + num(c.similarity, 2)));
      row.appendChild(name);

      var track = el("div", "chan__track");
      var fill = el("div", "chan__fill");
      fill.style.width = "0%";
      track.appendChild(fill);
      row.appendChild(track);
      row.appendChild(el("div", "chan__v", num(c.distinct, 2)));
      row.appendChild(el("div", "chan__blurb", c.blurb));
      box.appendChild(row);

      // animate after layout so the transition is visible
      requestAnimationFrame(function () {
        requestAnimationFrame(function () { fill.style.width = (c.distinct * 100) + "%"; });
      });
    });
    p.appendChild(box);

    var foot = el("p", "srcline");
    foot.textContent =
      "These nine channels carry the weighted composite. A tenth fingerprint " +
      "signal — the answer-letter sequence — is audited across the corpus rather " +
      "than pairwise, alongside slot-distribution drift and the longest-option budget." +
      (n.verdict ? "  Recorded verdict: " + n.verdict + "." : "");
    p.appendChild(foot);
  }

  // --------------------------------------------------- tab: blueprint
  function renderBlueprint(d) {
    var p = $("#panel-blueprint");
    clear(p);
    var b = d.blueprint || {};

    var lede = el("p", "sec-lede");
    lede.textContent = "The specification this set was rendered against. It was drawn " +
      "before any prose existed, and the finished passage was scored on how faithfully " +
      "it realised this plan.";
    p.appendChild(lede);

    var slots = el("div", "slots");
    var labels = {
      family: "Argument family", persona: "Persona", ending: "Ending",
      rhythm: "Rhythm", revelation: "Revelation",
      distractor_profile: "Distractor profile", topology: "Question topology"
    };
    Object.keys(labels).forEach(function (k) {
      var v = (b.slots || {})[k];
      if (!v) return;
      var s = el("div", "slot");
      s.appendChild(el("div", "slot__k", labels[k]));
      s.appendChild(el("div", "slot__v", v));
      slots.appendChild(s);
    });
    if (b.instability != null) {
      var i = el("div", "slot");
      i.appendChild(el("div", "slot__k", "Instability"));
      i.appendChild(el("div", "slot__v", num(b.instability, 2)));
      slots.appendChild(i);
    }
    if (b.aperture) {
      var a = el("div", "slot");
      a.appendChild(el("div", "slot__k", "Aperture"));
      a.appendChild(el("div", "slot__v", b.aperture));
      slots.appendChild(a);
    }
    p.appendChild(slots);

    if (b.tension_system) {
      p.appendChild(el("p", "srcline", "Tension system: " + b.tension_system));
    }

    if (b.movement && b.movement.length) {
      var h = el("p", "sec-lede");
      h.style.marginTop = "34px";
      h.textContent = "Paragraph plan — each paragraph is assigned a rhetorical " +
        "function, a word budget and a cadence before it is written.";
      p.appendChild(h);

      var mv = el("div", "movement");
      b.movement.forEach(function (m) {
        var row = el("div", "move");
        row.appendChild(el("div", "move__n", "¶" + m.para));
        var mid = el("div");
        mid.appendChild(el("div", "move__f", m.function));
        var budget = Array.isArray(m.len_words)
          ? (m.len_words[0] === m.len_words[1]
             ? m.len_words[0] + " words" : m.len_words[0] + "–" + m.len_words[1] + " words")
          : "";
        mid.appendChild(el("div", "move__meta",
          [budget, m.cadence].filter(Boolean).join(" · ")));
        row.appendChild(mid);
        row.appendChild(el("div", "move__g", m.gist || ""));
        mv.appendChild(row);
      });
      p.appendChild(mv);
    }
  }

  // ------------------------------------------------------ tab: verify
  function renderVerify(d) {
    var p = $("#panel-verify");
    clear(p);

    var lede = el("p", "sec-lede");
    lede.textContent = "Two passes, neither performed by the model that wrote the set: " +
      "a rubric judge scoring craft, and an independent solver that attempts the " +
      "questions without ever seeing the answer key.";
    p.appendChild(lede);

    var scores = (d.judge && d.judge.scores) || {};
    var keys = Object.keys(scores);
    if (keys.length) {
      var h1 = el("p", "eyebrow");
      h1.style.marginTop = "34px";
      h1.textContent = "Rubric judge";
      p.appendChild(h1);

      var rub = el("div", "rubric");
      keys.forEach(function (k) {
        var s = scores[k] || {};
        var card = el("div", "crit");
        var head = el("div", "crit__head");
        head.appendChild(el("div", "crit__name", titleCase(k)));
        head.appendChild(el("div", "crit__score", num(s.score, 1) + " / 10"));
        card.appendChild(head);
        var track = el("div", "crit__track");
        var fill = el("div", "crit__fill");
        fill.style.width = "0%";
        track.appendChild(fill);
        card.appendChild(track);
        if (s.note) card.appendChild(el("div", "crit__note", s.note));
        rub.appendChild(card);
        requestAnimationFrame(function () {
          requestAnimationFrame(function () {
            fill.style.width = Math.max(0, Math.min(100, (s.score || 0) * 10)) + "%";
          });
        });
      });
      p.appendChild(rub);
    }

    var solver = d.solver || {};
    if (solver.answers && solver.answers.length) {
      var h2 = el("p", "eyebrow");
      h2.style.marginTop = "40px";
      h2.textContent = "Independent solver";
      p.appendChild(h2);

      var meta = el("p", "sec-lede");
      meta.style.fontSize = "14px";
      meta.textContent = "Verdict: " + (solver.verdict || "—") +
        " · disputes raised: " + (solver.disputes ? solver.disputes.length : 0) +
        (solver.comparable === true ? " · answers comparable to the key" : "");
      p.appendChild(meta);

      var box = el("div", "answers");
      solver.answers.forEach(function (a) {
        var card = el("div", "ans" + (a.confidence ? " ans--" + a.confidence : ""));
        card.appendChild(el("div", "ans__q", "Q" + a.q));
        card.appendChild(el("div", "ans__a", a.answer || "?"));
        card.appendChild(el("div", "ans__c", a.confidence || ""));
        if (a.reasoning) card.title = a.reasoning;
        box.appendChild(card);
      });
      p.appendChild(box);

      var disputes = solver.disputes || [];
      if (disputes.length) {
        var dl = el("div", "gate__reasons");
        disputes.forEach(function (x) {
          dl.appendChild(el("span", "tag tag--reject",
            typeof x === "string" ? x : JSON.stringify(x)));
        });
        p.appendChild(dl);
      }
    }

    if (!keys.length && !(solver.answers || []).length) {
      p.appendChild(el("div", "locked", "No verification record was stored for this set."));
    }
  }

  // ---------------------------------------------------------- plumbing
  function loadSet(rcId) {
    if (state.cache[rcId]) return paint(state.cache[rcId]);
    fetchJSON("sets/" + encodeURIComponent(rcId) + ".json")
      .then(function (d) { state.cache[rcId] = d; paint(d); })
      .catch(function (e) {
        var p = $("#panel-read");
        clear(p);
        p.appendChild(el("div", "error", "Could not load " + rcId + " — " + e.message));
      });
  }

  function paint(d) {
    state.detail = d;
    renderMeta(d);
    renderRead(d);
    renderAudit(d);
    renderBlueprint(d);
    renderVerify(d);
  }

  function initTabs() {
    var tabs = Array.prototype.slice.call(document.querySelectorAll(".tab"));
    tabs.forEach(function (t, i) {
      t.addEventListener("click", function () { select(i); });
      t.addEventListener("keydown", function (e) {
        var d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
        if (!d) return;
        e.preventDefault();
        var next = (i + d + tabs.length) % tabs.length;
        select(next);
        tabs[next].focus();
      });
    });
    function select(idx) {
      tabs.forEach(function (t, j) {
        t.setAttribute("aria-selected", j === idx ? "true" : "false");
        t.setAttribute("tabindex", j === idx ? "0" : "-1");
        $("#" + t.getAttribute("aria-controls")).hidden = j !== idx;
      });
    }
    select(0);
  }

  function initTheme() {
    var btn = $("#themebtn");
    var saved = null;
    try { saved = localStorage.getItem("rc-demo-theme"); } catch (e) { /* private mode */ }
    var theme = saved || "dark";
    apply(theme);
    btn.addEventListener("click", function () {
      apply(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
    });
    function apply(t) {
      document.documentElement.setAttribute("data-theme", t);
      btn.textContent = t === "dark" ? "Light" : "Dark";
      try { localStorage.setItem("rc-demo-theme", t); } catch (e) { /* ignore */ }
    }
  }

  function fail(err) {
    var main = document.querySelector("main");
    var box = el("div", "shell");
    var e = el("div", "error", "Could not load the snapshot.");
    e.appendChild(el("code", null, String(err && err.message || err)));
    e.appendChild(el("code", null,
      "This page must be served over http(s) — opening index.html from the " +
      "filesystem blocks the JSON reads."));
    box.appendChild(e);
    main.insertBefore(box, main.firstChild);
  }

  function boot() {
    initTheme();
    initTabs();
    Promise.all([
      fetchJSON("corpus.json"),
      fetchJSON("funnel.json"),
      fetchJSON("sets.json")
    ]).then(function (r) {
      state.corpus = r[0];
      state.funnel = r[1];
      state.sets = r[2];
      renderStats();
      renderTables();
      renderFunnel();
      var first = renderPicker();
      if (first) loadSet(first);
    }).catch(fail);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
