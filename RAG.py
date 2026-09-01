import os
from datetime import datetime, timezone

import feedparser

# Windows consoles default to cp1252, which raises UnicodeEncodeError the moment
# a source title contains a macron, a curly quote, or an em dash — and it kills
# the whole ingest mid-run. It cost the 2026-08-22 widening run every feed after
# the first: the crash landed on entry 24 of 34 feeds, before anything was
# committed. Force UTF-8 and never let a printable character stop a fetch.
import sys as _sys
for _stream in (_sys.stdout, _sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import requests
import trafilatura
from playwright.sync_api import sync_playwright
from langchain_core.documents import Document
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, text/html, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

session = requests.Session()
session.headers.update(BROWSER_HEADERS)

PERSIST_DIR = "./essay_rc_db"

# Minimum word count for an essay to be stored, unless a feed overrides it.
# 1000 keeps passages rich enough to derive a 500-550 word RC from; a source
# only needs to carry a domain and a live tension, so this is generous.
DEFAULT_MIN_WORDS = 1000

# Master Endpoint Configuration for Target Publications.
# Each feed carries:
#   genre     : the metadata label stored on every essay from this feed
#   js        : True if the article pages sit behind a JS/Vercel challenge that
#               plain requests can't pass (Aeon and its sister site Psyche) —
#               those are fetched via a real headless browser (Playwright).
#   paths     : optional list of URL path fragments; only links containing one
#               of them are treated as long-form essays (skips /videos/,
#               /notes-to-self/, etc.). None = accept every link the feed lists.
#   min_words : optional per-feed override of DEFAULT_MIN_WORDS. JSTOR Daily
#               publishes complete, self-contained scholarly essays at ~800
#               words, so it uses a lower bar than magazine feeds.
# Feed rot is real and silent: on 2026-08-25 NINE of 34 feeds were failing, most
# of them long-standing rather than recent additions, and the only symptom was a
# thin ingest. Five had simply moved; three had no working feed at any known
# path and are commented out below. Re-check with:
#     grep -oE 'https://[^"]+' RAG.py | xargs -n1 curl -s -o /dev/null -w '%{http_code} %{url_effective}\n'
FEEDS = {
    # --- CAT gold: multi-move idea essays (hard/elite preferred pool) --------
    "https://aeon.co/feed.rss":
        {"genre": "Aeon", "js": True, "paths": ["/essays/"]},
    # Ideas only — /guides/ is self-help how-to (weak CAT seed).
    "https://psyche.co/feed.rss":
        {"genre": "Psyche", "js": True, "paths": ["/ideas/"]},
    "https://nautil.us/feed/":
        {"genre": "Nautilus", "js": False, "paths": None},
    "https://daily.jstor.org/feed/":
        {"genre": "JSTOR", "js": False, "paths": None, "min_words": 800},
    "https://www.publicbooks.org/feed/":
        {"genre": "Public Books", "js": False, "paths": None, "min_words": 900},
    "https://thepointmag.com/feed/":
        {"genre": "The Point", "js": False, "paths": None, "min_words": 1000},
    "https://hedgehogreview.com/web-features/feed":
        {"genre": "Hedgehog Review", "js": False, "paths": None, "min_words": 900},
    "https://www.thenewatlantis.com/feed":
        {"genre": "New Atlantis", "js": False, "paths": None, "min_words": 1000},
    "https://www.bostonreview.net/feed/":
        {"genre": "Boston Review", "js": False, "paths": None, "min_words": 900},
    # DEAD 2026-08-25 (404 on /feed/ and /rss) — re-enable if a feed reappears:
    # "https://lareviewofbooks.org/feed/":
    # {"genre": "LARB", "js": False, "paths": None, "min_words": 900},
    "https://www.commonwealmagazine.org/rss.xml":
        {"genre": "Commonweal", "js": False, "paths": None, "min_words": 900},
    "https://www.laphamsquarterly.org/rss.xml":
        {"genre": "Lapham's Quarterly", "js": False, "paths": None, "min_words": 900},
    "https://www.lrb.co.uk/feeds/rss":
        {"genre": "LRB", "js": False, "paths": None, "min_words": 1200},
    "https://www.nybooks.com/feed/":
        {"genre": "NYRB", "js": False, "paths": None, "min_words": 1200},
    "https://harpers.org/feed/":
        {"genre": "Harper's", "js": False, "paths": None, "min_words": 1000},
    "https://www.noemamag.com/feed/":
        {"genre": "Noema", "js": False, "paths": None, "min_words": 900},
    "https://www.quantamagazine.org/feed/":
        {"genre": "Quanta", "js": False, "paths": None, "min_words": 900},
    "https://undark.org/feed/":
        {"genre": "Undark", "js": False, "paths": None, "min_words": 900},

    # --- Medium-ok / uneven: keep ingesting, NOT in hard/elite preferred -----
    # Political magazines: often news/op-ed rather than multi-layer argument.
    "https://www.dissentmagazine.org/feed/":
        {"genre": "Dissent", "js": False, "paths": None, "min_words": 900},
    "https://jacobin.com/feed/":
        {"genre": "Jacobin", "js": False, "paths": None, "min_words": 1000},
    # DEAD 2026-08-25 (404 on /feed, /rss, /feeds/all.rss) — re-enable if a feed reappears:
    # "https://www.tabletmag.com/feed":
    # {"genre": "Tablet", "js": False, "paths": None, "min_words": 1000},
    # Single-take science explainers / light features — domain variety for medium.
    # DEAD 2026-08-25 (403 on every known path) — re-enable if a feed reappears:
    # "https://knowablemagazine.org/rss":
    # {"genre": "Knowable", "js": False, "paths": None, "min_words": 800},
    "https://www.scientificamerican.com/platform/syndication/rss/":
        {"genre": "Scientific American", "js": False, "paths": None, "min_words": 800},
    "https://www.smithsonianmag.com/rss/history/":
        {"genre": "history", "js": False, "paths": None, "min_words": 900},
    "https://www.smithsonianmag.com/rss/science-nature/":
        {"genre": "science", "js": False, "paths": None, "min_words": 900},

    # --- Genre widening (2026-08-22) ---------------------------------------
    # Every feed above is the same KIND of writing — the idea-essay — and it
    # showed: of ~60 stored topics, 14 opened "Whether..." and 11 "Why...",
    # essentially all of them two-sided conceptual disputes about a social
    # practice. A passage's voice is substantially what it is about, so no
    # amount of arc variety fixes a seed pool with one genre in it.
    #
    # These are chosen to keep the register CAT needs while changing the KIND:
    # narrative history, technical writing that stays technical, craft and
    # practice accounts, criticism of a single work, medicine, law, economics.
    # "kind" is the genre the seed classifier should usually find; it is a hint
    # for diversity accounting, not a promise.

    # Narrative history and archives — events reconstructed, not theses argued
    "https://publicdomainreview.org/rss.xml":
        {"genre": "Public Domain Review", "js": False, "paths": None,
         "min_words": 900, "kind": "narrative_history"},
    "https://www.historytoday.com/feed/rss.xml":
        {"genre": "History Today", "js": False, "paths": None,
         "min_words": 900, "kind": "narrative_history"},

    # Technical writing that stays technical
    "https://physicsworld.com/feed/":
        {"genre": "Physics World", "js": False, "paths": None,
         "min_words": 800, "kind": "technical_explainer"},

    # Craft, practice and how things actually get built
    "https://worksinprogress.co/rss.xml":
        {"genre": "Works in Progress", "js": False, "paths": None,
         "min_words": 1000, "kind": "practice_account"},
    "https://solar.lowtechmagazine.com/feeds/all.rss.xml":
        {"genre": "Low-tech Magazine", "js": False, "paths": None,
         "min_words": 900, "kind": "practice_account"},

    # Criticism anchored to one work rather than a general position
    "https://www.theparisreview.org/blog/feed/":
        {"genre": "Paris Review", "js": False, "paths": None,
         "min_words": 800, "kind": "criticism"},

    # Medicine and law — case-driven, and domains the corpus barely touches
    "https://www.statnews.com/feed/":
        {"genre": "STAT", "js": False, "paths": None,
         "min_words": 900, "kind": "reportage"},
    "https://verfassungsblog.de/feed/":
        {"genre": "Verfassungsblog", "js": False, "paths": None,
         "min_words": 900, "kind": "legal_analysis"},

    # Quantitative social science / economics
    "https://asteriskmag.com/feed":
        {"genre": "Asterisk", "js": False, "paths": None,
         "min_words": 1000, "kind": "analysis"},

    # Dropped (weak CAT seeds — do not re-add without a strong reason):
    #   Ars Technica (tech news), Smithsonian arts-culture / innovation
    #   (soft features), Psyche /guides/ (self-help; path filter above).
    #   Reportage-first outlets (ProPublica, Reveal, Longreads, Atavist) were
    #   considered on 2026-08-22 and NOT added: strong narrative, but they
    #   usually lack the argumentative spine an RC passage has to carry.
}

# Module-level cache so importing modules (e.g. rc_pipeline.py) can call
# get_db() repeatedly without reloading the embedding model each time.
_db_instance = None


def fetch_feed(url, timeout=15):
    """Fetch a feed URL with browser headers, then hand bytes to feedparser."""
    try:
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        print(f"    -> status={resp.status_code} bozo={feed.bozo} entries={len(feed.entries)}")
        return feed
    except requests.RequestException as e:
        print(f"    [error] HTTP fetch failed for {url}: {e}")
        return feedparser.parse("")


def fetch_html_requests(url, timeout=15):
    """Plain requests fetch — fine for sites without bot-challenge protection
    (e.g. Smithsonian)."""
    try:
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        print(f"    [error] Fetch failed for {url}: {e}")
        return None


def fetch_html_playwright(page, url, timeout_ms=20000):
    """Real-browser fetch via Playwright — needed for Aeon, which sits behind
    a Vercel JS challenge that plain requests can never pass."""
    try:
        page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)  # let the challenge/redirect settle
        return page.content()
    except Exception as e:
        print(f"    [error] Playwright fetch failed for {url}: {e}")
        return None


