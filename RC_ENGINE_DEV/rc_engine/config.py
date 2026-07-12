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
from pathlib import Path

# This package lives under RC_ENGINE_DEV/. Writes go to the DEV DB by default;
# novelty/topic/topology reads use the production corpus when present so scores
# are real (not 1.0 against an empty sandbox).
_DEV_ROOT = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _DEV_ROOT.parent
_DEFAULT_DB = str(_DEV_ROOT / "rc_engine_dev.db")
_DEFAULT_CORPUS = str(_PROJECT_ROOT / "rc_pipeline.db")

DB_PATH = os.environ.get("RC_ENGINE_DB", _DEFAULT_DB)
# Fingerprint / topic window for novelty prechecks (read-mostly).
CORPUS_DB_PATH = os.environ.get(
    "RC_ENGINE_CORPUS_DB",
    _DEFAULT_CORPUS if Path(_DEFAULT_CORPUS).is_file() else _DEFAULT_DB,
)
DB_BACKUP_DIR = os.environ.get(
    "RC_ENGINE_BACKUP_DIR", os.path.expanduser(r"~\rc_data\backups_dev"))
DB_BACKUP_KEEP = 10
ENGINE_VERSION = "rc-engine-dev-cheap-0.2"
BLUEPRINT_SCHEMA_VERSION = "2.0"

# ---------------------------------------------------------------------------
# Generation mode
#   cheap   — blueprint (free) + refine (cheap) + ONE fullset call + free gates
#   factory — legacy multi-stage (render + compliance + questions) for audits
# ---------------------------------------------------------------------------
DEFAULT_MODE = "cheap"

# ---------------------------------------------------------------------------
# Models & pricing ($ per million tokens: input, output)
# ---------------------------------------------------------------------------

OPUS = "claude-opus-4-8"
SONNET = "claude-sonnet-5"
HAIKU = "claude-haiku-4-5-20251001"

MODEL_RATES = {
    OPUS: (5.0, 25.0),
    SONNET: (2.0, 10.0),
    HAIKU: (1.0, 5.0),
}

# Conservative input-token estimate: chars // 3 overestimates English text
# by ~25-30%, which is the safe direction for a budget guard.
CHARS_PER_TOKEN_ESTIMATE = 3

# ---------------------------------------------------------------------------
# Per-tier hard budgets (USD per RC, all stages, all retries included)
# ---------------------------------------------------------------------------

# Per-RC caps. Hard uses Opus fullset — needs more headroom than Sonnet-only.
TIER_BUDGET_USD = {
    "medium": 0.10,
    "hard": 0.24,
    "elite": 0.26,
}

# ---------------------------------------------------------------------------
# Stage model assignment + output ceilings
# ---------------------------------------------------------------------------

STAGE_CONFIG = {
    # stage: {tier: (model, max_tokens)}
    "refine": {
        "medium": (HAIKU, 1600),
        "hard": (HAIKU, 2000),
        "elite": (SONNET, 2400),
    },
    # Single call: passage + questions (cheap mode). Hard = Opus.
    "fullset": {
        "medium": (SONNET, 6000),
        "hard": (OPUS, 7500),
        "elite": (OPUS, 8000),
    },
    # Cheap length-bias fix: questions-only rewrite (keep passage), Sonnet.
    "length_fix": {
        "medium": (SONNET, 4000),
        "hard": (SONNET, 4000),
        "elite": (SONNET, 4000),
    },
    # Factory-mode stages (opt-in --mode factory)
    "render": {
        "medium": (SONNET, 1400),
        "hard": (OPUS, 1600),
        "elite": (OPUS, 1600),
    },
    "compliance": {
        "medium": (HAIKU, 1400),
        "hard": (HAIKU, 1600),
        "elite": (HAIKU, 1600),
    },
    "questions": {
        "medium": (SONNET, 3200),
        "hard": (OPUS, 3200),
        "elite": (OPUS, 3200),
    },
    "solver": {
        "medium": (SONNET, 1000),
        "hard": (SONNET, 1200),
        "elite": (SONNET, 1200),
    },
    "judge": {
        "medium": (HAIKU, 1200),
        "hard": (HAIKU, 1600),
        "elite": (HAIKU, 1600),
    },
}

