"""Generation policies: a versioned boundary around what a blueprint may use.

Added 2026-09-13 (section 3 of 2026-09-13-cat-pyq-implementation-plan.md).
The CAT PYQ work will widen medium and hard — new families, beats, question
forms, prompt permissions and calibration weights — while elite must keep its
existing behaviour exactly. Editing the shared libraries in place cannot do
that: every draw, prompt and extraction reads one global vocabulary, so any
addition reaches elite, and a stored plan would be silently reinterpreted
under whatever the libraries say on the day it resumes.

So every such read goes through a policy:

  - The LEGACY policy (version "") is the engine as it stood on 2026-09-13.
    Its accessors return the existing global objects themselves — the same
    dicts, lists and order — so the legacy path consumes no extra RNG and
    builds byte-identical prompts. tests/test_generation_policy.py holds that
    against a golden run captured before this module existed.
  - A non-legacy policy may only ADD: components tagged for it in the
    libraries ("policies": [version]), plannable or recognised beats, stem
    forms, slot types, argument schemas, prompt text and weight adjustments.
    Untagged components stay available to it; tagged ones are invisible to
    every other policy, including legacy.
  - The version is persisted on the blueprint (Blueprint.generation_policy).
    A missing version means legacy. Resume, topology re-picks and question
    building resolve the policy from the stored blueprint, never from today's
    configuration, and an unknown version is an error rather than a fallback.
  - Elite always resolves to legacy, whatever config says.

Production policies live in policy_catalog.py and are registered at import
(2026-09-13: `cat-pyq-q1`, the section 4 question release). Registering is not
enabling: config.GENERATION_POLICY_FOR_NEW_PLANS decides which tiers compose
under a policy. Registering a version and later changing what it contains would
reinterpret every plan already stored under it, so a version's content is fixed
once plans can carry it; change means a new version. Tests register temporary
policies with `temporary_policy`.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from types import MappingProxyType

from . import config

LEGACY = ""
TIERS = ("medium", "hard", "elite")


class PolicyError(RuntimeError):
    pass


def _ro(d: dict) -> MappingProxyType:
    return MappingProxyType(dict(d))


@dataclass(frozen=True)
class GenerationPolicy:
    version: str
    tiers: frozenset
    description: str = ""
    # label -> gloss; plannable beats must also be listed in extra_move_groups
    extra_moves: MappingProxyType = field(default_factory=lambda: _ro({}))
    # group ("opening" | "middle" | "closing") -> labels that may be PLANNED.
    # A beat in extra_moves but in no group is recognised in extraction only.
    extra_move_groups: MappingProxyType = field(default_factory=lambda: _ro({}))
    extra_exam_move_shares: MappingProxyType = field(default_factory=lambda: _ro({}))
    extra_slot_types: MappingProxyType = field(default_factory=lambda: _ro({}))
    extra_stem_forms: MappingProxyType = field(default_factory=lambda: _ro({}))
    extra_argument_schemas: MappingProxyType = field(default_factory=lambda: _ro({}))
    # schema id -> {"family"|"topic_shape"|"render_stance": ids to add,
    #               "required_middle": [...]} (required_middle only for new schemas)
    extra_schema_forms: MappingProxyType = field(default_factory=lambda: _ro({}))
    # schema id -> extra middle moves the schema may use
    extra_schema_middle_moves: MappingProxyType = field(default_factory=lambda: _ro({}))
    # closing beat label -> closing register ids it may carry
    extra_closing_registers_by_beat: MappingProxyType = field(default_factory=lambda: _ro({}))
    extra_exam_derived_shapes: frozenset = frozenset()
    # stage -> text appended to that stage's USER prompt
    prompt_extensions: MappingProxyType = field(default_factory=lambda: _ro({}))
    # stage -> text appended to that stage's SYSTEM prompt
    system_extensions: MappingProxyType = field(default_factory=lambda: _ro({}))
    # callable(ctype, ids, weights, registry) -> weights; None = unchanged
    weight_adjuster: object = None
    # -- question contracts (section 4; see question_contracts.py) --
    # True: slots resolve to task/polarity/contract and generated questions are
    # checked against them. False keeps a policy's questions on legacy rules.
    question_contracts: bool = False
    # released negative tasks this policy may plan ("support", "application")
    negative_tasks: frozenset = frozenset()
    # tier -> exact number of negative slots per set, pre-existing ones included
    negative_slots_per_set: MappingProxyType = field(default_factory=lambda: _ro({}))
    # stem-pool keys beyond plain slot types: "<type>/negative", "<type>/<variant>"
    keyed_stem_forms: MappingProxyType = field(default_factory=lambda: _ro({}))
    # slot type -> variants resolved per plan (e.g. keyword_set: keywords, sequence)
    slot_variants: MappingProxyType = field(default_factory=lambda: _ro({}))

    # -- identity -------------------------------------------------------------

    @property
    def is_legacy(self) -> bool:
        return self.version == LEGACY

    # -- components -----------------------------------------------------------

    def component_eligible(self, item: dict) -> bool:
        tags = item.get("policies")
        if not tags:
            return True
        return (not self.is_legacy) and self.version in tags

    def eligible_ids(self, registry, ctype: str, tier: str | None = None) -> list[str]:
        """tier: when given and the policy resolves question contracts, a
        topology that cannot carry the tier's negative-slot target is not
        eligible (section 4). Legacy ignores it."""
        ids = registry.ids(ctype)
        if self.is_legacy and not registry.has_policy_tags(ctype):
            return ids
        ids = [i for i in ids if self.component_eligible(registry.get(ctype, i))]
        if ctype == "topology" and self.question_contracts and tier:
            from .question_contracts import topology_supports
            ids = [i for i in ids
                   if topology_supports(registry.get(ctype, i), self, tier)]
        return ids

    def exam_derived_shapes(self):
        if not self.extra_exam_derived_shapes:
            return config.EXAM_DERIVED_SHAPES
        return set(config.EXAM_DERIVED_SHAPES) | set(self.extra_exam_derived_shapes)

    # -- rhetorical beats -----------------------------------------------------

    def move_vocabulary(self) -> dict:
        if not self.extra_moves:
            return config.RHETORICAL_MOVES
        return {**config.RHETORICAL_MOVES, **self.extra_moves}

    def move_groups(self) -> dict:
        if not self.extra_move_groups:
            return config.MOVE_GROUPS
        return {g: list(config.MOVE_GROUPS.get(g, [])) + [
                    m for m in self.extra_move_groups.get(g, ())
                    if m not in config.MOVE_GROUPS.get(g, [])]
                for g in dict.fromkeys([*config.MOVE_GROUPS, *self.extra_move_groups])}

    def exam_move_shares(self) -> dict:
        if not self.extra_exam_move_shares:
            return config.EXAM_MOVE_SHARES
        return {**config.EXAM_MOVE_SHARES, **self.extra_exam_move_shares}

    # -- argument schemas and the voice plan ----------------------------------

    def argument_schemas(self) -> dict:
        if not self.extra_argument_schemas:
            return config.ARGUMENT_SCHEMAS
        return {**config.ARGUMENT_SCHEMAS, **self.extra_argument_schemas}

    def schema_forms(self) -> dict:
        from .voice_plan import SCHEMA_FORMS
        if not self.extra_schema_forms:
            return SCHEMA_FORMS
        out = {k: {kk: (set(vv) if isinstance(vv, set) else list(vv)) for kk, vv in v.items()}
               for k, v in SCHEMA_FORMS.items()}
        for schema, extra in self.extra_schema_forms.items():
            base = out.setdefault(schema, {"topic_shape": set(), "family": set(),
                                           "render_stance": set(), "required_middle": []})
            for key in ("topic_shape", "family", "render_stance"):
                base[key] = set(base.get(key, set())) | set(extra.get(key, ()))
            if "required_middle" in extra and schema not in SCHEMA_FORMS:
                base["required_middle"] = list(extra["required_middle"])
        return out

    def middle_moves(self, schema_id: str) -> set:
        from .voice_plan import SUPPORTING_MOVES, SCHEMA_EXTRA_MOVES
        base = SUPPORTING_MOVES | SCHEMA_EXTRA_MOVES.get(schema_id, set())
        extra = self.extra_schema_middle_moves.get(schema_id)
        return base | set(extra) if extra else base

    def closing_registers_by_beat(self) -> dict:
        from .voice_plan import CLOSING_REGISTERS_BY_BEAT
        if not self.extra_closing_registers_by_beat:
            return CLOSING_REGISTERS_BY_BEAT
        out = {k: set(v) for k, v in CLOSING_REGISTERS_BY_BEAT.items()}
        for beat, regs in self.extra_closing_registers_by_beat.items():
            out[beat] = out.get(beat, set()) | set(regs)
        return out

    # -- questions ------------------------------------------------------------

    def slot_type_definitions(self, registry) -> dict:
        if not self.extra_slot_types:
            return registry.slot_type_definitions
        return {**registry.slot_type_definitions, **self.extra_slot_types}

    def stem_forms(self, registry) -> dict:
        """Never mutates the shared pool elite reads: extras produce a copy with
        the library's own forms first, in their original order."""
        if not self.extra_stem_forms:
            return registry.stem_forms
        out = {k: list(v) for k, v in registry.stem_forms.items()}
        for stype, forms in self.extra_stem_forms.items():
            out[stype] = out.get(stype, []) + [f for f in forms if f not in out.get(stype, [])]
        return out

    def stem_pool(self, registry) -> dict:
        """Stem forms keyed as question_contracts.stem_key keys them. Without
        keyed forms this is stem_forms() itself (legacy: the shared pool)."""
        if not self.keyed_stem_forms:
            return self.stem_forms(registry)
        return {**self.stem_forms(registry),
                **{k: list(v) for k, v in self.keyed_stem_forms.items()}}

    # -- prompts and weights --------------------------------------------------

    def user_prompt(self, stage: str, text: str) -> str:
        ext = self.prompt_extensions.get(stage)
        return f"{text}\n\n{ext}" if ext else text

    def system_prompt(self, stage: str, text: str) -> str:
        ext = self.system_extensions.get(stage)
        return f"{text}\n\n{ext}" if ext else text

    def adjust_weights(self, ctype: str, ids: list[str], weights: list[float], registry):
        if self.weight_adjuster is None:
            return weights
        return self.weight_adjuster(ctype, ids, weights, registry)


