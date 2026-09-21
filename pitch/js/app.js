/**
 * Passage Works — faculty pitch interactions
 * Theme · progress · reveal · sticky CTA · Q demo
 */
(() => {
  "use strict";

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const root = document.documentElement;
  const KEY = "bp-pitch-theme";

  function systemTheme() {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function applyTheme(t) {
    root.setAttribute("data-theme", t);
    try { localStorage.setItem(KEY, t); } catch (_) {}
  }

  function initTheme() {
    let stored = null;
    try { stored = localStorage.getItem(KEY); } catch (_) {}
    applyTheme(stored === "light" || stored === "dark" ? stored : systemTheme());
  }

  function toggleTheme() {
    applyTheme(root.getAttribute("data-theme") === "light" ? "dark" : "light");
  }

  function initScroll() {
    const bar = $(".progress__bar");
    const progress = $(".progress");
    const sticky = $("#sticky-bar");
    const hero = $(".hero");
    const navLinks = $$(".nav a");
    const sections = $$("main section[id]");

    function onScroll() {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      const pct = max > 0 ? (window.scrollY / max) * 100 : 0;
      if (bar) bar.style.width = `${pct}%`;
      if (progress) progress.setAttribute("aria-valuenow", String(Math.round(pct)));

      if (sticky && hero) {
        const past = window.scrollY > hero.offsetHeight * 0.5;
        const nearEnd = window.scrollY + window.innerHeight > document.body.scrollHeight - 320;
        if (past && !nearEnd) {
          sticky.hidden = false;
          requestAnimationFrame(() => sticky.classList.add("is-shown"));
        } else {
          sticky.classList.remove("is-shown");
          if (!past) sticky.hidden = true;
        }
      }

      let current = "";
      const y = window.scrollY + 120;
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
      { rootMargin: "0px 0px -8% 0px", threshold: 0.08 }
    );
    nodes.forEach((n) => io.observe(n));
  }

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

  function initQDemo() {
    const hint = $("#q-hint");
    const opts = $$(".q-opt");
    if (!hint || !opts.length) return;
    opts.forEach((btn) => {
      btn.addEventListener("click", () => {
        opts.forEach((o) => o.classList.remove("is-on"));
        btn.classList.add("is-on");
        hint.textContent = btn.dataset.note || "";
      });
    });
  }

  function initKeys() {
    document.addEventListener("keydown", (e) => {
      const tag = e.target?.tagName || "";
      if (/INPUT|TEXTAREA|SELECT/.test(tag) || e.target?.isContentEditable) return;
      if (e.key.toLowerCase() === "t" && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        toggleTheme();
      }
    });
  }

  function boot() {
    initTheme();
    initScroll();
    initReveal();
    initAnchors();
    initQDemo();
    initKeys();
    $("#theme-toggle")?.addEventListener("click", toggleTheme);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
