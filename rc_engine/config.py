"""Central configuration for the RC engine.

Everything that affects cost or structure lives here, so production behavior
is auditable in one file. The invariant that matters commercially:

    An RC can NEVER cost more than TIER_BUDGET_USD[tier].

Enforced by llm.CostLedger.guard(): before every API call, the worst-case
cost of that call (estimated input tokens + the max_tokens output ceiling)
is checked against the remaining budget. If it cannot fit, the call is not
made — optional stages (solver, judge) are skipped, core stages abort the
RC cleanly with status 'budget_abort'.
"""

import os


def _load_dotenv(path: str | None = None) -> None:
    """Minimal .env loader: KEY=VALUE lines, '#' comments. Never overrides
    variables already set in the process environment, so exported vars win."""
    p = path or os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    try:
        with open(p, encoding="utf-8-sig") as f:  # utf-8-sig tolerates a BOM
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


_load_dotenv()

DB_PATH = os.environ.get("RC_ENGINE_DB", "rc_pipeline.db")
# The production DB lives inside a OneDrive-synced folder (sync + SQLite is a
# known corruption risk), so write paths back it up to a local non-synced dir.
DB_BACKUP_DIR = os.environ.get(
    "RC_ENGINE_BACKUP_DIR", os.path.expanduser(r"~\rc_data\backups"))
DB_BACKUP_KEEP = 10
ENGINE_VERSION = "rc-engine-v2.0"
BLUEPRINT_SCHEMA_VERSION = "2.0"

# ---------------------------------------------------------------------------
# Providers, models & pricing ($ per million tokens: input, output)
# ---------------------------------------------------------------------------
# One provider per run (CLI --provider / GUI dropdown). Each provider maps
# three roles — big / mid / small — and the stage plan below is written in
# roles, resolved into STAGE_CONFIG by set_provider().

DEFAULT_PROVIDER = "claude"
PROVIDERS = ("claude", "openai", "gemini")

OPUS = "claude-opus-4-8"
SONNET = "claude-sonnet-5"
HAIKU = "claude-haiku-4-5-20251001"

# EDITABLE: model IDs current as of 2026-07. Update here when providers ship
# new models; every ID used here must also have a MODEL_RATES entry.
PROVIDER_MODELS = {
    "claude": {"big": OPUS, "mid": SONNET, "small": HAIKU},
    "openai": {"big": "gpt-5.1", "mid": "gpt-5-mini", "small": "gpt-5-nano"},
    "gemini": {"big": "gemini-3-pro-preview", "mid": "gemini-2.5-flash",
               "small": "gemini-2.5-flash-lite"},
}

# EDITABLE: flat across providers — model IDs are globally unique, so the
# CostLedger / budget guard / `estimate` work unchanged. VERIFY these against
# the providers' current pricing pages before the first paid run; a wrong rate
# only skews the ledger, the hard per-tier budget cap still binds.
MODEL_RATES = {
    OPUS: (5.0, 25.0),
    SONNET: (2.0, 10.0),
    HAIKU: (1.0, 5.0),
    "gpt-5.1": (1.25, 10.0),
    "gpt-5-mini": (0.25, 2.0),
    "gpt-5-nano": (0.05, 0.40),
    "gemini-3-pro-preview": (2.0, 12.0),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
}

# Env var(s) that must hold the API key for each provider; first found wins.
PROVIDER_ENV_KEYS = {
    "claude": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
}

# Conservative input-token estimate: chars // 3 overestimates English text
# by ~25-30%, which is the safe direction for a budget guard.
CHARS_PER_TOKEN_ESTIMATE = 3

# ---------------------------------------------------------------------------
# Per-tier hard budgets (USD per RC, all stages, all retries included)
# ---------------------------------------------------------------------------

TIER_BUDGET_USD = {
    # Medium now uses Opus for render + questions (same quality path as hard,
    # shorter passage). Budget raised from $0.12 so happy path + one retry
    # still fits; Sonnet was the quality bottleneck on both prose and MCQs.
    "medium": 0.20,
    "hard": 0.22,
    "elite": 0.30,
}

