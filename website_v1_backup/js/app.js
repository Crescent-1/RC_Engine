/**
 * Blueprint Psychometrics — pitch site interactions
 */
(() => {
  "use strict";

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const root = document.documentElement;
  const THEME_KEY = "bp-theme";

  /* Theme ----------------------------------------------------------------- */
  function systemTheme() {
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }

  function applyTheme(t) {
    root.setAttribute("data-theme", t);
    try { localStorage.setItem(THEME_KEY, t); } catch (_) {}
    const meta = document.querySelector('meta[name="theme-color"]:not([media])') ||
      document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", t === "light" ? "#f4f6fa" : "#070b12");
  }

  function initTheme() {
    let stored = null;
    try { stored = localStorage.getItem(THEME_KEY); } catch (_) {}
    applyTheme(stored === "light" || stored === "dark" ? stored : systemTheme());
  }

  function toggleTheme() {
    applyTheme(root.getAttribute("data-theme") === "light" ? "dark" : "light");
    toast(root.getAttribute("data-theme") === "light" ? "Light mode" : "Dark mode");
  }

  /* Toast ----------------------------------------------------------------- */
  let toastTimer;
  function toast(msg) {
    const el = $("#toast");
    if (!el) return;
    el.hidden = false;
    el.textContent = msg;
    requestAnimationFrame(() => el.classList.add("is-on"));
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      el.classList.remove("is-on");
      setTimeout(() => { el.hidden = true; }, 280);
    }, 2200);
  }

  /* Scroll progress + nav + sticky CTA ------------------------------------ */
  function initScrollChrome() {
    const bar = $(".scroll-rail__bar");
    const rail = $(".scroll-rail");
    const sticky = $("#sticky-cta");
    const navLinks = $$(".nav a");
    const sections = $$("main section[id]");
    const hero = $(".hero");

    function onScroll() {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      const pct = max > 0 ? (window.scrollY / max) * 100 : 0;
      if (bar) bar.style.width = `${pct}%`;
      if (rail) rail.setAttribute("aria-valuenow", String(Math.round(pct)));

      // sticky after hero
      if (sticky && hero) {
        const past = window.scrollY > hero.offsetHeight * 0.55;
        const nearContact = window.scrollY + window.innerHeight > document.body.scrollHeight - 280;
        if (past && !nearContact) {
          sticky.hidden = false;
          requestAnimationFrame(() => sticky.classList.add("is-shown"));
        } else {
          sticky.classList.remove("is-shown");
          if (!past) sticky.hidden = true;
        }
      }

      let current = "";
      const y = window.scrollY + 130;
      for (const sec of sections) {
        if (sec.offsetTop <= y) current = sec.id;
      }
      navLinks.forEach((a) => {
        const id = (a.getAttribute("href") || "").slice(1);
        if (id && id === current) a.setAttribute("aria-current", "true");
        else a.removeAttribute("aria-current");
      });
    }

    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  /* Reveal ---------------------------------------------------------------- */
  function initReveal() {
    const nodes = $$("[data-reveal]");
    if (reduced) {
      nodes.forEach((n) => n.classList.add("is-in"));
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("is-in");
            io.unobserve(e.target);
          }
        });
      },
      { rootMargin: "0px 0px -6% 0px", threshold: 0.08 }
    );
    nodes.forEach((n) => io.observe(n));
  }

  /* Channel explorer ------------------------------------------------------ */
  const CHANNELS = [
    {
      exploit: "“These passages always argue the same way.”",
      enforce:
        "Every passage is built on one of <strong>32 distinct skeletons</strong>; no two recent sets share one, and your corpus stays balanced across all of them.",
    },
    {
      exploit: "“Para 2 raises the objection, para 4 resolves it.”",
      enforce:
        "The sequence of argumentative moves is tracked <strong>like a chess line</strong>; repeated move-orders are detected and rejected.",
    },
    {
      exploit: "“The author commits late — the answers live in the late paragraphs.”",
      enforce:
        "We measure how strongly the author appears committed to the thesis, paragraph by paragraph, and <strong>force that arc to vary</strong> — the single strongest rhythm students unconsciously learn.",
    },
    {
      exploit: "“The short paragraph is always the pivot.”",
      enforce:
        "Paragraph lengths, sentence cadence, and pivot placement are <strong>fingerprinted</strong>; repeated pacing shapes are blocked.",
    },
    {
      exploit: "“Q1 is the main-idea question; the last one is tone.”",
      enforce:
        "Question types, order, and difficulty curves are <strong>deliberately varied</strong> — there is no fixed question formula to learn.",
    },
    {
      exploit: "“Eliminate the extreme option and the too-broad option — done.”",
      enforce:
        "The <strong>way wrong options are wrong</strong> keeps changing. Elimination heuristics that work on one set fail on the next.",
    },
    {
      exploit: "“All these passages read like the same writer.”",
      enforce:
        "Passages are written in 20 voices verified as <strong>statistically different authors</strong>, using the methods of authorship forensics.",
    },
    {
      exploit: "“When in doubt, pick the longest option. Or C.”",
      enforce:
        "Letters, option lengths, and hedging of correct answers are tested for exploitable patterns <strong>across your whole series</strong>, not just within one set.",
    },
    {
      exploit: "“We've basically seen this passage before.”",
      enforce:
        "Content-level similarity is checked against <strong>every set in your history</strong> — the oldest check, still enforced.",
    },
  ];

  function initChannels() {
    const tabs = $$(".ch-tab");
    const exploit = $("#ch-exploit");
    const enforce = $("#ch-enforce");
    const panel = $("#ch-panel");
    if (!tabs.length || !exploit || !enforce) return;

    function select(i) {
      const ch = CHANNELS[i];
      if (!ch) return;
      tabs.forEach((t, idx) => {
        const on = idx === i;
        t.classList.toggle("is-active", on);
        t.setAttribute("aria-selected", on ? "true" : "false");
      });
      exploit.textContent = ch.exploit;
      enforce.innerHTML = ch.enforce;
      if (panel) panel.setAttribute("aria-labelledby", `tab-${i}`);
      if (!reduced) {
        panel?.animate(
          [
            { opacity: 0.4, transform: "translateY(6px)" },
            { opacity: 1, transform: "none" },
          ],
          { duration: 280, easing: "cubic-bezier(0.16,1,0.3,1)" }
        );
      }
    }

    tabs.forEach((tab) => {
      tab.addEventListener("click", () => select(Number(tab.dataset.ch)));
      tab.addEventListener("keydown", (e) => {
        const i = Number(tab.dataset.ch);
        if (e.key === "ArrowDown" || e.key === "ArrowRight") {
          e.preventDefault();
          const next = Math.min(tabs.length - 1, i + 1);
          tabs[next].focus();
          select(next);
        } else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
          e.preventDefault();
          const prev = Math.max(0, i - 1);
          tabs[prev].focus();
          select(prev);
        }
      });
    });
  }

  /* Magnetic buttons ------------------------------------------------------ */
  function initMagnetic() {
    if (reduced || window.matchMedia("(pointer: coarse)").matches) return;
    $$(".btn--mag").forEach((btn) => {
      const s = 10;
      btn.addEventListener("pointermove", (e) => {
        const r = btn.getBoundingClientRect();
        const x = e.clientX - r.left - r.width / 2;
        const y = e.clientY - r.top - r.height / 2;
        btn.style.transform = `translate(${(x / r.width) * s}px, ${(y / r.height) * s}px)`;
      });
      btn.addEventListener("pointerleave", () => {
        btn.style.transform = "";
      });
    });
  }

  /* Anchors --------------------------------------------------------------- */
  function initAnchors() {
    document.addEventListener("click", (e) => {
      const a = e.target.closest('a[href^="#"]');
      if (!a) return;
      const href = a.getAttribute("href");
      if (!href || href === "#") return;
      const target = document.getElementById(href.slice(1));
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
      history.pushState(null, "", href);
    });
  }

  /* Blueprint grid field -------------------------------------------------- */
  function initField() {
    const canvas = $("#grid-field");
    if (!canvas || reduced) return;
    const ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;

    let w = 0, h = 0, dpr = 1, raf = 0, running = true;
    let t0 = performance.now();
    let scroll = 0;
    let mouse = { x: 0.6, y: 0.35 };

    function resize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function colors() {
      const light = root.getAttribute("data-theme") === "light";
      return {
        grid: light ? "rgba(14,21,32,0.06)" : "rgba(232,238,248,0.045)",
        accent: light ? "rgba(61,95,217,0.35)" : "rgba(107,140,255,0.4)",
        accent2: light ? "rgba(26,155,114,0.28)" : "rgba(79,209,165,0.3)",
        node: light ? "rgba(61,95,217,0.55)" : "rgba(107,140,255,0.55)",
      };
    }

    function draw(now) {
      if (!running) return;
      const t = (now - t0) * 0.001;
      const c = colors();
      ctx.clearRect(0, 0, w, h);

      const cell = 56;
      const ox = (t * 6 + scroll * 40) % cell;
      const oy = (t * 3 + scroll * 20) % cell;

      ctx.strokeStyle = c.grid;
      ctx.lineWidth = 1;
      for (let x = -cell + ox; x < w + cell; x += cell) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
      }
      for (let y = -cell + oy; y < h + cell; y += cell) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }

      // floating blueprint nodes
      const n = 18;
      for (let i = 0; i < n; i++) {
        const seed = i * 1.7;
        const px = ((Math.sin(t * 0.15 + seed) * 0.35 + 0.5 + mouse.x * 0.08) * w + i * 37) % w;
        const py = ((Math.cos(t * 0.12 + seed * 1.3) * 0.35 + 0.45 + mouse.y * 0.06 + scroll * 0.1) * h + i * 53) % h;
        const r = 1.5 + (i % 3) * 0.6;
        ctx.beginPath();
        ctx.arc(px, py, r, 0, Math.PI * 2);
        ctx.fillStyle = i % 4 === 0 ? c.accent2 : c.node;
        ctx.fill();

        // short connector ticks
        if (i % 2 === 0) {
          ctx.beginPath();
          ctx.moveTo(px, py);
          ctx.lineTo(px + 18 + Math.sin(t + seed) * 8, py + Math.cos(t + seed) * 6);
          ctx.strokeStyle = i % 4 === 0 ? c.accent2 : c.accent;
          ctx.globalAlpha = 0.45;
          ctx.stroke();
          ctx.globalAlpha = 1;
        }
      }

      // soft radial focus near mouse
      const g = ctx.createRadialGradient(mouse.x * w, mouse.y * h, 0, mouse.x * w, mouse.y * h, 280);
      g.addColorStop(0, root.getAttribute("data-theme") === "light" ? "rgba(61,95,217,0.04)" : "rgba(107,140,255,0.06)");
      g.addColorStop(1, "transparent");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);

      raf = requestAnimationFrame(draw);
    }

    resize();
    window.addEventListener("resize", resize);
    window.addEventListener(
      "scroll",
      () => {
        const max = document.documentElement.scrollHeight - window.innerHeight;
        scroll = max > 0 ? window.scrollY / max : 0;
      },
      { passive: true }
    );
    window.addEventListener(
      "pointermove",
      (e) => {
        mouse.x = e.clientX / w;
        mouse.y = e.clientY / h;
      },
      { passive: true }
    );
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        running = false;
        cancelAnimationFrame(raf);
      } else {
        running = true;
        t0 = performance.now();
        raf = requestAnimationFrame(draw);
      }
    });
    raf = requestAnimationFrame(draw);
  }

  /* Keys ------------------------------------------------------------------ */
  function initKeys() {
    document.addEventListener("keydown", (e) => {
      const tag = e.target?.tagName || "";
      if (/INPUT|TEXTAREA|SELECT/.test(tag) || e.target?.isContentEditable) return;
      if (e.key.toLowerCase() === "t" && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        toggleTheme();
      }
    });
  }

  /* Boot ------------------------------------------------------------------ */
  function boot() {
    initTheme();
    initScrollChrome();
    initReveal();
    initChannels();
    initMagnetic();
    initAnchors();
    initField();
    initKeys();
    $("#theme-toggle")?.addEventListener("click", toggleTheme);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
