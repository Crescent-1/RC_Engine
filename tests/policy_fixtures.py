"""A test-only generation policy and the tagged components it owns.

Written 2026-09-13 for the policy-boundary tests (plan section 3). Nothing
here is registered in production. The policy deliberately exercises every
kind of addition section 4 may make — tagged family, persona, rhythm, topic
shape and topology; an extra planned beat; an extra slot type and stem forms
(including extra forms for an existing type); schema-form widening; prompt
and system extensions; and a weight adjuster that makes tagged components
near-certain draws, so a leak would show up rather than hide behind chance.
"""
from __future__ import annotations

import functools
import json
import os
import random
import shutil

TEST_VERSION = "test-policy-isolation"
TAG_SUFFIX = "90"
EXTRA_SLOT = "not_supported_test"
EXTRA_MOVE = "TEST_NEGATED_CLAIM"
EXTENSION = "POLICY TEST EXTENSION"
SYSTEM_EXTENSION = "POLICY TEST SYSTEM EXTENSION"
TAGGED = {"family": "F90", "persona": "P90", "rhythm": "T90",
          "topic_shape": "TS90", "topology": "QT90"}


def boost_tagged(ctype, ids, weights, registry):
    return [w * 1e6 if registry.get(ctype, i).get("policies") else w
            for w, i in zip(weights, ids)]


def make_policy():
    from rc_engine.generation_policy import GenerationPolicy, _ro
    from rc_engine.voice_plan import SCHEMA_FORMS
    return GenerationPolicy(
        version=TEST_VERSION, tiers=frozenset({"medium", "hard"}),
        description="test only: every kind of addition, all of it tagged",
        extra_moves=_ro({EXTRA_MOVE: "the author denies a claim the reader was led to expect"}),
        extra_move_groups=_ro({"middle": [EXTRA_MOVE]}),
        extra_exam_move_shares=_ro({EXTRA_MOVE: 0.95}),
        extra_slot_types=_ro({EXTRA_SLOT: "which statement the passage does NOT support"}),
        extra_stem_forms=_ro({
            EXTRA_SLOT: ["Which of the following is NOT supported by the passage? (test A)",
                         "The passage gives no support to which of the following? (test B)",
                         "All of the following are supported EXCEPT: (test C)"],
            "thesis": ["Which of the following is NOT the author's central claim? (test D)"],
        }),
        extra_schema_forms=_ro({s: {"family": [TAGGED["family"]],
                                    "topic_shape": [TAGGED["topic_shape"]]}
                                for s in SCHEMA_FORMS}),
        extra_schema_middle_moves=_ro({s: [EXTRA_MOVE] for s in SCHEMA_FORMS}),
        prompt_extensions=_ro({st: f"{EXTENSION} [{st}]"
                               for st in ("refine", "render", "compliance", "questions")}),
        system_extensions=_ro({st: f"{SYSTEM_EXTENSION} [{st}]"
                               for st in ("refine", "render", "compliance", "questions")}),
        weight_adjuster=boost_tagged,
    )


def build_components(dst: str) -> str:
    """Copy the production libraries to dst and add one tagged clone per type."""
    from rc_engine import config
    from rc_engine.registry import COMPONENTS_DIR
    shutil.copytree(COMPONENTS_DIR, dst, dirs_exist_ok=True)

    def edit(fname, fn):
        path = os.path.join(dst, fname)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        fn(data)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    def clone(data, pick, new_id, **changes):
        src = next(i for i in data["items"] if pick(i))
        item = json.loads(json.dumps(src))
        item.update(id=new_id, name=f"{src['name']} (policy test)",
                    policies=[TEST_VERSION], **changes)
        data["items"].append(item)
        return item

    edit("families.json", lambda d: clone(
        d, lambda i: i["tier_floor"] == "medium" and "tier_max" not in i,
        TAGGED["family"]))
    edit("personas.json", lambda d: clone(d, lambda i: True, TAGGED["persona"]))
    edit("rhythms.json", lambda d: clone(d, lambda i: True, TAGGED["rhythm"]))
    edit("topic_shapes.json", lambda d: clone(
        d, lambda i: not i["requires_tension"], TAGGED["topic_shape"],
        compatible_genres=[]))

    bar = config.TIER_TOPOLOGY_BAR

    def medium_ok(topo):
        m = bar.get("medium") or {}
        types = {s["type"] for s in topo["slots"]}
        spans = sum(1 for s in topo["slots"] if s["target"] == "span")
        return not (set(m.get("forbid_types", ())) & types) and spans <= m.get("max_span", 99)

    def add_topology(d):
        item = clone(d, medium_ok, TAGGED["topology"])
        k = next(n for n, s in enumerate(item["slots"])
                 if n > 0 and s["type"] not in ("except_scan", "thesis"))
        item["slots"][k]["type"] = EXTRA_SLOT
    edit("topologies.json", add_topology)
    return dst