LEGACY_POLICY = GenerationPolicy(
    version=LEGACY, tiers=frozenset(TIERS),
    description="the engine as it stood on 2026-09-13; missing version on a blueprint")

_POLICIES: dict[str, GenerationPolicy] = {LEGACY: LEGACY_POLICY}


def _register_catalog() -> None:
    """Idempotent. When policy_catalog is imported first it is still mid-import
    here, so this returns and the catalog calls it again once it is complete."""
    try:
        from .policy_catalog import PRODUCTION_POLICIES
    except ImportError:
        return
    for p in PRODUCTION_POLICIES:
        existing = _POLICIES.get(p.version)
        if existing is p:
            continue
        if existing is not None:
            raise PolicyError(f"policy {p.version!r} registered twice")
        _POLICIES[p.version] = p


def registered() -> dict[str, GenerationPolicy]:
    return dict(_POLICIES)


def get_policy(version: str | None) -> GenerationPolicy:
    version = version or LEGACY
    try:
        return _POLICIES[version]
    except KeyError:
        raise PolicyError(f"unknown generation policy {version!r}; stored plans are never "
                          f"reinterpreted under another policy")


def policy_for_new_plan(tier: str) -> GenerationPolicy:
    """The policy a NEW blueprint for this tier is composed under."""
    if tier == "elite":
        return LEGACY_POLICY
    version = getattr(config, "GENERATION_POLICY_FOR_NEW_PLANS", {}).get(tier, LEGACY)
    policy = get_policy(version)
    if tier not in policy.tiers:
        raise PolicyError(f"generation policy {version!r} is not enabled for tier {tier!r}")
    return policy