def get_db():
    """Returns the persistent Chroma vector store, loading the local embedding
    model only once. Safe to call from other modules (e.g. rc_pipeline.py)
    without triggering a feed sync."""
    global _db_instance
    if _db_instance is None:
        print("Loading local embedding model (BAAI/bge-small-en-v1.5)...")
        embedding_function = HuggingFaceEmbeddings(
            model_name="BAAI/bge-small-en-v1.5",
            encode_kwargs={"normalize_embeddings": True},
        )
        _db_instance = Chroma(persist_directory=PERSIST_DIR, embedding_function=embedding_function)
    return _db_instance


def get_unused_essay(db=None, genre=None, exclude_ids=None, randomize=True,
                     avoid_kinds=None):
    """Returns ONE not-yet-used essay from the vector store, or None if there
    isn't one. `genre` restricts the source pool and may be:
      - None            -> any genre
      - a single label  -> "Aeon"
      - a list of labels -> ["Aeon", "Psyche", "Nautilus", "JSTOR"]

    `avoid_kinds` steers away from content kinds (the `kind` metadata field,
    e.g. "idea_essay", "practice_account") rather than publications. Used when
    a seed GENRE is saturated and the rotation has to change something.

    By default picks uniformly at random among matches (so hard/elite are not
    stuck on the first Chroma hit / Aeon-heavy ordering). Set randomize=False
    for deterministic first-match behaviour.

    Return shape: {"id": chroma_doc_id, "text": page_content, "metadata": {...}}
    """
    import random as _random

    db = db or get_db()

    if genre:
        # genre may be a single label ("Aeon") or a list of labels
        # (["Aeon", "Psyche", ...]); a list becomes an $in filter so tiers can
        # draw from a pool of acceptable sources.
        genre_clause = {"genre": {"$in": list(genre)}} if isinstance(genre, (list, tuple, set)) \
            else {"genre": genre}
        where = {"$and": [genre_clause, {"used": False}]}
    else:
        where = {"used": False}

    exclude = set(exclude_ids or ())
    results = db.get(where=where)
    if not results or not results.get("ids"):
        return None

    candidates = []
    for i, doc_id in enumerate(results["ids"]):
        if doc_id in exclude:
            continue   # already tried this batch slot (novelty-retry rotation)
        candidates.append({
            "id": doc_id,
            "text": results["documents"][i],
            "metadata": results["metadatas"][i],
        })
    if not candidates:
        return None
    # A seed-genre rotation used to be a uniform redraw, which is why three
    # rotations off a saturated conceptual_essay share kept landing back on
    # conceptual essays: 41.5% of the unused pool is idea_essay. Steering by
    # content kind makes the rotation actually change something. Falls back to
    # the full candidate list rather than dead-ending the slot.
    if avoid_kinds:
        avoid = set(avoid_kinds)
        steered = [c for c in candidates
                   if (c["metadata"] or {}).get("kind") not in avoid]
        if steered:
            candidates = steered
    if randomize and len(candidates) > 1:
        return _random.choice(candidates)
    return candidates[0]


