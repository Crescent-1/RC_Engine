"""Compatibility rule engine. Rules are declarative (constraint_rules.json)
plus the inline incompatibilities carried by family entries."""

from __future__ import annotations

from .registry import ComponentRegistry


class CompatibilityRules:
    def __init__(self, registry: ComponentRegistry):
        self.registry = registry

    def violations(self, ids: dict) -> list[str]:
        """ids: {"family": "F07", "persona": "P12", ...} — may be partial
        (unset keys are simply not checked), so the composer can validate
        incrementally while sampling."""
        out = []

        fam = self.registry.libraries["family"].get(ids.get("family", ""))
        if fam:
            if ids.get("ending") in fam.get("incompatible_endings", []):
                out.append(f"family {fam['id']} forbids ending {ids['ending']}")
            if ids.get("revelation") in fam.get("incompatible_revelations", []):
                out.append(f"family {fam['id']} forbids revelation {ids['revelation']}")

        for rule in self.registry.rules:
            when = rule.get("when", {})
            if not all(ids.get(ctype) == cid for ctype, cid in when.items()):
                continue
            for ctype, forbidden in rule.get("forbid", {}).items():
                if ids.get(ctype) in forbidden:
                    out.append(f"rule: {rule.get('reason', 'incompatible')} "
                               f"({when} forbids {ctype}:{ids[ctype]})")
        return out

    def is_valid(self, ids: dict) -> bool:
        return not self.violations(ids)
