"""Loads and validates the component libraries. Fail-fast: any structural
problem in a JSON library raises at startup, never mid-batch."""

from __future__ import annotations

import json
import os

from . import config

COMPONENTS_DIR = os.path.join(os.path.dirname(__file__), "components")

LIBRARY_FILES = {
    "family": "families.json",
    "persona": "personas.json",
    "ending": "endings.json",
    "rhythm": "rhythms.json",
    "revelation": "revelations.json",
    "distractor_profile": "distractor_profiles.json",
    "topology": "topologies.json",
    "render_stance": "render_stances.json",
    "topic_shape": "topic_shapes.json",
}

REQUIRED_FIELDS = {
    "family": {"id", "name", "tier_floor", "core", "movement", "question_affinities",
               "closing_posture", "arc_shape"},
    "persona": {"id", "name", "register", "sentence_profile", "hedge_style", "signature_moves"},
    "ending": {"id", "name", "aperture", "gesture"},
    "rhythm": {"id", "name", "shape", "cadence_note"},
    "revelation": {"id", "name", "timing", "mechanism"},
    "distractor_profile": {"id", "name", "primary", "secondary", "note"},
    "topology": {"id", "name", "slots", "curve"},
    "render_stance": {"id", "name", "frame", "arc_constraint", "forbidden_beats"},
    "topic_shape": {"id", "name", "topic_form", "requires_tension",
                    "compatible_genres"},
}

MIN_COUNTS = {
    "family": 30, "persona": 20, "ending": 20, "rhythm": 20,
    "revelation": 20, "distractor_profile": 20, "topology": 20,
    # Fewer than the others on purpose: a stance rewrites the whole instruction
    # frame, so each one is a much larger change than a persona swap, and the
    # exclusion window (6) already forces rotation across a batch.
    "render_stance": 8,
    "topic_shape": 8,
}

# A slot type with one stem shape reproduces that wording in every set that
# draws it — the surface half of the "all the RCs ask the same six questions"
# complaint. Enforced at load so a thin library fails fast, not in production.
MIN_STEM_FORMS = 3


class RegistryError(RuntimeError):
    pass


def posture_class(posture: str) -> str:
    """Coarse closing-posture class: 'resolution' | 'reframe' | 'refusal'."""
    return posture.split("_", 1)[0]


