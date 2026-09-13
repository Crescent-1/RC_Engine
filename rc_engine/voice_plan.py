"""Compatibility for the prose plan, before any paid refinement.

2026-09-12: the latest eleven passages matched their requested primary schema
once. The schema was absent from refinement, and independently sampled stances
and endings often requested a different essay. These are semantic eligibility
rules, not novelty thresholds or a claim that the distribution is calibrated.
"""

def _ids(prefix, numbers):
    return {f"{prefix}{n:02d}" for n in numbers}


# Material -> reasoning purpose -> compatible family and writing stance.
# Families retain their existing tier, posture, recency and distance rules.
# F30 (self-application) and F37 (unreconciled parallel accounts) have no
# faithful fit among the eight current schemas; their library entries remain.
SCHEMA_FORMS = {
    "S1_INSTRUMENT_BLIND": {
        "topic_shape": _ids("TS", [4, 6, 8, 10, 12]),
        "family": _ids("F", [1, 2, 7, 12, 13, 16, 21, 22, 25, 26, 31,
                               33, 38, 39, 41, 43, 45, 49, 53, 55, 57]),
        "render_stance": _ids("RS", [1, 6, 7, 8]),
        "required_middle": ["COUNTEREXAMPLE_PRESSED"],
    },
    "S2_RECEIVED_ACCOUNT_REPLACED": {
        "topic_shape": _ids("TS", [5, 11, 12, 14]),
        "family": _ids("F", [5, 8, 10, 15, 20, 24, 28, 29, 35, 36, 44,
                               47, 48, 51, 53, 54, 55, 56]),
        "render_stance": _ids("RS", [1, 3, 4, 5, 9]),
        "required_middle": ["MECHANISM_EXPLAINED"],
    },
    "S3_TWO_CAMPS_RELOCATED": {
        "topic_shape": _ids("TS", [1, 8, 10]),
        "family": _ids("F", [4, 6, 13, 14, 18, 19, 23, 25, 27, 43, 45, 52]),
        # The existing ten stances all constrain or forbid one of this
        # schema's defining operations. An explicit schema-led stance below
        # is preferable to silently overriding either instruction.
        "render_stance": set(),
        "required_middle": ["TWO_CAMP_SPLIT", "LEVEL_RELOCATION"],
    },
    "S4_MECHANISM_TRACED": {
        "topic_shape": _ids("TS", [3, 9, 11, 12, 14]),
        "family": _ids("F", [11, 16, 22, 25, 33, 34, 38, 39, 44, 46,
                               47, 49, 50, 51, 52, 56]),
        "render_stance": _ids("RS", [1, 5, 9]),
        "required_middle": ["MECHANISM_EXPLAINED"],
    },
    "S5_PRACTICE_VS_THEORY": {
        "topic_shape": _ids("TS", [4, 7, 9]),
        "family": _ids("F", [2, 8, 10, 12, 16, 20, 24, 31, 33, 38, 39,
                               41, 46, 48, 53]),
        "render_stance": _ids("RS", [1, 5, 7, 9]),
        "required_middle": ["MECHANISM_EXPLAINED"],
    },
    "S6_ORIGIN_AND_DRIFT": {
        "topic_shape": _ids("TS", [2, 4, 5, 9]),
        "family": _ids("F", [9, 14, 17, 26, 27, 29, 34, 38, 39, 40,
                               41, 42, 45, 50, 57]),
        "render_stance": _ids("RS", [2, 7, 9]),
        "required_middle": ["GENEALOGY_TRACED"],
    },
    "S7_CASE_AGAINST_RULE": {
        "topic_shape": _ids("TS", [4, 8, 12, 14]),
        "family": _ids("F", [3, 10, 11, 15, 20, 22, 24, 28, 31, 33,
                               35, 36, 38, 39, 43, 44, 45, 51, 52, 55, 56]),
        "render_stance": _ids("RS", [1, 3, 4, 6, 7]),
        "required_middle": ["COUNTEREXAMPLE_PRESSED"],
    },
    "S8_REMEDIES_WEIGHED": {
        "topic_shape": _ids("TS", [13]),
        "family": _ids("F", [8, 11, 18, 20, 24, 28, 33, 34, 35, 36,
                               43, 44, 46, 48, 51, 58]),
        "render_stance": _ids("RS", [9]),
        "required_middle": ["INSTANCE_SURVEY", "MECHANISM_EXPLAINED"],
    },
}