def policy_for_blueprint(bp) -> GenerationPolicy:
    """The policy a STORED blueprint was composed under. Today's configuration
    plays no part: a plan resumes under the policy it was made with."""
    version = getattr(bp, "generation_policy", "") or LEGACY
    policy = get_policy(version)
    if getattr(bp, "tier", None) not in policy.tiers:
        raise PolicyError(f"blueprint {getattr(bp, 'blueprint_id', '?')} carries policy "
                          f"{version!r}, which does not admit tier {getattr(bp, 'tier', None)!r}")
    return policy


def known_argument_schema_ids() -> set:
    """Every schema any registered policy can plan or extract. Used where
    stored measurements are counted, so a policy's own schemas are not
    discarded as junk."""
    ids = set(config.ARGUMENT_SCHEMAS)
    for p in _POLICIES.values():
        ids |= set(p.extra_argument_schemas)
    return ids


@contextlib.contextmanager
def temporary_policy(policy: GenerationPolicy, new_plans: dict | None = None):
    """Register a policy (and optionally a tier -> version map for new plans)
    for the duration of a test."""
    if policy.version in _POLICIES:
        raise PolicyError(f"policy {policy.version!r} is already registered")
    old_map = getattr(config, "GENERATION_POLICY_FOR_NEW_PLANS", None)
    _POLICIES[policy.version] = policy
    if new_plans is not None:
        config.GENERATION_POLICY_FOR_NEW_PLANS = {**(old_map or {}), **new_plans}
    try:
        yield policy
    finally:
        _POLICIES.pop(policy.version, None)
        if new_plans is not None:
            config.GENERATION_POLICY_FOR_NEW_PLANS = old_map


def register_for_process(policy: GenerationPolicy) -> None:
    """Non-context registration for subprocess scenario setups."""
    if policy.version in _POLICIES:
        raise PolicyError(f"policy {policy.version!r} is already registered")
    _POLICIES[policy.version] = policy


