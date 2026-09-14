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


# Where each variable actually came from. Populated by _load_dotenv() so the
# CLI and GUI can SAY which credential is in play instead of silently using
# whichever one happened to win.
DOTENV_APPLIED: set[str] = set()     # .env supplied the value
DOTENV_SHADOWED: set[str] = set()    # .env defines it, but the environment
                                     # already held a DIFFERENT value and won


def _load_dotenv(path: str | None = None) -> None:
    """Minimal .env loader: KEY=VALUE lines, '#' comments. Never overrides
    variables already set in the process environment, so exported vars win.

    That precedence is deliberate (it lets you override for one run) but it
    fails silently and expensively: on 2026-07-26 a stale User-scope
    ANTHROPIC_API_KEY shadowed a working .env key, and the only symptom was a
    401 partway into a paid batch. So record the provenance — see
    var_source() / shadowing_conflicts()."""
    p = path or os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    try:
        with open(p, encoding="utf-8-sig") as f:  # utf-8-sig tolerates a BOM
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip("'\"")
                if not k:
                    continue
                if k not in os.environ:
                    os.environ[k] = v
                    DOTENV_APPLIED.add(k)
                elif os.environ[k] != v:
                    DOTENV_SHADOWED.add(k)
    except OSError:
        pass


_load_dotenv()


def var_source(name: str) -> str:
    """Human-readable provenance for one environment variable."""
    if name in DOTENV_SHADOWED:
        return "environment (SHADOWS a different value in .env)"
    if name in DOTENV_APPLIED:
        return ".env"
    return "environment" if os.environ.get(name) else "unset"


def shadowing_conflicts() -> list[str]:
    """Variables where the process environment silently beat a different value
    in .env. Non-empty means someone is not using the credential they think
    they are — the caller should say so loudly before spending money."""
    return sorted(DOTENV_SHADOWED)

DB_PATH = os.environ.get("RC_ENGINE_DB", "rc_pipeline.db")

# Clients (2026-09-12). Until this date every set in the DB was for one
# institute and every novelty lever read all of it. Each client now gets its
# own window (families, beats, movement, topology, usage decay, seed genre,
# similarity screen); argument skeletons, seed essays and rc ids stay global so
# no two clients ever receive the same structure — see history.py.
#
# FOUNDING_CLIENT_ID is a migration constant: it is the ADD COLUMN default that
# assigned every pre-existing row to the founding client. Never change it.
# DEFAULT_CLIENT_ID is what a command uses when --client is omitted.
FOUNDING_CLIENT_ID = "AA"
DEFAULT_CLIENT_ID = os.environ.get("RC_ENGINE_CLIENT") or FOUNDING_CLIENT_ID
# The production DB lives inside a OneDrive-synced folder (sync + SQLite is a
# known corruption risk), so write paths back it up to a local non-synced dir.
DB_BACKUP_DIR = os.environ.get(
    "RC_ENGINE_BACKUP_DIR", os.path.expanduser(r"~\rc_data\backups"))
DB_BACKUP_KEEP = 10
ENGINE_VERSION = "rc-engine-v2.0"
BLUEPRINT_SCHEMA_VERSION = "2.0"

# Generation policy for NEW blueprints, per tier (2026-09-13). "" is the legacy
# policy: the engine as it stood before the CAT PYQ changes. See
# rc_engine/generation_policy.py. Stored blueprints resume under the version
# they carry, never under this map, so switching a tier back to "" disables a
# policy for future plans without touching plans already made under it.
# Elite is legacy by rule; generation_policy refuses anything else.
#
# 2026-09-13: `cat-pyq-q1` (the section 4 question release) is registered but
# NOT the default. The plan requires a human-reviewed paid pilot before new
# question forms reach client batches, so medium/hard stay legacy here and a
# run opts in with `generate --generation-policy cat-pyq-q1` (or
# RC_ENGINE_NEW_PLAN_POLICY, which parallel workers inherit). Set the two tiers
# here only once the pilot has been reviewed.
GENERATION_POLICY_FOR_NEW_PLANS = {"medium": "", "hard": "", "elite": ""}
_new_plan_policy = os.environ.get("RC_ENGINE_NEW_PLAN_POLICY", "").strip()
if _new_plan_policy:
    GENERATION_POLICY_FOR_NEW_PLANS = {"medium": _new_plan_policy,
                                       "hard": _new_plan_policy, "elite": ""}
# 2026-09-14: elite may opt into a legacy-based policy only (`legacy-sf1`: the
# legacy engine plus seed fidelity). `generate --elite-policy` sets this for the
# run and its workers; any other version resolves elite to legacy.
_elite_plan_policy = os.environ.get("RC_ENGINE_ELITE_PLAN_POLICY", "").strip()
if _elite_plan_policy:
    GENERATION_POLICY_FOR_NEW_PLANS = {**GENERATION_POLICY_FOR_NEW_PLANS,
                                       "elite": _elite_plan_policy}

# ---------------------------------------------------------------------------
# Providers, models & pricing ($ per million tokens: input, output)
# ---------------------------------------------------------------------------
# One provider per run (CLI --provider / GUI dropdown). Each provider maps
# three roles — big / mid / small — and the stage plan below is written in
# roles, resolved into STAGE_CONFIG by set_provider().

DEFAULT_PROVIDER = "claude"
PROVIDERS = ("claude", "openai", "gemini")

# PINNED to Opus 4.8 (2026-08-10, by request) — not an upgrade oversight.
# Opus 5 and Opus 4.8 are the same price ($5/$25) and the same 1M context /
# 128k output, so this pin costs nothing; it holds the generator on the model
# the shipped corpus was written by, which keeps house voice and the novelty
# baselines (stylometry, persona_leak) comparable across old and new sets.
#
# The behavioural difference between them is handled in llm.py, not here: on
# Opus 4.8 a request that omits `thinking` runs WITHOUT thinking, on Opus 5 the
# same request runs WITH adaptive thinking. llm.py sends an explicit
# thinking={"type": "disabled"} for this constant either way — valid on both
# models — so the budget model's no-thinking assumption holds regardless of
# which one is pinned here.
#
# RC_ENGINE_OPUS_MODEL overrides the pin for one run without editing this file —
# added 2026-08-11 to A/B the generator against Opus 5 after every 4.8 set
# breached the length-bias gate. Opus 5 became the default pin 2026-08-21; pass
# the env var to fall back to 4.8 for a comparison run. Both models bill $5/$25,
# so MODEL_RATES below (keyed on this constant) stays correct either way.
#   RC_ENGINE_OPUS_MODEL=claude-opus-4-8 python -m rc_engine.cli generate --hard 1
OPUS = os.environ.get("RC_ENGINE_OPUS_MODEL", "claude-opus-5")
SONNET = "claude-sonnet-5"
HAIKU = "claude-haiku-4-5-20251001"

# EDITABLE: model IDs current as of 2026-07. Update here when providers ship
# new models; every ID used here must also have a MODEL_RATES entry.
PROVIDER_MODELS = {
    "claude": {"big": OPUS, "mid": SONNET, "small": HAIKU},
    # GPT-5.6 family (released 2026-07-09). Unlike GPT-5.x, which was one model
    # with an effort dial, 5.6 ships as three separate tiers, so they map onto
    # big/mid/small directly. Override the flagship for one run without editing
    # this file — Sol was still gated on some accounts as of 2026-08:
    #   RC_ENGINE_OPENAI_BIG=gpt-5.6-terra python -m rc_engine.cli generate ... --provider openai
    "openai": {"big": os.environ.get("RC_ENGINE_OPENAI_BIG", "gpt-5.6-sol"),
               "mid": "gpt-5.6-terra", "small": "gpt-5.6-luna"},
    "gemini": {"big": "gemini-3-pro-preview", "mid": "gemini-2.5-flash",
               "small": "gemini-2.5-flash-lite"},
}

# EDITABLE: flat across providers — model IDs are globally unique, so the
# CostLedger / budget guard / `estimate` work unchanged. VERIFY these against
# the providers' current pricing pages before the first paid run; a wrong rate
# only skews the ledger, the hard per-tier budget cap still binds.
MODEL_RATES = {
    OPUS: (5.0, 25.0),          # verified 2026-08-21: Opus 5 is $5 / $25
                                # (same rate card as Opus 4.8)
    # ACTION 2026-09-01: (2.0, 10.0) is Sonnet 5's introductory rate and it ends
    # 2026-08-31; the standard rate is (3.0, 15.0). Sonnet drives refine + solver
    # on hard/elite, so leaving this stale after that date makes the ledger
    # under-record them by 50% and lets the pre-call guard clear a call that
    # actually breaks the tier cap. Flip to (3.0, 15.0) then (or earlier — the
    # happy path is $0.152 against a $0.22 hard cap, so there is headroom).
    SONNET: (2.0, 10.0),
    HAIKU: (1.0, 5.0),
    # verified 2026-08-21 against OpenAI's published rates, which changed on
    # 2026-07-30 (Luna cut 80% from $1/$6, Terra 20% from $2.50/$15, Sol held).
    # NOTE: GPT-5.6 are reasoning models — reasoning tokens bill at the OUTPUT
    # rate and count against max_tokens, so realised output cost runs above the
    # nominal completion length. See providers.OpenAIClient.
    # verified 2026-08-22 against developers.openai.com model pages (NOT the
    # pricing aggregators, which had Sol at $5/$30 - it is $4/$20).
    # Cached input is cheaper still (Sol $0.40, Terra $0.20, Luna $0.02) but the
    # ledger does not model caching, so these are the uncached rates and the
    # recorded cost is therefore an upper bound. Luna additionally charges 2x
    # input / 1.5x output above 272K input tokens; our prompts are ~8K at most.
    # verified 2026-09-05 against developers.openai.com/api/docs/pricing on the
    # day GPT-6 Astra shipped. Cached input is $1.00; the ledger does not model
    # caching, so the recorded cost is an upper bound as with the 5.6 family.
    # NOTE the step change: Astra is 2.5x Sol on BOTH sides and 2x Opus 5's
    # $5/$25. Reasoning bills at the $50 output rate and cannot be switched off
    # (see OPENAI_EFFORT_SUPPORT), so an Astra render is the most expensive call
    # this engine can make. The tier budgets below were re-sized for it.
    "gpt-6-astra": (10.0, 50.0),
    "gpt-5.6-sol": (4.0, 20.0),
    "gpt-5.6-terra": (2.0, 12.0),
    "gpt-5.6-luna": (0.20, 1.20),
    # previous generation, kept so old ledger rows and pinned runs still price
    "gpt-5.1": (1.25, 10.0),
    "gpt-5-mini": (0.25, 2.0),
    "gpt-5-nano": (0.05, 0.40),
    "gemini-3-pro-preview": (2.0, 12.0),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
}

