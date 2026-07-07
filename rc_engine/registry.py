"""Loads and validates the component libraries. Fail-fast: any structural
problem in a JSON library raises at startup, never mid-batch."""

from __future__ import annotations

import json
import os

COMPONENTS_DIR = os.path.join(os.path.dirname(__file__), "components")

LIBRARY_FILES = {
    "family": "families.json",
    "persona": "personas.json",
    "ending": "endings.json",
    "rhythm": "rhythms.json",
    "revelation": "revelations.json",
    "distractor_profile": "distractor_profiles.json",
    "topology": "topologies.json",
}

REQUIRED_FIELDS = {
    "family": {"id", "name", "tier_floor", "core", "movement", "question_affinities",
               "closing_posture"},
    "persona": {"id", "name", "register", "sentence_profile", "hedge_style", "signature_moves"},
    "ending": {"id", "name", "aperture", "gesture"},
    "rhythm": {"id", "name", "shape", "cadence_note"},
    "revelation": {"id", "name", "timing", "mechanism"},
    "distractor_profile": {"id", "name", "primary", "secondary", "note"},
    "topology": {"id", "name", "slots", "curve"},
}

MIN_COUNTS = {
    "family": 30, "persona": 20, "ending": 20, "rhythm": 20,
    "revelation": 20, "distractor_profile": 20, "topology": 20,
}


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

    def ids(self, ctype: str) -> list[str]:
        return list(self.libraries[ctype].keys())

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
        for cid, topo in self.libraries["topology"].items():
            if len(topo["slots"]) != 6:
                errors.append(f"topology:{cid} must have exactly 6 slots")
            for i, slot in enumerate(topo["slots"]):
                if slot["type"] not in slot_types:
                    errors.append(f"topology:{cid} slot {i+1} unknown type {slot['type']!r}")

        postures = set(self.meta["family"].get("closing_postures", {}))
        if not postures:
            errors.append("family meta missing 'closing_postures' definitions")
        for cid, fam in self.libraries["family"].items():
            if not 3 <= len(fam["movement"]) <= 6:
                errors.append(f"family:{cid} movement must have 3-6 functions")
            if fam.get("closing_posture") not in postures:
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

        if errors:
            raise RegistryError("Component library validation failed:\n  " + "\n  ".join(errors))
