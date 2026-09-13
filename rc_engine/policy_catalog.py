"""Production generation policies. Registered at import by generation_policy.

A version's content is FIXED once any plan can carry it: a stored blueprint
resumes under the policy it names, so editing a registered version would
reinterpret plans already written. Change means a new version appended here.
Registering is not enabling — see config.GENERATION_POLICY_FOR_NEW_PLANS.

cat-pyq-q1 (2026-09-13) — section 4 of 2026-09-13-cat-pyq-implementation-plan.md,
the question release, for medium and hard only.

  Negation. Two negative slots per set on both tiers, single negation only,
  pre-existing EXCEPT slots counted. Evidence: 35.6% of PYQ stems are negated
  (41.5% in 2020-24) against ~7% of shipped engine stems
  (2026-09-13-cat-pyq-baseline.md). Two of eight is 25% — a working objective,
  not a CAT constant, and deliberately below the PYQ rate for a first release.
  Only the support and application negatives are released (plan 4.1 staging).

  New types. author_would_endorse (6.4% of PYQ stems, none in the engine) and
  keyword_set with keyword and sequence variants (2.8%, none), reachable through
  the tagged topologies QT25 and QT26. Their stem forms are new paraphrased
  templates, not PYQ text.

  New stem variants for existing types: word purpose, tone of a quoted
  sentence, where a reported party and the author disagree, similarity and
  difference, sense of a quoted sentence. Quoted material in any stem must be an
  exact passage span (checked deterministically).

  Nothing here touches passage structure, rendering, families or beats; those
  are section 5 and will be a new version.
"""
from __future__ import annotations

from .generation_policy import GenerationPolicy, _ro

CAT_PYQ_Q1 = "cat-pyq-q1"

_KEYWORD_FORMS = [
    "Which one of the following sets of keywords best captures the argument of the passage?",
    "Which one of the following sets of terms most closely maps the central concerns of the passage?",
    "Which set of keywords below comes closest to capturing the main arguments of the passage?",
]
_SEQUENCE_FORMS = [
    "Which one of the following sequences of words and phrases best captures the flow of the passage?",
    "Which one of the following best represents the order in which the passage develops its argument?",
    "Which sequence of ideas below most accurately traces the progression of the passage?",
]

_QUESTIONS_SYSTEM = """QUESTION CONTRACTS (this set follows policy cat-pyq-q1):
Every slot in the QUESTION PLAN states its polarity. Read it before writing the stem.

AFFIRMATIVE slots: the key is the option that meets the slot's relation. Do not
put NOT, EXCEPT, "least", "if false" or "none of" in the stem, and never give a
wrong option a contract marker as its mechanism.

NEGATIVE slots: the stem carries exactly ONE negation — NOT or EXCEPT in
capitals, or "least". Never combine two ("if false ... EXCEPT"). The option
contract flips, and the slot line says what each option must establish:
- The THREE non-key options each MEET the stated relation. Give each the slot's
  marker as its mechanism, and a why_wrong that cites where the relation is met
  (the passage location, or the condition of the passage's rule a scenario
  satisfies).
- The KEY fails the relation for one precise reason. Its why_right names that
  failure, and "correct" gains "failure_mode": one of scope | stance | causality
  | level | attribution | degree | contradiction | condition | mechanism.
- "Not mentioned" is never a failure: an option the passage never addresses
  fails nothing. "Not supported" is not the same as "false" — do not write a key
  that is merely absent from the passage, or merely extreme in wording.
- Exactly one option may fail. If a second option also fails on a fair reading,
  the question is broken: rewrite it.

QUOTED MATERIAL: words you put in quotation marks in a stem must be copied
exactly from the passage (shorten with an ellipsis if needed). Paragraph numbers
count the passage's paragraphs from 1 and must exist.

author_would_endorse: the key follows from commitments the author states or
clearly implies — not from what sounds reasonable in general. Wrong options are
positions the author reports but does not hold, positions that overreach the
author's commitment, and attractive views the passage never takes up.

keyword_set: every option is a list of 4-5 items, the same number in all four.
  variant keywords — short terms separated by commas, each at most 4 words;
    wrong sets swap in vivid but peripheral terms or drop a load-bearing one.
  variant sequence — phrases separated by " → ", each at most 6 words, in the
    passage's order; wrong sequences put the right ideas in the wrong order or
    skip a stage.
  Wrong options still name an allowed mechanism (example_promotion, half_truth,
  stage_misattribution, level_confusion, adjacent_answer are the usual fits).

JSON: for a negative slot, "correct" is
  {"text": "...", "why_right": "...", "failure_mode": "<one mode above>"}."""

