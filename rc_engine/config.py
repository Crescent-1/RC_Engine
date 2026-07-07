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

DB_PATH = os.environ.get("RC_ENGINE_DB", "rc_pipeline.db")
ENGINE_VERSION = "rc-engine-v2.0"
BLUEPRINT_SCHEMA_VERSION = "2.0"

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

TIER_BUDGET_USD = {
    "medium": 0.12,
    "hard": 0.22,
    "elite": 0.30,
}

# ---------------------------------------------------------------------------
# Stage model assignment + output ceilings
# ---------------------------------------------------------------------------

STAGE_CONFIG = {
    # stage: {tier: (model, max_tokens)}
    "refine": {
        "medium": (HAIKU, 1600),
        "hard": (SONNET, 2400),
        "elite": (SONNET, 2400),
    },
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

# Stages that may be skipped (not aborted) when the remaining budget cannot
# cover their worst case. Order = priority of spend.
OPTIONAL_STAGES = ("solver", "judge")

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
SERIOUS_GENRES = ["Aeon", "Psyche", "Nautilus", "JSTOR"]
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

# Below this corpus size the curve_pearson breach check is skipped entirely:
# commitment curves are 4-6 coarse values and late-thesis tiers all share a
# "low early, rising late" shape, so on a small corpus the channel rejects
# what the tier's structure inherently produces. The curve still contributes
# to the composite score; only the hard pairwise cap is suspended.
CURVE_CAP_MIN_CORPUS = 25

NOVELTY_CAPS = {
    "movement_levenshtein": 0.70,   # similarity cap
    "movement_bigram_jaccard": 0.60,
    "curve_pearson": 0.85,
    "rhythm_cosine": 0.92,
    "topology_similarity": 0.75,
    "embedding_cosine": 0.80,
    "stylometry_delta_floor": 0.90,  # Burrows' Delta BELOW this vs a different-persona RC = leak
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

EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"

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
