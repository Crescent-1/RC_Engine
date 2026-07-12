/**
 * ansh.systems — interaction layer
 * Field canvas · command palette · motion · theme · a11y
 */
(() => {
  "use strict";

  const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  /* --------------------------------------------------------------------------
   * Theme
   * ----------------------------------------------------------------------- */
  const THEME_KEY = "ansh-theme";
  const root = document.documentElement;

  function systemTheme() {
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }

  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "light" ? "#f4f0e8" : "#0c0b0a");
    try { localStorage.setItem(THEME_KEY, theme); } catch (_) { /* private mode */ }
  }

  function initTheme() {
    let stored = null;
    try { stored = localStorage.getItem(THEME_KEY); } catch (_) {}
    applyTheme(stored === "light" || stored === "dark" ? stored : systemTheme());
  }

  function toggleTheme() {
    const next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
    applyTheme(next);
    toast(next === "dark" ? "Dark mode" : "Light mode");
  }

  /* --------------------------------------------------------------------------
   * Toast
   * ----------------------------------------------------------------------- */
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
      setTimeout(() => { el.hidden = true; }, 300);
    }, 2200);
  }

  /* --------------------------------------------------------------------------
   * Scroll progress + nav highlight
   * ----------------------------------------------------------------------- */
  function initScroll() {
    const bar = $(".scroll-progress__bar");
    const progress = $(".scroll-progress");
    const sections = $$("main section[id]");
    const navLinks = $$(".nav__list a");

    function onScroll() {
      const doc = document.documentElement;
      const max = doc.scrollHeight - window.innerHeight;
      const pct = max > 0 ? (window.scrollY / max) * 100 : 0;
      if (bar) bar.style.width = `${pct}%`;
      if (progress) progress.setAttribute("aria-valuenow", String(Math.round(pct)));

      let current = "";
      const y = window.scrollY + 120;
      for (const sec of sections) {
        if (sec.offsetTop <= y) current = sec.id;
      }
      navLinks.forEach((a) => {
        const href = a.getAttribute("href") || "";
        const id = href.startsWith("#") ? href.slice(1) : "";
        if (id && id === current) a.setAttribute("aria-current", "true");
        else a.removeAttribute("aria-current");
      });
    }

    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  /* --------------------------------------------------------------------------
   * Reveal on intersect
   * ----------------------------------------------------------------------- */
  function initReveal() {
    const nodes = $$("[data-reveal]");
    if (prefersReduced) {
      nodes.forEach((n) => n.classList.add("is-visible"));
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("is-visible");
            io.unobserve(e.target);
          }
        });
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.08 }
    );
    nodes.forEach((n) => io.observe(n));
  }

  /* --------------------------------------------------------------------------
   * Metric counters
   * ----------------------------------------------------------------------- */
  function initCounters() {
    const metrics = $$("[data-count-to]");
    if (!metrics.length) return;

    const animate = (el) => {
      const target = Number(el.dataset.countTo);
      const suffix = el.dataset.suffix || "";
      const prefix = el.dataset.prefix || "";
      const valueEl = el.querySelector(".metric__value");
      if (!valueEl || el.dataset.exp) return; // static scientific notation
      if (prefersReduced) {
        valueEl.textContent = `${prefix}${target}${suffix}`;
        return;
      }
      const duration = 1200;
      const start = performance.now();
      const step = (now) => {
        const t = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - t, 3);
        const n = Math.round(target * eased);
        valueEl.textContent = `${prefix}${n}${suffix}`;
        if (t < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    };

    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            animate(e.target);
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.4 }
    );
    metrics.forEach((m) => io.observe(m));
  }

  /* --------------------------------------------------------------------------
   * Magnetic buttons
   * ----------------------------------------------------------------------- */
  function initMagnetic() {
    if (prefersReduced || window.matchMedia("(pointer: coarse)").matches) return;
    $$(".btn--magnetic").forEach((btn) => {
      const strength = 12;
      btn.addEventListener("pointermove", (e) => {
        const r = btn.getBoundingClientRect();
        const x = e.clientX - r.left - r.width / 2;
        const y = e.clientY - r.top - r.height / 2;
        btn.style.transform = `translate(${(x / r.width) * strength}px, ${(y / r.height) * strength}px)`;
      });
      btn.addEventListener("pointerleave", () => {
        btn.style.transform = "";
      });
    });
  }

  /* --------------------------------------------------------------------------
   * Chapters rail
   * ----------------------------------------------------------------------- */
  function initChapters() {
    const track = $("#chapters-track");
    if (!track) return;
    const step = () => Math.min(track.clientWidth * 0.85, 360);
    $("[data-chapters-prev]")?.addEventListener("click", () => {
      track.scrollBy({ left: -step(), behavior: prefersReduced ? "auto" : "smooth" });
    });
    $("[data-chapters-next]")?.addEventListener("click", () => {
      track.scrollBy({ left: step(), behavior: prefersReduced ? "auto" : "smooth" });
    });
  }

  /* --------------------------------------------------------------------------
   * Smooth anchor (respect reduced motion)
   * ----------------------------------------------------------------------- */
  function initAnchors() {
    document.addEventListener("click", (e) => {
      const a = e.target.closest('a[href^="#"], [data-scroll-to]');
      if (!a) return;
      const href = a.getAttribute("href") || a.getAttribute("data-scroll-to");
      if (!href || href === "#") return;
      const id = href.slice(1);
      const target = document.getElementById(id);
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({ behavior: prefersReduced ? "auto" : "smooth", block: "start" });
      history.pushState(null, "", href);
    });
  }

  /* --------------------------------------------------------------------------
   * Generative structure field (canvas)
   * ----------------------------------------------------------------------- */
  function initField() {
    const canvas = $("#field");
    if (!canvas || prefersReduced) return;
    const ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;

    let w = 0, h = 0, dpr = 1;
    let nodes = [];
    let raf = 0;
    let scrollT = 0;
    let mouse = { x: 0.5, y: 0.4 };
    let running = true;

    const NODE_COUNT = Math.min(48, Math.floor((window.innerWidth * window.innerHeight) / 28000) + 22);

    function themeColors() {
      const light = root.getAttribute("data-theme") === "light";
      return {
        node: light ? "rgba(196, 95, 18, 0.55)" : "rgba(232, 160, 80, 0.55)",
        nodeSoft: light ? "rgba(31, 122, 100, 0.35)" : "rgba(126, 200, 176, 0.35)",
        link: light ? "rgba(26, 22, 18, 0.08)" : "rgba(242, 235, 224, 0.07)",
        linkHot: light ? "rgba(196, 95, 18, 0.22)" : "rgba(232, 160, 80, 0.22)",
      };
    }

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

    function seed() {
      nodes = Array.from({ length: NODE_COUNT }, (_, i) => ({
        x: Math.random() * w,
        y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.22,
        vy: (Math.random() - 0.5) * 0.22,
        r: 1.2 + Math.random() * 1.8,
        phase: Math.random() * Math.PI * 2,
        kind: i % 5 === 0 ? 1 : 0,
      }));
    }

    function draw(t) {
      if (!running) return;
      const colors = themeColors();
      ctx.clearRect(0, 0, w, h);

      const mx = mouse.x * w;
      const my = mouse.y * h;
      const pull = 0.0008 + scrollT * 0.0004;

      for (const n of nodes) {
        n.x += n.vx + Math.sin(t * 0.0004 + n.phase) * 0.05;
        n.y += n.vy + Math.cos(t * 0.0003 + n.phase) * 0.05;
        n.vx += (mx - n.x) * pull * 0.02;
        n.vy += (my - n.y) * pull * 0.02;
        n.vx *= 0.992;
        n.vy *= 0.992;
        if (n.x < -20) n.x = w + 20;
        if (n.x > w + 20) n.x = -20;
        if (n.y < -20) n.y = h + 20;
        if (n.y > h + 20) n.y = -20;
      }

      const maxDist = 140 + scrollT * 40;
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i];
          const b = nodes[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const d = Math.hypot(dx, dy);
          if (d > maxDist) continue;
          const alpha = 1 - d / maxDist;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.strokeStyle = alpha > 0.55 ? colors.linkHot : colors.link;
          ctx.globalAlpha = alpha * 0.9;
          ctx.lineWidth = alpha > 0.6 ? 1.1 : 0.7;
          ctx.stroke();
          ctx.globalAlpha = 1;
        }
      }

      for (const n of nodes) {
        const pulse = 0.6 + Math.sin(t * 0.002 + n.phase) * 0.4;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r * pulse, 0, Math.PI * 2);
        ctx.fillStyle = n.kind ? colors.nodeSoft : colors.node;
        ctx.fill();
      }

      raf = requestAnimationFrame(draw);
    }

    function onScroll() {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      scrollT = max > 0 ? window.scrollY / max : 0;
    }

    resize();
    seed();
    window.addEventListener("resize", () => {
      resize();
      seed();
    });
    window.addEventListener("scroll", onScroll, { passive: true });
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
        raf = requestAnimationFrame(draw);
      }
    });

    // Rebuild colors when theme changes via MutationObserver on data-theme
    const mo = new MutationObserver(() => { /* colors read each frame */ });
    mo.observe(root, { attributes: true, attributeFilter: ["data-theme"] });

    raf = requestAnimationFrame(draw);
  }

  /* --------------------------------------------------------------------------
   * Command palette
   * ----------------------------------------------------------------------- */
  function initCommandPalette() {
    const cmd = $("#cmd");
    const input = $("#cmd-input");
    const list = $("#cmd-list");
    if (!cmd || !input || !list) return;

    const actions = [
      { group: "Navigate", label: "Hero", hint: "Top", run: () => go("#top") },
      { group: "Navigate", label: "Thesis", hint: "01", run: () => go("#thesis") },
      { group: "Navigate", label: "Engine — Flagship", hint: "02", run: () => go("#engine") },
      { group: "Navigate", label: "Outcomes", hint: "03", run: () => go("#proof") },
      { group: "Navigate", label: "Path — Experience", hint: "04", run: () => go("#path") },
      { group: "Navigate", label: "Capabilities", hint: "05", run: () => go("#stack") },
      { group: "Navigate", label: "Contact", hint: "06", run: () => go("#signal") },
      {
        group: "Actions",
        label: "Toggle theme",
        hint: "T",
        run: () => { toggleTheme(); },
      },
      {
        group: "Actions",
        label: "Email Ansh",
        hint: "mailto",
        run: () => { window.location.href = "mailto:anshupadhyay1@hotmail.com"; },
      },
      {
        group: "Actions",
        label: "Call",
        hint: "phone",
        run: () => { window.location.href = "tel:+917415444058"; },
      },
      {
        group: "Actions",
        label: "Copy email",
        hint: "clipboard",
        run: async () => {
          try {
            await navigator.clipboard.writeText("anshupadhyay1@hotmail.com");
            toast("Email copied");
          } catch {
            toast("Could not copy — use mailto");
          }
        },
      },
      {
        group: "Easter",
        label: "System pulse check",
        hint: "?",
        run: () => toast("All 9 novelty channels nominal · cost ledger green"),
      },
    ];

    function go(hash) {
      const el = document.querySelector(hash);
      if (el) el.scrollIntoView({ behavior: prefersReduced ? "auto" : "smooth" });
    }

    let filtered = actions;
    let index = 0;
    let open = false;

    function render() {
      list.innerHTML = "";
      if (!filtered.length) {
        list.innerHTML = `<li class="cmd__empty">No matches</li>`;
        return;
      }
      let lastGroup = "";
      filtered.forEach((item, i) => {
        if (item.group !== lastGroup) {
          lastGroup = item.group;
          const g = document.createElement("li");
          g.className = "cmd__group";
          g.textContent = item.group;
          g.setAttribute("role", "presentation");
          list.appendChild(g);
        }
        const li = document.createElement("li");
        li.setAttribute("role", "option");
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "cmd__item";
        btn.setAttribute("aria-selected", i === index ? "true" : "false");
        btn.innerHTML = `<span>${item.label}</span><span class="cmd__item-meta">${item.hint}</span>`;
        btn.addEventListener("click", () => select(i));
        btn.addEventListener("mouseenter", () => {
          index = i;
          updateSelection();
        });
        li.appendChild(btn);
        list.appendChild(li);
      });
    }

    function updateSelection() {
      const items = $$(".cmd__item", list);
      items.forEach((el, i) => el.setAttribute("aria-selected", i === index ? "true" : "false"));
      items[index]?.scrollIntoView({ block: "nearest" });
    }

    function filter(q) {
      const s = q.trim().toLowerCase();
      filtered = !s
        ? actions
        : actions.filter(
            (a) =>
              a.label.toLowerCase().includes(s) ||
              a.group.toLowerCase().includes(s) ||
              a.hint.toLowerCase().includes(s)
          );
      index = 0;
      render();
    }

    function select(i) {
      const item = filtered[i];
      if (!item) return;
      close();
      item.run();
    }

    function openPalette() {
      open = true;
      cmd.hidden = false;
      input.value = "";
      filter("");
      requestAnimationFrame(() => input.focus());
      document.body.style.overflow = "hidden";
    }

    function close() {
      open = false;
      cmd.hidden = true;
      document.body.style.overflow = "";
    }

    function isOpen() {
      return open;
    }

    $("#cmd-open")?.addEventListener("click", openPalette);
    $("#footer-cmd")?.addEventListener("click", openPalette);
    $$("[data-cmd-close]").forEach((el) => el.addEventListener("click", close));

    input.addEventListener("input", () => filter(input.value));

    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        index = Math.min(filtered.length - 1, index + 1);
        updateSelection();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        index = Math.max(0, index - 1);
        updateSelection();
      } else if (e.key === "Enter") {
        e.preventDefault();
        select(index);
      } else if (e.key === "Escape") {
        e.preventDefault();
        close();
      }
    });

    return { open: openPalette, close, isOpen };
  }

  /* --------------------------------------------------------------------------
   * Keyboard shortcuts
   * ----------------------------------------------------------------------- */
  function initKeys(palette) {
    document.addEventListener("keydown", (e) => {
      const tag = (e.target && e.target.tagName) || "";
      const typing = /INPUT|TEXTAREA|SELECT/.test(tag) || e.target?.isContentEditable;

      // ⌘K / Ctrl+K
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (palette.isOpen()) palette.close();
        else palette.open();
        return;
      }

      if (e.key === "Escape" && palette.isOpen()) {
        palette.close();
        return;
      }

      if (typing) return;

      if (e.key.toLowerCase() === "t" && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        toggleTheme();
      }

      if (e.key === "?" && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        toast("Shortcuts: ⌘K palette · T theme · ? help");
      }
    });
  }

  /* --------------------------------------------------------------------------
   * Placeholder links
   * ----------------------------------------------------------------------- */
  function initPlaceholders() {
    $$("[data-placeholder]").forEach((a) => {
      a.addEventListener("click", (e) => {
        e.preventDefault();
        const kind = a.dataset.placeholder;
        toast(kind === "linkedin" ? "Add your LinkedIn URL in index.html" : "Add your GitHub URL in index.html");
      });
    });
  }

  /* --------------------------------------------------------------------------
   * Year
   * ----------------------------------------------------------------------- */
  function initYear() {
    const y = $("#year");
    if (y) y.textContent = String(new Date().getFullYear());
  }

  /* --------------------------------------------------------------------------
   * Boot
   * ----------------------------------------------------------------------- */
  function boot() {
    initTheme();
    initYear();
    initScroll();
    initReveal();
    initCounters();
    initMagnetic();
    initChapters();
    initAnchors();
    initField();
    initPlaceholders();
    const palette = initCommandPalette();
    initKeys(palette);
    $("#theme-toggle")?.addEventListener("click", toggleTheme);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
