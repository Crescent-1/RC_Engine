"""Stage 1 — BlueprintComposer.

Deterministic structure sampling (free, local) followed by one LLM refinement
call that fills content slots (tension axes, trap anchors, paragraph gists)
without touching any sampled component ID.
"""

from __future__ import annotations

import json
import random
import uuid
from datetime import datetime, timezone

from . import config
from .constraints import CompatibilityRules
from .history import HistoryStore
from .llm import BudgetExceeded, CostLedger, extract_json
from .models import Blueprint, ParagraphPlan, SeedEssay
from .registry import ComponentRegistry, posture_class

TIER_ORDER = {"medium": 0, "hard": 1, "elite": 2}


class CompositionExhausted(RuntimeError):
    pass


def blueprint_categorical_similarity(a: dict, b: dict) -> float:
    """Channel 1: weighted agreement between two blueprints' component IDs.
    1.0 = identical component tuple."""
    sim = 0.0
    for key, w in config.BLUEPRINT_HAMMING_WEIGHTS.items():
        if a.get(key) == b.get(key):
            sim += w
    return sim / sum(config.BLUEPRINT_HAMMING_WEIGHTS.values())


REFINE_SYSTEM = """You are the content-planning stage of a CAT VARC generation engine.
You receive a structural blueprint (argument family, paragraph movement plan, persona,
revelation pattern, ending type) plus an optional inspiration essay excerpt.

Your job: invent CONTENT that fits the given structure exactly. You must NOT change
the structure — paragraph count, functions, and order are fixed.

Respond ONLY with valid JSON, no markdown fences:
{
  "topic": "one-line topic, intellectually serious, suitable for Aeon/LRB-style prose",
  "tension_system": {
    "primary": {"axis": "...", "poles": ["...", "..."], "fate": "resolved|left_open|dissolved_not_resolved|displaced"},
    "secondary": {"axis": "...", "poles": ["...", "..."], "fate": "..."},
    "interaction": "one line on how the secondary tension interacts with the primary"
  },
  "paragraph_briefs": [{"para": 1, "gist": "1-2 line content brief realizing that paragraph's structural function"}, ...one per paragraph...],
  "trap_map": [
    {"trap_id": "TR1", "anchor_para": 1, "invited_misreading": "the specific wrong reading this paragraph should invite", "mechanism": "..."},
    ...exactly 3 traps, anchored to different paragraphs...
  ],
  "title_hint": "plausible essay title"
}
Trap mechanisms MUST be chosen from the allowed list given in the input.
The topic must NOT be about the mechanics of test-taking, and must be treatable
without specialist prior knowledge."""