# ---------------------------------------------------------------------------
# Stage model assignment + output ceilings
# ---------------------------------------------------------------------------
# Written in provider-independent roles; set_provider() resolves the plan
# into STAGE_CONFIG for the active provider. On the claude roles:
# Medium uses big (Opus) on the two quality-critical stages (render,
# questions) — was Sonnet, the passage-quality / MCQ length-bias bottleneck.
# Refine stays small (structure already fixed); solver stays mid (cheap
# optional gate). Hard/elite unchanged.

_STAGE_PLAN = {
    # stage: {tier: (role, max_tokens)}
    "refine": {
        "medium": ("small", 1600),
        "hard": ("mid", 2400),
        "elite": ("mid", 2400),
    },
    "render": {
        "medium": ("big", 1500),
        "hard": ("big", 1600),
        "elite": ("big", 1600),
    },
    "compliance": {
        "medium": ("small", 1400),
        "hard": ("small", 1600),
        "elite": ("small", 1600),
    },
    "questions": {
        "medium": ("big", 3200),
        "hard": ("big", 3200),
        "elite": ("big", 3200),
    },
    "solver": {
        "medium": ("mid", 1000),
        "hard": ("mid", 1200),
        "elite": ("mid", 1200),
    },
    "judge": {
        "medium": ("small", 1200),
        "hard": ("small", 1600),
        "elite": ("small", 1600),
    },
}

ACTIVE_PROVIDER = DEFAULT_PROVIDER
STAGE_CONFIG: dict = {}


def set_provider(provider: str) -> None:
    """Resolve _STAGE_PLAN into STAGE_CONFIG for one provider. Idempotent.
    Rebinding the module global is safe: every call site reads via
    config.STAGE_CONFIG attribute lookup, never a stale reference."""
    global ACTIVE_PROVIDER, STAGE_CONFIG
    if provider not in PROVIDER_MODELS:
        raise ValueError(
            f"unknown provider {provider!r}; expected one of {PROVIDERS}")
    models = PROVIDER_MODELS[provider]
    STAGE_CONFIG = {
        stage: {tier: (models[role], max_tok)
                for tier, (role, max_tok) in tiers.items()}
        for stage, tiers in _STAGE_PLAN.items()
    }
    ACTIVE_PROVIDER = provider


set_provider(DEFAULT_PROVIDER)

# Anthropic output_config.effort per stage/tier (None = API default "high").
# Medium uses Opus at "low" for render+questions: same model family as hard,
# fewer tokens / lower latency / lower $ than default high effort. Hard/elite
# stay at default high for max quality. Valid: low | medium | high | xhigh | max.
STAGE_EFFORT = {
    "refine":     {"medium": None, "hard": None, "elite": None},
    "render":     {"medium": "low", "hard": None, "elite": None},
    "compliance": {"medium": None, "hard": None, "elite": None},
    "questions":  {"medium": "low", "hard": None, "elite": None},
    "solver":     {"medium": None, "hard": None, "elite": None},
    "judge":      {"medium": None, "hard": None, "elite": None},
}

# Typical input sizes per stage (tokens) — used only by `cli estimate` to
# print the cost table; the runtime guard measures the real prompt instead.
ESTIMATED_INPUT_TOKENS = {
    "refine": 3200,
    "render": 2600,
    "compliance": 2600,
    "questions": 4200,
    "solver": 1700,
    "judge": 2800,
}

# Retry ceilings. Compose retries are local sampling (free).
MAX_COMPOSE_ATTEMPTS = 40
MAX_REFINE_ATTEMPTS = 3      # transient empty/truncated refine responses
MAX_RENDER_ATTEMPTS = 2      # render + compliance loop
MAX_QUESTION_ATTEMPTS = 2
MAX_JUDGE_ATTEMPTS = 2

# One render-level retry with breach-specific directives before a Gate-B novelty
# rejection falls back to a full recompose. Only fires for render-movable
# channels (rhythm/curve/embedding/stylometry), never blueprint-derived movement.
GATE_B_RENDER_RETRY = 1

# Corpus-aware negative steering ($0): seed the render contract with directives
# that push the passage's prose texture (sentence rhythm, opening altitude) away
# from its nearest corpus neighbours, so the soft stylometry/rhythm channels are
# diversified at the source instead of caught after a paid render. Structural
# axes fixed by the blueprint (thesis schedule, closing posture) are never touched.
DIVERGENCE_DIRECTIVES_ENABLED = True
DIVERGENCE_MAX_NEIGHBORS = 2