# Cached-input rates, charged when a prompt prefix is served from OpenAI's
# prompt cache. Measured 2026-09-05 against the live API: a 2,614-token system
# prompt cached 100% on the SECOND identical call and every one after it.
#
#     call 1  prompt=2614  cached=0     (0%)
#     call 2  prompt=2615  cached=2604  (100%)
#     call 3  prompt=2615  cached=2604  (100%)
#
# This engine sends the same large system prompt for every stage of every set,
# so nearly all input after the first call of a run is cached at a tenth of the
# price. Ignoring it made the ledger over-record the 2026-09-05 Astra batch
# 3.7x: $0.9671 booked against ~$0.26 actually billed. The gap was that large
# because the batch ran at effort "low", where reasoning is minimal and input
# DOMINATES the bill -- the regime where the discount is biggest. At medium
# effort output grows and the recorded figure converges back toward the truth.
#
# Only CostLedger.record() uses these. CostLedger.guard() deliberately keeps
# charging the uncached rate: the guard's job is to refuse a call whose WORST
# case would break the cap, and a cache hit is never guaranteed.
MODEL_RATES_CACHED_IN = {
    "gpt-6-astra": 1.00,
    "gpt-5.6-sol": 0.40,
    "gpt-5.6-terra": 0.20,
    "gpt-5.6-luna": 0.02,
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

# Raised 2026-07-26 alongside the questions ceiling (3200 -> 4200). These now
# sit above the ALL-STAGES-WORST case ($0.203 medium / $0.228 hard+elite), which
# is the point: on the 2026-07-26 batch a near-ceiling questions call exhausted
# the hard budget, the guard skipped solver AND judge, and with no judge verdict
# the set could never reach 'approved' — it was demoted to needs_review for
# budget reasons despite f1=1.0 and a 501-word passage. Paying $0.017 for the
# judge beats manually reviewing every set the engine produces.
#
# Raised again 2026-08-10 for the 6 -> 8 question change. Only three stages
# scale with question count (questions, solver, judge); refine/render/compliance
# are passage-only and unchanged. Measured happy path moves $0.133 -> $0.159
# (medium) and $0.149 -> $0.175 (hard/elite). The +$0.10 headroom over the old
# caps is deliberately generous: a cap is a ceiling, not a spend, and the
# failure it buys out of — a set demoted to needs_review because the guard
# skipped the judge on budget rather than on quality — costs a manual review.
TIER_BUDGET_USD = {
    "medium": 0.34,
    "hard": 0.36,
    "elite": 0.42,
}

# Per-provider budget overrides, applied by set_provider().
#
# The caps above were sized for Anthropic, where llm.py runs the big model with
# thinking DISABLED so nothing is billed for reasoning. Reasoning providers pay
# for thinking at the output rate — a Sol elite render at high effort spends
# ~5,000 reasoning tokens on top of ~700 visible — so the same work costs
# roughly twice as much and needs a cap that reflects that rather than
# aborting mid-set.
#
# Deliberately NOT a global raise: loosening Anthropic's cap would silently buy
# more retries on a path that does not need them, and the cap is the one
# guarantee this engine makes about spend.
# 2026-09-05: hard and elite re-sized for GPT-6 Astra at $10/$50. `estimate`
# put the happy path at $0.4426/set — above hard's $0.36, which would have
# aborted every hard set mid-generation, and inside elite's $0.45 by $0.0074,
# which is a cap with no retry headroom at all. Both are now $0.70.
#
# $0.70 is not a round number, it is the happy path plus the single most
# expensive in-attempt retry: questions is $0.2265 on Astra and is marked x2
# worst, so 0.4426 + 0.2265 = $0.669. Under $0.669 a questions retry aborts a
# set that has already paid for its render. Above ~$1.23 the cap stops binding
# at all (that is the fully-retried worst case).
#
# Note what this tier now costs: ~$0.44/set against ~$0.15 on the Anthropic
# path. Astra is 2x Opus 5 per token AND pays for reasoning that Opus has
# disabled. Medium deliberately stays on Terra for that reason.
# Back to the pre-Astra cap when hard and elite returned to Terra/Sol
# (2026-09-05). Left as a single elite entry, which is what it was before.
#
# These are UNCACHED worst-case figures, as the guard requires: it must refuse
# a call whose worst case breaks the cap, and a cache hit is never guaranteed.
# Read them as a ceiling, not a forecast.
PROVIDER_TIER_BUDGET_USD = {
    "openai": {"elite": 0.45},
}

# Reverted to 0 on 2026-08-22, same day it was added.
#
# The premise was that GPT-5.6 undershoots: 503, 479 and 486 words against a
# 500-550 band. It does — but only at LOW reasoning effort. An effort ablation
# on one blueprint showed the model aims at the TOP of whatever range it is
# given: told 520-570 it wrote 569, 571 and 573, all outside the real band.
# The offset converted an undershoot into an overshoot.
#
# The durable fix is effort, not a fudge factor: at medium and above these
# models hit the stated band, so state the band you actually want. Kept as a
# lever in case a future model genuinely undershoots at working effort.
PROVIDER_WORD_TARGET_OFFSET = {}


# Experiment escape hatch: lift the per-RC cap for one run to MEASURE what an
# uncapped configuration actually costs. The guard still runs — it just has a
# ceiling high enough not to bind — so spend is recorded normally and nothing
# silently overspends in production, where this is unset.
_budget_override = os.environ.get("RC_ENGINE_TIER_BUDGET_USD", "").strip()
if _budget_override:
    TIER_BUDGET_USD = {t: float(_budget_override) for t in TIER_BUDGET_USD}

# Frozen AFTER the env override so set_provider() cannot undo it: an explicit
# RC_ENGINE_TIER_BUDGET_USD is an operator decision and outranks the per-provider
# defaults. Rebuilding from this snapshot each call also stops repeated
# set_provider() calls from accumulating overrides.
_BASE_TIER_BUDGET_USD = dict(TIER_BUDGET_USD)
_BUDGET_OVERRIDDEN = bool(_budget_override)

# ---------------------------------------------------------------------------
# Stage model assignment + output ceilings
# ---------------------------------------------------------------------------
# Written in provider-independent roles; set_provider() resolves the plan
# into STAGE_CONFIG for the active provider. On the claude roles:
# Medium uses big (Opus) on the two quality-critical stages (render,
# questions) — was Sonnet, the passage-quality / MCQ length-bias bottleneck.
# Refine stays small (structure already fixed); solver stays mid (cheap
# optional gate). Hard/elite unchanged.

# ---------------------------------------------------------------------------
# EXPERIMENT HOOK (2026-08-11) — adaptive thinking on the big model
# ---------------------------------------------------------------------------
# Off by default; nothing below changes for a normal run.
#
# Every Opus 4.8 set breached the length-bias gate (mean 5.25/8 correct-longest
# vs Opus 5's 2.5/8). The length-bias self-check is a counting task — tally word
# counts across 32 options, then rebalance — and llm.py disables thinking on
# every call, so 4.8 has to do that arithmetic in the forward pass. This turns
# adaptive thinking on for the OPUS stages (render + questions) to see whether
# the bias closes, and at what cost.
#
# Thinking tokens bill at OUTPUT rates and count against max_tokens, so the
# ceilings below must rise with it or the call truncates mid-JSON and _validate
# rejects it — measuring nothing. Pair with RC_ENGINE_TIER_BUDGET_USD, since the
# pre-call guard prices worst case at the full ceiling.
#   RC_ENGINE_OPUS_THINKING=1 RC_ENGINE_TIER_BUDGET_USD=2.00 \
#       python -m rc_engine.cli generate --hard 1
OPUS_THINKING = os.environ.get("RC_ENGINE_OPUS_THINKING", "").strip().lower() in (
    "1", "true", "on", "yes", "adaptive")

# QUESTIONS ONLY — deliberately not render.
#
# The first attempt at this probe (2026-08-11) enabled thinking on both OPUS
# stages and produced no data at all: the passage novelty gate sits BETWEEN
# render and questions, all three attempts were rejected there on persona_leak,
# and the questions stage — the only one with the length-bias problem — never
# ran. Thinking on render tripled the cost of every attempt ($0.10 -> ~$0.29)
# and bought nothing, because the hypothesis is about the option-balancing
# self-check, which happens in the questions call.
# INVARIANT: thinking is sent only for stages listed here, and every one of them
# must have a raised ceiling below. Breaking that pairing is not a config typo,
# it is a guaranteed truncation: thinking bills at output rates and counts
# against max_tokens, so a stage with thinking ON and its normal ceiling spends
# the budget reasoning and then truncates mid-output. That happened on
# 2026-08-11 — render kept thinking at its 1600 ceiling and returned
# failed_render twice for $0.17. test_thinking_experiment.py pins the pairing.
THINKING_STAGES = ("questions",)
_THINKING_CEILINGS = {"questions": 16000}
assert set(THINKING_STAGES) == set(_THINKING_CEILINGS), (
    "every thinking stage needs a raised max_tokens ceiling")

# The engine calls messages.create() NON-streaming everywhere. The Anthropic SDK
# refuses a non-streaming request whose max_tokens implies a >10-minute
# response, raising ValueError before anything is sent — measured at 21333 for
# our model. A first attempt at the thinking probe used 24000 and died there
# ($0.00 spent, but the run was lost). Anthropic's own guidance is to stream
# above ~16K, so that is the ceiling used and the bound asserted below; raising
# any stage past it requires switching that call to messages.stream() first.
MAX_NONSTREAMING_TOKENS = 16000
assert all(v <= MAX_NONSTREAMING_TOKENS for v in _THINKING_CEILINGS.values()), (
    "a thinking ceiling exceeds the non-streaming limit — the SDK will reject "
    "the call before sending; switch the stage to streaming or lower it")

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
    # 4200, not 3200: on the 2026-07-26 batch the elite question payload
    # measured ~3171 output tokens against a 3200 ceiling — i.e. sitting on the
    # limit. Anything marginally wordier truncates, _validate rejects it, and
    # the stage retries a full ~$0.08 Opus call (that is what produced the
    # failed_questions on BP_260726_d184f1f4). 6 questions x (stem + 4 options +
    # why_right + 3 why_wrong) genuinely needs this much room.
    #
    # 5600 at QUESTIONS_PER_SET = 8: the same 4200/3171 = 1.32x headroom ratio
    # applied to the scaled payload (3171 * 8/6 = 4228). Keep that ratio if the
    # count changes again — sitting on the ceiling is what makes the stage retry.
    "questions": {
        "medium": ("big", 5600),
        "hard": ("big", 5600),
        "elite": ("big", 5600),
    },
    # solver/judge scale with question count too: the solver emits one answer
    # object per question, the judge reads the full set.
    "solver": {
        "medium": ("mid", 1400),
        "hard": ("mid", 1600),
        "elite": ("mid", 1600),
    },
    "judge": {
        "medium": ("small", 1500),
        "hard": ("small", 2000),
        "elite": ("small", 2000),
    },
    # Blind rhetorical-move read of the rendered passage. Deliberately the
    # cheapest model at every tier and deliberately a SEPARATE call from
    # compliance: the compliance prompt contains the blueprint, and a channel
    # that sees the plan ends up re-measuring the plan (that is exactly how
    # movement_string stopped being an independent signal). ~750 in / ~120 out
    # on the small model is well under a cent per passage.
    # 1200, not the ~120 the JSON actually needs: every current "small" model
    # across the three providers is a reasoning model, and reasoning tokens are
    # consumed from the same ceiling before a single character of answer is
    # emitted. At 300 the reasoning can eat the whole budget, the call returns
    # empty, and the channel silently stops scoring — which for the primary
    # novelty detector is far worse than the sub-cent the headroom costs
    # (worst case $0.0018 on Luna, $0.0075 on Haiku).
    # Reads the seed before any paid stage. Cheapest model, low effort.
    "seed_classify": {
        "medium": ("small", 1400),
        "hard": ("small", 1400),
        "elite": ("small", 1400),
    },
    "move_signature": {
        "medium": ("small", 2400),
        "hard": ("small", 2400),
        "elite": ("small", 2400),
    },
    # cat-pyq-f3 plan check (2026-09-14, rc_engine/seed_fidelity.py): does the
    # refined plan stay on the seed's subject and kind of material? Runs only
    # for f3 plans, before render. Same reasoning-headroom logic as above.
    "seed_fidelity": {
        "medium": ("small", 1400),
        "hard": ("small", 1400),
        "elite": ("small", 1400),
    },
    # Both pinned to the cheap tier via STAGE_MODEL_PINS. Ceilings are generous
    # because reasoning models spend the ceiling before emitting any JSON, and
    # a check that silently returns nothing is worse than one that costs a
    # fraction of a cent more.
    "answerability": {
        "medium": ("small", 3000),
        "hard": ("small", 3000),
        "elite": ("small", 3000),
    },
    "solver_tiebreak": {
        "medium": ("small", 1200),
        "hard": ("small", 1200),
        "elite": ("small", 1200),
    },
}

ACTIVE_PROVIDER = DEFAULT_PROVIDER
# Per-tier overrides of a role->model mapping, scoped to one provider.
#
# The engine normally resolves models by ROLE per stage (big/mid/small), which
# is why every tier renders on the same "big" model. That is right for Claude,
# where one Opus serves all three tiers. It is wrong for the GPT-5.6 family,
# which ships three separate tiers of model rather than one model with an effort
# dial — so the natural mapping is Sol for elite and Terra below it.
#
# Only the named (provider, tier, role) combinations change; everything else
# falls through to PROVIDER_MODELS. Claude is untouched.
PROVIDER_TIER_ROLE_OVERRIDES = {
    "openai": {
        "medium": {"big": "gpt-5.6-terra"},
        "hard":   {"big": "gpt-5.6-terra"},
        # 2026-08-22: elite moved off Sol. Sol at high effort cost $0.56/set,
        # scored 6.0 with a `regenerate` verdict, and wrote explicit verdicts
        # into F40 "The Sequence Without Verdict" — whose whole definition is
        # that no paragraph states one. Terra at a higher effort is the
        # experiment replacing it.
        #
        # 2026-09-05: hard and elite spent a day on GPT-6 Astra and came back.
        # Four sets at $0.32-0.56 each scored f1 0.766, 0.784, 0.804, 0.822
        # against the Anthropic path's 0.85-0.87 at roughly half the price, and
        # neither effort setting closed the gap (low and medium were within
        # noise of each other on n=2 vs n=1). Everything else Astra needed is
        # KEPT and tested — MODEL_RATES, OPENAI_EFFORT_SUPPORT, clamp_effort,
        # OPENAI_MODEL_STAGE_EFFORT, RC_ENGINE_OPENAI_GEN_EFFORT — so putting a
        # tier back on it is a one-line change here, not a re-integration.
        "elite":  {"big": "gpt-5.6-sol"},
    },
}

# OpenAI reasoning effort to use when STAGE_EFFORT says None ("provider
# default"). GPT-5.6 accepts none | low | medium | high | xhigh | max and
# defaults to medium when the parameter is omitted.
#
# The client previously forced "low" here to mirror the Anthropic path, where
# llm.py disables thinking on the big model. That parity is defensible on cost
# but it silently caps quality: a Sol elite render at effort "low" is not the
# model the tier is paying for. Stage-level values in STAGE_EFFORT still win.
OPENAI_DEFAULT_EFFORT = "medium"