QUALITY_OPUS_HARD = True  # hard fullset uses Opus (see STAGE_CONFIG)

ESTIMATED_INPUT_TOKENS = {
    "refine": 3200,
    "fullset": 5000,
    "length_fix": 4200,
    "render": 2600,
    "compliance": 2600,
    "questions": 4200,
    "solver": 1700,
    "judge": 2800,
}

# Retry ceilings — cheap mode: almost no recomposes
MAX_COMPOSE_ATTEMPTS = 40
MAX_REFINE_ATTEMPTS = 2
MAX_FULLSET_ATTEMPTS = 1     # one fullset call; broken parse → fail slot
MAX_LENGTH_FIX_ATTEMPTS = 1  # one questions-only rewrite if length-biased
MAX_RENDER_ATTEMPTS = 2      # factory only
MAX_QUESTION_ATTEMPTS = 2    # factory only
MAX_JUDGE_ATTEMPTS = 1
MAX_SLOT_ATTEMPTS = 3        # allow recomposes when topic precheck kills seedless draws

# Stages that may be skipped when remaining budget cannot cover worst case.
OPTIONAL_STAGES = ("solver", "judge")

# Cheap mode: skip solver by default (judge still runs if budget allows).
CHEAP_RUN_SOLVER = False
CHEAP_RUN_JUDGE = True
# If fullset options fail length audit, rewrite questions only (keep passage).
CHEAP_LENGTH_FIX = True

# Soft novelty: these breaches flag needs_review instead of rejecting.
SOFT_NOVELTY_BREACH_PREFIXES = (
    "persona_leak",
    "rhythm_cosine",
    "curve_pearson",
)

# ---------------------------------------------------------------------------
# Tier structural parameter regions
# ---------------------------------------------------------------------------

TIER_PARAMS = {
    "medium": {
        "instability_range": (0.15, 0.40),
        "passage_words": (400, 450),
        "allowed_topologies": ["QT01", "QT02", "QT05", "QT20"],
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
# Seed sourcing: which RAG genres each tier prefers.
#   The elite/hard prompt design assumes serious long-form register (Aeon,
#   Psyche, Nautilus, JSTOR Daily). Medium accepts anything, including the
#   lighter Smithsonian feeds. Labels here must match RAG.py FEEDS genres.
#   None = any genre. If a tier's preferred pool is exhausted the seed provider
#   falls back to ANY unused essay, then to seedless — so a batch never starves
#   just because serious sources ran out.
# ---------------------------------------------------------------------------
SERIOUS_GENRES = [
    "Aeon", "Psyche", "Nautilus", "JSTOR",
    "Public Books", "The Point", "Hedgehog Review", "New Atlantis",
    "Boston Review", "LARB", "Commonweal", "Lapham's Quarterly",
    "LRB", "NYRB", "Harper's", "Dissent", "Noema",
]
TIER_SEED_GENRES = {
    "elite": SERIOUS_GENRES,
    "hard": SERIOUS_GENRES,
    "medium": None,   # any genre
}

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
# DEV cheap mode: enforce topic precheck (1 re-refine max) so we never pay
# fullset on an obvious topic collision.
# ---------------------------------------------------------------------------
TOPIC_PRECHECK_ENABLED = True
TOPIC_PRECHECK_ENFORCE = True
TOPIC_PRECHECK_COSINE = 0.80
TOPIC_PRECHECK_PASSAGE_COSINE = 0.75
TOPIC_PRECHECK_MAX_REREFINES = 2

# Free pre-spend topology clearance (re-pick before fullset).
TOPOLOGY_PRECHECK_ENABLED = True
TOPOLOGY_PRECHECK_MAX_REPICKS = 5

SEED_PRESCREEN_COSINE = 0.75
SEED_PRESCREEN_MAX_ROTATIONS = 2

# Hard fullset already Opus when QUALITY_OPUS_HARD; keep toggle for Sonnet fallback.
if not QUALITY_OPUS_HARD:
    STAGE_CONFIG["fullset"]["hard"] = (SONNET, 7000)

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