def validation_errors(registry) -> list[str]:
    """Checks run by ComponentRegistry._validate."""
    errors = []
    new_plans = getattr(config, "GENERATION_POLICY_FOR_NEW_PLANS", {})
    for tier, version in new_plans.items():
        if tier not in TIERS:
            errors.append(f"GENERATION_POLICY_FOR_NEW_PLANS has unknown tier {tier!r}")
        if version not in _POLICIES:
            errors.append(f"GENERATION_POLICY_FOR_NEW_PLANS[{tier!r}] names unknown policy {version!r}")
        elif tier == "elite" and version != LEGACY:
            errors.append("elite must stay on the legacy generation policy")
        elif tier in TIERS and tier not in _POLICIES[version].tiers:
            errors.append(f"policy {version!r} does not admit tier {tier!r}")
    for ctype, items in registry.libraries.items():
        for cid, item in items.items():
            tags = item.get("policies")
            if tags is None:
                continue
            if not isinstance(tags, list) or not tags:
                errors.append(f"{ctype}:{cid} 'policies' must be a non-empty list of versions")
                continue
            for v in tags:
                if v == LEGACY:
                    errors.append(f"{ctype}:{cid} must not tag the legacy policy; untagged "
                                  f"components are already legacy")
                elif v not in _POLICIES:
                    errors.append(f"{ctype}:{cid} tagged for unknown policy {v!r}")
    from .registry import MIN_STEM_FORMS
    for version, p in _POLICIES.items():
        types = set(p.slot_type_definitions(registry))
        forms = p.stem_forms(registry)
        for stype in p.extra_slot_types:
            if len(forms.get(stype, [])) < MIN_STEM_FORMS:
                errors.append(f"policy {version!r} slot type {stype!r} needs >= {MIN_STEM_FORMS} stem forms")
        for stype in p.extra_stem_forms:
            if stype not in types:
                errors.append(f"policy {version!r} adds stem forms for unknown slot type {stype!r}")
        vocab = p.move_vocabulary()
        for group, moves in p.extra_move_groups.items():
            for m in moves:
                if m not in vocab:
                    errors.append(f"policy {version!r} plans beat {m!r} with no gloss")
        if "elite" in p.tiers and not p.is_legacy:
            errors.append(f"policy {version!r} must not admit elite")
        if p.question_contracts:
            errors.extend(_contract_errors(version, p, registry))
    return errors


def _contract_errors(version: str, p: GenerationPolicy, registry) -> list[str]:
    from .question_contracts import (NEGATIVE_CONTRACTS, TASK_OF_TYPE,
                                     negation_count, topology_supports)
    from .registry import MIN_STEM_FORMS
    errors = []
    pool = p.stem_pool(registry)
    types = set(p.slot_type_definitions(registry))
    for task in p.negative_tasks:
        if task not in NEGATIVE_CONTRACTS:
            errors.append(f"policy {version!r} enables unknown negative task {task!r}")
        elif not NEGATIVE_CONTRACTS[task]["released"]:
            errors.append(f"policy {version!r} enables unreleased negative task {task!r}")
    for tier, n in p.negative_slots_per_set.items():
        if tier not in p.tiers:
            errors.append(f"policy {version!r} sets a negative target for {tier!r}, "
                          f"which it does not admit")
    for stype, task in TASK_OF_TYPE.items():
        if task in p.negative_tasks and stype != "except_scan" and stype in types:
            if len(pool.get(f"{stype}/negative", [])) < MIN_STEM_FORMS:
                errors.append(f"policy {version!r} can negate {stype!r} but has fewer "
                              f"than {MIN_STEM_FORMS} negative stem forms")
    for stype, variants in p.slot_variants.items():
        for v in variants:
            if len(pool.get(f"{stype}/{v}", [])) < MIN_STEM_FORMS:
                errors.append(f"policy {version!r} variant {stype}/{v} needs "
                              f">= {MIN_STEM_FORMS} stem forms")
    # A negative form must carry exactly one negation; every other form none.
    # Otherwise a negative stem gets dealt to an affirmative contract.
    for key, forms in pool.items():
        negative = key.endswith("/negative") or key == "except_scan"
        for form in forms:
            n = negation_count(form)
            if negative and n != 1:
                errors.append(f"policy {version!r} stem {key!r} needs exactly one "
                              f"negation: {form!r}")
            elif not negative and n:
                errors.append(f"policy {version!r} affirmative stem {key!r} is negated: {form!r}")
    for tid in p.eligible_ids(registry, "topology"):
        topo = registry.get("topology", tid)
        if not topo.get("policies"):
            continue
        for tier in p.negative_slots_per_set:
            if not topology_supports(topo, p, tier):
                errors.append(f"topology:{tid} cannot carry policy {version!r}'s "
                              f"{tier} negative-slot target")
    return errors


_register_catalog()