_ANSWERABILITY_SYSTEM = """NEGATED STEMS (NOT, EXCEPT, least): the question asks for the one
option that FAILS the stated relation. It is unique only if exactly one option
fails; list every option that fails as a contender. For a set of keywords or a
sequence, it is unique only if exactly one set maps the passage's argument (or its
order)."""

_TIEBREAK_SYSTEM = """If the stem is negated (NOT, EXCEPT, least), "supported" means the option
that correctly answers the negated question: the one that fails the stated
relation."""

_SOLVER_SYSTEM = """Some stems are negated (NOT, EXCEPT, least): they ask for the single option
that fails the stated relation. Read each stem's polarity before eliminating."""

_JUDGE_SYSTEM = """Some questions are negated (NOT, EXCEPT, least). Their three non-key options
meet the stated relation and are labelled with a contract marker
(passage_supported, rule_satisfied) instead of a distractor mechanism. Judge those
explanations on whether each cites where the relation is met, and whether the
key's explanation names a precise failure rather than "not mentioned"."""

CAT_PYQ_Q1_POLICY = GenerationPolicy(
    version=CAT_PYQ_Q1,
    tiers=frozenset({"medium", "hard"}),
    description="section 4 question release: polarity contracts, two negative slots, "
                "author_would_endorse, keyword_set, QT25/QT26, new stem variants",
    extra_slot_types=_ro({
        "author_would_endorse":
            "which practice, proposal or view the author would most likely support; "
            "the key follows from the author's stated commitments, not from what "
            "sounds reasonable in general",
        "keyword_set":
            "which set of 4-5 keywords, or which ordered sequence of phrases, best "
            "maps the passage's argument; wrong sets use peripheral terms or the "
            "right terms in the wrong order",
    }),
    extra_stem_forms=_ro({
        "author_would_endorse": [
            "Based on the passage, the author would be most supportive of which one of the following?",
            "Which one of the following proposals is most consistent with the author's position on {X}?",
            "The author would most likely agree with which one of the following statements about {X}?",
            "Which one of the following practices would the author most readily endorse?",
        ],
        # Plain key lists both variants for registry validation; plans always
        # resolve a variant and deal from "keyword_set/<variant>".
        "keyword_set": _KEYWORD_FORMS + _SEQUENCE_FORMS,
        "structural_function": [
            "Why does the author use the word '{X}' in {the specified paragraph}?",
        ],
        "stance": [
            "In the sentence '{quoted sentence}', the author's tone is best described as:",
        ],
        "author_vs_reported": [
            "On which one of the following points would {the reported writer} and the author most likely disagree?",
            "Which one of the following best expresses both a similarity and a difference between {X} and {Y}?",
        ],
        "contextual_inference": [
            "Which one of the following best captures the sense of '{quoted sentence}'?",
        ],
    }),
    question_contracts=True,
    negative_tasks=frozenset({"support", "application"}),
    negative_slots_per_set=_ro({"medium": 2, "hard": 2}),
    keyed_stem_forms=_ro({
        "detail_check/negative": [
            "According to the passage, all of the following are true of {X}, EXCEPT:",
            "Which one of the following claims about {X} is NOT supported by the passage?",
            "The passage describes {X} in all of the following ways, EXCEPT:",
        ],
        "contextual_inference/negative": [
            "All of the following can be inferred from the passage, EXCEPT:",
            "Which one of the following can NOT be inferred from the author's account of {X}?",
            "Based on the passage, each of the following is a reasonable inference about {X}, EXCEPT:",
        ],
        "application/negative": [
            "Each of the following scenarios would fit the author's account of {X}, EXCEPT:",
            "Which one of the following situations does NOT illustrate the mechanism the passage describes?",
            "The principle the author draws from {X} would apply to all of the following cases, EXCEPT:",
        ],
        "keyword_set/keywords": _KEYWORD_FORMS,
        "keyword_set/sequence": _SEQUENCE_FORMS,
    }),
    slot_variants=_ro({"keyword_set": ("keywords", "sequence")}),
    system_extensions=_ro({
        "questions": _QUESTIONS_SYSTEM,
        "answerability": _ANSWERABILITY_SYSTEM,
        "solver_tiebreak": _TIEBREAK_SYSTEM,
        "solver": _SOLVER_SYSTEM,
        "judge": _JUDGE_SYSTEM,
    }),
)

PRODUCTION_POLICIES = (CAT_PYQ_Q1_POLICY,)

# Covers `import rc_engine.policy_catalog` before generation_policy: the
# registration generation_policy attempted at its own import found this module
# incomplete and returned.
from . import generation_policy as _generation_policy  # noqa: E402

_generation_policy._register_catalog()