# Stages that may be skipped (not aborted) when the remaining budget cannot
# cover their worst case. Order = priority of spend.
OPTIONAL_STAGES = ("solver", "judge")

# Per-stage slack on the worst-case budget guard. The guard's input estimate is
# deliberately ~25-30% conservative (chars//3 + the full max_tokens ceiling), so
# it aborts on false positives. For the questions stage only, allow a small
# overshoot so a fully-paid, novelty-clean passage is never stranded for the sake
# of a worst case that almost never materializes. Bound on the tier invariant:
# at most budget * (1 + slack) on exactly one stage (hard tier: +$0.033).
BUDGET_GUARD_SLACK = {
    "questions": 0.15,
}

# ---------------------------------------------------------------------------
# Tier structural parameter regions
# ---------------------------------------------------------------------------

TIER_PARAMS = {
    "medium": {
        "instability_range": (0.15, 0.40),
        "passage_words": (400, 450),
        # Broader than the original 4 — those four all hit 1.0 topology
        # collisions once a few mediums/elites shipped, so every medium
        # attempt died at the free precheck. Still avoid the hardest curves
        # (cliff ambush-only sets, double counterfactual, etc.).
        "allowed_topologies": [
            "QT01", "QT02", "QT03", "QT04", "QT05", "QT06",
            "QT08", "QT13", "QT14", "QT16", "QT20",
        ],
        # medium uses only structurally simpler families (tier_floor == medium)
    },
    "hard": {
        "instability_range": (0.35, 0.70),
        "passage_words": (450, 500),
        "allowed_topologies": None,  # all
    },
    "elite": {
        # floor lowered 0.55 -> 0.45: instability ~1.0 reads as "fully suspended"
        # and pushed elite renders toward irresolution regardless of family; the
        # closing-posture directive now governs the ending's stance instead.
        "instability_range": (0.45, 0.95),
        "passage_words": (500, 550),
        "allowed_topologies": None,
    },
}

TIER_LETTERS = {"medium": "M", "hard": "H", "elite": "E"}

# ---------------------------------------------------------------------------
# Seed sourcing: preferred genre pools per tier (labels = RAG.py FEEDS genres).
#   Hard/elite draw uniformly at random ONLY from CAT_SEED_GENRES (multi-move
#   essay sources). They do NOT fall back to news/op-ed or Smithsonian-lite.
#   Medium may draw from any unused essay (including political / explainer).
# ---------------------------------------------------------------------------
# Gold + solid CAT seed genres (see RAG FEEDS "CAT gold" block).
CAT_SEED_GENRES = [
    "Aeon", "Psyche", "Nautilus", "JSTOR",
    "Public Books", "The Point", "Hedgehog Review", "New Atlantis",
    "Boston Review", "LARB", "Commonweal", "Lapham's Quarterly",
    "LRB", "NYRB", "Harper's", "Noema",
    "Quanta", "Undark",
]
# Back-compat alias
SERIOUS_GENRES = CAT_SEED_GENRES

TIER_SEED_GENRES = {
    "elite": CAT_SEED_GENRES,   # random within CAT-quality pool only
    "hard": CAT_SEED_GENRES,    # same
    "medium": None,             # any unused genre at random
}
# When True, hard/elite never fall back to non-preferred genres (seedless
# instead). Keeps Nation / SciAm / Smithsonian out of hard/elite.
TIER_SEED_STRICT = True

# ---------------------------------------------------------------------------
# Composer: exclusion windows (in shipped RCs) and decay weighting
# ---------------------------------------------------------------------------

EXCLUSION_WINDOWS = {
    "family": 25,
    "topology": 12,
    "persona": 10,
    "revelation": 10,
    "distractor_profile": 8,
    "ending": 8,
    "rhythm": 6,
}
PAIR_WINDOW = 60          # family x revelation, family x ending, topology x distractor
DECAY_LAMBDA = 0.5        # weight *= lambda ** uses_in_trailing_100

# Closing-posture diversity (coarse classes: resolution | reframe | refusal).
# Hard rule prevents the observed failure (3 consecutive refusal-postured sets);
# soft decay applies steady pressure toward balance across the 5 fine postures.
POSTURE_RUN_MAX = 2          # hard-exclude a coarse class after this many consecutive shipped uses
POSTURE_DECAY_LAMBDA = 0.7   # fine-posture counts aggregate many families; 0.5 would starve the refusal class
POSTURE_DECAY_WINDOW = 15

