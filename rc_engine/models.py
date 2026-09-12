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

    @property
    def words_label(self) -> str:
        """How this paragraph's length is stated in a prompt. The composer now
        emits a single target per paragraph (a degenerate (n, n) band), so print
        one number; legacy blueprints stored with a real range still render as
        'lo-hi'."""
        lo, hi = self.len_words
        return f"{lo}" if lo == hi else f"{lo}-{hi}"


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
    render_stance_id: str = ""   # id from components/render_stances.json
    topic_shape_id: str = ""     # id from components/topic_shapes.json
    # What the argument DOES, one level above the rhetorical moves and
    # independent of subject. Key into config.ARGUMENT_SCHEMAS. Deliberately
    # NOT in component_ids: that property feeds combo_hash, and adding a key
    # would invalidate every stored hash at once.
    argument_schema_id: str = ""
    # Empty on old plans. New coherent contracts can be distinguished from
    # independently sampled pre-fix plans in before/after corpus reports.
    voice_plan_version: str = ""
    seed_genre: str = ""         # from seed_classify; "" = never classified
    # Prescribed rhetorical beats (labels from config.RHETORICAL_MOVES), in
    # order. A PLAN, not a ban list — see BlueprintComposer._sample_move_plan.
    move_plan: list[str] = field(default_factory=list)
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
            "render_stance": self.render_stance_id,
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
    # Blind read of what the argument DOES, against bp.argument_schema_id.
    # "" means the read failed, which is "unknown" — never "repeated".
    argument_schema: str = ""
    argument_schema_secondary: str = ""
    final_line_is_aphorism: bool | None = None  # None = classifier gave no usable answer
    rhetorical_moves: list[str] = field(default_factory=list)
    # Did the prose open and close on the beats the plan prescribed? Membership
    # of the plan was checked from the start; POSITION was not, and position is
    # where the house voice lived (see ComplianceAuditor.audit).
    opening_beat_ok: bool = True
    closing_beat_ok: bool = True
    # Did the passage end inside the commitment band its closing posture
    # implies? The curve was measured and weighted but never targeted.
    commitment_in_band: bool = True
    # Middle-beat discipline: retention of the planned body beats, and the
    # DISTINCTIVE moves the passage added without being asked. Order inside the
    # middle is deliberately not checked.
    middle_beats_ok: bool = True
    middle_retention: float = 1.0
    gratuitous_moves: list[str] = field(default_factory=list)

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
    # Blind rhetorical-move read of the PROSE ("|"-joined, closed vocabulary).
    # Empty = never extracted; treated as unknown, never as similar.
    move_signature: str = ""


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
    # Of input_tokens, how many were served from the provider's prompt cache
    # and therefore billed at config.MODEL_RATES_CACHED_IN. Defaulted so the
    # Anthropic and Gemini paths, which do not report it, are unaffected.
    cached_input_tokens: int = 0


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
    # On rejected_seed_genre: which genre was over its cap, so the batch's seed
    # rotation can steer away from the source kinds that produce it instead of
    # redrawing uniformly (which could not clear the saturation).
    saturated_genre: str = ""
