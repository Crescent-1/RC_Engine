/**
 * Passage Works — site interactions v2
 * Zero dependencies. Every animation degrades gracefully under
 * prefers-reduced-motion and without JS (content is fully static HTML).
 */
(() => {
  "use strict";

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const root = document.documentElement;
  const THEME_KEY = "bp-theme";

  /* ---------------------------------------------------------------- theme */
  const systemTheme = () =>
    window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";

  function applyTheme(t) {
    root.setAttribute("data-theme", t);
    try { localStorage.setItem(THEME_KEY, t); } catch (_) {}
  }

  (function initTheme() {
    let stored = null;
    try { stored = localStorage.getItem(THEME_KEY); } catch (_) {}
    applyTheme(stored === "light" || stored === "dark" ? stored : systemTheme());
  })();

  $("#theme-toggle")?.addEventListener("click", () => {
    applyTheme(root.getAttribute("data-theme") === "dark" ? "light" : "dark");
  });
  addEventListener("keydown", (e) => {
    if (e.key.toLowerCase() === "t" && !/input|textarea|select/i.test(e.target.tagName)) {
      applyTheme(root.getAttribute("data-theme") === "dark" ? "light" : "dark");
    }
  });

  /* ---------------------------------------------------------- scroll rail */
  const rail = $(".scroll-rail");
  const railBar = $(".scroll-rail__bar");
  function updateRail() {
    const h = document.documentElement.scrollHeight - innerHeight;
    const p = h > 0 ? (scrollY / h) * 100 : 0;
    railBar.style.width = p + "%";
    rail.setAttribute("aria-valuenow", Math.round(p));
  }
  addEventListener("scroll", updateRail, { passive: true });
  updateRail();

  /* --------------------------------------------------------------- reveal */
  const revealIO = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) { e.target.classList.add("is-in"); revealIO.unobserve(e.target); }
    }
  }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
  $$("[data-reveal]").forEach((el) => revealIO.observe(el));

  // Failsafe: if IntersectionObserver never delivers (frame-starved webviews,
  // exotic embedders), un-hide everything rather than leave a blank page.
  addEventListener("load", () => {
    setTimeout(() => {
      if (!$("[data-reveal].is-in")) {
        $$("[data-reveal]").forEach((el) => el.classList.add("is-in"));
        $(".skeleton-demo")?.classList.add("is-revealed");
      }
    }, 1200);
  });

  /* ----------------------------------------------------------- nav active */
  const navLinks = $$(".nav a");
  const navTargets = navLinks
    .map((a) => $(a.getAttribute("href")))
    .filter(Boolean);
  const navIO = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      navLinks.forEach((a) =>
        a.classList.toggle("is-active", a.getAttribute("href") === "#" + e.target.id));
    }
  }, { rootMargin: "-40% 0px -55% 0px" });
  navTargets.forEach((t) => navIO.observe(t));

  /* -------------------------------------------------------- ambient field */
  const canvas = $("#field");
  if (canvas && !reduced) {
    const ctx = canvas.getContext("2d");
    let w, h, nodes = [], raf;
    const N = 42;
    function resize() {
      w = canvas.width = innerWidth * devicePixelRatio;
      h = canvas.height = innerHeight * devicePixelRatio;
    }
    function seed() {
      nodes = Array.from({ length: N }, () => ({
        x: Math.random() * w, y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.12 * devicePixelRatio,
        vy: (Math.random() - 0.5) * 0.12 * devicePixelRatio,
        r: (Math.random() * 1.1 + 0.4) * devicePixelRatio,
      }));
    }
    function tick() {
      ctx.clearRect(0, 0, w, h);
      const dark = root.getAttribute("data-theme") === "dark";
      const dot = dark ? "rgba(140,160,220," : "rgba(60,80,160,";
      const link = dark ? "rgba(107,140,255," : "rgba(61,90,224,";
      for (const n of nodes) {
        n.x += n.vx; n.y += n.vy;
        if (n.x < 0 || n.x > w) n.vx *= -1;
        if (n.y < 0 || n.y > h) n.vy *= -1;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.fillStyle = dot + "0.35)";
        ctx.fill();
      }
      const maxD = 150 * devicePixelRatio;
      for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
        const a = nodes[i], b = nodes[j];
        const dx = a.x - b.x, dy = a.y - b.y, d = Math.hypot(dx, dy);
        if (d < maxD) {
          ctx.beginPath();
          ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
          ctx.strokeStyle = link + (0.08 * (1 - d / maxD)).toFixed(3) + ")";
          ctx.lineWidth = devicePixelRatio * 0.7;
          ctx.stroke();
        }
      }
      raf = requestAnimationFrame(tick);
    }
    resize(); seed(); tick();
    addEventListener("resize", () => { resize(); seed(); });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) cancelAnimationFrame(raf); else tick();
    });
  }

  /* ------------------------------------------------------- component data */
  const LIB = {
    families: [
      ["The Autopsy", "how a consensus formed, not who was right"],
      ["The Borrowed Lens", "an imported framework distorts more than it reveals"],
      ["The Scale Shift", "the claim inverts when you zoom out"],
      ["The Definitional Undertow", "the real fight is over the key term"],
      ["The Reluctant Conversion", "the author argues themselves across the line"],
      ["The Third Thing", "both rivals share one hidden premise"],
      ["The Vanishing Object", "inquiry dissolves its own object"],
      ["The Costed Victory", "the thesis stands — diminished"],
      ["The Time-Lag Argument", "judged by criteria from a vanished era"],
      ["The Practitioner's Rebuke", "theory meets detail that breaks it"],
      ["The Asymmetry Hunt", "a habitual symmetry comes apart"],
      ["The Successful Failure", "failed its goal, succeeded at another"],
      ["The Category Refugee", "no taxonomy fits without mutilation"],
      ["The Inheritance Dispute", "two traditions claim one ancestor"],
      ["The Diagnostic Reversal", "the disease re-read as adaptation"],
      ["The Silent Partner", "an invisible condition erodes"],
      ["The Half-Life", "a concept decays as it migrates"],
      ["The Double Bind", "two legitimate, incompatible demands"],
      ["The Wrong Question", "answered, found wanting, reframed"],
      ["The Minority Report", "a lost view steelmanned, not endorsed"],
      ["The Instrument Effect", "the method produces what it finds"],
      ["The Threshold Argument", "degree becomes kind — but where?"],
      ["The Proxy War", "a technical dispute hides a commitment"],
      ["The Hospitable Critic", "sincere admiration, fatal objection"],
      ["The Ecology", "agents refused; equilibrium described"],
      ["The Untranslatable", "resistance to translation as evidence"],
      ["The Simultaneity Problem", "the causal arrow breaks"],
      ["The Boring Truth", "spectacle deflated for a hard mundane fact"],
      ["The Moving Target", "a critique outlived by its object"],
      ["The Self-Application", "a theory applied to itself"],
      ["The Load-Bearing Anecdote", "one incident, three readings"],
      ["The Coalition of Errors", "a true belief held for bad reasons"],
    ],
    personas: [
      "The Forensic Skeptic", "The Disenchanted Insider", "The Genial Contrarian",
      "The Systems Cartographer", "The Moral Accountant", "The Historian of the Present",
      "The Reluctant Modernist", "The Analytic Miniaturist", "The Field Reporter Turned Theorist",
      "The Recovering Enthusiast", "The Institutional Anthropologist", "The Epistemic Auditor",
      "The Comparative Synthesist", "The Patient Explicator", "The Ironic Formalist",
      "The Pragmatist Judge", "The Melancholy Realist", "The Precision Provocateur",
      "The Archaeologist of Ideas", "The Cold Enthusiast",
    ],
    endings: [
      "The Widened Aperture", "The Returned Key", "The Burden Shift", "The Practical Deflation",
      "The Residue", "The Horizon Clause", "The Quiet Verdict", "The Displacement",
      "The Cost Disclosure", "The Open Ledger", "The Retrospective Frame", "The Scale Exit",
      "The Instrument Doubt", "The Minor Character Promotion", "The Refused Synthesis",
      "The Time Bomb", "The Narrowed Claim", "The Anti-Conclusion", "The Handover",
      "The Earned Banality",
    ],
    rhythms: [
      "Monolith & Shards", "Staircase", "Inverted Staircase", "Pendulum", "Twin Peaks",
      "Slow Fuse", "Front-Load", "Interruption", "Braid", "Spiral", "Ledger", "Wave",
      "Trapdoor", "Overture", "Long Corridor", "Eddy", "Counterweight", "Cold Open",
      "Descent", "Ascent",
    ],
    reveals: [
      "Immediate-then-Eroded", "Decoy First", "Negative Space", "Late Crystallization",
      "Two-Stage", "Borrowed Mouth", "Question Form", "Retrospective Reveal",
      "Progressive Sharpening", "Casual Aside", "Definitional Smuggle", "Concessive Carrier",
      "Split Thesis", "Counter-Punch", "Example-Borne", "Escalating Denial", "Frame Shift",
      "Delayed Referent", "Convergence", "Erosion Reversal",
    ],
    distractors: [
      "The Premature Closer", "The Scope Inflater", "The Time Traveler", "The Sympathetic Import",
      "The Half-Truth Ledger", "The Inversion Artist", "The Tone Deaf", "The Vocabulary Magnet",
      "The Reasonable Extremist", "The Straw Vendor", "The Category Slipper",
      "The Consensus Peddler", "The Symmetry Faker", "The Level Confuser",
      "The Necessary/Sufficient Swapper", "The Example Promoter", "The Missing Link",
      "The Overqualifier", "The Adjacent Answer", "The Terminological Twin",
    ],
    topologies: [
      "Classic Gauntlet", "Inverted", "Structural Emphasis", "Application Heavy",
      "Local–Global Ladder", "The Ambush", "Assumption Cluster", "Tone Split",
      "Cross-Paragraph Weave", "The Decoy Mirror", "Evidence Audit", "Counterfactual Set",
      "The Compression Test", "The Expansion Test", "Sequential Dependency", "Deep Drill",
      "Author vs. Reported", "Strengthen/Weaken Pair", "The Ending Interrogation",
      "The Uniform Field",
    ],
  };
  const LIB_ORDER = ["families", "personas", "endings", "rhythms", "reveals", "distractors", "topologies"];
  const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
  const nameOf = (lib, item) => (lib === "families" ? item[0] : item);
  const hash = () => Array.from({ length: 10 }, () => "0123456789abcdef"[Math.floor(Math.random() * 16)]).join("");

  /* --------------------------------------------------------- hero composer */
  const composer = $("#hero-composer");
  if (composer) {
    const slots = $$("[data-slot]", composer);
    const state = $("#composer-state");
    const hashEl = $("#composer-hash");
    const distEl = $("#composer-dist");
    const idEl = $("#composer-id");
    let run = 0;

    function compose() {
      const myRun = ++run;
      state.classList.remove("is-locked");
      state.querySelector("b").textContent = "composing";
      hashEl.innerHTML = "combo · sampling under exclusion windows…";
      distEl.textContent = "";
      idEl.textContent = "BLUEPRINT · BP-2026-07-0" + (140 + Math.floor(Math.random() * 60));
      slots.forEach((s) => { s.classList.remove("is-locked"); });

      if (reduced) {
        slots.forEach((s, i) => {
          s.textContent = nameOf(LIB_ORDER[i], pick(LIB[LIB_ORDER[i]]));
          s.classList.add("is-locked");
        });
        lock(myRun);
        return;
      }

      slots.forEach((slot, i) => {
        const lib = LIB[LIB_ORDER[i]];
        let ticks = 0;
        const max = 7 + i * 3;
        const iv = setInterval(() => {
          if (myRun !== run) { clearInterval(iv); return; }
          slot.textContent = nameOf(LIB_ORDER[i], pick(lib));
          if (++ticks >= max) {
            clearInterval(iv);
            slot.classList.add("is-locked");
            if (i === slots.length - 1) lock(myRun);
          }
        }, 90);
      });
    }
    function lock(myRun) {
      if (myRun !== run) return;
      state.classList.add("is-locked");
      state.querySelector("b").textContent = "contract locked";
      hashEl.innerHTML = "combo · <b>" + hash() + "</b> · never reused";
      const d = (0.58 + Math.random() * 0.3).toFixed(2);
      distEl.innerHTML = "distance vs last 50 · <b>" + d + " PASS</b>";
    }
    // First run when hero becomes visible; re-run every 9s while visible.
    let composerTimer = null;
    const composerIO = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (e.isIntersecting) {
          compose();
          if (!reduced && !composerTimer) composerTimer = setInterval(compose, 9000);
        } else if (composerTimer) { clearInterval(composerTimer); composerTimer = null; }
      }
    }, { threshold: 0.2 });
    composerIO.observe(composer);
  }

  /* -------------------------------------------------------- skeleton demo */
  const skDemo = $(".skeleton-demo");
  if (skDemo) {
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (e.isIntersecting) { skDemo.classList.add("is-revealed"); io.disconnect(); }
      }
    }, { threshold: 0.45 });
    io.observe(skDemo);
  }

  /* ------------------------------------------------------ pipeline scroll */
  const pipeSteps = $$(".pipe-step");
  const pipeNodes = $$(".pipe-node");
  if (pipeSteps.length) {
    const stepIO = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        const idx = Number(e.target.dataset.step);
        pipeSteps.forEach((s) => s.classList.toggle("is-active", s === e.target));
        pipeNodes.forEach((n) => {
          const ni = Number(n.dataset.node);
          n.classList.toggle("is-active", ni === idx);
          n.classList.toggle("is-done", ni < idx);
        });
      }
    }, { rootMargin: "-42% 0px -50% 0px" });
    pipeSteps.forEach((s) => stepIO.observe(s));
  }

  /* -------------------------------------------------------- audit console */
  const CONSOLE_CHANNELS = [
    ["blueprint distance", 0.45],
    ["movement string", 0.70],
    ["conviction arc", 0.85],
    ["rhythm vector", 0.92],
    ["question topology", 0.75],
    ["distractor mix", 0.80],
    ["voice stylometry", 0.72],
    ["answer behaviour", 0.78],
    ["topic embedding", 0.80],
  ];
  // Two scripted runs: first breaches "movement string", recompose passes all.
  const RUN_REJECT = [0.31, 0.74, 0.52, 0.44, 0.38, 0.47, 0.41, 0.33, 0.36];
  const RUN_PASS   = [0.22, 0.38, 0.41, 0.35, 0.29, 0.42, 0.37, 0.28, 0.31];

  const consoleEl = $(".console");
  if (consoleEl) {
    const verdictEl = $("#console-verdict");
    const titleEl = $("#console-title");
    const capEl = $("#console-cap");
    const rows = $$("#console-rows .crow"); // pre-rendered in HTML (no-JS fallback shows the pass state)

    let playing = false;
    function setRow(i, sim, breach) {
      const row = rows[i];
      row.classList.toggle("is-breach", breach);
      $(".crow__fill", row).style.width = (sim * 100).toFixed(0) + "%";
      $(".crow__val", row).textContent = sim.toFixed(2);
    }
    function resetRows() {
      rows.forEach((row) => {
        row.classList.remove("is-breach");
        $(".crow__fill", row).style.width = "0%";
        $(".crow__val", row).textContent = "—";
      });
    }
    function verdict(text, cls) {
      verdictEl.textContent = text;
      verdictEl.className = "console__verdict mono is-stamp " + (cls || "");
      setTimeout(() => verdictEl.classList.remove("is-stamp"), 450);
    }
    async function play() {
      if (playing) return;
      playing = true;
      const wait = (ms) => new Promise((r) => setTimeout(r, reduced ? 0 : ms));

      // Run 1 — rejection
      resetRows();
      titleEl.textContent = "AUDIT · RC-E-0711-2 · vs trailing 100";
      capEl.textContent = "Channel caps are hard limits — a single structural breach rejects the set and a fresh blueprint is composed.";
      verdict("running…");
      await wait(350);
      for (let i = 0; i < 9; i++) {
        const sim = RUN_REJECT[i];
        const breach = sim > CONSOLE_CHANNELS[i][1];
        setRow(i, sim, breach);
        await wait(240);
      }
      verdict("rejected · movement too close to RC-E-0630-1", "is-reject");
      await wait(1900);

      // Run 2 — recomposed set passes
      resetRows();
      titleEl.textContent = "AUDIT · RC-E-0711-2R · recomposed · vs trailing 100";
      verdict("recomposing · fresh blueprint…");
      await wait(900);
      for (let i = 0; i < 9; i++) {
        setRow(i, RUN_PASS[i], false);
        await wait(200);
      }
      verdict("pass · composite novelty 0.67 · cleared to ship", "is-pass");
      capEl.textContent = "The rejected attempt still enters the corpus memory — future sets must diverge from it too.";
      playing = false;
    }
    $("#console-replay")?.addEventListener("click", play);
    const cio = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (e.isIntersecting) { play(); cio.disconnect(); }
      }
    }, { threshold: 0.35 });
    cio.observe(consoleEl);
  }

  /* -------------------------------------------------------------- sampler */
  const samplerBtn = $("#sampler-btn");
  if (samplerBtn) {
    const vEls = $$("[data-sample]");
    const gEls = $$("[data-gloss]");
    const check = $("#sampler-check");
    let rolling = false;
    function roll() {
      if (rolling) return;
      rolling = true;
      const finals = LIB_ORDER.map((lib) => pick(LIB[lib]));
      if (reduced) { settle(finals); return; }
      vEls.forEach((el) => el.closest(".slot").classList.add("is-rolling"));
      let ticks = 0;
      const iv = setInterval(() => {
        vEls.forEach((el, i) => {
          el.textContent = nameOf(LIB_ORDER[i], pick(LIB[LIB_ORDER[i]]));
        });
        if (++ticks >= 9) { clearInterval(iv); settle(finals); }
      }, 75);
    }
    function settle(finals) {
      vEls.forEach((el, i) => {
        el.textContent = nameOf(LIB_ORDER[i], finals[i]);
        el.closest(".slot").classList.remove("is-rolling");
      });
      gEls.forEach((el, i) => {
        el.textContent = LIB_ORDER[i] === "families" ? finals[i][1] : "";
      });
      // Occasionally dramatise a pre-check rejection + auto-resample.
      const d = 0.42 + Math.random() * 0.5;
      if (d < 0.55) {
        check.classList.add("is-fail");
        check.innerHTML = "distance vs last 50 · <b>" + d.toFixed(2) + "</b> · REJECTED — resampling…";
        setTimeout(() => { rolling = false; roll(); }, reduced ? 0 : 900);
      } else {
        check.classList.remove("is-fail");
        check.innerHTML = "distance vs last 50 · <b>" + d.toFixed(2) + "</b> · PASS";
        rolling = false;
      }
    }
    samplerBtn.addEventListener("click", roll);
  }

  /* -------------------------------------------------------- trap question */
  const qHint = $("#q-hint");
  $$(".q-opt").forEach((opt) => {
    opt.addEventListener("click", () => {
      $$(".q-opt").forEach((o) => o.classList.remove("is-open"));
      opt.classList.add("is-open");
      const mech = opt.dataset.mech;
      const chip = $(".q-opt__chip", opt);
      chip.textContent = mech === "correct" ? "✓ correct" : mech;
      if (qHint) qHint.textContent = opt.dataset.note;
    });
  });

  /* ------------------------------------------------------------ counters */
  const counters = $$("[data-count]");
  if (counters.length && !reduced) {
    const cio = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        cio.unobserve(e.target);
        const end = Number(e.target.dataset.count);
        const t0 = performance.now();
        const dur = 1100;
        const step = (t) => {
          const p = Math.min(1, (t - t0) / dur);
          e.target.textContent = Math.round(end * (1 - Math.pow(1 - p, 3)));
          if (p < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      }
    }, { threshold: 0.6 });
    counters.forEach((c) => cio.observe(c));
  }

  /* ----------------------------------------------------------- sticky CTA */
  const sticky = $("#sticky-cta");
  if (sticky) {
    sticky.hidden = false;
    const contact = $("#contact");
    const hero = $("#top");
    function updateSticky() {
      const past = scrollY > (hero?.offsetHeight || 600) * 1.2;
      const nearEnd = contact &&
        contact.getBoundingClientRect().top < innerHeight * 0.85;
      sticky.classList.toggle("is-visible", past && !nearEnd);
    }
    addEventListener("scroll", updateSticky, { passive: true });
    updateSticky();
  }
})();