# Backstop at the novelty gate: reject only renderer disobedience.
POSTURE_RUN_K = 3            # realized same-class count ...
POSTURE_RUN_M = 6            # ... within the most recent M posture-keyed fingerprints
APHORISM_FLAG_WINDOW = 10
APHORISM_FLAG_MIN = 6        # >= this many aphorism endings in the trailing window -> corpus flag

# Final-sentence register rotation (id, weight, render instruction).
# Weights give ~12.5% aphorism allowance: the device stays in the repertoire
# but stops being the house style.
CLOSING_REGISTERS = [
    ("bound_continuation", 3,
     "The final sentence must NOT be a detachable aphorism or epigram: it must stay "
     "syntactically and referentially tied to the paragraph's ongoing argument "
     "(e.g., it depends on a referent introduced in the preceding sentences)."),
    ("concrete_particular", 2,
     "End on a specific concrete particular - an example, a named case, a physical "
     "detail - not on an abstraction or a maxim."),
    ("quiet_qualification", 2,
     "End on a quietly qualified sentence - a subordinate clause or hedge carries "
     "the final weight; no quotable pronouncement."),
    ("aphoristic", 1,
     "A terse, freestanding final line is permitted here."),
]
BLUEPRINT_DISTANCE_WINDOW = 50
MIN_BLUEPRINT_DISTANCE = 0.55

# Channel-1 weights (blueprint categorical distance)
BLUEPRINT_HAMMING_WEIGHTS = {
    "family": 0.35,
    "topology": 0.20,
    "revelation": 0.15,
    "persona": 0.10,
    "ending": 0.08,
    "rhythm": 0.06,
    "distractor_profile": 0.06,
}

# ---------------------------------------------------------------------------
# Novelty auditor: pairwise caps + composite floor
# ---------------------------------------------------------------------------

FINGERPRINT_WINDOW = 100

# Below this corpus size the curve_pearson breach check is kept composite-only:
# commitment curves are 4-6 coarse values and late-thesis tiers all share a
# "low early, rising late" shape. A curve match is useful evidence, but too
# coarse to hard-veto a billion-way blueprint space until the corpus is large.
CURVE_CAP_MIN_CORPUS = 75

NOVELTY_CAPS = {
    "movement_levenshtein": 0.70,   # similarity cap
    "movement_bigram_jaccard": 0.60,
    "curve_pearson": 0.85,
    "rhythm_cosine": 0.92,
    "topology_similarity": 0.75,
    "embedding_cosine": 0.80,
    "stylometry_delta_floor": 0.90,  # Burrows' Delta BELOW this vs a different-persona RC = leak
}

# Coarse semantic/shape channels should not veto alone. They become hard
# rejects only when a second channel says the same pair is structurally close,
# or when the score is so high that it is probably a duplicate topic/arc.
NOVELTY_SUPPORT_CAPS = {
    "blueprint_sim": 0.35,
    "movement_similarity": 0.45,
    "rhythm_cosine": 0.88,
    "curve_pearson_extreme": 0.98,
    "embedding_cosine_extreme": 0.92,
    # persona_leak: a low Burrows' Delta only *means* "same author wrote the same
    # essay twice" when a second structural channel agrees. Below this extreme
    # floor the voices are near-identical regardless of structure, so reject
    # unconditionally; between here and stylometry_delta_floor, require support.
    # (The single generator has a house voice that trips the 0.90 floor on nearly
    # every render; blind re-rolls cannot change it, so an unsupported breach is a
    # false positive that only burns a paid render.)
    "stylometry_delta_extreme": 0.70,
}

COMPOSITE_WEIGHTS = {
    "blueprint": 0.20,
    "movement": 0.18,
    "curve": 0.14,
    "rhythm": 0.08,
    "topology": 0.14,
    "distractor_jsd": 0.10,
    "stylometry": 0.08,
    "embedding": 0.08,
}
MIN_COMPOSITE_NOVELTY = 0.35

COMPLIANCE_F1_THRESHOLD = 0.75
JUDGE_SCORE_THRESHOLD = 7.0