def unused_pool_kinds(db=None, genre=None) -> dict:
    """Kind mix of the unused pool a tier can actually draw from.

    Used to tell a genre-saturation gate whether it has anywhere to rotate TO.
    Hard and elite draw from an 18-magazine whitelist whose entire unused pool
    is one kind, so a saturation gate there is a deadlock rather than a
    diversity lever — see config.SEED_GENRE_SATURATION."""
    db = db or get_db()
    if genre:
        clause = {"genre": {"$in": list(genre)}} if isinstance(genre, (list, tuple, set))             else {"genre": genre}
        where = {"$and": [clause, {"used": False}]}
    else:
        where = {"used": False}
    try:
        got = db.get(where=where, include=["metadatas"])
    except Exception:
        return {}
    out: dict[str, int] = {}
    for m in (got.get("metadatas") or []):
        k = (m or {}).get("kind") or "unknown"
        out[k] = out.get(k, 0) + 1
    return out


def mark_essay_used(db, doc_id: str, rc_id: str):
    """Flags an essay as used in its metadata: sets used=True, stamps
    used_at with the current UTC datetime, and records the rc_id(s) it
    produced (comma-separated if more than one RC was generated from it).
    Once flagged, get_unused_essay() will skip it on future calls."""
    db = db or get_db()
    existing = db.get(ids=[doc_id])
    if not existing or not existing.get("metadatas"):
        print(f"  [warn]  Could not find doc_id={doc_id} to mark as used.")
        return False

    metadata = dict(existing["metadatas"][0])
    metadata["used"] = True
    metadata["used_at"] = datetime.now(timezone.utc).isoformat()
    metadata["rc_id"] = rc_id

    # Chroma's underlying collection metadata update — replaces the metadata
    # dict for this id in place (embeddings/documents are untouched).
    db._collection.update(ids=[doc_id], metadatas=[metadata])
    return True