# Which reasoning_effort values each OpenAI model actually accepts, and the
# ladder used to clamp a request onto the nearest one it does.
#
# Probed against the live API on 2026-09-05, NOT read off a docs page or a
# launch write-up. Every third-party summary of Astra's launch said it supported
# "low through max"; the API returns HTTP 400 for max. It also refuses "none":
#
#   none  400  "does not support 'none' with this model"
#   max   400  "does not support 'max' with this model"
#   low | medium | high | xhigh  OK
#
# The refusal of "none" is the one that would have broken a run rather than
# merely downgraded it: OPENAI_STAGE_EFFORT pins "questions" to none, so every
# Astra set would have died at the questions stage AFTER paying for its render.
# That is the same shape of failure as the 2026-08-22 move_signature ceiling
# bug — a cheap parameter mistake that only bills you once the expensive stage
# has already run.
EFFORT_LADDER = ("none", "low", "medium", "high", "xhigh", "max")
OPENAI_EFFORT_SUPPORT = {
    "gpt-6-astra":   ("low", "medium", "high", "xhigh"),
    "gpt-5.6-sol":   ("none", "low", "medium", "high", "xhigh", "max"),
    "gpt-5.6-terra": ("none", "low", "medium", "high", "xhigh"),
    "gpt-5.6-luna":  ("none", "low", "medium", "high", "xhigh"),
}
# Anything older tops out at high — the pre-5.6 clamp this table replaces.
OPENAI_EFFORT_SUPPORT_DEFAULT = ("none", "low", "medium", "high")


def clamp_effort(model: str, effort: str) -> str:
    """Nearest effort this model accepts. Prefers DOWN (cheaper) and only goes
    up when nothing below is supported, so clamping never silently raises
    spend — except for "none" on a model that has no "none", where the only
    direction available is up to "low"."""
    ok = OPENAI_EFFORT_SUPPORT.get(model, OPENAI_EFFORT_SUPPORT_DEFAULT)
    if effort in ok:
        return effort
    if effort not in EFFORT_LADDER:
        return "medium"
    i = EFFORT_LADDER.index(effort)
    for cand in reversed(EFFORT_LADDER[:i]):
        if cand in ok:
            return cand
    for cand in EFFORT_LADDER[i + 1:]:
        if cand in ok:
            return cand
    return "medium"


# Reasoning tokens are drawn from the SAME ceiling as the answer, so a model
# that reasons needs the answer's budget PLUS its thinking budget.
#
# Measured 2026-08-22 on a real ~3.2K-token render contract (gpt-5.6-terra),
# which is why this is additive rather than a multiplier — the visible output
# barely moved while the reasoning grew 12x:
#   effort=low     reasoning   421   visible 596
#   effort=medium  reasoning 3,420   visible 682
#   effort=high    reasoning 5,027   visible 714
#
# A 2x multiplier was wrong in both directions: too generous for a 1200-token
# classification stage, and too MEAN for a high-effort render, which needs
# ~5,700 against a 1,600 base. Values below carry roughly 30% margin over
# what was measured.
REASONING_HEADROOM = {
    "none": 0, "low": 1200, "medium": 4500,
    # high raised 6,500 -> 9,000 and xhigh 10,000 -> 21,000 after Sol blew
    # through an 8,100-token render ceiling twice in one batch and Terra spent
    # 16,597 reasoning tokens at xhigh. Under-sizing these is expensive: the
    # doubling retry recovers the call but pays for it twice.
    "high": 9000, "xhigh": 21000, "max": 28000,
}

# Providers whose models spend the output ceiling on reasoning. Anthropic is
# absent deliberately: llm.py disables thinking on the big model and manages
# _THINKING_CEILINGS itself for the experimental path.
REASONING_PROVIDERS = {"openai"}

# Per-stage reasoning effort for OpenAI, used where STAGE_EFFORT says None.
#
# Measured 2026-08-22 on the real move_signature payload (~1800 input tokens,
# gpt-5.6-luna), because a blanket default broke the first live batch:
#   effort=none    0 reasoning tokens,    71 out, $0.00040 - MISSED a move
#                  that is plainly in the passage (LEVEL_RELOCATION)
#   effort=low   512 reasoning tokens,   581 out, $0.00101 - correct
#   effort=medium 2048 reasoning tokens, 2136 out, $0.00289 - correct, 2.9x cost
#   effort=medium against the old 1200 ceiling: 1200 reasoning, EMPTY RESPONSE
#
# The lesson is that reasoning effort is not a quality dial you can set once.
# On a classification stage against a closed vocabulary, medium spends 2048
# tokens to emit a nine-item list and returns nothing at all if the ceiling is
# tight. On a generative stage it is the whole point. So it is set per stage.
# Per-(tier, stage) effort, layered over OPENAI_STAGE_EFFORT below.
#
# NOTE: "max" exists only on Sol. Terra and Luna accept none|low|medium|high|
# xhigh and return HTTP 400 on max, so xhigh is the ceiling for elite here.
#
# Measured on one elite render contract (gpt-5.6-terra):
#   high   6,484 reasoning /   733 visible / 530 words / $0.0923 /  68s
#   xhigh 16,597 reasoning /   860 visible / 530 words / $0.2151 / 165s
# The passage came out the same length either way; whether the extra 10k
# reasoning tokens buy a better passage is what this run is testing.
OPENAI_TIER_STAGE_EFFORT = {
    # xhigh removed 2026-08-22 after the ablation below: on the same blueprint,
    # medium scored f1 0.925 against high's 0.895 and xhigh produced an
    # identical 530-word passage for 3.7x medium's cost. Elite keeps high for
    # the render (the prose is what is judged) and medium elsewhere; there is
    # no measured return above that.
    "elite": {},
}

# Per-MODEL effort overrides, consulted before the tier and stage tables.
#
# Effort is a property of the model, not of the tier, and the 2026-09-05 Astra
# run proved the tables below cannot express that. Both generative stages are
# pinned to "none" as a deliberate 5.6-family cost trade; Astra has no "none",
# so clamp_effort sent them to "low" -- and "low" is the WORST rung on the
# ablation recorded under "render" below (f1 0.750, against 0.795 at none and
# 0.925 at medium). The batch cost $0.97 and told us nothing about the model,
# because it ran the one setting nobody would have chosen.
#
# Medium on both generative stages, from that same ablation. Not high: the
# 2026-08-22 measurement has high buying 5,027 reasoning tokens against
# medium's 3,420 while visible output moves 682 -> 714, and on Astra those
# tokens bill at $50/MTok. The checking stages stay where they are; they are
# pinned to Luna anyway and never see this table.
OPENAI_MODEL_STAGE_EFFORT = {
    "gpt-6-astra": {"render": "medium", "questions": "medium"},
}

# Experiment escape hatch: force the GENERATIVE stages to one effort for a
# single run, so an A/B needs no edit to the table above.
#
#   RC_ENGINE_OPENAI_GEN_EFFORT=low python -m rc_engine.cli generate ...
#
# Added 2026-09-05 because this session ran the same comparison three times by
# editing config in place, which is how the 2026-09-05 Astra batch ended up at
# an effort nobody chose. Clamped per model at call time like any other value,
# so an unsupported setting degrades instead of failing. Checking stages are
# untouched: they are pinned to Luna and cost fractions of a cent, and
# starving them was separately measured to lose real moves.
_gen_effort = os.environ.get("RC_ENGINE_OPENAI_GEN_EFFORT", "").strip()
if _gen_effort:
    for _m in OPENAI_MODEL_STAGE_EFFORT:
        OPENAI_MODEL_STAGE_EFFORT[_m] = dict(
            OPENAI_MODEL_STAGE_EFFORT[_m],
            **{"render": _gen_effort, "questions": _gen_effort})
    OPENAI_MODEL_STAGE_EFFORT.setdefault(
        "gpt-5.6-sol", {"render": _gen_effort, "questions": _gen_effort})
    OPENAI_MODEL_STAGE_EFFORT.setdefault(
        "gpt-5.6-terra", {"render": _gen_effort, "questions": _gen_effort})

OPENAI_STAGE_EFFORT = {
    # reading and classification - reasoning adds cost, not accuracy
    "seed_classify":     "low",
    "seed_fidelity":     "low",
    "move_signature":    "low",
    "compliance":        "low",
    "judge":             "low",
    "answerability":     "low",
    "similarity_screen": "low",
    # judgement calls on genuinely ambiguous material
    "solver_tiebreak":   "medium",
    "refine":            "medium",
    "solver":            "medium",
    # Generative stages with reasoning OFF (operator decision, 2026-08-22).
    #
    # The ablation on one elite blueprint put render f1 at 0.795 (none) and
    # 0.750 (low) against 0.925 (medium) — both at or below the 0.75 threshold
    # that triggers a paid re-render — so this trades reasoning spend for
    # re-render risk. Whether that trade wins depends on how often it fires,
    # which one blueprint cannot say. Watch the compliance-retry rate.
    #
    # The cheap CHECKING stages stay at "low" deliberately: move_signature at
    # "none" was measured missing a move that is plainly in the passage
    # (LEVEL_RELOCATION), and those stages cost fractions of a cent.
    "render":            "none",
    # questions at medium, not high (2026-08-22): measured on a real render
    # payload, high buys 5,027 reasoning tokens against medium's 3,420 while
    # visible output moves 682 -> 714. The questions stage is the single
    # largest line on a set, so that delta is where the money goes; the render
    # keeps high because the prose is the thing being judged.
    "questions":         "none",
}

STAGE_CONFIG: dict = {}


# Defined above set_provider() because that runs at import time and the
# ceiling calculation resolves pins to decide whether a stage needs
# reasoning headroom.
def resolve_stage_pin(stage: str, tier: str | None = None):
    """(provider, model) for this stage/tier, or None when unpinned."""
    pin = STAGE_MODEL_PINS.get(stage)
    if pin is None:
        return None
    if isinstance(pin, dict):
        if tier is None:
            return None          # tier-scoped pin, and we do not know the tier
        return pin.get(tier)
    return pin


STAGE_MODEL_PINS = {
    "compliance":       ("openai", "gpt-5.6-luna"),
    "judge":            ("openai", "gpt-5.6-luna"),
    # refine is the ONE generative stage pinned here, and ONLY at medium.
    #
    # A stage-level pin would have been wrong: refine takes the "small" role at
    # medium (Haiku on Anthropic) but "mid" at hard and elite (Sonnet 5). A
    # blanket pin silently demoted hard and elite content planning from Sonnet
    # to Luna, which nobody asked for. The per-tier form below removes Haiku
    # without touching the tiers that were never on it.
    "refine":           {"medium": ("openai", "gpt-5.6-luna")},
    "seed_classify":    ("openai", "gpt-5.6-luna"),
    "seed_fidelity":    ("openai", "gpt-5.6-luna"),
    "move_signature":   ("openai", "gpt-5.6-luna"),
    "answerability":    ("openai", "gpt-5.6-luna"),
    "solver_tiebreak":  ("openai", "gpt-5.6-luna"),
}