# Thesis-question length tell: the thesis slot is the most exploitable place
# for a "longest option = right" heuristic, so beyond the per-set rule (any
# thesis-longest set routes to needs_review / vet warning) there is a corpus
# budget: over the trailing THESIS_LONGEST_WINDOW keyed sets, at most
# THESIS_LONGEST_MAX may have the correct thesis option strictly longest
# (i.e. no more than 1 in 3). Breaches surface as corpus flags.
THESIS_LONGEST_WINDOW = 9
THESIS_LONGEST_MAX = 3

EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"

# How many recent blueprint topics (shipped + rejected) the refine prompt
# lists as AVOID territories — proactive topical divergence at ~$0.0003/call.
REFINE_AVOID_TOPICS = 12

# ---------------------------------------------------------------------------
# Pre-render topic-collision precheck (local embeddings, $0 per check).
# Catches embedding-channel collisions BEFORE the expensive render call: the
# refined blueprint's topic document is embedded and compared against prior
# blueprint topics and corpus passage embeddings. On collision the blueprint
# is re-refined (~$0.01) instead of discovering the duplicate after render +
# compliance (~$0.07 wasted).
# Rollout: enabled in LOG-ONLY mode first (records topic_precheck audits,
# never blocks). Set TOPIC_PRECHECK_ENFORCE = True after reviewing a batch.
# ---------------------------------------------------------------------------
# Thresholds backtested (2026-07-11) against the 20 historical embedding-breach
# rejections vs the 9 shipped sets, chronologically simulated:
#   topic-vs-passage 0.75 -> caught 15/20 breaches, flagged 3/9 shipped
#   topic-vs-topic   0.80 -> secondary signal (noisier: shipped sets can share
#                            topic territory with rejected attempts)
# A false positive costs one re-refine (~$0.01-0.03); a miss costs a wasted
# render + compliance (~$0.07).
TOPIC_PRECHECK_ENABLED = True
TOPIC_PRECHECK_ENFORCE = True            # enforced: blocks colliding topics pre-render
TOPIC_PRECHECK_COSINE = 0.80             # topic-doc vs prior topic-doc
TOPIC_PRECHECK_PASSAGE_COSINE = 0.75     # topic-doc vs stored passage embedding
TOPIC_PRECHECK_MAX_REREFINES = 2

# Free pre-render topology clearance: a blueprint whose planned topology signature
# is too close to the corpus is re-picked (local registry shuffle, $0) BEFORE any
# paid render — otherwise a topology collision is only caught at Gate C, after the
# Opus questions call has already been paid for (~$0.15 wasted).
TOPOLOGY_PRECHECK_ENABLED = True
TOPOLOGY_PRECHECK_MAX_REPICKS = 5

# Free pre-render movement clearance: planned paragraph-function sequence is
# compared to the fingerprint window with the same NOVELTY_CAPS as Gate B.
# Identical / near-identical movement is a family-level skeleton collision —
# seed rotation alone cannot fix it. On hit we ban the family + movement
# string and recompose (refine only, no render) before any Opus passage call.
# Gate-B movement rejects also accumulate into the same ban sets for the
# batch recompose loop so a second paid render never re-uses F24's skeleton.
MOVEMENT_PRECHECK_ENABLED = True
MOVEMENT_PRECHECK_MAX_RECOMPOSES = 3   # local recompose attempts inside generate_one

# Seed pre-screen: embed the seed excerpt before composing and rotate seeds
# whose territory is already saturated in the corpus — today a colliding seed
# costs a full render before rotation. Rotation is free (the untried seed
# stays unused); false positives only burn seeds, never RCs.
SEED_PRESCREEN_COSINE = 0.75
SEED_PRESCREEN_MAX_ROTATIONS = 3

# Seedless mode: domains the refiner may invent topics within.
DOMAIN_POOL = [
    "philosophy of science and epistemology",
    "political economy and moral philosophy",
    "sociology of institutions and modernity",
    "cognitive science and philosophy of language",
    "history of ideas and intellectual movements",
    "aesthetics and cultural criticism",
    "philosophy of technology",
    "anthropology of knowledge and expertise",
]

GLOBAL_FORBIDDEN_TICS = [
    "furthermore", "moreover", "in conclusion", "it is a testament",
    "tapestry", "delve", "paradigm shift", "navigate the complexities",
    "underscores", "multifaceted",
]
