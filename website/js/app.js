/* ==========================================================================
   Passage Works — site interactions v3 (2026-09-03)

   Deliberately small. v2 ran a particle canvas, three self-playing "console"
   animations and a slot-machine number roll; all of it was decoration that
   made the page read as a generated landing page rather than a content
   supplier's site. What remains is the four things that do actual work.

   Progressive enhancement: with JS off, CSS forces every [data-reveal] block
   visible, so the whole page still reads.
   ========================================================================== */
(function () {
  "use strict";

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  };
  var reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------------------------------------------------------- 1. theme ---- */
  var toggle = $("#theme");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("pw-theme", next); } catch (e) { /* private mode */ }
    });
  }

  /* --------------------------------------------------------- 2. reveal ---- */
  var revealables = $$("[data-reveal]");
  function showAll() {
    revealables.forEach(function (el) { el.classList.add("is-in"); });
  }
  if (reduced || !("IntersectionObserver" in window)) {
    showAll();
  } else {
    var revealIO = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-in");
          revealIO.unobserve(entry.target);
        }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.05 });
    revealables.forEach(function (el) { revealIO.observe(el); });

    // Failsafe: frame-starved webviews sometimes never deliver a first callback.
    // Measured on the v2 build; 1.2s is long enough to avoid fighting a real
    // scroll and short enough that nobody sees a blank column.
    setTimeout(showAll, 1200);
  }

  /* ------------------------------------------------------- 3. nav spy ----- */
  var links = $$(".nav__set");
  var targets = links
    .map(function (a) { return $(a.getAttribute("href")); })
    .filter(Boolean);

  if (targets.length && "IntersectionObserver" in window) {
    var navIO = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        links.forEach(function (a) {
          a.classList.toggle("is-here", a.getAttribute("href") === "#" + entry.target.id);
        });
      });
    }, { rootMargin: "-45% 0px -50% 0px" });
    targets.forEach(function (section) { navIO.observe(section); });
  }

  /* --------------------------------------------- 4. the question specimen -- */
  // Selecting an option names the misreading it implements. This is the one
  // interaction on the page that carries content a VARC head actually wants:
  // it is the answer-key rationale, in miniature.
  var opts = $$("#opts .opt");
  var verdict = $("#verdict");
  var vmech = $("#vmech");
  var vwhy = $("#vwhy");

  if (opts.length && verdict && vmech && vwhy) {
    opts.forEach(function (btn) {
      btn.addEventListener("click", function () {
        opts.forEach(function (o) { o.classList.toggle("is-on", o === btn); });
        var mech = btn.getAttribute("data-mech");
        vmech.textContent = btn.getAttribute("data-ltr") + " — " +
          (mech === "Correct" ? "correct answer" : "wrong option: " + mech.toLowerCase());
        vwhy.innerHTML = btn.getAttribute("data-why");
        verdict.hidden = false;
      });
    });
  }
})();