class BlueprintComposer:
    def __init__(self, registry: ComponentRegistry, history: HistoryStore,
                 rules: CompatibilityRules, llm, rng: random.Random | None = None):
        self.registry = registry
        self.history = history
        self.rules = rules
        self.llm = llm
        self.rng = rng or random.Random()

    # ------------------------------------------------------------- sampling

    def _eligible(self, ctype: str, tier: str,
                  ban_families: set[str] | None = None) -> list[str]:
        ids = self.registry.ids(ctype)
        if ctype == "family":
            floor = TIER_ORDER[tier]
            ids = [i for i in ids
                   if TIER_ORDER[self.registry.get("family", i)["tier_floor"]] <= floor]
            ids = self._posture_filter(ids)
            if ban_families:
                filtered = [i for i in ids if i not in ban_families]
                # never empty the pool: fall back rather than dead-end the slot
                if filtered:
                    ids = filtered
        if ctype == "topology":
            allowed = config.TIER_PARAMS[tier]["allowed_topologies"]
            if allowed:
                ids = [i for i in ids if i in allowed]
        # hard exclusion window
        window = config.EXCLUSION_WINDOWS[ctype]
        positions = self.history.component_positions(ctype)
        ids = [i for i in ids if positions.get(i, 10**9) >= window]
        return ids

    def _posture_filter(self, ids: list[str]) -> list[str]:
        """Hard rule: if the last POSTURE_RUN_MAX shipped RCs share one coarse
        closing-posture class, drop families of that class. Falls back to the
        unfiltered pool rather than dead-ending (the 25-wide family exclusion
        window can leave all survivors in the banned class)."""
        recent = self.history.recent_shipped_blueprints(config.POSTURE_RUN_MAX)
        classes = []
        for b in recent:
            try:
                classes.append(posture_class(self.registry.posture_of(b["family"])))
            except Exception:   # legacy row with unknown/missing family id
                continue
        if len(classes) < config.POSTURE_RUN_MAX or len(set(classes)) != 1:
            return ids
        banned = classes[0]
        filtered = [i for i in ids
                    if posture_class(self.registry.posture_of(i)) != banned]
        if not filtered:
            print(f"  [composer] posture ban on '{banned}' skipped: "
                  f"would empty the family pool")
            return ids
        return filtered

    def _weighted_pick(self, ctype: str, ids: list[str]) -> str:
        counts = self.history.usage_counts_trailing(ctype, 100)
        weights = [config.DECAY_LAMBDA ** counts.get(i, 0) for i in ids]
        if ctype == "family":
            # soft pressure on the FINE posture (the hard ban uses the coarse
            # class): postures aggregate many families, so a gentler lambda.
            fam_counts = self.history.usage_counts_trailing(
                "family", config.POSTURE_DECAY_WINDOW)
            pcounts: dict[str, int] = {}
            for fid, n in fam_counts.items():
                try:
                    p = self.registry.posture_of(fid)
                except Exception:
                    continue
                pcounts[p] = pcounts.get(p, 0) + n
            weights = [w * config.POSTURE_DECAY_LAMBDA
                       ** pcounts.get(self.registry.posture_of(i), 0)
                       for w, i in zip(weights, ids)]
        return self.rng.choices(ids, weights=weights, k=1)[0]

    def sample_skeleton(self, tier: str,
                        ban_families: set[str] | None = None,
                        ban_movements: set[str] | None = None) -> dict:
        """Returns {"family": ..., "persona": ..., ...} or raises.

        ban_families / ban_movements: slot-local bans from a prior movement
        collision (precheck or Gate B). Families are dropped from the pool;
        movement strings are checked after the family's function sequence is
        built (same family + rhythm can still insert fillers — reject those).
        """
        ban_f = set(ban_families or ())
        ban_m = set(ban_movements or ())
        order = ["family", "topology", "revelation", "persona", "ending",
                 "rhythm", "distractor_profile"]
        recent = self.history.recent_shipped_blueprints(config.BLUEPRINT_DISTANCE_WINDOW)
        shipped_hashes = self.history.shipped_combo_hashes()
        recent_pairs: set[str] = set()
        for b in recent[:config.PAIR_WINDOW]:
            recent_pairs.update(b["pair_hashes"].values())

        for _ in range(config.MAX_COMPOSE_ATTEMPTS):
            ids: dict[str, str] = {}
            ok = True
            for ctype in order:
                pool = self._eligible(ctype, tier, ban_families=ban_f)
                # drop candidates that violate constraints against already-picked ids
                pool = [c for c in pool if self.rules.is_valid({**ids, ctype: c})]
                if not pool:
                    ok = False
                    break
                ids[ctype] = self._weighted_pick(ctype, pool)
            if not ok:
                continue

            probe = Blueprint(
                blueprint_id="probe", tier=tier,
                schema_version=config.BLUEPRINT_SCHEMA_VERSION,
                family_id=ids["family"], persona_id=ids["persona"],
                ending_id=ids["ending"], rhythm_id=ids["rhythm"],
                revelation_id=ids["revelation"],
                distractor_profile_id=ids["distractor_profile"],
                topology_id=ids["topology"], instability=0.0, aperture="")
            if probe.combo_hash in shipped_hashes:
                continue
            if recent_pairs & set(probe.pair_hashes.values()):
                continue
            worst = max((blueprint_categorical_similarity(ids, b) for b in recent), default=0.0)
            if 1.0 - worst < config.MIN_BLUEPRINT_DISTANCE:
                continue
            # Planned movement must not reuse a banned skeleton (family-fixed
            # function sequence, optional filler inserts).
            if ban_m:
                fam = self.registry.get("family", ids["family"])
                rh = self.registry.get("rhythm", ids["rhythm"])
                ms = "|".join(p.function for p in self._build_movement(fam, rh))
                if ms in ban_m:
                    # force the next attempt off this family
                    ban_f.add(ids["family"])
                    continue
            return ids
        raise CompositionExhausted(
            f"could not sample a valid {tier} blueprint in "
            f"{config.MAX_COMPOSE_ATTEMPTS} attempts — exclusion windows may be "
            f"too tight for the current corpus velocity")

    # ------------------------------------------------------ structure build

    def _build_movement(self, family: dict, rhythm: dict) -> list[ParagraphPlan]:
        functions = list(family["movement"])
        shape = list(rhythm["shape"])
        fillers = list(self.registry.generic_fillers)
        # align paragraph count: pad functions with generic fillers at interior
        # positions, or extend the shape by repeating its middle class
        while len(shape) < len(functions):
            shape.insert(len(shape) // 2, shape[len(shape) // 2])
        while len(functions) < len(shape):
            pos = self.rng.randint(1, len(functions) - 1)
            functions.insert(pos, self.rng.choice(fillers))

        cadences = ["long_periodic", "mixed", "dense_analytic", "staccato"]
        plans = []
        for i, (fn, cls) in enumerate(zip(functions, shape), start=1):
            lo, hi = self.registry.length_class_range(cls)
            cadence = self.rng.choice(cadences)
            plans.append(ParagraphPlan(para=i, function=fn, len_words=(lo, hi), cadence=cadence))
        return plans

    def _scale_lengths(self, plans: list[ParagraphPlan], tier: str) -> list[ParagraphPlan]:
        """Scale paragraph word bands so the passage total lands in the tier's range."""
        lo_t, hi_t = config.TIER_PARAMS[tier]["passage_words"]
        target = (lo_t + hi_t) / 2
        current = sum((p.len_words[0] + p.len_words[1]) / 2 for p in plans)
        f = target / current if current else 1.0
        for p in plans:
            p.len_words = (int(p.len_words[0] * f), int(p.len_words[1] * f))
        return plans

    def _letter_plan(self) -> list[str]:
        """Sampled per set: no letter more than twice, no 3-in-a-row."""
        while True:
            plan = [self.rng.choice("ABCD") for _ in range(6)]
            if max(plan.count(c) for c in "ABCD") > 2:
                continue
            if any(plan[i] == plan[i + 1] == plan[i + 2] for i in range(4)):
                continue
            return plan

    def _revelation_para(self, revelation: dict, n_paras: int) -> int:
        timing = revelation["timing"]
        return {
            "early": 1, "early_hidden": 1,
            "mid": max(2, n_paras // 2),
            "late": max(2, n_paras - 1),
            "penultimate": max(2, n_paras - 1),
            "retrospective": n_paras,
            "split": max(2, n_paras // 2),
            "distributed": max(2, n_paras // 2),
            "never_stated": n_paras,
        }.get(timing, max(2, n_paras - 1))

    # --------------------------------------------------------------- compose

    def compose(self, tier: str, seed: SeedEssay, ledger: CostLedger,
                ban_families: set[str] | None = None,
                ban_movements: set[str] | None = None) -> Blueprint:
        ids = self.sample_skeleton(tier, ban_families=ban_families,
                                   ban_movements=ban_movements)
        family = self.registry.get("family", ids["family"])
        rhythm = self.registry.get("rhythm", ids["rhythm"])
        ending = self.registry.get("ending", ids["ending"])
        revelation = self.registry.get("revelation", ids["revelation"])
        profile = self.registry.get("distractor_profile", ids["distractor_profile"])

        movement = self._scale_lengths(self._build_movement(family, rhythm), tier)
        lo, hi = config.TIER_PARAMS[tier]["instability_range"]
        reg_ids = [r[0] for r in config.CLOSING_REGISTERS]
        reg_wts = [r[1] for r in config.CLOSING_REGISTERS]
        closing_register = self.rng.choices(reg_ids, weights=reg_wts, k=1)[0]

        bp = Blueprint(
            blueprint_id=f"BP_{datetime.now(timezone.utc).strftime('%y%m%d')}_{uuid.uuid4().hex[:8]}",
            tier=tier, schema_version=config.BLUEPRINT_SCHEMA_VERSION,
            family_id=ids["family"], persona_id=ids["persona"], ending_id=ids["ending"],
            rhythm_id=ids["rhythm"], revelation_id=ids["revelation"],
            distractor_profile_id=ids["distractor_profile"], topology_id=ids["topology"],
            instability=round(self.rng.uniform(lo, hi), 2),
            aperture=ending["aperture"], movement=movement,
            letter_plan=self._letter_plan(),
            closing_register=closing_register,
            revelation_detail={"planned_para": self._revelation_para(revelation, len(movement)),
                               "timing": revelation["timing"]},
            seed={"doc_id": seed.doc_id, "url": seed.url, "title": seed.title,
                  "domain_hint": seed.domain_hint},
        )

        # ---- LLM refinement (fills content, never structure) ----
        model, max_tokens = config.STAGE_CONFIG["refine"][tier]
        mechanisms = [profile["primary"], profile["secondary"]]
        base_user = self._refine_user_prompt(bp, family, revelation, ending, profile, seed)
        refined = self._refine_with_retry(bp, model, max_tokens, base_user,
                                          mechanisms, ledger)
        return self._apply_refined(bp, refined, mechanisms)

    def refine_only(self, bp: Blueprint, seed: SeedEssay, ledger: CostLedger,
                    avoid_topics: list[str] | None = None) -> Blueprint:
        """Re-run the refine stage on an existing blueprint (structure stays
        fixed), steering the topic away from avoid_topics. Used by the
        pre-render topic-collision precheck: a re-refine costs ~$0.01-0.03 vs
        ~$0.07 for a render + compliance that novelty would then reject."""
        family = self.registry.get("family", bp.family_id)
        revelation = self.registry.get("revelation", bp.revelation_id)
        ending = self.registry.get("ending", bp.ending_id)
        profile = self.registry.get("distractor_profile", bp.distractor_profile_id)
        model, max_tokens = config.STAGE_CONFIG["refine"][bp.tier]
        mechanisms = [profile["primary"], profile["secondary"]]
        user = self._refine_user_prompt(bp, family, revelation, ending, profile, seed)
        if avoid_topics:
            user += ("\n\nCRITICAL: a previous topic for this structure was too "
                     "semantically close to existing passages. Choose a DIFFERENT "
                     "domain, far from ALL of these:\n  - "
                     + "\n  - ".join(t for t in avoid_topics if t))
        refined = self._refine_with_retry(bp, model, max_tokens, user,
                                          mechanisms, ledger)
        return self._apply_refined(bp, refined, mechanisms)

    def _apply_refined(self, bp: Blueprint, refined: dict,
                       mechanisms: list[str]) -> Blueprint:
        bp.topic = refined.get("topic", "") or bp.topic
        bp.tension_system = refined.get("tension_system", {})
        bp.trap_map = self._sanitize_traps(refined.get("trap_map", []), mechanisms,
                                           len(bp.movement))
        gists = {b.get("para"): b.get("gist", "") for b in refined.get("paragraph_briefs", [])}
        for p in bp.movement:
            p.gist = gists.get(p.para, "")
        return bp

    def _refine_with_retry(self, bp: Blueprint, model: str, max_tokens: int,
                           base_user: str, mechanisms: list[str],
                           ledger: CostLedger) -> dict:
        """One transient empty/truncated/unparseable refine response must never
        crash a batch. Retry with a nudge; if all attempts fail, fall back to a
        deterministic minimal plan so the blueprint is still renderable (the
        structure — the part that matters for novelty — is already fixed)."""
        last_err = "no response"
        user = base_user
        for attempt in range(1, config.MAX_REFINE_ATTEMPTS + 1):
            try:
                text, truncated = self.llm.call(
                    ledger, "refine", model, max_tokens, REFINE_SYSTEM, user,
                    context={"blueprint": bp, "mechanisms": mechanisms})
            except BudgetExceeded:
                raise
            except Exception as e:                       # API hiccup on this attempt
                last_err = f"call error: {e}"
                continue
            if truncated:
                last_err = "truncated"
                user = base_user + "\n\nKeep every field brief; the JSON MUST be complete."
                continue
            if not text or not text.strip():
                last_err = "empty response"
                continue
            try:
                refined = extract_json(text)
            except (ValueError, json.JSONDecodeError) as e:
                last_err = f"unparseable: {e}"
                user = base_user + "\n\nYour previous reply was not valid JSON. Emit ONLY the JSON object."
                continue
            if refined.get("topic") and refined.get("tension_system"):
                return refined
            last_err = "missing required keys"
        print(f"  [refine] all {config.MAX_REFINE_ATTEMPTS} attempts failed "
              f"({last_err}) — using deterministic fallback plan.")
        return self._fallback_refine(bp, mechanisms)

    def _fallback_refine(self, bp: Blueprint, mechanisms: list[str]) -> dict:
        """Content fallback when the refiner is unavailable. Uses the family's
        own description so the render prompt still has a real topic and tension;
        the renderer will flesh out specifics."""
        family = self.registry.get("family", bp.family_id)
        n = len(bp.movement)
        domain = bp.seed.get("domain_hint") or (self.rng.choice(config.DOMAIN_POOL))
        return {
            "topic": f"a live conceptual tension in {domain}",
            "tension_system": {
                "primary": {"axis": family["difficulty_source"],
                            "poles": ["one framing", "its rival"], "fate": "left_open"},
                "secondary": {"axis": "local claim versus global implication",
                              "poles": ["local", "global"], "fate": "displaced"},
                "interaction": "the secondary tension complicates the primary at the passage's turn",
            },
            "paragraph_briefs": [{"para": p.para, "gist": ""} for p in bp.movement],
            "trap_map": [
                {"trap_id": "TR1", "anchor_para": 1, "mechanism": mechanisms[0],
                 "invited_misreading": "the opening framing is the author's settled conclusion"},
                {"trap_id": "TR2", "anchor_para": max(2, n // 2), "mechanism": mechanisms[1],
                 "invited_misreading": "a rehearsed rival position is the one the author endorses"},
                {"trap_id": "TR3", "anchor_para": n, "mechanism": mechanisms[0],
                 "invited_misreading": "the ending resolves the tension more than it does"},
            ],
        }

    def _sanitize_traps(self, traps: list, mechanisms: list[str], n_paras: int) -> list[dict]:
        clean = []
        for i, t in enumerate(traps[:3]):
            mech = t.get("mechanism", mechanisms[0])
            if mech not in self.registry.mechanisms:
                mech = mechanisms[0]
            anchor = t.get("anchor_para", 1)
            if not isinstance(anchor, int) or not 1 <= anchor <= n_paras:
                anchor = min(i + 1, n_paras)
            clean.append({"trap_id": f"TR{i + 1}", "anchor_para": anchor,
                          "invited_misreading": str(t.get("invited_misreading", ""))[:300],
                          "mechanism": mech})
        while len(clean) < 3:
            clean.append({"trap_id": f"TR{len(clean) + 1}",
                          "anchor_para": min(len(clean) + 1, n_paras),
                          "invited_misreading": "over-reading the paragraph's local claim as the passage's final view",
                          "mechanism": mechanisms[0]})
        return clean

    def _refine_user_prompt(self, bp: Blueprint, family: dict, revelation: dict,
                            ending: dict, profile: dict, seed: SeedEssay) -> str:
        seed_part = ""
        if seed.text:
            words = seed.text.split()
            excerpt = " ".join(words[:550])
            seed_part = (f"\nINSPIRATION ESSAY EXCERPT (adapt its domain and intellectual "
                         f"territory; do NOT copy its argument):\n{excerpt}\n")
        else:
            domain = seed.domain_hint or self.rng.choice(config.DOMAIN_POOL)
            seed_part = f"\nNo seed essay. Invent a topic within this domain: {domain}\n"
        movement_lines = "\n".join(
            f"  para {p.para}: {p.function} ({p.len_words[0]}-{p.len_words[1]} words)"
            for p in bp.movement)
        # topical divergence up front (~150 input tokens on the cheap refine
        # model) so passages stop colliding on the embedding channel AFTER the
        # expensive render call; includes recently rejected topics on purpose
        avoid_part = ""
        avoid = self.history.recent_topics(config.REFINE_AVOID_TOPICS)
        if avoid:
            avoid_part = ("\nAVOID these recently used topical territories — invent "
                          "something semantically distant from ALL of them:\n  - "
                          + "\n  - ".join(avoid) + "\n")
        return f"""STRUCTURAL BLUEPRINT (fixed — invent content for it):
ARGUMENT FAMILY: {family['name']} — {family['core']}
Difficulty must come from: {family['difficulty_source']}
PARAGRAPH MOVEMENT PLAN:
{movement_lines}
THESIS REVELATION: {revelation['name']} — {revelation['mechanism']}
(thesis first becomes visible around paragraph {bp.revelation_detail['planned_para']})
ENDING: {ending['name']} — {ending['gesture']} (aperture: {ending['aperture']})
REQUIRED CLOSING POSTURE: {family['closing_posture']} — {self.registry.closing_postures[family['closing_posture']]}
(the 'fate' fields in tension_system must be consistent with this posture)
INSTABILITY DEGREE: {bp.instability} (0 = neat closure, 1 = fully suspended; this governs how contested the middle feels — the ending's stance is governed by the closing posture above)
ALLOWED TRAP MECHANISMS: {profile['primary']}, {profile['secondary']}
{seed_part}{avoid_part}
Produce the JSON now."""