def sync_feeds(db=None):
    """Scrapes all configured feeds, extracts long-form essay text, and adds
    any new (not-already-stored) essays to the vector store with a fresh
    "used": False flag. Skips anything already present by URL."""
    db = db or get_db()

    # Extract Existing Cache to Prevent Duplicate Storage
    existing_docs = db.get()
    if existing_docs and "metadatas" in existing_docs and existing_docs["metadatas"]:
        existing_urls = set(meta.get("url") for meta in existing_docs["metadatas"] if meta)
    else:
        existing_urls = set()

    processed_documents = []

    print(f"\n[sync] Syncing feeds... (Database currently holds {len(existing_urls)} unique essays)")

    # Iterative Scraping and Parsing Loop.
    # One Playwright browser instance is reused across every Aeon article,
    # so we're not paying browser-launch cost per essay.
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pw_page = browser.new_page(user_agent=BROWSER_HEADERS["User-Agent"])

        for url, cfg in FEEDS.items():
            genre = cfg["genre"]
            print(f"\nScanning endpoint feed: {url}  [{genre}]")
            feed = fetch_feed(url)

            for entry in feed.entries:
                link = getattr(entry, "link", None)
                title = getattr(entry, "title", "Untitled Essay")

                if not link or link in existing_urls:
                    continue

                # Path filter: keep only long-form article URLs (skip /videos/,
                # /notes-to-self/, etc. for feeds that mix content types).
                allowed_paths = cfg.get("paths")
                if allowed_paths and not any(p in link for p in allowed_paths):
                    continue

                # JS-challenged sites (Aeon, Psyche) need a real browser; the
                # rest are fine over plain requests.
                if cfg.get("js"):
                    downloaded = fetch_html_playwright(pw_page, link)
                else:
                    downloaded = fetch_html_requests(link)

                if not downloaded:
                    continue

                try:
                    essay_text = trafilatura.extract(downloaded, include_formatting=False)
                    if essay_text:
                        word_count = len(essay_text.split())

                        min_words = cfg.get("min_words", DEFAULT_MIN_WORDS)
                        if word_count < min_words:
                            print(f"  [skip]  Skipping '{title}' - only {word_count} words (below {min_words} threshold)")
                            continue

                        doc = Document(
                            page_content=essay_text,
                            metadata={
                                "title": title,
                                "url": link,
                                "genre": genre,
                                # CONTENT kind, distinct from `genre` (which is
                                # the publication name). The FEEDS table has
                                # carried `kind` since 2026-08-25, when ten
                                # genre-widening feeds were added — but it was
                                # never written here, so all 935 stored docs
                                # were untagged and seed rotation was blind to
                                # content type. That is why a saturated
                                # conceptual_essay share could not be rotated
                                # away from: the redraw was uniform over a pool
                                # whose kinds were invisible.
                                "kind": cfg.get("kind", "idea_essay"),
                                "word_count": word_count,
                                # Usage-tracking fields — every new essay starts unused.
                                "used": False,
                                "used_at": "",
                                "rc_id": "",
                            },
                        )
                        processed_documents.append(doc)
                        print(f"  -> Added to buffer: [{genre.upper()}] {title} ({word_count} words)")

                except Exception as e:
                    print(f"  [error] Skipping entry evaluation for '{title}' due to extraction exception: {e}")

        browser.close()

    # Write to Local Chroma Instance
    if processed_documents:
        total_docs = len(processed_documents)
        print(f"\n[embed] Embedding and committing {total_docs} new documents locally...")
        try:
            db.add_documents(processed_documents)
            print("[ok] RAG Database synchronization complete! Local vector files successfully updated.")
        except Exception as e:
            print(f"[error] Error while embedding/storing documents: {e}")
    else:
        print("\n[done] Verification complete. Your local database is completely up to date with all live endpoints.")

    return len(processed_documents)


if __name__ == "__main__":
    sync_feeds(get_db())