def set_provider(provider: str) -> None:
    """Resolve _STAGE_PLAN into STAGE_CONFIG for one provider. Idempotent.
    Rebinding the module global is safe: every call site reads via
    config.STAGE_CONFIG attribute lookup, never a stale reference."""
    global ACTIVE_PROVIDER, STAGE_CONFIG
    if provider not in PROVIDER_MODELS:
        raise ValueError(
            f"unknown provider {provider!r}; expected one of {PROVIDERS}")
    models = PROVIDER_MODELS[provider]
    tier_over = PROVIDER_TIER_ROLE_OVERRIDES.get(provider, {})

    def _model_for(role: str, tier: str) -> str:
        return tier_over.get(tier, {}).get(role, models[role])

    # Reasoning tokens are drawn from the SAME ceiling as the answer, so a
    # ceiling sized for a non-reasoning model starves the output. First live
    # OpenAI batch (2026-08-22): render exhausted 1500 and compliance exhausted
    # 1400 twice, each recovering only via the doubling retry — which works but
    # pays for the call twice. Sizing the ceiling correctly up front is cheaper
    # than retrying into it. Ceilings cost nothing unless used; they only make
    # the pre-call budget guard more conservative.
    global TIER_BUDGET_USD
    TIER_BUDGET_USD = dict(_BASE_TIER_BUDGET_USD)
    if not _BUDGET_OVERRIDDEN:
        TIER_BUDGET_USD.update(PROVIDER_TIER_BUDGET_USD.get(provider, {}))

    def _ceiling(stage: str, tier: str, base: int, role: str = "big") -> int:
        # Headroom follows the model that ACTUALLY runs the stage, not the
        # batch provider. Getting this wrong cost real money on 2026-08-24: the
        # Luna-pinned check stages kept their bare Anthropic ceilings on a
        # --provider claude run, exhausted them on reasoning, and paid twice via
        # the doubling retry — five times in one batch.
        pin = resolve_stage_pin(stage, tier)
        stage_provider = pin[0] if pin else provider
        if stage_provider not in REASONING_PROVIDERS:
            return base
        stage_model = pin[1] if pin else _model_for(role, tier)
        # Looked up through globals() rather than by name: set_provider() runs
        # at import, and some of these tables are defined further down the
        # module. A missing table here means "no explicit effort", which falls
        # through to the OpenAI default — not a crash at import time.
        g = globals()
        effort = (g.get("OPENAI_MODEL_STAGE_EFFORT", {}).get(
                      stage_model, {}).get(stage)
                  or g.get("OPENAI_TIER_STAGE_EFFORT", {}).get(tier, {}).get(stage)
                  or g.get("STAGE_EFFORT", {}).get(stage, {}).get(tier)
                  or g.get("OPENAI_STAGE_EFFORT", {}).get(
                      stage, g.get("OPENAI_DEFAULT_EFFORT", "medium")))
        # Size the ceiling for the effort that will ACTUALLY run, not the one
        # asked for. providers.py clamps unsupported values per model, and the
        # two disagree exactly where it is expensive: "questions" asks for
        # "none" (headroom 0) but Astra has no "none" and runs it at "low",
        # which spends real reasoning tokens against a ceiling sized for zero.
        # That is the doubling-retry path — it recovers the call and bills it
        # twice, on the single most expensive model in the table.
        effort = clamp_effort(stage_model, effort)
        return base + g.get("REASONING_HEADROOM", {}).get(effort, 4500)

    STAGE_CONFIG = {
        stage: {tier: (_model_for(role, tier),
                       _THINKING_CEILINGS[stage]
                       if (OPUS_THINKING and role == "big"
                           and stage in _THINKING_CEILINGS)
                       else _ceiling(stage, tier, max_tok, role))
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
    "seed_classify": {"medium": None, "hard": None, "elite": None},
    "seed_fidelity": {"medium": None, "hard": None, "elite": None},
    "move_signature": {"medium": None, "hard": None, "elite": None},
    "answerability": {"medium": None, "hard": None, "elite": None},
    "solver_tiebreak": {"medium": None, "hard": None, "elite": None},
}

# Typical input sizes per stage (tokens) — used only by `cli estimate` to
# print the cost table; the runtime guard measures the real prompt instead.
# Measured 2026-07-26 by building the real prompts for a representative
# hard-tier blueprint (the previous values were 1.5-2x high, which made the
# printed headroom look tighter than it is).
# questions/solver/judge revised up 2026-08-10 for 8 slots: the questions prompt
# carries two more slot lines + stem shapes, and solver/judge prompts carry two
# more full questions (stem + 4 options).
ESTIMATED_INPUT_TOKENS = {
    "refine": 1830,
    "render": 1680,
    "compliance": 1500,
    "questions": 2250,
    "solver": 2180,
    "judge": 3650,
    "seed_classify": 900,
    "seed_fidelity": 1100,
    "move_signature": 900,
    "answerability": 2400,
    "solver_tiebreak": 1100,
}

# Retry ceilings. Compose retries are local sampling (free).
MAX_COMPOSE_ATTEMPTS = 40
MAX_REFINE_ATTEMPTS = 3      # transient empty/truncated refine responses

# Seed fidelity (cat-pyq-f3 plans only; rc_engine/seed_fidelity.py).
# A plan that fails the check gets this many directed re-refines before the
# attempt is rejected as rejected_seed_fidelity and the slot rotates its seed.
SEED_FIDELITY_MAX_REREFINES = 1
# Rendered passage vs seed, local bge-small cosine on the first 400 words
# (free). Measured 2026-09-14 over the 134 shipped sets: passages plainly on
# their seed's subject scored 0.71-0.86; most of the corpus, whose topics had
# left the seed (left-handedness -> shipping containers), scored 0.47-0.65. The
# floor sits below every on-subject set measured, so it catches gross drift the
# plan check missed rather than grading closeness. Recalibrate on f3 output.
SEED_FIDELITY_PASSAGE_FLOOR = 0.65
# Extra topic-shape cohort ceilings for seed-fidelity plans only, applied like
# TOPIC_SHAPE_COHORT_MAX_SHARE (restrict to the cohort on a winning flip, away
# from it otherwise; never empties the pool). First paid f3 batch, 2026-09-14:
# the narrowed shape pools put TS01 (The Conceptual Dispute) on six of nine
# plans, and every shipped set screened red for one two-camps architecture.
# 0.20 is roughly uniform over the four-to-six shapes a subject can carry.
# Label-based draws (`generate --subject/--genre`, 2026-09-14) skip essays the
# store labels as carrying fewer topic shapes than this. The first paid f3 batch
# drew essays with one or two carriable shapes; every such plan landed on TS01
# and the sets screened red for one shared architecture.
SEED_MIN_CARRIABLE_SHAPES = 3

SEED_FIDELITY_COHORT_MAX_SHARE = [
    ({"TS01"}, 0.20),
]
MAX_RENDER_ATTEMPTS = 2      # render + compliance loop

# Transient API failures — 429 rate limit, 5xx overload, dropped connections —
# are retried with exponential backoff and jitter before the batch is stopped
# (2026-09-02). Until now a single 429 raised APIExhausted and ended the whole
# run, which is precisely the first thing a larger or parallel batch hits.
# Quota / credit-balance errors are NOT retried: waiting cannot fix them, and
# they still stop the batch cleanly as before.
API_BACKOFF_MAX_RETRIES = 5
API_BACKOFF_BASE_S = 2.0        # 2, 4, 8, 16, 32 s (+ up to 25% jitter)
API_BACKOFF_MAX_S = 60.0

# Parallel batches (2026-09-02): `generate --workers N`. Sequential (1) is the
# default and unchanged. See rc_engine/workers.py for what keeps concurrent
# renders from shipping near-duplicates of each other. 4 is a ceiling, not a
# recommendation: rate limits, and the fact that every worker re-scores the
# same window, make 2-3 the useful range until measured otherwise.
BATCH_WORKERS_DEFAULT = 1
BATCH_WORKERS_MAX = 4
PARALLEL_SEEDS_PER_SLOT = 3     # primary seed + spares for pre-screen/novelty rotation
INFLIGHT_STALE_MIN = 30         # a reservation older than this is a dead worker's
SHIP_LOCK_STALE_S = 600         # a lock file older than this is a dead worker's
SHIP_LOCK_WAIT_S = 120          # after this, ship unlocked rather than hang
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
# Passage length: ONE house standard, not a tier parameter
# ---------------------------------------------------------------------------
# Every tier ships a 500-word passage. Length used to differentiate the tiers
# (400-450 / 450-500 / 500-550) but real CAT passages sit near 500 regardless
# of difficulty, so the tiers now differ only where difficulty actually lives:
# instability_range, allowed_topologies, family tier_floor, TIER_SEED_GENRES,
# STAGE_EFFORT and TIER_BUDGET_USD.
#
# The band is enforced, not advisory: a passage outside it can never
# auto-approve — pipeline routes it to needs_review (a free check; no
# re-render is paid for). Both the engine and `cli vet` read these two
# constants, so they can no longer disagree.
#
# The render prompt states this as a RANGE ("500-550 words"), not a single
# number. The per-paragraph plan still carries exact integers that sum to the
# midpoint (525) — that mechanism is what produced 500/501-word passages on the
# first real batch — but the passage as a whole is judged against the range.
PASSAGE_WORD_MIN = 500
PASSAGE_WORD_MAX = 550

# ---------------------------------------------------------------------------
# Questions per set
# ---------------------------------------------------------------------------
# Raised 6 -> 8 on 2026-08-10 at client request. This is the single source of
# truth: the count used to be a literal 6 in a dozen places (registry slot
# validation, the questions prompt and its validator, the solver prompt and its
# comparability check, the answer-key letter plan, the vet parser, the library
# stats). Every one of those now reads this constant, so the next change is one
# line here plus a topologies.json rebuild.
#
# Two things are DERIVED from it and must move together:
#   - every topology in components/topologies.json carries exactly this many slots
#     (enforced by registry.validate)
#   - the questions/solver/judge max_tokens ceilings and TIER_BUDGET_USD below
QUESTIONS_PER_SET = 8

# Length-bias ceiling: in how many questions the correct option may be the
# strictly longest one. N//3 keeps the same absolute ceiling (2) that 6-question
# sets had, which at 8 questions is proportionally stricter — the right
# direction, since "longest option is right" is the most exploitable tell.
MAX_CORRECT_LONGEST = QUESTIONS_PER_SET // 3

# ---------------------------------------------------------------------------
# Tier structural parameter regions
# ---------------------------------------------------------------------------
# passage_words is the same (lo, hi) range on every tier now.

TIER_PARAMS = {
    "medium": {
        "instability_range": (0.15, 0.40),
        "passage_words": (PASSAGE_WORD_MIN, PASSAGE_WORD_MAX),
        # medium uses only structurally simpler families (tier_floor == medium)
    },
    "hard": {
        "instability_range": (0.35, 0.70),
        "passage_words": (PASSAGE_WORD_MIN, PASSAGE_WORD_MAX),
    },
    "elite": {
        # floor lowered 0.55 -> 0.45: instability ~1.0 reads as "fully suspended"
        # and pushed elite renders toward irresolution regardless of family; the
        # closing-posture directive now governs the ending's stance instead.
        "instability_range": (0.45, 0.95),
        "passage_words": (PASSAGE_WORD_MIN, PASSAGE_WORD_MAX),
    },
}

# ---------------------------------------------------------------------------
# Tier question difficulty: which plans a tier may draw, and how it renders them
# ---------------------------------------------------------------------------
# This replaces TIER_PARAMS["medium"]["allowed_topologies"], a hand-picked list
# of 11 that never actually controlled difficulty: its mean slot difficulty was
# 0.680 against 0.711 for the topologies it excluded, and four of its entries
# carried a 0.90 slot. It also could not be narrowed safely — a pool near
# EXCLUSION_WINDOWS["topology"] in size empties and dead-ends sample_skeleton,
# which is why it had already been widened once.
#
# So the pool stays wide and difficulty moves onto the plan itself. Only
# structurally hard plans are barred; everything else is handled by scaling.
#
# max_span is a PROPORTION of the set expressed as an absolute. It was 2 of 6
# slots (33%); at QUESTIONS_PER_SET = 8 the same intent is 3 (37.5%). Left at 2
# during the 6 -> 8 rebuild it barred 22 of 24 topologies and cut the medium
# pool to 2 — below EXCLUSION_WINDOWS["topology"], which dead-ends composition.
# Medium also pulls one span back to local at question time (TIER_SLOT_SCALING
# span_to_local), so a 3-span plan renders as 2 spans at medium anyway.
TIER_TOPOLOGY_BAR = {
    "medium": {
        "forbid_types": {"counterfactual_structure", "decoy_escape"},
        "max_span": 3,
    },
    "hard": {},
    "elite": {},
}

# The same topology must yield an easier set at medium than at elite. Slot
# difficulties in topologies.json are authored at hard-tier calibration; each
# tier maps them into its own band before they reach the question prompt.
#   scale/cap/floor -> per-slot difficulty
#   span_to_local   -> how many cross-paragraph slots to pull back to local
TIER_SLOT_SCALING = {
    "medium": {"scale": 0.85, "cap": 0.70, "floor": None, "span_to_local": 1},
    "hard":   {"scale": 1.00, "cap": 0.90, "floor": None, "span_to_local": 0},
    "elite":  {"scale": 1.00, "cap": 0.95, "floor": 0.60, "span_to_local": 0},
}

# Stated verbatim to the render and question models. Neither prompt used to say
# which tier it was writing for, so tier character lived only in the manual
# prompt's table. Single source now, so the three cannot drift.
TIER_DIFFICULTY_CHARACTER = {
    "medium": ("one clean structural turn; readable throughout. A careful reader "
               "should reach every answer in one pass, and at most one question "
               "may require synthesis across paragraphs. The answers live in the "
               "passage, not behind it."),
    "hard": ("genuine interpretive work; the author's stance has to be tracked "
             "across the argument rather than read off any one sentence."),
    "elite": ("architectural difficulty: late thesis, layered tensions, traps that "
              "reward re-reading. A strong reader should have to work."),
}

TIER_LETTERS = {"medium": "M", "hard": "H", "elite": "E"}

# ---------------------------------------------------------------------------
# Seed sourcing: preferred genre pools per tier (labels = RAG.py FEEDS genres).
#   Hard/elite draw uniformly at random ONLY from CAT_SEED_GENRES (multi-move
#   essay sources). They do NOT fall back to news/op-ed or Smithsonian-lite.
#   Medium may draw from any unused essay (including political / explainer).
# ---------------------------------------------------------------------------
# Gold + solid CAT seed genres (see RAG FEEDS "CAT gold" block).
# Audited 2026-09-07: SEVEN of these eighteen have zero documents in the seed
# store — Public Books, Boston Review, LARB, Lapham's Quarterly and NYRB
# because their feeds rotted (the first four are now commented out in RAG.py;
# NYRB's path was fixed and should refill), Harper's and Undark because their
# feeds serve but nothing has cleared min_words. The nominal pool of eighteen
# publications is really eleven, which is most of why the shipped corpus is 19%
# Philosophy & Ethics. Left in place rather than pruned: a name with no
# documents costs nothing, and NYRB/Harper's/Undark should come back.
CAT_SEED_GENRES = [
    "Aeon", "Psyche", "Nautilus", "JSTOR",
    "Public Books", "The Point", "Hedgehog Review", "New Atlantis",
    "Boston Review", "LARB", "Commonweal", "Lapham's Quarterly",
    "LRB", "NYRB", "Harper's", "Noema",
    "Quanta", "Undark",
]
# Back-compat alias
SERIOUS_GENRES = CAT_SEED_GENRES

# Hard's pool, widened 2026-09-01. Every one of the 18 CAT_SEED_GENRES
# publications runs idea essays, so hard's 168 unused documents were 100% ONE
# content kind — which deadlocked the seed-genre saturation gate (conceptual
# essay sat at 62% of the trailing window with no legal alternative to rotate
# to) and made the tier a genre monoculture by construction.
#
# These four are long-form and reported, anchored to a specific place, episode
# or object rather than to a discourse. Elite is deliberately NOT widened: the
# 2026-08-26 decision to keep elite on the literary forms stands, and this is
# the seed-side counterpart of it. Elite therefore remains single-kind, and its
# saturation gate still stands down — that is a known, deliberate gap.
# Ceiling on the share of seeds drawn from idea-essay sources (2026-09-05).
#
# 22 of 34 feeds are idea_essay, so 53% of seeds classified conceptual_essay —
# which is also the FALLBACK genre, so every unparseable classify lands there
# too. Combined with the old shape matrix that gave conceptual_essay only 4 of
# 10 outlets, 67% of shipped sets landed in three topic shapes.
#
# The classified GENRE is only known after the ~$0.001 classify call, so the
# ceiling acts on the feed KIND, which is known at draw time (backfilled onto
# all 935 documents on 2026-09-01).
#
# Enforced by steering BOTH ways — restrict to the kind on a winning flip,
# away from it on a losing one — because a permit-only flip multiplies the flip
# probability by the kind's base rate and under-binds. That is exactly how the
# 20% first-person persona ceiling realised 4-5% until _steer_share was fixed
# on 2026-08-29. Whitelist-limited tiers degrade rather than starve:
# get_unused_essay falls back to the full pool if the restriction would empty it.
SEED_KIND_MAX_SHARE = {"idea_essay": 0.45}

# Share ceilings on GROUPS of topic shapes that ask the same underlying
# question, enforced the same way as SEED_KIND_MAX_SHARE and
# FIRST_PERSON_MAX_SHARE: one bidirectional coin flip per draw.
#
# Measured 2026-09-05 over the last 30 shipped sets (the all-time figure is
# meaningless — 60 of 107 predate the topic_shape column):
#
#     TS06 13.3% + TS12 13.3% = 26.7%   against 14.3% uniform for 2 of 14
#     over the last 14 shipped it was 6 of 14 = 43%
#
# Why these two and not the raw counts. Three sets that screened red on
# consecutive days — RC-HARD-260905-0081 (TS06), RC-HARD-260905-0084 (TS12) and
# RC-ELITE-260905-0077 — turned out on a read to be ONE argument: an instrument
# is accurate inside its design, blind outside it, and the blind spot governs.
# They shared no family, persona or topology (the exclusion windows guarantee
# that), and came from unrelated seeds. The repetition is in the QUESTION the
# passage asks, and TS06 ("someone set out to count or rank something, and one
# thing got left out") and TS12 ("a long-held belief, and one study that tests
# it") both put that question to the renderer directly.
#
# This is also why five earlier levers moved the red rate nothing: families,
# seeds, beat placement and register all vary channels that are orthogonal to
# the schema. The 2026-09-05 register fix in particular cannot touch it —
# RC-ELITE-260905-0077's nouns are hydrants, valve covers and trenches, so it
# passes the vocabulary-density check and is still the instrument argument.
#
# Capped AT uniform rather than below it. The shapes are not defective and the
# exam asks this question too; what is defective is asking it three times a
# week. If the red rate does not move at uniform, the attractor is in the render
# contract rather than the shape library, and no ceiling here will reach it.
TOPIC_SHAPE_COHORT_MAX_SHARE = [
    ({"TS06", "TS12"}, 0.14),
]

# Widened again 2026-09-07. Two separate problems, one fix.
#
# First: the feeds added on 2026-08-22 and 2026-09-01 to break the idea-essay
# monoculture were never added to a TIER list, and TIER_SEED_STRICT is True, so
# hard and elite could not draw them at all — only medium could, at 4 slots a
# week. The result is visible in the store: Works in Progress holds 224 UNUSED
# documents (the largest pool by far) and has seeded 3 sets; Verfassungsblog 50
# unused and 1 set; Physics World 18 unused, Asterisk 20 unused, Paris Review 8
# unused and ZERO sets each. Widening the feed list again without this line
# would just have grown the unused pile.
#
# Second: the shipped-corpus genre audit (2026-09-07, RC_Shipping_Tracker
# "Genre Mix") showed Literature & Criticism and Education at one set in 78,
# and Economics, Medicine and Life Sciences at four or fewer. The six feeds
# added to RAG.FEEDS on the same date are aimed at exactly those buckets.
#
# "Rest of World" retained though its feed died 2026-09-07: 9 unused documents
# are still in the store and remain drawable.
HARD_SEED_GENRES = CAT_SEED_GENRES + [
    "Damn Interesting", "Hakai", "Rest of World", "Atlas Obscura",
    # stranded by the missing TIER entry, not by quality
    "Works in Progress", "Verfassungsblog", "Physics World", "Asterisk",
    "Paris Review", "Public Domain Review", "History Today",
    # aimed at the thin buckets in the shipped corpus
    "The Millions", "Nursing Clio", "Sapiens", "ProMarket", "Kappan",
    "The Revelator",
]

# Elite, widened 2026-09-05 — literary register only. Its 174 unused documents
# were all one content kind, which left _pool_is_single_kind holding the
# saturation gate permanently disarmed. These three are already in RAG.FEEDS,
# are long-form and literary, and are NOT idea-essay in form:
#   Public Domain Review, History Today  -> narrative_history
#   Hakai                                -> reportage (narrative science)
# Deliberately excluded: Atlas Obscura and Damn Interesting, which are popular
# rather than literary in register. They stay on hard, where they were added on
# 2026-09-01. This keeps the 2026-08-26 decision that elite stays literary while
# ending the monoculture that decision accidentally created.
# Extended 2026-09-07 with three more that meet the same literary-register bar
# and are not idea-essay in form: Paris Review and The Millions are criticism
# anchored to one work, Nursing Clio is narrative history of medicine. The
# 2026-08-26 decision that elite stays literary is intact — ProMarket, Kappan,
# Sapiens, The Revelator, Works in Progress, Physics World, Verfassungsblog and
# Asterisk are hard-only, being professional or popular rather than literary.
ELITE_SEED_GENRES = CAT_SEED_GENRES + [
    "Public Domain Review", "History Today", "Hakai",
    "Paris Review", "The Millions", "Nursing Clio",
]

TIER_SEED_GENRES = {
    "elite": ELITE_SEED_GENRES,  # literary pool, but more than one kind
    "hard": HARD_SEED_GENRES,   # + four long-form reported sources
    "medium": None,             # any unused genre at random
}
# When True, hard/elite never fall back to non-preferred genres (seedless
# instead). Keeps Nation / SciAm / Smithsonian out of hard/elite.
TIER_SEED_STRICT = True

# ---------------------------------------------------------------------------
# Composer: exclusion windows (in shipped RCs) and decay weighting
# ---------------------------------------------------------------------------

# The ARGUMENT SCHEMA: what a passage's argument DOES, one level above the
# rhetorical moves and independent of what it is about.
#
# Added 2026-09-05 after the schema audit below. Every other novelty channel in
# this engine — family, movement, rhythm, curve, embedding, lexical overlap —
# was already forcing sets apart, and the similarity screen kept calling them
# repeats anyway. The reason, once measured, was that none of those channels
# encodes the argument's shape:
#
#   PRIMARY schema, last 32 shipped        vs the 124 RC125 exam passages
#     S1_INSTRUMENT_BLIND        46.9%          12.9%     3.6x over
#     S4_MECHANISM_TRACED        18.8%          30.6%     0.6x under
#     S3_TWO_CAMPS_RELOCATED     15.6%           8.1%     1.9x over
#     S2_RECEIVED_ACCOUNT_REPL   12.5%          25.8%     0.5x under
#     S7_CASE_AGAINST_RULE        3.1%          11.3%     0.3x under
#     S5 / S8                     0.0%           7.2%     never produced
#
#   S1 was PRESENT (primary or secondary) in 72% of our sets against 18% of the
#   exam's. Four consecutive sets that read as one argument — RC-HARD-0081,
#   RC-HARD-0084, RC-ELITE-0077, RC-MEDIUM-0063 — shared no family, persona or
#   topology, spanned all three tiers and two providers, and drew four
#   different topic shapes. Only the schema was common.
#
# This is also why the red/green pairwise analysis found nothing (max Cohen's
# d 0.49): with S1 in 72% of sets, both groups carry it, so no channel could
# separate them. There was no discriminator to find.
#
# Weighted TO THE EXAM rather than to uniform. The exam repeats S4 at 30% and
# that is correct for the form; a uniform draw would be as wrong in the other
# direction. Capping S1 alone would only redistribute into whatever the engine
# reaches for next — the whole distribution is off, in both tails.
ARGUMENT_SCHEMAS = {
    "S1_INSTRUMENT_BLIND": {
        "description": "a method, measure, record or category is accurate inside "
                       "its design but blind to something outside it, and the "
                       "blind spot is what governs",
        "directive": "Build the argument around something that measures, counts, "
                     "records or classifies, which does its job correctly and "
                     "still misses what turns out to matter most.",
        "exam_share": 0.129},
    "S2_RECEIVED_ACCOUNT_REPLACED": {
        "description": "a long-standing explanation is retired and a different "
                       "mechanism is worked through in its place",
        "directive": "State the explanation the field has long accepted, give the "
                     "single ground on which it fails, then work a replacement "
                     "through in detail. The argument is the new mechanism.",
        "exam_share": 0.258},
    "S3_TWO_CAMPS_RELOCATED": {
        "description": "two schools disagree, and the passage argues the dispute "
                       "as posed is the wrong dispute",
        "directive": "Stage two positions fairly, then show the disagreement as "
                     "posed is not the real one, and relocate it.",
        "exam_share": 0.081},
    "S4_MECHANISM_TRACED": {
        "description": "how something works, followed step by step, including "
                       "where it breaks",
        "directive": "Follow how the thing actually works, step by step, far "
                     "enough that a reader could describe the steps afterwards. "
                     "Where it breaks is one specific place, not a limit in "
                     "principle.",
        "exam_share": 0.306},
    "S5_PRACTICE_VS_THEORY": {
        "description": "how a thing is actually done on the ground, against how "
                       "it is described or prescribed",
        "directive": "Show the practice as it is really carried out, and let the "
                     "gap with its official description emerge from the detail "
                     "rather than being announced.",
        "exam_share": 0.024},
    "S6_ORIGIN_AND_DRIFT": {
        "description": "where a term or practice came from and how it changed as "
                       "it travelled",
        "directive": "Date the origin, then follow the term or practice across "
                     "domains or eras, showing what each move cost it.",
        "exam_share": 0.040},
    "S7_CASE_AGAINST_RULE": {
        "description": "a general rule stated, then a specific case that breaks "
                       "it, then what explains the exception",
        "directive": "State the general rule plainly, name the case that breaks "
                     "it precisely, and keep what PROVED the exception separate "
                     "from what explains it.",
        "exam_share": 0.113},
    "S8_REMEDIES_WEIGHED": {
        "description": "a practical problem, the available fixes, and what each "
                       "one costs",
        "directive": "Name the problem concretely and say who has it. Give each "
                     "remedy as it is really practised, with its real drawback.",
        "exam_share": 0.048},
}

# Same inverse-frequency damping as every other component, but applied ON TOP of
# the exam weights rather than instead of them: weight = exam_share * lambda**n.
# 0.7 rather than DECAY_LAMBDA's 0.5 because there are only eight schemas and
# the exam genuinely repeats its top two; 0.5 would flatten the target
# distribution the weights exist to reproduce.
ARGUMENT_SCHEMA_DECAY_LAMBDA = 0.7
ARGUMENT_SCHEMA_WINDOW = 12

EXCLUSION_WINDOWS = {
    # TS08 was drawn for two of three elite sets on 2026-08-25 and the screen
    # correctly flagged the pair as a repeat — the shared structure it named
    # was TS08's own instruction. Topic shapes need the same recency pressure
    # every other component has.
    "topic_shape": 4,
    "render_stance": 6,
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
     "(e.g., it depends on a referent introduced in the preceding sentences). "
     "TEST IT: if the sentence could be lifted out and quoted on its own and still "
     "read as a complete thought, it fails — rewrite it so that it cannot. It must "
     "contain a pronoun, demonstrative, or definite reference that is unintelligible "
     "without the sentences before it. Do not end on a maxim, a reversal, a "
     "balanced antithesis, or a wry qualification of a general claim."),
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

# Fingerprints whose rc_sets row carries one of these statuses are hidden from
# the novelty window (2026-09-02). A solver_dispute set may never ship and a
# rejected_novelty row is a duplicate by definition, yet both sat in the
# baseline as magnets: of the five RCs new renders collided with most between
# 2026-08-20 and 09-01, two were solver_dispute sets, one of them blamed
# sixteen times. Rows with no rc_sets row (legacy/manual backfill) stay in —
# they shipped. Audit/reporting paths pass include_quarantined=True and see
# everything, exactly as they do for quarantined rows.
NOVELTY_WINDOW_EXCLUDE_STATUSES = ("solver_dispute", "rejected_novelty")

# Statuses that mean a set actually ships to the client. Everything else is a
# dead attempt: rejected_* and failed_* never reach anyone.
#
# Added 2026-09-05 because the similarity screen was selecting its subjects with
# `[r.rc_id for r in results if r.rc_id]` — i.e. "has an ID", not "shipped". A
# set rejected at the parallel ship lock already HAS an rc_id and an rc_sets
# row, so RC-MEDIUM-260904-0059 was screened, charged $0.0019, and had a red
# verdict written onto a row that will never be exported. It also inflated the
# batch's red count, which is how a wrong figure reached the operator.
SHIPPING_STATUSES = ("approved", "needs_review", "solver_dispute")

# Below this corpus size the curve breach check is kept composite-only:
# commitment curves are 4-6 coarse values and late-thesis tiers all share a
# "low early, rising late" shape. A curve match is useful evidence, but too
# coarse to hard-veto a billion-way blueprint space until the corpus is large.
CURVE_CAP_MIN_CORPUS = 75

# Topology (the set's question layout) at Gate C — operator decision 2026-09-14:
# report, do not reject. A layout shared with a recent set is coincidence; what
# must hold is the question-type MIX across the corpus, measured in `health`
# against the CAT PYQ task shares (rc_engine/question_mix.py). Evidence: topology
# was 3 of the 4 full-gate rejections in the whole DB, and on 2026-09-14 it cost
# a paid medium passage (BP_260914_18b725c5) after its questions were bought.
# The free pre-render re-pick still runs; only the reject is gone. The cap below
# stays for that re-pick and for reporting.
TOPOLOGY_GATE_ENFORCE = False

NOVELTY_CAPS = {
    "movement_levenshtein": 0.70,   # similarity cap
    "movement_bigram_jaccard": 0.60,
    # Level-aware curve distance (fingerprints.curve_similarity), NOT pearson.
    # Calibrated 2026-08-10 against the 31 real curves in rc_pipeline.db, whose
    # highest observed pairwise similarity is 0.979 — so 0.95 sits inside the
    # corpus's own spread and only 7 pairs exceed it, 6 of which also match on
    # movement or rhythm (i.e. the supported tier fires on genuinely close
    # pairs, not on every rising arc). The pearson cap this replaces sat at 0.85
    # and flagged 90% of renders.
    "curve_similarity": 0.95,
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
    # Unconditional-reject tier for the curve channel. 0.98 is above the whole
    # corpus's observed ceiling (0.979), so it costs zero false positives today
    # while still catching a genuinely duplicated arc: an identical curve scores
    # 1.000 and a +/-0.05-per-point near-duplicate scores 0.989.
    "curve_similarity_extreme": 0.98,
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

# persona_leak specificity. A leak is one voice bleeding through; a render that
# lands inside the leak band against this many DISTINCT personas at once is not
# leaking any of them, it is sitting near the corpus centroid — the generator's
# house voice. Diffuse cases become a corpus flag instead of a rejection,
# because a blind re-roll cannot move the house voice and only burns a render.
#
# 3 separates the observed cases with margin (2026-08-11): shipped sets that
# trip the gate breach exactly 1 distinct persona; the render that consumed
# three paid hard-tier attempts breached 7.
PERSONA_LEAK_DIFFUSE_MIN = 3

# Arc-shape decay (2026-08-22). Families are sampled with a per-SHAPE penalty on
# top of the per-ID one, because the library is lopsided by construction: 32 of
# 46 families encode the identical stage -> develop -> turn -> settle arc, so
# uniform ID sampling reproduces that arc ~70% of the time however healthy the
# family KL looks.
#
# Tuned by measurement, not by feel. The two decays STACK — every legacy family
# also carries recent per-ID usage while F33-F46 carry none — so the shape term
# bites far harder than its lambda suggests. Measured share of the legacy arc
# over 150 hard-tier draws against the 2026-08 corpus:
#   0.45 -> 0%    0.75 -> 1%    0.85 -> 0%    0.92 -> 7%    0.95 -> 7%
# Anything below ~0.9 excludes all 32 legacy families outright, which throws
# away a working library to fix a distribution problem. 0.92 leaves the legacy
# arc a real but small share that rises back toward parity as the new shapes
# accumulate trailing usage of their own.
SHAPE_DECAY_LAMBDA = 0.92

# Share of passages allowed a first-person-SINGULAR persona (2026-08-29).
#
# The persona library is 6/20 = 30% singular-I, and the sampler sits exactly on
# that rate corpus-wide (22 of 74). So this was never a sampling bug — it is a
# library-composition choice, and the choice was out of calibration: measured
# against 129 real CAT/XAT/GMAT passages, an authorial "I" appears in 6% of
# them. Ours: 6 of the 9 shipped 08-24..08-28, which is 11x the exam rate and
# reads as one recurring narrator no matter how much the topic changes.
#
# Not driven to 6%. The house style is deliberately more literary than the exam
# (see the 2026-08-26 decision to keep elite on the literary families), and a
# first-person essayist is a legitimate register — it just cannot be the
# default one. 30% -> 20% keeps it available and stops it being the voice.
#
# Enforced as one coin flip per skeleton, the same way EXAM_FORM_MAX_SHARE is:
# the realised share otherwise drifts above the ceiling because downstream
# rejections do not fall evenly across personas.
FIRST_PERSON_MAX_SHARE = 0.20


# Hard ceiling on how much of the corpus may take an exam-derived expository
# form (2026-08-25).
#
# Those six families were derived by clustering 124 real CAT/XAT/GMAT passages,
# and left to the decay weighting alone they took 71% of medium draws and 52% of
# hard — brand-new components with no usage history always dominate at first.
# That would make our passages read like the exam corpus, which is NOT the
# target: this engine deliberately sets above exam level. They are a variety
# valve, not a template.
#
# Enforced exactly rather than tuned: the sampler rescales their aggregate
# weight so their draw probability cannot exceed the share below. Elite is 0 —
# see tier_max on the families themselves, which excludes them outright.
EXAM_FORM_MAX_SHARE = {"medium": 0.50, "hard": 0.35, "elite": 0.0}

# Arc shapes that came from the exam corpus rather than from our own design.
EXAM_DERIVED_SHAPES = {
    "expository_bound", "surveyed_account", "definitional_process",
    "traced_development", "posed_problem", "asymmetry_noted",
}
SHAPE_DECAY_WINDOW = 20

# Q1 replacement for families that state no thesis (2026-08-22).
#
# Q1 is the thesis/main-idea slot in all 24 topologies and is hardcoded as such
# in QUESTION_SYSTEM. Four of the arc-shape families withhold a position by
# design — parallel accounts never reconciled, a sequence with no evaluative
# paragraph, six unarbitrated witnesses, an inventory with no ranking. Asking
# "which best captures the central idea" of those produces a key that is
# arguable rather than correct.
#
# primary_purpose keeps a strong integrating opener — it still requires holding
# the whole passage — but asks what the passage is DOING rather than what it
# claims, which is answerable from a text that claims nothing.
NO_THESIS_Q1_SLOT = "primary_purpose"

# ---------------------------------------------------------------------------
# Seed genre + topic shape (2026-08-22)
# ---------------------------------------------------------------------------
# The topic layer was the last place the house voice was living. See
# rc_engine/seed_classify.py for the evidence; in short, every feed was one
# genre and the refine schema made every topic bipolar.
SEED_GENRES = {
    "conceptual_essay", "narrative_history", "technical_explainer", "reportage",
    "investigation", "criticism", "biography", "practice_account", "analysis",
    "legal_analysis", "unknown",
}

# Trailing share above which a genre is rotated past rather than used. Set
# loosely on purpose: with 25 of 34 feeds still idea-essays, a tight cap would
# reject most seeds and starve the batch. Tighten as the widened feeds land.
# Raised 0.45 -> 0.60 on 2026-08-25. At 0.45 the cap blocked an entire hard
# tier: conceptual_essay sat at 55% of 11 keyed sets, so every hard seed was
# rotated and three attempts died. With a keyed corpus this small one extra
# essay swings the share nine points, and 25 of the 34 RAG feeds are still
# idea-essays, so most seeds classify that way regardless. This is a ceiling
# for catching genuine monoculture, not a quota — tighten it once the widened
# feeds have shifted the pool.
SEED_GENRE_SATURATION = 0.60
SEED_GENRE_WINDOW = 20
SEED_GENRE_MIN_CORPUS = 10      # below this a share means nothing
SEED_CLASSIFY_MAX_USD = 0.02
MAX_SEED_ROTATIONS = 3          # never spin forever looking for a rare genre

# Which STORE kinds tend to produce which classified seed GENRE (2026-08-29).
#
# The store's `kind` is the feed's content type; the classifier's `genre` is a
# read of the essay itself. They are related but not identical, so a saturated
# genre is rotated away from by avoiding the kinds that generate it.
#
# Needed because rotation was a uniform redraw: on 2026-08-29 a batch of five
# lost both hard slots and the elite slot to `rejected_seed_genre`, all three
# exhausting MAX_SEED_ROTATIONS, because conceptual_essay sat at 61.5% of the
# trailing window and 41.5% of the unused pool is idea_essay. The pool was
# never the problem — 866 unused seeds across 8 kinds — the rotation simply
# could not see kind, since `kind` was defined on FEEDS but never written into
# document metadata at ingest.
GENRE_SOURCE_KINDS = {
    "conceptual_essay": ["idea_essay"],
    "criticism": ["criticism"],
    "reportage": ["reportage"],
    "technical": ["technical_explainer"],
}

# Seed-ANCESTRY pre-screen (2026-08-28, $0 — local embeddings only).
#
# The existing pre-screen compares a candidate seed against shipped PASSAGES.
# That misses the case where two different seeds sit in the same territory and
# the refine stage independently walks them to the same place:
#
#   RC-ELITE-260822-0062  seed: New Atlantis "AI's Builders Are Arrogant and
#                         Afraid"  -> chatbots built in the likeness of the dead
#   RC-HARD-260828-0067   seed: Noema "AI's Greatest Gift To Humanity"
#                         -> a parish prayer board scanned into a livestream chat
#
# Different family, different stance, different topic shape — and the screen
# still called them the same essay. The passages are not close in embedding
# space (a parish board is not a chatbot); their SEEDS are. So compare seed to
# seed as well, using embeddings already in the store.
#
# Deliberately looser than SEED_PRESCREEN_COSINE: two seeds from the same
# fortnight of AI commentary are genuinely close without being the same piece,
# and this fires before anything is spent, so a false rotation costs nothing.
# Calibrated from 946 seed pairs across the 44 most recent distinct seeds:
#   median 0.537   p90 0.634   p95 0.658   p99 0.719   max 0.870
# 0.75 sits just above p99, rotating ~0.7% of pairs. The pair that motivated
# this (RC-HARD-260828-0067 / RC-ELITE-260822-0062, both AI-ethics essays) is
# 0.764 and is caught. My first guess of 0.86 was set by feel and would have
# missed it — the same mistake as the first move-signature cap.
SEED_ANCESTRY_COSINE = 0.75
SEED_ANCESTRY_WINDOW = 12

# ---------------------------------------------------------------------------
# Similarity screen (2026-08-22) — the last gate, and the only one that reads
# ---------------------------------------------------------------------------
# Runs after generation and before export: a cheap model reads each new passage
# beside the last N shipped ones and says whether a person would notice the
# repetition. Green exports normally; red exports to FLAGGED_EXPORT_DIR instead.
# It routes — it never blocks, deletes, or rewrites.
#
# Pinned to its own provider and model on purpose, independent of --provider.
# Asking the model that wrote the passage whether the passage is repetitive is
# asking the judgement that produced the sameness to notice the sameness.
#
# Priced on the cheap tier because it reads WHOLE passages: ~10 x 550 words plus
# the candidate is roughly 8k input tokens per set, which is under a cent on
# gpt-5.6-luna ($0.20/$1.20 per MTok) and would not be on an Opus-class model.
SIMILARITY_SCREEN = {
    "provider": "openai",
    "model": "gpt-5.6-luna",
    "compare_n": 10,
    "max_tokens": 1200,     # reasoning models spend this before emitting JSON
    "max_usd": 0.05,        # per set; the whole screen is far under this
}

# Red sets land here instead of the normal export directory. Separate folder
# rather than a status flag so the split is visible in the filesystem, the way
# the exports are actually reviewed.
FLAGGED_EXPORT_DIR = "exported_rc_sets/flagged_similar"
# Where `export` moves a copy it has superseded (2026-09-14 review): the same set
# in the other folder after its screen verdict changed. Moved, never deleted, and
# outside the client deliverables. Found 7 such pairs, green in one folder and
# red in the other.
EXPORT_SUPERSEDED_DIR = os.environ.get(
    "RC_ENGINE_EXPORT_SUPERSEDED_DIR", os.path.expanduser(r"~\rc_data\export_superseded"))

# ---------------------------------------------------------------------------
# Per-stage model pinning (2026-08-22)
# ---------------------------------------------------------------------------
# A stage listed here runs on its own provider/model regardless of --provider.
# Only cheap CHECKING stages belong here — never refine, render, or questions,
# which is where output quality actually comes from.
#
# Measured share of an elite set before this change: questions 53%, render 18%,
# refine 10%, solver 8%, then judge 5% / compliance 4% / move_signature 2%.
# Those last three are pure reading and classification, they run on every
# attempt including rejected ones, and gpt-5.6-luna ($0.20/$1.20) prices them at
# roughly a fifth of claude-haiku-4-5 ($1/$5) — about $0.016 off every set and
# $0.008 off every wasted attempt.
#
# A value is either (provider, model) for every tier, or {tier: (provider,
# model)} to pin only some tiers. resolve_stage_pin() below normalises both.
#
# FALLBACK IS MANDATORY, NOT OPTIONAL. If the pinned provider has no key or its
# SDK is not installed, the stage silently reverts to the active provider's
# model for that role. A pin is an optimisation; it must never be able to stop
# a batch that would otherwise run.
# (The table itself is defined above set_provider(), which needs it at import.)

# ---------------------------------------------------------------------------
# Rhetorical move vocabulary (2026-08-21)
# ---------------------------------------------------------------------------
# Why this exists: RC-ELITE-260712-0028 (an oboist retuning mid-concert) and
# RC_E_0706_1 (a grandmaster explaining a knight sacrifice) read as the same
# passage to a human, while scoring maximally novel on EVERY existing channel —
# different personas (P01/P03), zero movement-token overlap, near-inverted
# commitment curves, 5 vs 4 paragraphs, para-length stdev 37.6 vs 89.7.
#
# What they actually share is a sequence of rhetorical OPERATIONS:
#   scene -> two-camp split -> disclaim/restate -> instance survey ->
#   staccato triad -> easy reading demolished -> level relocation ->
#   both-sides refused -> hedged aphorism
#
# Nothing in the engine measured that layer. movement_string is the blueprint
# echoed back by an auditor that was shown the blueprint; rhythm_vector is
# punctuation and sentence-length statistics; stylometry is function words.
# All three can differ wildly while the prose performs an identical argument.
#
# The vocabulary is CLOSED on purpose — an open-ended description per passage
# would never align well enough between two passages to compare. Labels are
# operations, not topics, and are grouped by where they typically land.
RHETORICAL_MOVES = {
    # --- openings ---
    "SCENE_PARTICULAR": "opens on a concrete scene or a practitioner performing a small specific act",
    "ABSTRACT_CLAIM_OPEN": "opens on a general proposition stated in the abstract",
    "QUESTION_POSED": "opens by putting a question to the reader or to the field",
    "HISTORICAL_ORIGIN": "opens by dating or attributing where an idea or practice came from",
    "DEFINITION_STAKED": "opens by fixing what a term will mean here",
    # --- middles ---
    "TWO_CAMP_SPLIT": "stages two named factions or schools taking opposite views of the same thing",
    "DISCLAIM_RESTATE": "denies a strong reading of its own claim, then restates it ('not X; rather Y')",
    "INSTANCE_SURVEY": "sweeps several examples, jurisdictions, or cases in quick succession",
    "STACCATO_TRIAD": "three or more consecutive very short declarative sentences used for cadence",
    "CONCESSION_GRANTED": "grants the opposing point at something close to face value",
    "EASY_READING_DEMOLISHED": "names the obvious or tempting interpretation and dismisses it as a mistake",
    "LEVEL_RELOCATION": "argues the parties are not disagreeing about what they think they are — the dispute AS POSED is misconceived, and the passage relocates it. Not merely naming a deeper cause; the question itself must be reframed",
    "AUTHORITY_QUOTED": "brings in an outside voice or document — a real and checkable source, an unnamed-but-described practitioner, or a document the passage characterises. NOT an invented scholar or fabricated study (see the render contract's no-fabricated-scholarship rule)",
    "GENEALOGY_TRACED": "follows a term or practice as it migrates across domains or eras",
    "COUNTEREXAMPLE_PRESSED": "presses one specific case against the general claim",
    "SELF_CORRECTION": "visibly re-steers mid-argument, correcting what it just said",
    "ANALOGY_EXTENDED": "carries a single analogy across several sentences",
    "MECHANISM_EXPLAINED": "explains step by step how the thing actually works",
    "UNDERLYING_CAUSE_NAMED": "identifies a deeper cause behind a surface phenomenon while leaving the question as posed intact (the mild, common form that LEVEL_RELOCATION is not)",
    "STAKES_RAISED": "argues the matter now matters more, or to more parties, than it used to",
    "SYMMETRY_BROKEN": "shows two things treated as parallel are not in fact parallel",
    # --- closings ---
    "BOTHSIDES_REFUSED": "anticipates the split-the-difference verdict and explicitly rejects it",
    "CONCESSION_COSTED": "settles for one side while naming precisely what that costs",
    "HEDGED_APHORISM": "closes on a quotable freestanding maxim, usually carrying a hedge",
    "BOUND_CONTINUATION": "closes on a sentence still tied to the paragraph's ongoing argument",
    "QUESTION_LEFT_OPEN": "closes by reformulating the question rather than answering it",
    "CONCRETE_RETURN": "closes by returning to a specific particular or named case",
}

# Where each move naturally sits in a passage. The composer builds a move plan
# as one opening + several middles + one closing so the prescribed arc is
# coherent; without the grouping, inverse-frequency sampling happily puts
# QUESTION_LEFT_OPEN first and HISTORICAL_ORIGIN last.
MOVE_GROUPS = {
    "opening": ["SCENE_PARTICULAR", "ABSTRACT_CLAIM_OPEN", "QUESTION_POSED",
                "HISTORICAL_ORIGIN", "DEFINITION_STAKED"],
    "middle": ["TWO_CAMP_SPLIT", "DISCLAIM_RESTATE", "INSTANCE_SURVEY",
               "STACCATO_TRIAD", "CONCESSION_GRANTED", "EASY_READING_DEMOLISHED",
               "LEVEL_RELOCATION", "AUTHORITY_QUOTED", "GENEALOGY_TRACED",
               "COUNTEREXAMPLE_PRESSED", "SELF_CORRECTION", "ANALOGY_EXTENDED",
               "MECHANISM_EXPLAINED", "STAKES_RAISED", "SYMMETRY_BROKEN",
               "UNDERLYING_CAUSE_NAMED"],
    "closing": ["BOTHSIDES_REFUSED", "CONCESSION_COSTED", "HEDGED_APHORISM",
                "BOUND_CONTINUATION", "QUESTION_LEFT_OPEN", "CONCRETE_RETURN"],
}

# How many moves a prescribed plan contains (inclusive), including the opening
# and closing.
#
# Was (5, 7). Raised 2026-08-22 after the first prescriptive batch: the two
# shipped sets realized 10 moves each against plans of 6 and 7, hit only 3/6 and
# 4/7 of the planned beats, and filled every leftover slot with the house spine
# — LEVEL_RELOCATION, EASY_READING_DEMOLISHED and MECHANISM_EXPLAINED all
# appeared in both, planned in neither. A plan shorter than the passage leaves
# gaps, and the gaps default to the voice we are trying to move.
#
# Sizing to the observed length closes them without adding a single
# prohibition, which is the point — the ban-list build failed precisely because
# prohibitions get ignored.
MOVE_PLAN_LEN = (8, 10)

# Per-tier plan length and the density floor that bounds it (2026-09-05).
#
# Measured against 12 of the densest RC125 passages: a real hard exam passage
# performs about 7.8 rhetorical moves over 4.3 paragraphs, giving each move
# roughly 62 words. Ours performed 10.2 in the same length -- 52 words a move,
# about 20% MORE crowded than the exam. That crowding is why the renderer keeps
# only ~51% of its planned middle beats and fills the rest with the same four
# habits: at 52 words a beat the instruction is too dense to execute, so it
# reaches for what it can produce without thinking.
#
# The sampling ran against the LONGEST exam passages, which carry more beats
# than typical, so 62 is if anything a generous floor.
#
# Beats also become a tier lever here, which they were not before: realised
# counts were flat at medium 10.3 / hard 9.6 / elite 10.8. More distinct
# operations in the same space is a real reading load and gives the question
# stage more structural targets. NOTE this is a hypothesis, not a measured
# effect -- move count correlates with judge score at r=+0.09, so the judge
# will not confirm it either way.
#
# Every tier lands at or above exam density; elite merely matches it.
#   medium 6-7 beats -> ~78 words each
#   hard   7-8       -> ~70
#   elite  8         -> ~66  (the densest the floor permits)
# Upper bounds are set so the DENSITY FLOOR below never has to clamp them: at
# 525 words, 9 beats is 58 words each, under the 62 floor. An earlier draft
# wrote (8, 9) for elite and the cap silently reduced every draw to 8 — a
# declared range that could not occur. The ranges here are what actually
# happens.
MOVE_PLAN_LEN_BY_TIER = {
    "medium": (6, 7),   # ~75-87 words a beat
    "hard": (7, 8),     # ~66-75
    "elite": (8, 8),    # ~66, the densest the floor allows
}
# Hard floor on words per beat. A plan that would crowd past this is trimmed
# rather than issued: the exam never goes below it, and below it the renderer
# stops writing and starts coping. The visible symptom is signposting -- prose
# that narrates its own scaffolding ("the first step", "having argued"), which
# question_engine.texture_report already scans for free on every render. That
# rate (~4 warnings in ~20 sets before this change) is the canary: if it climbs,
# the plan is too dense and this floor should go UP.
MIN_WORDS_PER_BEAT = 62
# A paragraph shorter than this carries at most one beat, so an S-class
# paragraph (30-60 words) is never asked to perform three operations.
SINGLE_BEAT_PARA_WORDS = 60

# Inverse-frequency sampling strength. weight = (1 - trailing_share) ** this.
#
# This is a FEEDBACK LOOP, not a fixed policy: a move's weight falls as its
# realized share rises, so the system converges on a roughly uniform move
# distribution rather than on whatever the exponent says today. That is the
# same target `health` already uses for families (KL vs design uniform).
#
# Expect a transient. Measured at composition time against the 2026-08 corpus,
# LEVEL_RELOCATION drops from a 97% realized share to a 1% planned share while
# ANALOGY_EXTENDED rises from 3% to ~43% — so the next dozen sets will lean on
# the moves the old corpus never used, which is its own tell until the shares
# even out. Raising the exponent does not fix that (0.75 through 2.0 all land
# the rarest move between 40% and 53%): the driver is that a plan draws 3-5 of
# 15 middle moves, so anything favoured clears 25% by construction. Watch
# `health` move saturation over the next 20 sets rather than re-tuning early.
MOVE_PLAN_RARITY_POWER = 1.0

# Share of the plan that must be realized for the move-plan half of compliance
# to count as satisfied. Not 1.0: the extractor reads the prose blind and will
# not always name a move the writer did perform, so demanding every beat would
# make this a permanent failure.
MOVE_PLAN_MIN_REALIZED = 0.6

# Middle-beat discipline (2026-09-01).
#
# The first and last beat have been position-enforced since 2026-08-29, and it
# worked: openings went 2/9 -> 5/5 -> 3/3, and endings stopped landing on a
# named physical object (5/5 -> 0/3). The MIDDLE was never checked, and that is
# where the house voice actually lives. Measured over the 13 sets of
# 08-29..09-01: planned middle beats are retained only 43% of the time, and the
# passage substitutes the same handful in most sets regardless of which family
# was assigned — EASY_READING_DEMOLISHED unplanned in 10 of 13, CONCESSION_GRANTED
# in 8. That is the concede-then-pivot spine arriving on its own.
#
# beat_score alone could not catch it: it is computed over the WHOLE plan, so
# now that the two endpoints land reliably they prop the score up while the
# middle rots. A plan of 8 with both ends landing and 4 of 6 middle beats lost
# still scores 0.75 and never fires.
MOVE_PLAN_MIN_MIDDLE_RETAINED = 0.6

# Share of the 124 real CAT/XAT/GMAT passages that perform each move, from the
# blind extraction run on 2026-08-26. Only moves above 15% are listed; anything
# absent is rarer than that in real exam prose.
#
# Used to tell ORDINARY connective moves from DISTINCTIVE ones. A passage adding
# an unplanned MECHANISM_EXPLAINED is doing what 91% of exam passages do and is
# not worth a directive; a passage adding an unplanned EASY_READING_DEMOLISHED
# is reaching for a rhetorical gesture it was not given, and that gesture is one
# of the two the corpus over-produces.
EXAM_MOVE_SHARES = {
    "MECHANISM_EXPLAINED": 0.91,
    "BOUND_CONTINUATION": 0.81,
    "ABSTRACT_CLAIM_OPEN": 0.77,
    "AUTHORITY_QUOTED": 0.53,
    "UNDERLYING_CAUSE_NAMED": 0.52,
    "INSTANCE_SURVEY": 0.49,
    "EASY_READING_DEMOLISHED": 0.41,
    "STAKES_RAISED": 0.41,
    "CONCESSION_GRANTED": 0.33,
    "SYMMETRY_BROKEN": 0.27,
    "TWO_CAMP_SPLIT": 0.21,
    "COUNTEREXAMPLE_PRESSED": 0.19,
    "GENEALOGY_TRACED": 0.16,
    "QUESTION_POSED": 0.15,
}
# An unplanned move at or above this exam share is ordinary connective tissue and
# is not flagged; below it, the passage reached for something distinctive it was
# not asked to perform. 0.50 keeps MECHANISM_EXPLAINED and UNDERLYING_CAUSE_NAMED
# free while catching EASY_READING_DEMOLISHED and CONCESSION_GRANTED, which are
# the two the measurement actually implicates.
UNPLANNED_MOVE_EXAM_FLOOR = 0.50

# Free pre-render check on the PLANNED move signature (2026-08-22).
#
# 150 of 205 blueprints ever composed died at a novelty gate, and every one of
# them had already paid for refine + render (~$0.05 on an elite set) by the time
# it was rejected. Now that the composer PLANS the rhetorical grammar, a
# collision on that grammar is knowable before any of that is spent: score the
# plan against the corpus with the same function Gate B uses, and recompose for
# $0 instead of rejecting for $0.05. This session alone Gate B rejected paid
# renders on move_signature at 0.70, 0.76 and 0.63.
#
# Set slightly BELOW the Gate B cap on purpose. The realized signature is longer
# and richer than the plan, so a plan that already scores near the cap will
# almost certainly breach it once rendered; leaving a margin catches those too.
# It is a precheck, not a second gate — the plan is a subset of what gets
# written, so a plan that passes here can still be rejected later.
MOVE_PLAN_PRECHECK_CAP = 0.55
MOVE_PLAN_PRECHECK_TRIES = 4

# Move-signature novelty cap. Checked against the WHOLE window, not just the
# recent slice the movement_* channels use: recycling a movement token after an
# exclusion window is deliberate composer policy, but repeating a rhetorical
# grammar is a defect at any distance.
#
# Calibrated from `move-audit` over 85 sets / 3570 pairs (2026-08-21):
#   p50=0.32  p90=0.47  p95=0.51  p99=0.61  max=0.73
# 0.62 sits just above p99, so it catches genuine near-duplicates and costs
# almost no false positives.
#
# READ THIS BEFORE TIGHTENING IT. The pair that motivated the whole channel —
# RC-ELITE-260712-0028 (oboist) vs RC_E_0706_1 (grandmaster), which a human
# instantly called "almost identical" — scores 0.31, the 53rd percentile. It is
# a MEDIAN pair, not an outlier. Half the corpus is that similar to itself.
# A pairwise gate therefore cannot be the primary instrument here: set it low
# enough to catch the median and it rejects everything; set it where it does
# not, and it leaves the sameness untouched. It is a backstop for true
# duplicates. The primary instrument is MOVE_SATURATION_* below.
MOVE_SIGNATURE_CAPS = {
    # 0.62 (p99 of the old corpus) was measured against a corpus, not against
    # live renders. First real batch under the saturation bans: the two sets
    # that SHIPPED scored 0.60 and 0.58 against their nearest neighbour — i.e.
    # the cap sat inside the normal working range, fired on roughly half of all
    # renders, and pushed an elite RC into budget_abort at $0.42 after paying
    # for a re-render it did not need.
    #
    # 0.68 keeps the backstop (corpus max is 0.73, and a literal duplicate
    # scores 1.00) while leaving the day-to-day work to MOVE_SATURATION_BAN.
    # That division of labour is the whole point: the pairwise gate catches
    # duplicates, the saturation bans move the distribution.
    "move_signature_sim": 0.68,
}

# ---------------------------------------------------------------------------
# Move saturation — the corpus-level instrument (2026-08-21)
# ---------------------------------------------------------------------------
# What the first move-audit found, over 85 shipped sets spanning every tier and
# all three sources (engine / legacy / manual):
#
#   LEVEL_RELOCATION         82/85   96%
#   EASY_READING_DEMOLISHED  73/85   86%
#   MECHANISM_EXPLAINED      62/85   73%
#   CONCESSION_GRANTED       50/85   59%
#   ...
#   ANALOGY_EXTENDED          4/85    5%
#
# Nearly every passage in the corpus performs the same core operation — "the
# real dispute sits at a deeper level than it appears", set up by "the obvious
# reading is wrong". That spine, not any pair of passages, is the house voice.
#
# So the fix is rationing at compose time, not rejection at gate time: a move
# whose trailing share is above MOVE_SATURATION_BAN gets named in the render
# contract as forbidden for this passage. Driving LEVEL_RELOCATION from 96%
# toward its fair share diversifies the corpus globally, which no pairwise
# threshold can do.
MOVE_SATURATION_BAN = 0.55     # trailing share above this -> banned in new contracts
MOVE_SATURATION_WARN = 0.40    # above this -> reported by `health`
MOVE_SATURATION_WINDOW = 30    # trailing sets the share is computed over
MOVE_SATURATION_MAX_BANS = 4   # never hand the renderer more than this many at once

# Global house-voice pressure (2026-09-12). Every lever above is per client, so
# a new client starts fresh — but the engine has one voice, and a student or a
# faculty member who sees two institutes' mocks would still hear it. So the
# components and moves recently given to OTHER clients get a gentle pull-away
# on top of the per-client terms:
#   component weight *= GLOBAL_DECAY_LAMBDA ** uses_by_other_clients (trailing)
#   move weight      *= (1 - share_among_other_clients) ** GLOBAL_MOVE_RARITY_POWER
# Softer than the per-client terms by design (0.85 vs DECAY_LAMBDA 0.5; power
# 0.5 vs MOVE_PLAN_RARITY_POWER 1.0): a client's own recency decides, the
# global term only tilts the draw.
#
# With one client, "other clients" is empty, every factor is exactly 1.0 and
# the founding client's draws are bit-for-bit what they were (checked
# 2026-09-12 with a seeded composer snapshot on a copy of the production DB).
# These values are starting points, not calibrated: re-measure with
# `health --all` once a second client has shipped ~30 sets.
GLOBAL_DECAY_LAMBDA = 0.85
GLOBAL_USAGE_WINDOW = 50       # other clients' trailing shipped blueprints, pooled
GLOBAL_MOVE_WINDOW = 60        # other clients' trailing keyed fingerprints, pooled
GLOBAL_MOVE_RARITY_POWER = 0.5


# 2026-08-21 rebalance: blueprint 0.20->0.14 and movement 0.18->0.10, with the
# freed weight going to move_signature. Rationale in RHETORICAL_MOVES above —
# `movement` is largely the blueprint measured twice (the compliance auditor is
# handed the plan and asked to echo the planned token back), so between them
# they were spending 0.38 of the composite on one plan-shaped signal while the
# prose's own argumentative shape carried none.
# Where each closing posture should leave the commitment curve (2026-09-01).
#
# The curve was PURELY EMERGENT: compliance measured it, novelty weighted it at
# 0.14 -- the largest single channel -- and no stage ever targeted it. Measured
# across 74 real curves, the planned posture moved the realised endpoint by a
# spread of only 0.20, and refusal_suspended (which is supposed to end
# unresolved) had a MEDIAN endpoint of 0.93. Third instance of the same bug:
# a lever assigned, instructed, and audited only on its LABEL.
#
# Bands are read off each posture's own definition in families.json, not
# invented: the postures that "END by committing" sit high, the ones that
# suspend or dissolve sit low. They are bands, not targets -- the point is to
# stop every passage terminating in the same place, not to pin them all to a
# new one.
#
# NOTE: these are only meaningful alongside the 2026-09-01 change to the
# commitment definition in compliance.py (measure against the OPENING QUESTION,
# not against wherever the passage ends). Curves recorded before that date were
# scored under the older, ambiguous wording and read systematically higher at
# the endpoint; comparisons across the boundary overstate novelty rather than
# understate it, so they let sets through rather than blocking them.
POSTURE_END_COMMITMENT = {
    "resolution_qualified":  (0.70, 1.00),
    "resolution_costed":     (0.70, 1.00),
    "affirmation_endorsed":  (0.75, 1.00),
    "reframe_displace":      (0.50, 0.90),
    "refusal_dissolved":     (-0.20, 0.45),
    "refusal_suspended":     (-0.30, 0.40),
}
# How far outside its band a realised endpoint may sit before it counts as a
# compliance miss. Generous: the classifier reads prose, not a dial.
POSTURE_END_TOLERANCE = 0.15

COMPOSITE_WEIGHTS = {
    "blueprint": 0.14,
    "movement": 0.10,
    "move_signature": 0.16,
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
#
# 2026-07-26: the comparison pool is now SHIPPED blueprints only (it used to
# include 'composed' and both rejected_* states). With 17 of 91 blueprints
# shipped, ~80% of the old pool was topics no customer ever saw, and a
# rejection permanently blocked its own neighbourhood — one rejected topic
# seeds a re-refine on an adjacent topic, that gets rejected too, and the pair
# then blocks everything nearby. Replaying all 91 blueprints chronologically:
# 47/91 blocked under the old pool vs 33/91 shipped-only, and one of the 14
# freed blueprints had actually SHIPPED. Rejected topics keep steering the
# refine prompt for free via history.recent_topics() — they just stop being a
# hard blocker. (This also defuses _fallback_refine's formulaic
# "a live conceptual tension in {domain}" topic, which collides at ~1.0 with
# any other fallback blueprint.)
#
# Thresholds recalibrated 2026-07-26 against the real corpus, because the pool
# fix alone still left 78 of 91 blueprints blocked. Measured max-cosine
# distributions showed both caps sitting AT OR BELOW the median of the
# population they filter — 0.768 median on the passage channel vs a 0.75 cap.
# A filter set below its own median is a blanket block, not a filter. Measured
# against the 17 blueprints that actually SHIPPED (judge 8.4-8.8), the old caps
# would have blocked 29% of them on the passage channel and 24% on the topic
# channel, pre-render, for nothing.
#
#   threshold  % of SHIPPED sets wrongly blocked
#              topic ch.   passage ch.
#     0.75       35%          29%
#     0.80       24%          12%
#     0.82       24%           0%
#     0.88       18%           0%
#
# The passage cap is the cross-granularity one — a short topic doc (topic +
# two axes + paragraph gists) against a full 500-word passage embedding. Two
# serious essays in the same house register score high on that regardless of
# topic, so it needs a HIGHER cap than the same-granularity comparison, not a
# lower one. 0.82 is the lowest value with no observed false positive.
#
# The precheck must stay strictly MORE permissive than the gates downstream of
# it. It buys nothing but an earlier (cheaper) rejection: Gate B still scores
# embedding_cosine passage-vs-passage at NOVELTY_CAPS 0.80, and Gate C still
# runs after questions. A precheck stricter than the real gate rejects work the
# real gate would have accepted — which is exactly what was happening.
TOPIC_PRECHECK_ENABLED = True
TOPIC_PRECHECK_ENFORCE = True            # enforced: blocks colliding topics pre-render
TOPIC_PRECHECK_COSINE = 0.88             # topic-doc vs prior SHIPPED topic-doc
TOPIC_PRECHECK_PASSAGE_COSINE = 0.82     # topic-doc vs stored passage embedding
# 1, not 2: 16 blueprints paid three refine calls (compose + 2 re-refines) and
# were rejected anyway. One re-refine is the whole value of the retry.
TOPIC_PRECHECK_MAX_REREFINES = 1

# Free pre-render topology clearance: a blueprint whose planned topology signature
# is too close to the corpus is re-picked (local registry shuffle, $0) BEFORE any
# paid render — otherwise a topology collision is only caught at Gate C, after the
# Opus questions call has already been paid for (~$0.15 wasted).
TOPOLOGY_PRECHECK_ENABLED = True
TOPOLOGY_PRECHECK_MAX_REPICKS = 5

# Free pre-render movement clearance: planned paragraph-function sequence is
# compared to the recent fingerprint window with the same NOVELTY_CAPS as Gate B.
# Identical / near-identical movement is a family-level skeleton collision —
# seed rotation alone cannot fix it. On hit we ban the movement string (and the
# family only once ALL its movement strings are gone) and recompose (refine
# only, no render) before any Opus passage call. Gate-B movement rejects also
# accumulate into the same ban sets for the batch recompose loop so a second
# paid render never re-uses the same skeleton.
MOVEMENT_PRECHECK_ENABLED = True
MOVEMENT_PRECHECK_MAX_RECOMPOSES = 3   # local recompose attempts inside generate_one

# How far back the movement channel looks — in the free precheck AND in Gate B,
# which must use the same number or the precheck stops being a precheck (a
# candidate would clear the free gate, get rendered, then be rejected on the
# same channel against an older set). Deliberately EXCLUSION_WINDOWS["family"]:
# the composer is allowed to reuse a family once that many sets have passed, and
# rhythm only pads a family's function sequence, so a recycled family
# necessarily reproduces one of its 3-5 movement strings. Scoring against the
# whole corpus therefore made the composer's own recycling policy unreachable —
# by 31 shipped sets it had blocked ~87% of the library's movement space and
# every hard-tier attempt on 2026-08-10 died here. Scoped to 25 the clear-rate
# goes 11% -> 29%.
#
# This mirrors the topology channel, which novelty.py already scopes to the
# recent corpus for exactly this reason; the two policies now agree. If
# EXCLUSION_WINDOWS["family"] changes, this follows it.
MOVEMENT_RECENCY_WINDOW = EXCLUSION_WINDOWS["family"]

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

# The first ten are LLM register tells. The rest are architecture signposts,
# added 2026-08-22: phrases whose only job is to announce the passage's own
# argumentative structure. They go here rather than staying advice in the render
# prompt because this list is genuinely ENFORCED — the compliance auditor
# reports forbidden_tics_found, which caps f1 at 0.5 and produces a targeted
# re-render directive. Prompt-level requests have repeatedly been ignored this
# month; audited ones have not.
#
# Keep only fixed phrases here. "the deeper issue" is checkable; "signposting in
# general" is not, and belongs in the render prompt's HARD RULES where it is.
GLOBAL_FORBIDDEN_TICS = [
    "furthermore", "moreover", "in conclusion", "it is a testament",
    "tapestry", "delve", "paradigm shift", "navigate the complexities",
    "underscores", "multifaceted",
    "the deeper issue", "the real point", "the deeper question",
    "this raises the question", "the question then becomes",
    "the first objection", "what remains is", "it is worth pausing",
    "which brings us to", "to put it another way",
    # Added 2026-08-22: this one came from our OWN prompt, which offered it as
    # an example of a midstream re-steer. Four passages copied it verbatim.
    # The example is gone from renderer.py; this makes the phrase auditable so
    # a re-render is triggered if it reappears.
    "no: more precisely",
]