# Endings can express a gesture without naming a rhetorical closing label.
# The beat and surface register must nevertheless be capable of expressing it.
ENDING_BEATS = {
    **{e: {"QUESTION_LEFT_OPEN", "BOUND_CONTINUATION"}
       for e in _ids("E", [1, 5, 10, 12, 13, 16, 18, 19])},
    "E02": {"CONCRETE_RETURN"},
    "E09": {"CONCESSION_COSTED", "BOUND_CONTINUATION"},
    "E15": {"BOTHSIDES_REFUSED", "BOUND_CONTINUATION"},
}
DEFAULT_ENDING_BEATS = {"BOUND_CONTINUATION", "HEDGED_APHORISM"}
CLOSING_REGISTERS_BY_BEAT = {
    "HEDGED_APHORISM": {"aphoristic"},
    "CONCRETE_RETURN": {"concrete_particular"},
    "BOUND_CONTINUATION": {"bound_continuation", "quiet_qualification"},
    "QUESTION_LEFT_OPEN": {"quiet_qualification"},
    "CONCESSION_COSTED": {"bound_continuation", "quiet_qualification"},
    "BOTHSIDES_REFUSED": {"bound_continuation", "quiet_qualification"},
}

# Supporting operations may develop the chosen argument without quietly
# turning it into a different one. In particular, procedural/historical plans
# should not acquire a rival-camps or easy-reading-demolition spine by lottery.
SUPPORTING_MOVES = {
    "INSTANCE_SURVEY", "AUTHORITY_QUOTED", "COUNTEREXAMPLE_PRESSED",
    "ANALOGY_EXTENDED", "MECHANISM_EXPLAINED", "STAKES_RAISED",
    "SYMMETRY_BROKEN", "UNDERLYING_CAUSE_NAMED",
}
SCHEMA_EXTRA_MOVES = {
    "S1_INSTRUMENT_BLIND": {"CONCESSION_GRANTED", "DISCLAIM_RESTATE"},
    "S2_RECEIVED_ACCOUNT_REPLACED": {"SELF_CORRECTION", "GENEALOGY_TRACED"},
    "S3_TWO_CAMPS_RELOCATED": {"TWO_CAMP_SPLIT", "LEVEL_RELOCATION", "CONCESSION_GRANTED"},
    "S4_MECHANISM_TRACED": set(),
    "S5_PRACTICE_VS_THEORY": {"GENEALOGY_TRACED"},
    "S6_ORIGIN_AND_DRIFT": {"GENEALOGY_TRACED"},
    "S7_CASE_AGAINST_RULE": {"SELF_CORRECTION", "CONCESSION_GRANTED"},
    "S8_REMEDIES_WEIGHED": {"CONCESSION_GRANTED"},
}


def middle_moves(schema_id, policy=None):
    """Body beats this schema may plan. A generation policy may widen the set
    for its own plans (2026-09-13); the legacy result is unchanged."""
    if policy is not None and not policy.is_legacy:
        return policy.middle_moves(schema_id)
    return SUPPORTING_MOVES | SCHEMA_EXTRA_MOVES[schema_id]


FAMILY_FORBIDDEN_MOVES = {
    "F33": {"SELF_CORRECTION", "EASY_READING_DEMOLISHED"},
    "F36": {"CONCESSION_GRANTED", "CONCESSION_COSTED"},
    "F40": {"HEDGED_APHORISM", "CONCESSION_COSTED", "BOTHSIDES_REFUSED"},
}