# ---- subprocess hooks (tests/policy_harness.py) ------------------------------

def install_disabled(patch, options):
    """Register the policy and the tagged libraries, with no tier using it."""
    from rc_engine import generation_policy, pipeline, registry
    generation_policy.register_for_process(make_policy())
    d = build_components(options["components_dir"])
    patch.setattr(pipeline, "ComponentRegistry",
                  functools.partial(registry.ComponentRegistry, d))


def enable_medium_hard(patch, options):
    from rc_engine import config
    patch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                  {"medium": TEST_VERSION, "hard": TEST_VERSION, "elite": ""})


def enable_cat_pyq_q1(patch, options):
    """The production question release, with the production libraries."""
    from rc_engine import config
    from rc_engine.policy_catalog import CAT_PYQ_Q1
    patch.setattr(config, "GENERATION_POLICY_FOR_NEW_PLANS",
                  {"medium": CAT_PYQ_Q1, "hard": CAT_PYQ_Q1, "elite": ""})


_SIDE: dict = {}


def run_side_attempt(patch, options, i, tier):
    """Before each main attempt, run one medium/hard attempt under the policy
    in a SEPARATE pipeline (own DB, RNG, ids and mock client) in the same
    process. Any global state the policy path mutated — shared libraries,
    config dicts, stem pools — would then show up in the main elite output."""
    import rc_engine.composer as composer_mod
    from rc_engine.history import HistoryStore
    from rc_engine.llm import MockLLMClient
    from rc_engine.models import SeedEssay
    from rc_engine.pipeline import RCPipeline

    if not _SIDE:
        _SIDE["history"] = HistoryStore(os.path.join(options["workdir"], "side.db"))
        _SIDE["pipe"] = RCPipeline(_SIDE["history"], MockLLMClient(), embed=False,
                                   rng=random.Random(77))
        _SIDE["n"] = 0
        _SIDE["report"] = []
    main_uuid4 = composer_mod.uuid.uuid4

    class _U:
        def __init__(self, n):
            self.hex = f"f{n:07x}" + "0" * 24

    def side_uuid4():
        _SIDE["n"] += 1
        return _U(_SIDE["n"])

    composer_mod.uuid.uuid4 = side_uuid4
    try:
        side_tier = ("hard", "medium")[i % 2]
        res = _SIDE["pipe"].generate_one(side_tier, SeedEssay(
            url=f"https://example.org/side-{i}", title=f"Side {i}",
            text="A side seed about ledger audits in a port authority and what they missed."))
    finally:
        composer_mod.uuid.uuid4 = main_uuid4
    row = _SIDE["history"].conn.execute(
        "SELECT blueprint_json FROM blueprints WHERE blueprint_id = ?",
        (res.blueprint_id,)).fetchone() if res.blueprint_id else None
    bp = json.loads(row[0]) if row else {}
    slots = bp.get("question_slots") or []
    _SIDE["report"].append({"tier": side_tier, "status": res.status,
                            "generation_policy": bp.get("generation_policy"),
                            "family": bp.get("family_id"), "topology": bp.get("topology_id"),
                            "question_slots": len(slots),
                            "negatives": sum(1 for s in slots if s.get("polarity") == "negative")})
    with open(options["side_report"], "w", encoding="utf-8") as f:
        json.dump(_SIDE["report"], f, indent=1)