class ComponentRegistry:
    def __init__(self, components_dir: str = COMPONENTS_DIR):
        self.libraries: dict[str, dict[str, dict]] = {}
        self.meta: dict[str, dict] = {}
        for ctype, fname in LIBRARY_FILES.items():
            path = os.path.join(components_dir, fname)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            items = {item["id"]: item for item in data.get("items", [])}
            self.libraries[ctype] = items
            self.meta[ctype] = {k: v for k, v in data.items() if k != "items"}
        rules_path = os.path.join(components_dir, "constraint_rules.json")
        with open(rules_path, encoding="utf-8") as f:
            self.rules = json.load(f)["items"]
        self._validate()

    # -- access ------------------------------------------------------------

    def get(self, ctype: str, cid: str) -> dict:
        try:
            return self.libraries[ctype][cid]
        except KeyError:
            raise RegistryError(f"Unknown component {ctype}:{cid}")

    def withholds_thesis(self, family_id: str) -> bool:
        """True when the family states no position by design, so a thesis /
        main-idea question would have no defensible answer in the text."""
        return bool(self.get("family", family_id).get("withholds_thesis", False))

    def shape_of(self, family_id: str) -> str:
        """The family's ARC SHAPE — the sequence-level form of the argument.

        Added 2026-08-22. All 32 original families encode one shape
        (stage -> develop/concede -> turn -> settle) under 32 different
        function-token vocabularies, and 31 of them were exactly 4 paragraphs.
        `health` reported family KL at 0.128 throughout, because KL over IDs
        measures how evenly the labels rotate, not whether they name different
        things. Shape is what the reader actually perceives as sameness."""
        return self.get("family", family_id).get("arc_shape", "unknown")

    def shapes(self) -> dict[str, list[str]]:
        """arc_shape -> family ids carrying it."""
        out: dict[str, list[str]] = {}
        for fid in self.ids("family"):
            out.setdefault(self.shape_of(fid), []).append(fid)
        return out

    def ids(self, ctype: str) -> list[str]:
        """Every id in the library, whatever policy it belongs to. Sampling
        and question paths must use GenerationPolicy.eligible_ids instead;
        this stays unfiltered for reports and validation."""
        return list(self.libraries[ctype].keys())

    def has_policy_tags(self, ctype: str) -> bool:
        """True when any item of this type is restricted to a generation
        policy (see generation_policy.py)."""
        return any(item.get("policies") for item in self.libraries[ctype].values())

    def length_class_range(self, cls: str) -> tuple[int, int]:
        rng = self.meta["rhythm"]["length_classes"][cls]
        return (rng[0], rng[1])

    @property
    def mechanisms(self) -> list[str]:
        return self.meta["distractor_profile"]["mechanisms"]

    @property
    def slot_type_definitions(self) -> dict:
        return self.meta["topology"]["slot_types"]

    @property
    def stem_forms(self) -> dict:
        """slot type -> the authentic CAT stem shapes it may be asked in. The
        question prompt rotates one per slot so a type does not always produce
        the same wording."""
        return self.meta["topology"]["stem_forms"]

    @property
    def generic_fillers(self) -> list[str]:
        return self.meta["family"]["generic_fillers"]

    @property
    def closing_postures(self) -> dict:
        """posture value -> render directive text (defined in families.json meta)."""
        return self.meta["family"]["closing_postures"]

    def posture_of(self, family_id: str) -> str:
        return self.get("family", family_id)["closing_posture"]

    # -- validation ----------------------------------------------------------

    def _validate(self):
        errors = []
        for ctype, items in self.libraries.items():
            if len(items) < MIN_COUNTS[ctype]:
                errors.append(f"{ctype}: only {len(items)} items, need >= {MIN_COUNTS[ctype]}")
            for cid, item in items.items():
                missing = REQUIRED_FIELDS[ctype] - set(item)
                if missing:
                    errors.append(f"{ctype}:{cid} missing fields {sorted(missing)}")

        mechanisms = set(self.mechanisms)
        for cid, prof in self.libraries["distractor_profile"].items():
            for key in ("primary", "secondary"):
                if prof[key] not in mechanisms:
                    errors.append(f"distractor_profile:{cid} unknown mechanism {prof[key]!r}")

        slot_types = set(self.slot_type_definitions)
        stem_forms = self.stem_forms
        for stype in sorted(slot_types):
            if len(stem_forms.get(stype, [])) < MIN_STEM_FORMS:
                errors.append(f"slot type {stype!r} needs >= {MIN_STEM_FORMS} stem "
                              f"forms, has {len(stem_forms.get(stype, []))}")
        for stype in stem_forms:
            if stype not in slot_types:
                errors.append(f"stem_forms has unknown slot type {stype!r}")
        n_slots = config.QUESTIONS_PER_SET
        for cid, topo in self.libraries["topology"].items():
            if len(topo["slots"]) != n_slots:
                errors.append(f"topology:{cid} must have exactly {n_slots} slots")
            # Q1 is pinned to the thesis/main-idea question on every topology
            # (client requirement 2026-08-10). Validated here rather than left to
            # the library so a hand-edited topology cannot silently drop it.
            if topo["slots"] and topo["slots"][0]["type"] != "thesis":
                errors.append(f"topology:{cid} slot 1 must be 'thesis', "
                              f"got {topo['slots'][0]['type']!r}")
            # A topology tagged for generation policies may also use slot types
            # every one of those policies adds (2026-09-13); an untagged one is
            # read by legacy plans and must stay inside the library's own types.
            allowed_types = slot_types
            if topo.get("policies"):
                from .generation_policy import registered
                policies = registered()
                extras = [set(policies[v].extra_slot_types)
                          for v in topo["policies"] if v in policies]
                if extras:
                    allowed_types = slot_types | set.intersection(*extras)
            for i, slot in enumerate(topo["slots"]):
                if slot["type"] not in allowed_types:
                    errors.append(f"topology:{cid} slot {i+1} unknown type {slot['type']!r}")

        postures = set(self.meta["family"].get("closing_postures", {}))
        if not postures:
            errors.append("family meta missing 'closing_postures' definitions")
        for cid, fam in self.libraries["family"].items():
            if not 3 <= len(fam["movement"]) <= 6:
                errors.append(f"family:{cid} movement must have 3-6 functions")
            # Variants must be real alternatives the builder can run, and must
            # obey the same length rule — a variant is a movement string like
            # any other and gets banned/enumerated as one.
            for k, v in enumerate(fam.get("movement_variants") or []):
                if not isinstance(v, list) or not 3 <= len(v) <= 6:
                    errors.append(f"family:{cid} movement_variants[{k}] must "
                                  f"be a list of 3-6 functions")
                elif list(v) == list(fam["movement"]):
                    errors.append(f"family:{cid} movement_variants[{k}] "
                                  f"duplicates the canonical movement")
                elif sorted(v) != sorted(fam["movement"]):
                    errors.append(f"family:{cid} movement_variants[{k}] must "
                                  f"reorder the same functions, not introduce "
                                  f"new ones")
            # A family tagged for generation policies may close on a posture
            # every one of those policies defines (2026-09-13, e.g. the
            # neutral exposition); untagged families stay on the library's own.
            allowed_postures = postures
            if fam.get("policies"):
                from .generation_policy import registered
                known = registered()
                extras = [set(known[v].extra_closing_postures)
                          for v in fam["policies"] if v in known]
                if extras:
                    allowed_postures = postures | set.intersection(*extras)
            if fam.get("closing_posture") not in allowed_postures:
                errors.append(f"family:{cid} unknown closing_posture "
                              f"{fam.get('closing_posture')!r}")
            for eid in fam.get("incompatible_endings", []):
                if eid not in self.libraries["ending"]:
                    errors.append(f"family:{cid} references unknown ending {eid}")
            for rid in fam.get("incompatible_revelations", []):
                if rid not in self.libraries["revelation"]:
                    errors.append(f"family:{cid} references unknown revelation {rid}")

        valid_classes = set(self.meta["rhythm"]["length_classes"])
        for cid, rhy in self.libraries["rhythm"].items():
            bad = [c for c in rhy["shape"] if c not in valid_classes]
            if bad:
                errors.append(f"rhythm:{cid} unknown length classes {bad}")

        rule_types = {"family", "persona", "ending", "rhythm", "revelation",
                      "distractor_profile", "topology"}
        for i, rule in enumerate(self.rules):
            for section in ("when", "forbid"):
                for ctype in rule.get(section, {}):
                    if ctype not in rule_types:
                        errors.append(f"rule {i}: unknown component type {ctype!r}")
            for ctype, ids in rule.get("forbid", {}).items():
                for cid in ids:
                    if cid not in self.libraries[ctype]:
                        errors.append(f"rule {i}: forbids unknown {ctype}:{cid}")
            for ctype, cid in rule.get("when", {}).items():
                if cid not in self.libraries[ctype]:
                    errors.append(f"rule {i}: 'when' references unknown {ctype}:{cid}")

        from .generation_policy import validation_errors
        errors.extend(validation_errors(self))

        if errors:
            raise RegistryError("Component library validation failed:\n  " + "\n  ".join(errors))