def schema_ids_for_shape(shape_id, policy=None):
    forms_by_schema = policy.schema_forms() if policy is not None else SCHEMA_FORMS
    return [s for s, forms in forms_by_schema.items()
            if not shape_id or shape_id in forms["topic_shape"]]


def closing_beats(ending_id, posture, family_id=""):
    pool = set(ENDING_BEATS.get(ending_id, DEFAULT_ENDING_BEATS))
    if posture.startswith(("resolution", "affirmation")):
        pool.discard("QUESTION_LEFT_OPEN")
    if posture.startswith("refusal"):
        pool.discard("CONCESSION_COSTED")
    return pool - FAMILY_FORBIDDEN_MOVES.get(family_id, set())


def plan_violations(bp, registry):
    """Validate the complete new contract; legacy blueprints remain resumable.
    Checked under the policy the blueprint carries (2026-09-13)."""
    if not bp.argument_schema_id:
        return []
    from .generation_policy import policy_for_blueprint
    policy = policy_for_blueprint(bp)
    forms = policy.schema_forms()[bp.argument_schema_id]
    issues = []
    for key in ("family", "topic_shape", "render_stance"):
        value = getattr(bp, key + "_id")
        if value and value not in forms[key]:
            issues.append(f"{key} {value} conflicts with {bp.argument_schema_id}")
    if bp.move_plan:
        if FAMILY_FORBIDDEN_MOVES.get(bp.family_id, set()) & set(bp.move_plan):
            issues.append("beat plan contradicts the family's arc")
        if set(bp.move_plan[1:-1]) - middle_moves(bp.argument_schema_id, policy):
            issues.append("body contains operations outside the chosen schema")
        for move in forms["required_middle"]:
            if move not in bp.move_plan[1:-1]:
                issues.append(f"schema requires {move} in the body")
        last = bp.move_plan[-1]
        if last not in closing_beats(bp.ending_id, registry.posture_of(bp.family_id), bp.family_id):
            issues.append(f"closing beat {last} conflicts with ending {bp.ending_id}")
        if bp.closing_register not in policy.closing_registers_by_beat().get(last, set()):
            issues.append(f"register {bp.closing_register} conflicts with closing beat {last}")
    if bp.render_stance_id:
        stance = registry.get("render_stance", bp.render_stance_id)
        forbidden = set(stance["forbidden_beats"]) & set(bp.move_plan)
        if forbidden:
            issues.append(f"stance forbids {', '.join(sorted(forbidden))}")
    return issues


def review_reasons(bp, realized):
    """Observational voice-review reasons, including missing extraction.

    This does not request a re-render or change a novelty cap. The reviewer
    gets the evidence even when unrelated compliance points are high. Reasons
    alone do not change approval status during the observational launch.
    """
    reasons = []
    if bp.move_plan:
        if not realized.rhetorical_moves:
            reasons.append("rhetorical moves were not measured")
        else:
            if not realized.opening_beat_ok:
                reasons.append("opening beat differs from the plan")
            if not realized.closing_beat_ok:
                reasons.append("closing beat differs from the plan")
            if not realized.middle_beats_ok:
                reasons.append(f"body plan retention {realized.middle_retention:.0%}; "
                               f"unplanned moves: {', '.join(realized.gratuitous_moves) or 'none'}")
    if bp.argument_schema_id:
        if not realized.argument_schema:
            reasons.append("argument schema was not measured")
        elif bp.argument_schema_id not in (realized.argument_schema,
                                           realized.argument_schema_secondary):
            reasons.append(f"schema planned {bp.argument_schema_id}, "
                           f"realized {realized.argument_schema}")
    if (realized.final_line_is_aphorism and bp.closing_register
            and bp.closing_register != "aphoristic"):
        reasons.append("unplanned aphoristic ending")
    if not realized.commitment_in_band:
        reasons.append("closing commitment is outside the planned band")
    return reasons
