"""Dataclasses shared across the engine. Component library entries stay as
plain dicts (validated by registry.py); these classes model the artifacts
the pipeline creates and stores."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict


@dataclass
class SeedEssay:
    doc_id: str | None = None
    url: str | None = None
    title: str | None = None
    text: str | None = None          # trimmed excerpt, not the full essay
    domain_hint: str | None = None


@dataclass
class ParagraphPlan:
    para: int
    function: str
    len_words: tuple[int, int]
    cadence: str
    gist: str = ""                   # filled by the refine stage


@dataclass
class Blueprint:
    blueprint_id: str
    tier: str
    schema_version: str
    family_id: str
    persona_id: str
    ending_id: str
    rhythm_id: str
    revelation_id: str
    distractor_profile_id: str
    topology_id: str
    instability: float
    aperture: str
    movement: list[ParagraphPlan] = field(default_factory=list)
    letter_plan: list[str] = field(default_factory=list)
    closing_register: str = ""   # id from config.CLOSING_REGISTERS
    # refine-stage content (dicts straight from the refiner JSON)
    topic: str = ""
    tension_system: dict = field(default_factory=dict)
    trap_map: list[dict] = field(default_factory=list)
    revelation_detail: dict = field(default_factory=dict)
    seed: dict = field(default_factory=dict)

    @property
    def component_ids(self) -> dict:
        return {
            "family": self.family_id,
            "persona": self.persona_id,
            "ending": self.ending_id,
            "rhythm": self.rhythm_id,
            "revelation": self.revelation_id,
            "distractor_profile": self.distractor_profile_id,
            "topology": self.topology_id,
        }

    @property
    def combo_hash(self) -> str:
        key = "|".join(self.component_ids[k] for k in sorted(self.component_ids))
        return hashlib.sha1(key.encode()).hexdigest()[:16]

    @property
    def pair_hashes(self) -> dict:
        pairs = {
            "family_revelation": (self.family_id, self.revelation_id),
            "family_ending": (self.family_id, self.ending_id),
            "topology_distractor": (self.topology_id, self.distractor_profile_id),
        }
        return {k: hashlib.sha1("|".join(v).encode()).hexdigest()[:12] for k, v in pairs.items()}

    def movement_string(self) -> str:
        return "|".join(p.function for p in self.movement)

    def to_json(self) -> str:
        d = asdict(self)
        d["combo_hash"] = self.combo_hash
        d["pair_hashes"] = self.pair_hashes
        return json.dumps(d, ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> "Blueprint":
        d = json.loads(s)
        d.pop("combo_hash", None)
        d.pop("pair_hashes", None)
        d["movement"] = [
            ParagraphPlan(p["para"], p["function"], tuple(p["len_words"]), p["cadence"], p.get("gist", ""))
            for p in d.get("movement", [])
        ]
        return cls(**d)


@dataclass
class RealizedStructure:
    paragraph_functions: list[str] = field(default_factory=list)
    matches: list[bool] = field(default_factory=list)
    thesis_first_visible_para: int | None = None
    commitment_curve: list[float] = field(default_factory=list)
    traps_present: list[str] = field(default_factory=list)
    forbidden_tics_found: list[str] = field(default_factory=list)
    word_counts: list[int] = field(default_factory=list)
    f1: float = 0.0
    directives: list[str] = field(default_factory=list)
    closing_posture_guess: str = ""            # blind classifier output ("" = unusable)
    final_line_is_aphorism: bool | None = None  # None = classifier gave no usable answer

    def movement_string(self) -> str:
        return "|".join(self.paragraph_functions)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> "RealizedStructure":
        return cls(**json.loads(s))


@dataclass
class Fingerprint:
    rc_id: str
    blueprint_id: str
    persona_id: str
    movement_string: str
    commitment_curve: list[float]
    rhythm_vector: list[float]
    topology_signature: list[dict]        # [{"type":..., "target":..., "difficulty":...}]
    trap_histogram: dict                   # mechanism -> count
    letter_sequence: str
    stylometry: dict                       # word -> relative freq (plus _stats keys)
    embedding: list[float] | None = None
    source: str = "engine"                 # engine | legacy | manual (filterable)


@dataclass
class NoveltyReport:
    verdict: str                           # pass | reject_pairwise | reject_composite
    composite: float = 1.0
    channel_scores: dict = field(default_factory=dict)   # channel -> {"sim":..,"nearest":..}
    breached: list[str] = field(default_factory=list)
    corpus_flags: list[str] = field(default_factory=list)


@dataclass
class CostLine:
    stage: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class RCResult:
    rc_id: str | None
    blueprint_id: str
    tier: str
    status: str                            # approved | needs_review | solver_dispute |
                                           # rejected_novelty | budget_abort | failed_*
    rc_text: str | None = None
    average_score: float = 0.0
    compliance_f1: float = 0.0
    novelty_composite: float = 1.0
    cost_usd: float = 0.0
    cost_lines: list[CostLine] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # On rejected_novelty from a movement collision, the batch recompose loop
    # accumulates these so the next generate_one cannot re-sample the same
    # family skeleton (seed rotation alone does not change movement).
    ban_families: list[str] = field(default_factory=list)
    ban_movements: list[str] = field(default_factory=list)
