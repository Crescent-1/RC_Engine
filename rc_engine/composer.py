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
from .llm import APIExhausted, BudgetExceeded, CostLedger, extract_json
from .models import Blueprint, ParagraphPlan, SeedEssay
from .fingerprints import move_signature_similarity
from .generation_policy import LEGACY_POLICY, policy_for_blueprint, policy_for_new_plan
from .registry import ComponentRegistry, posture_class
from .voice_plan import middle_moves, plan_violations, schema_ids_for_shape

NL = chr(10)

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


# coherent_plans (2026-09-14; see GenerationPolicy.coherent_plans for the counts).
# Beat pairs whose glosses contradict: LEVEL_RELOCATION reframes the question,
# UNDERLYING_CAUSE_NAMED names a cause "while leaving the question as posed intact".
CONFLICTING_BEATS = (frozenset({"LEVEL_RELOCATION", "UNDERLYING_CAUSE_NAMED"}),)
# Posture classes (label prefix) whose close must commit to a position.
COMMITTED_POSTURE_CLASSES = ("resolution", "affirmation")

REFINE_SYSTEM = """You are the content-planning stage of a CAT VARC generation engine.
You receive a structural blueprint (argument family, paragraph movement plan, persona,
revelation pattern, ending type) plus an optional inspiration essay excerpt.

Your job: invent CONTENT that fits the given structure exactly. You must NOT change
the structure — paragraph count, functions, and order are fixed.

The TOPIC SHAPE in the input governs what KIND of question the passage is about.
Obey it. Not every passage is a dispute between two positions: when the shape does
not call for one, do NOT manufacture one, and do NOT phrase the topic as
"whether X or Y" or "why X, and what it reveals about Y". Those two forms
accounted for nearly half of this engine's back catalogue and are the single most
recognisable thing about it.

The ARGUMENT SCHEMA fixes what the reasoning must accomplish. The family,
paragraph roles and beats are its implementation, not competing essay briefs.
Give each paragraph a concrete content brief that performs its assigned beats
and advances that schema. Do not invent an objection-and-rebuttal sequence
unless this plan actually calls for one.

Ground the topic in the SOURCE GENRE and the concrete particulars given. A
technical piece should stay technical; a reconstructed episode should stay an
episode. Converting the source into a conceptual essay is the failure mode.

Respond ONLY with valid JSON, no markdown fences:
{
  "topic": "one-line topic, intellectually serious, suitable for Aeon/LRB-style prose",
  "tension_system": {
    "primary": {"axis": "...", "poles": ["...", "..."], "fate": "resolved|left_open|dissolved_not_resolved|displaced"},
    "secondary": {"axis": "...", "poles": ["...", "..."], "fate": "..."},
    "interaction": "one line on how the secondary tension interacts with the primary"
  },
  "content_frame": "<give this INSTEAD of tension_system when the topic shape does not require two poles: 2-3 lines fixing the specific material — the event, the object, the procedure, the measurement — the passage is built from. Emit tension_system as null in that case. When the shape DOES require two poles, give tension_system and omit this.>",
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

    @staticmethod
    def _steer_share(pool: list[str], allow: bool, in_cohort) -> list[str]:
        """Restrict `pool` to the cohort when this skeleton won the share flip,
        and away from it when it did not. Never empties the pool — an absent
        cohort (banned, exhausted, or barred by tier) leaves the pool as-is
        rather than dead-ending the slot."""
        want = [i for i in pool if in_cohort(i) == allow]
        return want or pool

    # Set by RCPipeline when running under workers.py; "" means sequential, and
    # every in-flight lookup below is skipped.
    inflight_worker: str = ""

    def _eligible(self, ctype: str, tier: str,
                  ban_families: set[str] | None = None,
                  allowed_ids: set[str] | None = None,
                  policy=None) -> list[str]:
        policy = policy or LEGACY_POLICY
        # The generation-policy boundary comes first (2026-09-13): no recency,
        # posture or tier fallback below may re-admit a component that belongs
        # to another policy. The tier lets a contract policy drop topologies
        # that cannot carry its negative-slot target (section 4).
        ids = policy.eligible_ids(self.registry, ctype, tier)
        # Compatibility comes before recency: an exhausted recency window
        # may fall back, but must never fall back to an incompatible form.
        if allowed_ids is not None:
            ids = [i for i in ids if i in allowed_ids]
        if not ids:
            return []
        if ctype == "family":
            floor = TIER_ORDER[tier]
            ids = [i for i in ids
                   if TIER_ORDER[self.registry.get("family", i)["tier_floor"]] <= floor]
            # Drop families whose ONLY movement string is already inside the
            # precheck window, BEFORE anything is spent on them.
            #
            # The precheck previously discovered these after compose — which
            # includes the paid refine — and then banned the family. On
            # 2026-08-28 that cost three hard attempts and $0.18 for nothing,
            # and killed the tier: 7 of the 11 single-string hard families were
            # blocked at once, because they are the newest families and had all
            # been used inside the window. Excluding them here changes no
            # outcome; it just stops paying to rediscover it.
            try:
                recent_ms = {w.movement_string for w
                             in self.history.fingerprint_window(
                                 config.MOVEMENT_RECENCY_WINDOW)
                             if w.movement_string}
            except Exception:
                recent_ms = set()
            if recent_ms:
                usable = []
                for i in ids:
                    opts, can_pad = self.family_movement_options(i, policy)
                    if can_pad or not opts or (set(opts) - recent_ms):
                        usable.append(i)
                if usable:            # never empty the pool
                    ids = usable

            # tier_max is a CEILING, the mirror of tier_floor: a family carrying
            # it is unavailable ABOVE that tier. Added 2026-08-25 for the
            # exam-derived expository families — they widen medium and hard,
            # but elite keeps only the literary forms that produce the hardest
            # passages. Absent tier_max means "no ceiling", so every existing
            # family is unaffected.
            ids = [i for i in ids
                   if TIER_ORDER[self.registry.get("family", i)
                                 .get("tier_max", "elite")] >= floor]
            ids = self._posture_filter(ids)
            if ban_families:
                filtered = [i for i in ids if i not in ban_families]
                # never empty the pool: fall back rather than dead-end the slot
                if filtered:
                    ids = filtered
        if ctype == "topology":
            allowed = [i for i in ids if self._topology_allowed(i, tier)]
            # never empty the pool: the same fallback discipline as the posture ban
            if allowed:
                ids = allowed
            else:
                print(f"  [composer] topology bar for '{tier}' skipped: "
                      f"would empty the pool")
        # Exclusion window — recency, not a correctness constraint. It gets the
        # SAME "never empty the pool" fallback as the posture ban and the
        # topology tier bar above, and for the same reason: a window wider than
        # the tier's eligible pool starves it deterministically.
        #
        # Concretely (2026-08-10): EXCLUSION_WINDOWS["family"] is 25, but only 16
        # of 32 families clear medium's tier_floor. With 14 of those inside the
        # window, medium had exactly 2 families left; the movement precheck
        # banned both and every medium in the batch died at failed_composition
        # having spent $0 and produced nothing. Widening recency is never worth
        # dead-ending a tier — degrade to the least-recently-used candidates and
        # say so, rather than returning an empty pool.
        window = config.EXCLUSION_WINDOWS[ctype]
        positions = self.history.component_positions(ctype)
        # A component a live sibling is holding has effectively just been used;
        # it simply is not in the shipped history yet. Folding it in at position
        # 0 reuses the whole window mechanism — including the never-empty-pool
        # fallback below — instead of adding a parallel ban path. Without this a
        # parallel batch loses every exclusion window except family, which is
        # what let two workers take topology QT08 on 2026-09-05 and discover it
        # only after $0.18 of questions.
        if self.inflight_worker:
            try:
                held = self.history.inflight_components(self.inflight_worker)
                for cid in held.get(ctype, ()):
                    positions[cid] = 0
            except Exception:                                # noqa: BLE001
                pass
        fresh = [i for i in ids if positions.get(i, 10**9) >= window]
        if fresh:
            if ctype == "family":
                # A family recency window must never delete an entire ARC SHAPE
                # from the pool.
                #
                # Measured 2026-08-24: 32 of 46 families carry the legacy
                # four-beat arc and had not been used in 25 sets, while all 14
                # new-shape families had been used that day. The window
                # therefore excluded every new shape and left medium with 7
                # candidates, all legacy — the mechanism meant to prevent
                # repetition was enforcing the exact arc we were trying to move
                # away from, and two of three sets in that batch came back
                # flagged as repeats.
                #
                # Recency still applies WITHIN a shape; it just cannot erase the
                # shape. Each missing shape gets back its least-recently-used
                # family only.
                have = {self.registry.shape_of(i) for i in fresh}
                for shape in {self.registry.shape_of(i) for i in ids} - have:
                    members = [i for i in ids
                               if self.registry.shape_of(i) == shape]
                    fresh.append(max(members,
                                     key=lambda i: positions.get(i, 10**9)))
            return fresh
        if not ids:
            return []
        # Oldest-first, so the fallback still maximises distance from recent use.
        ids = sorted(ids, key=lambda i: -positions.get(i, 10**9))
        print(f"  [composer] {ctype} exclusion window ({window}) would empty the "
              f"'{tier}' pool — falling back to the {len(ids)} least-recently-used")
        return ids

    def family_movement_options(self, family_id: str,
                                policy=None) -> tuple[set[str], bool]:
        """(deterministic movement strings, can_randomize) for this family.

        _build_movement pads a family's function sequence with RANDOM generic
        fillers, at a random interior position, whenever the family has fewer
        functions than the rhythm's shape has slots. So a family splits into two
        cases per rhythm:
          - shape fits (no padding) -> exactly one movement string, deterministic
          - shape is longer         -> filler-padded, a fresh string per roll
        Only the first kind can be enumerated; if any rhythm triggers padding the
        family has an open-ended supply and can never be exhausted.
        """
        fam = self.registry.get("family", family_id)
        fixed: set[str] = set()
        can_randomize = False
        rhythms = (policy or LEGACY_POLICY).eligible_ids(self.registry, "rhythm")
        for seq in self._movement_sequences(fam):
            n_functions = len(seq)
            for rid in rhythms:
                shape = self.registry.get("rhythm", rid)["shape"]
                if n_functions < len(shape):
                    can_randomize = True      # fillers are sampled, not fixed
                    continue
                # deterministic case: the sequence IS the movement string, no
                # padding and no reordering, so read it off directly rather
                # than calling _build_movement (which now picks a variant at
                # random and would make this enumeration non-deterministic).
                fixed.add("|".join(seq))
        return fixed, can_randomize

    # NOTE (2026-08-25): an attempt to let long families dodge a movement ban
    # by "inserting a filler" was reverted the same day. _build_movement only
    # pads functions when the family is SHORTER than the rhythm, which never
    # happens for a 5-6 beat family — F47 produces exactly one movement string
    # across all 20 rhythms. Declaring escape routes the builder cannot
    # generate would have left the composer re-sampling the same banned string.
    # A single-string family that collides genuinely is exhausted; the fix for
    # F43/F33/F35/F36 being banned in one batch is that they were drawn too
    # often while new, which the usage decay resolves on its own.

    def family_movement_exhausted(self, family_id: str, ban_m: set[str],
                                  policy=None) -> bool:
        """True only when the family genuinely cannot produce an unbanned
        movement string — the sole case where a collision justifies barring it.

        Conservative by construction: a family that can pad with random fillers
        is never declared exhausted, because re-rolling reaches new strings.
        Being wrong in this direction costs one extra recompose; being wrong the
        other way discards a usable family, which is the bug this replaced.
        """
        fixed, can_randomize = self.family_movement_options(family_id, policy)
        if can_randomize:
            return False
        return not (fixed - set(ban_m or ()))

    def _topology_allowed(self, topology_id: str, tier: str) -> bool:
        """Structural bar only — see config.TIER_TOPOLOGY_BAR. Medium's actual
        difficulty comes from TIER_SLOT_SCALING at question time, not from
        shrinking this pool: a pool near EXCLUSION_WINDOWS['topology'] in size
        both repeats itself and can empty."""
        bar = config.TIER_TOPOLOGY_BAR.get(tier) or {}
        if not bar:
            return True
        slots = self.registry.get("topology", topology_id)["slots"]
        if set(bar.get("forbid_types", ())) & {s["type"] for s in slots}:
            return False
        max_span = bar.get("max_span")
        if max_span is not None:
            if sum(1 for s in slots if s["target"] == "span") > max_span:
                return False
        return True

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
        # The ban must not erase an ARC SHAPE. Same rule as the family exclusion
        # window, and for the same reason it was added there on 2026-08-26.
        #
        # Measured 2026-08-29: all six exam-derived families (F47-F52) close on
        # resolution_qualified, so a two-set resolution run — POSTURE_RUN_MAX is
        # 2, and resolution is 27 of 52 families, so this happens roughly a
        # quarter of the time — removed the whole cohort at once. Realised
        # exam-form share was 0.0% against ceilings of 50% (medium) and 35%
        # (hard). A ban on a posture is a ban on a cadence; it was silently
        # acting as a ban on an entire arc-shape family group.
        kept = set(filtered)
        for shape in {self.registry.shape_of(i) for i in ids}:
            if any(self.registry.shape_of(i) == shape for i in filtered):
                continue
            survivor = next(i for i in ids if self.registry.shape_of(i) == shape)
            kept.add(survivor)
        return [i for i in ids if i in kept]

    def _other_client_counts(self, ctype: str, window: int) -> dict[str, int]:
        """Trailing usage by every OTHER client — the global house-voice term
        (config.GLOBAL_DECAY_LAMBDA). {} while only one client exists, and for
        test doubles that predate clients; either way the term is skipped."""
        fn = getattr(self.history, "usage_counts_other_clients", None)
        if fn is None:
            return {}
        try:
            return fn(ctype, window) or {}
        except Exception:                                    # noqa: BLE001
            return {}

    def _other_client_move_shares(self) -> dict[str, float]:
        """Share of each rhetorical move across other clients' recent sets."""
        fn = getattr(self.history, "fingerprint_window_other_clients", None)
        if fn is None:
            return {}
        try:
            window = fn(config.GLOBAL_MOVE_WINDOW)
        except Exception:                                    # noqa: BLE001
            return {}
        sigs = [w.move_signature.split("|") for w in window if w.move_signature]
        if not sigs:
            return {}
        counts: dict[str, int] = {}
        for moves in sigs:
            for m in set(moves):
                counts[m] = counts.get(m, 0) + 1
        return {m: n / len(sigs) for m, n in counts.items()}

    def _global_pressure(self, ctype: str, ids: list[str],
                         weights: list[float]) -> list[float]:
        other = self._other_client_counts(ctype, config.GLOBAL_USAGE_WINDOW)
        if not other:
            return weights
        return [w * config.GLOBAL_DECAY_LAMBDA ** other.get(i, 0)
                for w, i in zip(weights, ids)]

    def _weighted_pick(self, ctype: str, ids: list[str],
                       tier: str | None = None, policy=None) -> str:
        counts = self.history.usage_counts_trailing(ctype, 100)
        weights = [config.DECAY_LAMBDA ** counts.get(i, 0) for i in ids]
        # Global house-voice pressure (2026-09-12): what other clients were
        # recently given is a slightly rarer draw here. Per-client recency above
        # still decides; see config.GLOBAL_DECAY_LAMBDA.
        weights = self._global_pressure(ctype, ids, weights)
        if ctype == "family":
            # Shape pressure (2026-08-22). Without this the 32 legacy families
            # outvote the 14 new shapes 32:14 on every draw, and since all 32
            # carry the same arc the corpus keeps producing it no matter how
            # evenly the IDs rotate. Weighting by the SHAPE's trailing usage
            # makes an over-used arc cost every family that carries it.
            shape_counts: dict[str, int] = {}
            for fid, cnt in self.history.usage_counts_trailing(
                    "family", config.SHAPE_DECAY_WINDOW).items():
                try:
                    shape_counts[self.registry.shape_of(fid)] = (
                        shape_counts.get(self.registry.shape_of(fid), 0) + cnt)
                except Exception:
                    continue
            # Normalise by how many families carry each shape BEFORE applying
            # the recency penalty.
            #
            # Without this the two decays fight each other and the legacy arc
            # wins: 32 of 46 families share staged_turn_settled, so its trailing
            # uses spread thin and every individual legacy family looks unused,
            # carrying no per-ID penalty — while each of the 14 new families
            # carries its own. Measured 2026-08-24, the composer was drawing the
            # legacy arc 78% of the time, worse than before the shapes existed.
            # Dividing by the family count gives every SHAPE equal total weight,
            # and the recency term then does what it was meant to do.
            per_shape: dict[str, int] = {}
            for fid in ids:
                sh = self.registry.shape_of(fid)
                per_shape[sh] = per_shape.get(sh, 0) + 1
            weights = [w / max(1, per_shape.get(self.registry.shape_of(i), 1))
                       * config.SHAPE_DECAY_LAMBDA
                       ** shape_counts.get(self.registry.shape_of(i), 0)
                       for w, i in zip(weights, ids)]
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
            # Exact cap on the exam-derived forms, applied last so it cannot be
            # undone by the decay terms above. Solve for the scale factor f that
            # puts their aggregate share exactly at the ceiling:
            #     f*We / (f*We + Wo) = cap   ->   f = cap*Wo / ((1-cap)*We)
            # Only ever scales DOWN: if they are already under the cap the
            # decay weighting is left alone.
            # NOTE: the primary control is the up-front coin flip in
            # sample_skeleton. This rescale only smooths the mix WITHIN a draw
            # that is already allowed to use an exam form.
            cap = None
            if cap is not None:
                exam = [k for k, i in enumerate(ids)
                        if self.registry.shape_of(i) in config.EXAM_DERIVED_SHAPES]
                if exam:
                    we = sum(weights[k] for k in exam)
                    wo = sum(weights) - we
                    if cap <= 0:
                        for k in exam:
                            weights[k] = 0.0
                    elif wo > 0 and we > 0 and we / (we + wo) > cap:
                        f = cap * wo / ((1 - cap) * we)
                        for k in exam:
                            weights[k] *= f
        # Policy calibration hook (2026-09-13). The legacy policy returns the
        # same list untouched and consumes no randomness.
        weights = (policy or LEGACY_POLICY).adjust_weights(ctype, ids, weights, self.registry)
        return self.rng.choices(ids, weights=weights, k=1)[0]

    def _move_frequencies(self) -> tuple[dict[str, float], int]:
        """Trailing share of each rhetorical move across the novelty window."""
        window = self.history.fingerprint_window(config.MOVE_SATURATION_WINDOW)
        sigs = [w.move_signature.split("|") for w in window if w.move_signature]
        if not sigs:
            return {}, 0
        counts: dict[str, int] = {}
        for moves in sigs:
            for m in set(moves):
                counts[m] = counts.get(m, 0) + 1
        return {m: n / len(sigs) for m, n in counts.items()}, len(sigs)

    def _plan_collides(self, plan: list[str]) -> tuple[float, str] | None:
        """Worst corpus similarity of a PLANNED move signature, if over cap.

        Free: reuses the stored signatures and the same similarity function
        Gate B scores the rendered passage with. Catching the collision here
        costs a recompose; catching it at Gate B costs the render."""
        if not plan:
            return None
        window = self.history.fingerprint_window(config.FINGERPRINT_WINDOW)
        sigs = [(w.rc_id, w.move_signature.split("|"))
                for w in window if w.move_signature]
        if len(sigs) < 8:
            return None
        freq: dict[str, int] = {}
        for _, moves in sigs:
            for m in set(moves):
                freq[m] = freq.get(m, 0) + 1
        worst, worst_id = 0.0, ""
        for rc_id, moves in sigs:
            sim = move_signature_similarity(plan, moves, freq, len(sigs))
            if sim > worst:
                worst, worst_id = sim, rc_id
        if worst > config.MOVE_PLAN_PRECHECK_CAP:
            return worst, worst_id
        return None

    def _sample_move_plan_checked(self, stance: dict | None,
                                  tier: str | None = None,
                                  movement=None, **voice) -> list[str]:
        """Draw a move plan that does not already collide with the corpus."""
        plan = self._sample_move_plan(stance, tier, movement, **voice)
        for attempt in range(1, config.MOVE_PLAN_PRECHECK_TRIES):
            hit = self._plan_collides(plan)
            if hit is None:
                return plan
            worst, rc_id = hit
            print(f"  [move-plan] planned grammar near {rc_id} @ {worst:.2f} "
                  f"- resampling {attempt}/{config.MOVE_PLAN_PRECHECK_TRIES - 1} ($0)")
            plan = self._sample_move_plan(stance, tier, movement, **voice)
        return plan

    def _plan_length(self, tier: str | None, movement) -> int:
        """How many beats this passage can carry.

        Two bounds. The tier sets the ambition (config.MOVE_PLAN_LEN_BY_TIER);
        the passage's own word budget sets the ceiling, because a beat needs
        room to happen. Measured 2026-09-05: real exam passages give a move ~62
        words and ours were giving 52, which is the crowding that made the
        renderer drop half its planned middle beats.
        """
        lo, hi = config.MOVE_PLAN_LEN_BY_TIER.get(
            tier or "", config.MOVE_PLAN_LEN)
        want = self.rng.randint(lo, hi)
        words = sum(p.len_words[1] for p in movement) if movement else 0
        if words:
            ceiling = max(3, int(words // config.MIN_WORDS_PER_BEAT))
            want = min(want, ceiling)
        return max(3, want)

    @staticmethod
    def allocate_beats(move_plan: list[str], movement) -> list[list[str]]:
        """Assign each beat to a paragraph, in order, PROPORTIONAL to that
        paragraph's word budget.

        Every other constraint in the render contract carries an address -- the
        word target, the paragraph role, the thesis paragraph, the trap anchor --
        and every one of them is obeyed. The beat plan was the only instruction
        with no location ("each beat may span or share paragraphs"), and it was
        obeyed 51% of the time. The two beats that DID get addresses, the first
        and last sentence, went from 2/9 to 5/5 the moment they got them.

        Proportional rather than uniform because the rhythm library already
        varies paragraph length hard (T02 Staircase runs S,M,L,XL; T03 runs the
        reverse), and real exam passages are back-loaded -- last paragraph 3.4
        beats against a 2.5-beat opener, 7 of 10 passages carrying their heaviest
        load last. Riding the rhythm reproduces that where the rhythm calls for
        it, and front-loads where it does not, without a new component or a
        fixed rule.

        A paragraph under config.SINGLE_BEAT_PARA_WORDS carries at most one
        beat, so an S-class paragraph is never handed three operations.
        """
        n = len(movement or [])
        if not move_plan or n == 0:
            return [list(move_plan or [])]
        if n == 1:
            return [list(move_plan)]
        words = [max(1, p.len_words[1]) for p in movement]
        total_w = sum(words)
        # Largest-remainder apportionment, so the beats always sum to the plan.
        exact = [w * len(move_plan) / total_w for w in words]
        take = [int(x) for x in exact]
        for i in sorted(range(n), key=lambda i: exact[i] - take[i], reverse=True):
            if sum(take) >= len(move_plan):
                break
            take[i] += 1
        # short paragraphs cannot be overloaded; spill into the roomiest one
        for i in range(n):
            if words[i] < config.SINGLE_BEAT_PARA_WORDS and take[i] > 1:
                spill = take[i] - 1
                take[i] = 1
                j = max(range(n), key=lambda k: words[k] - take[k] * 40)
                take[j] += spill
        # the opening beat belongs to paragraph 1 and the closing to the last
        take[0] = max(1, take[0])
        take[-1] = max(1, take[-1])
        while sum(take) > len(move_plan):
            j = max((k for k in range(n) if take[k] > 1),
                    key=lambda k: take[k], default=None)
            if j is None:
                break
            take[j] -= 1
        out, cur = [], 0
        for k in take:
            out.append(move_plan[cur:cur + k])
            cur += k
        if cur < len(move_plan):          # rounding leftovers ride the last para
            out[-1].extend(move_plan[cur:])
        return out

    def _sample_move_plan(self, stance: dict | None,
                          tier: str | None = None, movement=None,
                          schema_id: str = "", ending_id: str = "",
                          posture: str = "", family_id: str = "",
                          policy=None) -> list[str]:
        """Prescribe the passage's rhetorical beats, rarest-first.

        Replaces the ban list that shipped on 2026-08-21 and did not work. The
        render contract already carried 'do not perform LEVEL_RELOCATION' from
        two directions, and RC-ELITE-260821-0050 performed it anyway, along with
        both other banned moves and a forbidden aphorism ending. The engine's
        POSITIVE instructions — the paragraph movement plan — are obeyed
        reliably in the same prompt, so the grammar is prescribed here instead
        of forbidden there.

        Weighting is (1 - trailing_share) ** MOVE_PLAN_RARITY_POWER, so the
        moves that made the corpus monotone (LEVEL_RELOCATION at 96%,
        EASY_READING_DEMOLISHED at 86%) become rare draws rather than banned
        ones — they can still appear when a passage genuinely wants them.
        """
        policy = policy or LEGACY_POLICY
        groups = policy.move_groups()
        exam_shares = policy.exam_move_shares()
        shares, n = self._move_frequencies()
        other_shares = self._other_client_move_shares()
        banned = set((stance or {}).get("forbidden_beats", []))
        if schema_id:
            banned.update(policy.family_forbidden_moves(family_id))

        def clashes(m: str, taken: set[str]) -> bool:
            return policy.coherent_plans and any(
                m in pair and (pair - {m}) & taken for pair in CONFLICTING_BEATS)

        def pick(pool: list[str], k: int, taken: set[str]) -> list[str]:
            out: list[str] = []
            for _ in range(k):
                cands = [m for m in pool if m not in taken and m not in banned
                         and not clashes(m, taken)]
                if not cands and schema_id:
                    break  # fewer useful operations beats repeating or violating the stance
                if not cands:
                    cands = [m for m in pool if m not in taken] or list(pool)
                weights = [max(0.01, (1.0 - shares.get(m, 0.0))
                               ** config.MOVE_PLAN_RARITY_POWER) for m in cands]
                if schema_id:
                    # The reference distribution is uneven. Recency pressure
                    # should not turn a rare stylistic trick into a duty.
                    weights = [w * exam_shares.get(m, 0.08)
                               for w, m in zip(weights, cands)]
                if other_shares:
                    # The house voice is one voice across every client: a beat
                    # other clients' passages lean on is a softer rarity here.
                    weights = [w * max(0.01, 1.0 - other_shares.get(m, 0.0))
                               ** config.GLOBAL_MOVE_RARITY_POWER
                               for w, m in zip(weights, cands)]
                choice = self.rng.choices(cands, weights=weights, k=1)[0]
                out.append(choice)
                taken.add(choice)
            return out

        total = self._plan_length(tier, movement)
        taken: set[str] = set()
        opening = pick(groups["opening"], 1, taken)
        close_pool = groups["closing"]
        if schema_id:
            close_pool = [m for m in close_pool
                          if m in policy.closing_beats(ending_id, posture, family_id)
                          and m not in banned]
            if not close_pool:
                raise CompositionExhausted("ending and stance have no compatible closing beat")
        closing = pick(close_pool, 1, taken)
        required = (list(policy.schema_forms()[schema_id]["required_middle"])
                    if schema_id else [])
        if banned & set(required):
            raise CompositionExhausted("stance forbids a defining operation of the schema")
        taken.update(required)
        middle_pool = groups["middle"]
        if schema_id:
            middle_pool = [m for m in middle_pool if m in middle_moves(schema_id, policy)]
        middles = required + pick(middle_pool, max(0, total - 2 - len(required)), taken)
        return opening + middles + closing

    def sample_skeleton(self, tier: str,
                        ban_families: set[str] | None = None,
                        ban_movements: set[str] | None = None,
                        argument_schema_id: str = "",
                        policy=None, seed_genre: str = "") -> dict:
        """Returns {"family": ..., "persona": ..., ...} or raises.

        ban_families / ban_movements: slot-local bans from a prior movement
        collision (precheck or Gate B). Families are dropped from the pool;
        movement strings are checked after the family's function sequence is
        built (same family + rhythm can still insert fillers — reject those).
        policy: the generation policy the plan is composed under; None = legacy.
        """
        policy = policy or LEGACY_POLICY
        schema_forms = policy.schema_forms()
        exam_shapes = policy.exam_derived_shapes()
        ban_f = set(ban_families or ())
        ban_m = set(ban_movements or ())

        # Decide up front whether THIS blueprint may take an exam-derived form,
        # then hold that decision across every retry.
        #
        # Capping inside the per-draw weighting was not enough: sample_skeleton
        # resamples on combo-hash, pair-hash, distance and movement-ban
        # rejections, and exam-form candidates survive those at a different
        # rate, so the realised share drifted above the ceiling (hard measured
        # 40.8% against a 35% cap). One coin flip per skeleton makes the share
        # exact regardless of how many retries follow.
        cap = config.EXAM_FORM_MAX_SHARE.get(tier, 0.0)
        allow_exam_form = self.rng.random() < cap
        # Same up-front coin flip, same reason (see the note above): decided once
        # per skeleton so the realised share matches the ceiling exactly instead
        # of drifting with the retry pattern.
        allow_first_person = self.rng.random() < getattr(
            config, "FIRST_PERSON_MAX_SHARE", 1.0)
        order = ["family", "topology", "revelation", "persona", "ending",
                 "rhythm", "distractor_profile", "render_stance"]
        recent = self.history.recent_shipped_blueprints(config.BLUEPRINT_DISTANCE_WINDOW)
        shipped_hashes = self.history.shipped_combo_hashes()
        recent_pairs: set[str] = set()
        for b in recent[:config.PAIR_WINDOW]:
            recent_pairs.update(b["pair_hashes"].values())

        for _ in range(config.MAX_COMPOSE_ATTEMPTS):
            ids: dict[str, str] = {}
            ok = True
            for ctype in order:
                forms = schema_forms.get(argument_schema_id, {})
                allowed = forms.get(ctype)
                if ctype == "render_stance" and allowed == set():
                    ids[ctype] = ""  # the schema itself supplies the writing stance
                    continue
                if ctype == "revelation" and argument_schema_id:
                    # Section 5.2 (2026-09-13): a revelation whose timing the
                    # schema's directive contradicts is not eligible. Empty for
                    # every policy without exclusions, which leaves this a no-op.
                    excluded = policy.revelations_excluded_by(argument_schema_id)
                    if excluded:
                        allowed = {i for i in policy.eligible_ids(self.registry, ctype)
                                   if i not in excluded}
                pool = self._eligible(ctype, tier, ban_families=ban_f,
                                      allowed_ids=allowed, policy=policy)
                if (ctype == "revelation" and policy.coherent_plans and "family" in ids
                        and self.registry.posture_of(ids["family"]).split("_")[0]
                        in COMMITTED_POSTURE_CLASSES):
                    # A thesis that is never stated cannot also be the verdict
                    # the close must commit to (see GenerationPolicy.coherent_plans).
                    pool = [i for i in pool
                            if self.registry.get(ctype, i).get("timing") != "never_stated"]
                bound = policy.family_bound_components.get(ctype)
                if bound and "family" in ids:
                    # e.g. E21 "The Scope Fixed" only closes F61 (2026-09-13);
                    # a bound component never joins another family.
                    pool = [i for i in pool if i not in bound or ids["family"] in bound[i]]
                if ctype == "persona" and policy.genre_filtered_personas and seed_genre \
                        and seed_genre != "unknown":
                    # A persona that names the genres it can carry is drawn only
                    # for those (section 5.3: P21-P23 need compatible material).
                    # Never empties the pool.
                    fits = [i for i in pool
                            if seed_genre in (self.registry.get(ctype, i).get("compatible_genres")
                                              or [seed_genre])]
                    pool = fits or pool
                if ctype == "render_stance" and argument_schema_id:
                    required = set(forms["required_middle"])
                    endings = policy.closing_beats(ids["ending"], self.registry.posture_of(ids["family"]),
                                                   ids["family"])
                    pool = [i for i in pool
                            if not required.intersection(self.registry.get(ctype, i)["forbidden_beats"])
                            and endings.difference(self.registry.get(ctype, i)["forbidden_beats"])
                            and (i != "RS04" or self.registry.get("persona", ids["persona"]).get(
                                "pronoun_person") == "first_singular")]
                # A share ceiling has to steer BOTH ways. Permitting a cohort
                # on the winning flip and then letting it compete against the
                # whole pool multiplies the two probabilities: measured
                # 2026-08-29, a 20% first-person ceiling realised 4-5%, because
                # the flip passed 20% of the time and the sampler then drew a
                # first-person persona 30% of the time (0.20 x 0.30 = 6%). So
                # the winning flip restricts TO the cohort and the losing flip
                # restricts AWAY from it, which makes realised == cap.
                if ctype == "family":
                    pool = self._steer_share(
                        pool, allow_exam_form,
                        lambda i: (self.registry.shape_of(i) in exam_shapes))
                if ctype == "persona":
                    pool = self._steer_share(
                        pool, allow_first_person,
                        lambda i: (self.registry.get("persona", i).get(
                            "pronoun_person") == "first_singular"))
                # drop candidates that violate constraints against already-picked ids
                pool = [c for c in pool if self.rules.is_valid({**ids, ctype: c})]
                if not pool:
                    ok = False
                    break
                ids[ctype] = self._weighted_pick(ctype, pool, tier, policy)
            if not ok:
                continue

            probe = Blueprint(
                blueprint_id="probe", tier=tier,
                schema_version=config.BLUEPRINT_SCHEMA_VERSION,
                family_id=ids["family"], persona_id=ids["persona"],
                ending_id=ids["ending"], rhythm_id=ids["rhythm"],
                revelation_id=ids["revelation"],
                distractor_profile_id=ids["distractor_profile"],
                topology_id=ids["topology"], instability=0.0, aperture="",
                render_stance_id=ids.get("render_stance", ""))
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
                    # Re-sample rather than banning the family. A family produces
                    # 3-5 distinct movement strings across the rhythm library, so
                    # one banned string leaves several usable; escalating to a
                    # family ban here threw those away and burned through the
                    # pool a family at a time. Only bar the family once EVERY
                    # movement string it can produce is banned.
                    if self.family_movement_exhausted(ids["family"], ban_m, policy):
                        ban_f.add(ids["family"])
                    continue
            return ids
        raise CompositionExhausted(
            f"could not sample a valid {tier} blueprint in "
            f"{config.MAX_COMPOSE_ATTEMPTS} attempts — exclusion windows may be "
            f"too tight for the current corpus velocity")

    # ------------------------------------------------------ structure build

    def _movement_sequences(self, family: dict) -> list[list[str]]:
        """Every function sequence this family may legitimately run.

        `movement` is the canonical order; `movement_variants` holds genuine
        alternative orderings written by hand. Added 2026-08-29: a family with
        5+ functions is never shorter than any rhythm shape (13 of 20 shapes
        are 4 slots, 4 are 5, 3 are 3), so _build_movement never pads it and it
        produces exactly ONE movement string across all 20 rhythms. Fourteen
        families were in that state, and movement similarity was the second
        largest drag on the novelty composite, with lev=1.00 exact collisions
        recurring in every batch.

        Filler padding was the only source of variety before this, and a
        generic filler is a weaker thing than a real reordering — the variants
        are authored so the alternative is an argument the family could
        actually make, not a spacer.
        """
        seqs = [list(family["movement"])]
        for v in family.get("movement_variants") or []:
            v = list(v)
            if v and v not in seqs:
                seqs.append(v)
        return seqs

    def _build_movement(self, family: dict, rhythm: dict) -> list[ParagraphPlan]:
        functions = list(self.rng.choice(self._movement_sequences(family)))
        shape = list(rhythm["shape"])
        fillers = list(self.registry.generic_fillers)
        if rhythm.get("exclude_fillers"):
            # 2026-09-13 (T21/T22): a rhythm may refuse a filler. CONCESSION_TRAP
            # pads a short family into the concede-then-pivot spine the beat
            # plan is fighting; newsroom and explainer cadences do not want it.
            # Legacy rhythms carry no such field, so their draws are unchanged.
            fillers = [f for f in fillers if f not in rhythm["exclude_fillers"]] or fillers
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
        """Scale the rhythm's paragraph bands into a plan whose per-paragraph
        word targets sum to EXACTLY the tier target.

        Each paragraph ends up with a single target (stored as a degenerate
        (n, n) band so nothing downstream has to change shape). Two reasons:
        the renderer hits a stated integer far more reliably than a range, and
        the old `int()` on both bounds truncated every paragraph downward, so
        the plan the model saw never added up to the total the same prompt
        asked for."""
        lo_t, hi_t = config.TIER_PARAMS[tier]["passage_words"]
        target = int(round((lo_t + hi_t) / 2))
        current = sum((p.len_words[0] + p.len_words[1]) / 2 for p in plans)
        f = target / current if current else 1.0

        raw = [((p.len_words[0] + p.len_words[1]) / 2) * f for p in plans]
        sized = [max(1, round(x)) for x in raw]
        # Rounding leaves a few words of drift; hand them to the paragraphs that
        # lost the most in rounding (or take them from the ones that gained).
        drift = target - sum(sized)
        if drift and sized:
            step = 1 if drift > 0 else -1
            order = sorted(range(len(sized)), key=lambda i: raw[i] - sized[i],
                           reverse=drift > 0)
            for k in range(abs(drift)):
                i = order[k % len(order)]
                sized[i] = max(1, sized[i] + step)
        for p, n in zip(plans, sized):
            p.len_words = (n, n)
        return plans

    def _letter_plan(self) -> list[str]:
        """Sampled per set: no letter over-represented, no 3-in-a-row.

        The cap is N//4 + 1, not a literal 2. At 6 questions those are the same
        thing, but at 8 a cap of 2 would force EXACTLY two of each letter in
        every set — itself a usable tell, and a strictly worse one than the
        imbalance it was meant to prevent. N//4 + 1 keeps the cap one above
        perfectly even, so 3/2/2/1 and 2/2/2/2 are both reachable.
        """
        n = config.QUESTIONS_PER_SET
        cap = n // 4 + 1
        while True:
            plan = [self.rng.choice("ABCD") for _ in range(n)]
            if max(plan.count(c) for c in "ABCD") > cap:
                continue
            if any(plan[i] == plan[i + 1] == plan[i + 2] for i in range(n - 2)):
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

    def classify_and_pick_shape(self, seed: SeedEssay, ledger: CostLedger,
                                tier: str, policy=None) -> tuple[dict, str]:
        """Read the seed, then choose a topic shape it can actually carry.

        Runs before any expensive stage, so a seed whose genre the corpus is
        already saturated with can be rotated for a tenth of a cent instead of
        being discovered after a $0.02 refine. Returns (info, topic_shape_id).
        """
        from .seed_classify import (classify_seed, eligible_topic_shapes,
                                    genre_is_saturated)

        policy = policy or policy_for_new_plan(tier)
        menu = ""
        if policy.seed_fidelity:
            from .seed_classify import shape_menu
            menu = shape_menu(self.registry, policy.eligible_ids(self.registry, "topic_shape"))
        stored = getattr(seed, "labels", None)
        if stored:
            # 2026-09-14: labelled once in the seed store (seed_labels.py); the
            # stored shapes cover the whole library, filtered per policy below.
            info = dict(stored)
            print("  [seed] labels from the seed store")
        else:
            info = classify_seed(seed, self.llm, ledger, tier, menu=menu)
        info["saturated"] = genre_is_saturated(self.history, info["genre"])
        if menu and getattr(seed, "text", ""):
            print(f"  [seed] shapes this essay can carry: "
                  f"{', '.join(info.get('carriable_shapes') or []) or 'none reported'}")

        eligible = eligible_topic_shapes(self.registry, info, policy)
        # Ceiling on groups of shapes that ask the same question, BEFORE the
        # inverse-frequency draw below. It has to come first: the decay weight
        # is a soft preference, and two shapes that are each individually rare
        # can still be the same passage three times running -- which is exactly
        # what TS06/TS12 did (see config.TOPIC_SHAPE_COHORT_MAX_SHARE).
        #
        # Bidirectional, like every other share ceiling here: restrict TO the
        # cohort on a winning flip and AWAY from it on a losing one. A
        # permit-only flip multiplies two probabilities and under-binds; that
        # is how FIRST_PERSON_MAX_SHARE realised 4-5% against a 20% ceiling.
        cohorts = list(getattr(config, 'TOPIC_SHAPE_COHORT_MAX_SHARE', []))
        if policy.seed_fidelity:
            # 2026-09-14: see config.SEED_FIDELITY_COHORT_MAX_SHARE.
            cohorts += list(getattr(config, 'SEED_FIDELITY_COHORT_MAX_SHARE', []))
        for cohort, cap in cohorts:
            eligible = self._steer_share(
                eligible, self.rng.random() < cap, lambda i, c=cohort: i in c)
        # Same inverse-frequency logic the move plan and arc shapes use: a
        # shape the recent corpus leans on becomes a rare draw rather than a
        # banned one.
        counts = self.history.usage_counts_trailing("topic_shape", 30) \
            if hasattr(self.history, "usage_counts_trailing") else {}
        weights = [config.DECAY_LAMBDA ** counts.get(i, 0) for i in eligible]
        weights = self._global_pressure("topic_shape", eligible, weights)
        weights = policy.adjust_weights("topic_shape", eligible, weights, self.registry)
        shape_id = self.rng.choices(eligible, weights=weights, k=1)[0]
        return info, shape_id

    def sample_argument_schema(self, eligible: list[str] | None = None,
                               policy=None) -> str:
        """Draw what the argument will DO, weighted to the exam's measured
        distribution and damped by recent use.

        Weighted to the EXAM, not to uniform: the exam runs S4 at 30.6% and
        S2 at 25.8%, and flattening those would be as wrong as the
        monoculture this replaces. The engine's own last 32 sets ran S1 at
        46.9% against the exam's 12.9%, while never once producing S5 or S8.

        Damping is multiplicative on top of the exam weight rather than a
        hard exclusion window, for the same reason: a window would force
        uniformity on a distribution that is deliberately uneven.
        """
        schemas = (policy or LEGACY_POLICY).argument_schemas()
        ids = list(schemas) if eligible is None else list(eligible)
        if not ids:
            raise CompositionExhausted("no argument schema fits the source's topic shape")
        try:
            measured = getattr(self.history, "argument_schema_counts", None)
            counts = (measured(config.ARGUMENT_SCHEMA_WINDOW) if measured else
                      self.history.usage_counts_trailing(
                          'argument_schema', config.ARGUMENT_SCHEMA_WINDOW))
        except Exception:                                    # noqa: BLE001
            counts = {}
        lam = config.ARGUMENT_SCHEMA_DECAY_LAMBDA
        weights = [schemas[i]['exam_share'] * lam ** counts.get(i, 0)
                   for i in ids]
        measured = getattr(self.history, "argument_schema_counts", None)
        if measured:
            other = measured(config.GLOBAL_USAGE_WINDOW, scope="others")
            weights = [w * config.GLOBAL_DECAY_LAMBDA ** other.get(i, 0)
                       for i, w in zip(ids, weights)]
        else:
            weights = self._global_pressure("argument_schema", ids, weights)
        if not any(weights):          # every schema saturated: fall back flat
            weights = [1.0] * len(ids)
        return self.rng.choices(ids, weights=weights, k=1)[0]

    def _fallback_topic_shape(self, seed_info, policy, tried: list[str]) -> str | None:
        from .seed_classify import eligible_topic_shapes
        options = [t for t in eligible_topic_shapes(self.registry, seed_info or {}, policy)
                   if t not in tried and schema_ids_for_shape(t, policy)]
        return self.rng.choice(options) if options else None

    def compose(self, tier: str, seed: SeedEssay, ledger: CostLedger,
                ban_families: set[str] | None = None,
                ban_movements: set[str] | None = None,
                seed_info: dict | None = None,
                topic_shape_id: str = "", policy=None) -> Blueprint:
        # 2026-09-13: every draw below happens under one generation policy,
        # resolved once for the plan and stored on it.
        policy = policy or policy_for_new_plan(tier)
        # 2026-09-12: choose the reasoning purpose before content exists.
        # Retry incompatible/exhausted schemas locally, never after a paid
        # refiner has already committed to a different argument.
        schemas = schema_ids_for_shape(topic_shape_id, policy)
        ids = None
        tried_shapes = [topic_shape_id]
        while True:
            while schemas:
                schema_id = self.sample_argument_schema(schemas, policy)
                try:
                    ids = self.sample_skeleton(tier, ban_families=ban_families,
                                               ban_movements=ban_movements,
                                               argument_schema_id=schema_id,
                                               policy=policy,
                                               seed_genre=(seed_info or {}).get("genre", ""))
                    break
                except CompositionExhausted:
                    schemas.remove(schema_id)
            if ids is not None or policy.reads_legacy or not topic_shape_id:
                break
            # 2026-09-13 (measured in tools/cat_pyq/simulate_policies.py): a
            # section-5 topic shape can lead to a single schema with a single
            # family (TS15 -> S9 -> F60). Once that family's revelation and
            # ending pairs sit in the recent-pair window every skeleton collides,
            # and the attempt died as failed_composition — 10 of 80 hard attempts
            # under cat-pyq-s1. A non-legacy plan instead falls back, at most
            # twice, to another topic shape this seed can carry. Legacy plans
            # keep failing exactly as before.
            nxt = self._fallback_topic_shape(seed_info, policy, tried_shapes)
            if nxt is None or len(tried_shapes) > 2:
                break
            print(f"  [composer] topic shape {topic_shape_id} exhausted for {tier} - "
                  f"falling back to {nxt}")
            topic_shape_id = nxt
            tried_shapes.append(nxt)
            schemas = schema_ids_for_shape(topic_shape_id, policy)
        if ids is None:
            raise CompositionExhausted("no compatible schema/family remains for this source and tier")
        family = self.registry.get("family", ids["family"])
        rhythm = self.registry.get("rhythm", ids["rhythm"])
        ending = self.registry.get("ending", ids["ending"])
        revelation = self.registry.get("revelation", ids["revelation"])
        profile = self.registry.get("distractor_profile", ids["distractor_profile"])

        movement = self._scale_lengths(self._build_movement(family, rhythm), tier)
        lo, hi = config.TIER_PARAMS[tier]["instability_range"]
        stance = self.registry.get("render_stance", ids["render_stance"]) if ids.get("render_stance") else None
        move_plan = self._sample_move_plan_checked(
            stance, tier, movement, schema_id=schema_id,
            ending_id=ids["ending"], posture=family["closing_posture"], family_id=ids["family"],
            policy=policy)
        registers = [r for r in config.CLOSING_REGISTERS
                     if r[0] in policy.closing_registers_by_beat()[move_plan[-1]]]
        reg_ids = [r[0] for r in registers]
        reg_wts = [r[1] for r in registers]
        closing_register = self.rng.choices(reg_ids, weights=reg_wts, k=1)[0]

        bp = Blueprint(
            blueprint_id=f"BP_{datetime.now(timezone.utc).strftime('%y%m%d')}_{uuid.uuid4().hex[:8]}",
            tier=tier, schema_version=config.BLUEPRINT_SCHEMA_VERSION,
            family_id=ids["family"], persona_id=ids["persona"], ending_id=ids["ending"],
            rhythm_id=ids["rhythm"], revelation_id=ids["revelation"],
            distractor_profile_id=ids["distractor_profile"], topology_id=ids["topology"],
            render_stance_id=ids.get("render_stance", ""),
            topic_shape_id=topic_shape_id,
            argument_schema_id=schema_id,
            voice_plan_version="2026-09-12",
            generation_policy=policy.version,
            seed_genre=(seed_info or {}).get("genre", ""),
            move_plan=move_plan,
            instability=round(self.rng.uniform(lo, hi), 2),
            aperture=ending["aperture"], movement=movement,
            letter_plan=self._letter_plan(),
            closing_register=closing_register,
            revelation_detail={"planned_para": self._revelation_para(revelation, len(movement)),
                               "timing": revelation["timing"]},
            seed={"doc_id": seed.doc_id, "url": seed.url, "title": seed.title,
                  "domain_hint": seed.domain_hint},
        )

        if policy.seed_fidelity:
            # 2026-09-14: the anchor rides on the plan so a re-refine or a plan
            # check later in the attempt reads what this compose read.
            from .seed_fidelity import anchor_from
            bp.seed.update(anchor_from(seed, seed_info))

        issues = plan_violations(bp, self.registry)
        if issues:
            raise CompositionExhausted("incompatible voice plan: " + "; ".join(issues))

        # ---- LLM refinement (fills content, never structure) ----
        model, max_tokens = config.STAGE_CONFIG["refine"][tier]
        mechanisms = [profile["primary"], profile["secondary"]]
        base_user = self._refine_user_prompt(bp, family, revelation, ending, profile, seed)
        refined = self._refine_with_retry(bp, model, max_tokens, base_user,
                                          mechanisms, ledger, seed)
        return self._apply_refined(bp, refined, mechanisms, seed)

    def refine_only(self, bp: Blueprint, seed: SeedEssay, ledger: CostLedger,
                    avoid_topics: list[str] | None = None,
                    fidelity_failure: str = "") -> Blueprint:
        """Re-run the refine stage on an existing blueprint (structure stays
        fixed), steering the topic away from avoid_topics. Used by the
        pre-render topic-collision precheck: a re-refine costs ~$0.01-0.03 vs
        ~$0.07 for a render + compliance that novelty would then reject.

        fidelity_failure (seed-fidelity plans, 2026-09-14): why the previous
        plan failed the seed check, restated so the re-plan returns to the
        seed's subject."""
        family = self.registry.get("family", bp.family_id)
        revelation = self.registry.get("revelation", bp.revelation_id)
        ending = self.registry.get("ending", bp.ending_id)
        profile = self.registry.get("distractor_profile", bp.distractor_profile_id)
        model, max_tokens = config.STAGE_CONFIG["refine"][bp.tier]
        mechanisms = [profile["primary"], profile["secondary"]]
        user = self._refine_user_prompt(bp, family, revelation, ending, profile, seed)
        fidelity = policy_for_blueprint(bp).seed_fidelity
        if avoid_topics and fidelity:
            # Changing domain is exactly what f3 forbids: the collision is
            # escaped by angle, question or particulars inside the seed's subject.
            user += ("\n\nCRITICAL: a previous topic for this structure was too "
                     "semantically close to existing passages. Keep the source essay's "
                     "subject and kind of material, and choose a different angle, question "
                     "or set of particulars within it, far from ALL of these:\n  - "
                     + "\n  - ".join(t for t in avoid_topics if t))
        elif avoid_topics:
            user += ("\n\nCRITICAL: a previous topic for this structure was too "
                     "semantically close to existing passages. Choose a DIFFERENT "
                     "domain, far from ALL of these:\n  - "
                     + "\n  - ".join(t for t in avoid_topics if t))
        if fidelity_failure and fidelity:
            user += ("\n\nCRITICAL: the previous plan left the source essay "
                     f"({fidelity_failure}). Re-plan on the essay's own subject, as the "
                     "same kind of material, with the structure unchanged.")
        refined = self._refine_with_retry(bp, model, max_tokens, user,
                                          mechanisms, ledger, seed)
        return self._apply_refined(bp, refined, mechanisms, seed)

    def _apply_facts(self, bp: Blueprint, refined: dict, seed) -> None:
        """Section 6 (2026-09-13): keep the refiner's candidate facts that survive
        structural validation, and swap planned beats the survivors cannot carry.
        Only rejection REASONS are recorded; source text never reaches a log."""
        from .source_facts import replace_unsupported_beats, validate
        facts, reasons = validate(refined.get("source_facts") or [], seed,
                                  strict=policy_for_blueprint(bp).strict_source_fact_audit)
        bp.source_facts = facts
        notes = [f"source facts: {len(facts)} kept"
                 + (f", {len(reasons)} rejected ({'; '.join(sorted(set(reasons)))})"
                    if reasons else "")]
        if bp.move_plan:
            policy = policy_for_blueprint(bp)
            stance = (self.registry.get("render_stance", bp.render_stance_id)
                      if bp.render_stance_id else {})
            forbidden = (set(stance.get("forbidden_beats", []))
                         | policy.family_forbidden_moves(bp.family_id))
            bp.move_plan, swapped = replace_unsupported_beats(bp.move_plan, facts, forbidden)
            notes.extend(swapped)
        bp.source_fact_notes = notes
        print(f"  [facts] {notes[0]}" + (f"; {'; '.join(notes[1:])}" if notes[1:] else ""))

    def _apply_refined(self, bp: Blueprint, refined: dict,
                       mechanisms: list[str], seed=None) -> Blueprint:
        bp.topic = refined.get("topic", "") or bp.topic
        bp.tension_system = refined.get("tension_system") or {}
        if refined.get("content_frame"):
            # Shapes that do not run on two poles still need their material
            # fixed somewhere the renderer will read. tension_system is
            # consumed with `or {}` downstream, so an absent one is safe.
            bp.tension_system["content_frame"] = str(refined["content_frame"])
        bp.trap_map = self._sanitize_traps(refined.get("trap_map", []), mechanisms,
                                           len(bp.movement))
        gists = {b.get("para"): b.get("gist", "") for b in refined.get("paragraph_briefs", [])}
        for p in bp.movement:
            p.gist = gists.get(p.para, "")
        if policy_for_blueprint(bp).source_facts:
            self._apply_facts(bp, refined, seed)
        return bp

    def _refine_with_retry(self, bp: Blueprint, model: str, max_tokens: int,
                           base_user: str, mechanisms: list[str],
                           ledger: CostLedger, seed=None) -> dict:
        """One transient empty/truncated/unparseable refine response must never
        crash a batch. Retry with a nudge; if all attempts fail, fall back to a
        deterministic minimal plan so the blueprint is still renderable (the
        structure — the part that matters for novelty — is already fixed)."""
        last_err = "no response"
        user = base_user
        policy = policy_for_blueprint(bp)
        system = policy.system_prompt("refine", REFINE_SYSTEM)
        context = {"blueprint": bp, "mechanisms": mechanisms}
        if policy.source_facts:
            from .source_facts import retained_excerpt
            context["seed_excerpt"] = retained_excerpt(getattr(seed, "text", "") if seed else "")
        for attempt in range(1, config.MAX_REFINE_ATTEMPTS + 1):
            try:
                text, truncated = self.llm.call(
                    ledger, "refine", model, max_tokens, system, user,
                    context=context)
            except (BudgetExceeded, APIExhausted):
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
            # A valid payload needs a topic plus ITS OWN kind of content:
            # tension_system for the two-pole shapes, content_frame for the
            # rest. Requiring tension_system unconditionally is what broke the
            # first topic-shape batch (2026-08-22) — every refine fell through
            # to the deterministic fallback, which produces generic topics, and
            # three elite attempts then died on topic collisions.
            if refined.get("topic") and (refined.get("tension_system")
                                         or refined.get("content_frame")):
                return refined
            missing = []
            if not refined.get("topic"):
                missing.append("topic")
            if not (refined.get("tension_system") or refined.get("content_frame")):
                missing.append("tension_system or content_frame")
            last_err = f"missing required keys: {', '.join(missing)}"
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
        if policy_for_blueprint(bp).seed_fidelity and (bp.seed.get("subject")
                                                       or bp.seed.get("title")):
            # 2026-09-14: domain_hint is the PUBLICATION ("a live conceptual
            # tension in Aeon"), so the legacy fallback topic was never the seed's.
            domain = bp.seed.get("subject") or bp.seed.get("title")
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
        policy = policy_for_blueprint(bp)
        vocab = policy.move_vocabulary()
        schema = policy.argument_schemas().get(bp.argument_schema_id)
        schema_part = (f"ARGUMENT SCHEMA: {bp.argument_schema_id}\n"
                       f"  {schema['directive']}\n") if schema else ""
        stance_part = ""
        if bp.render_stance_id:
            stance = self.registry.get("render_stance", bp.render_stance_id)
            stance_part = f"WRITING STANCE: {stance['name']} — {stance['frame']}\n"
        allocation = self.allocate_beats(bp.move_plan, bp.movement) if bp.move_plan else []
        shape_part = ""
        if bp.topic_shape_id:
            sh = self.registry.get("topic_shape", bp.topic_shape_id)
            shape_part = (f"{NL}TOPIC SHAPE (hard requirement): {sh['name']}"
                          f"{NL}  {sh['topic_form']}{NL}")
            if sh.get("requires_tension"):
                shape_part += ("  This shape DOES run on two poles: give a "
                               "tension_system and omit content_frame." + NL)
            else:
                shape_part += ("  This shape does NOT run on two poles: emit "
                               '"tension_system": null and give content_frame '
                               "instead — " + sh.get("content_frame", "") + NL)
        genre_part = ""
        if getattr(bp, "seed_genre", "") and bp.seed_genre != "unknown":
            genre_part = (f"{NL}SOURCE GENRE: {bp.seed_genre} — the topic should stay "
                          f"in this kind of material rather than being converted "
                          f"into a conceptual essay about it.{NL}")

        seed_part = ""
        fidelity = policy.seed_fidelity and bool(seed.text)
        if fidelity:
            # 2026-09-14 (seed_fidelity.py): "adapt its territory" is how a
            # virtue essay became a probate passage. The excerpt keeps its label
            # (f1/f2 fact spans are quoted "from the INSPIRATION ESSAY EXCERPT").
            from .seed_fidelity import anchor_block
            excerpt = " ".join(seed.text.split()[:550])
            seed_part = (f"\n{anchor_block(bp, seed)}"
                         f"INSPIRATION ESSAY EXCERPT (stay on its subject and kind of "
                         f"material; build your own argument, do NOT copy its argument):"
                         f"\n{excerpt}\n")
        elif seed.text:
            words = seed.text.split()
            excerpt = " ".join(words[:550])
            seed_part = (f"\nINSPIRATION ESSAY EXCERPT (adapt its domain and intellectual "
                         f"territory; do NOT copy its argument):\n{excerpt}\n")
        else:
            domain = seed.domain_hint or self.rng.choice(config.DOMAIN_POOL)
            seed_part = f"\nNo seed essay. Invent a topic within this domain: {domain}\n"
        seed_part = shape_part + genre_part + seed_part
        movement_lines = "\n".join(
            f"  para {p.para}: {p.function} ({p.words_label} words)"
            + ("; operations: " + "; ".join(
                f"{m} — {vocab[m]}" for m in allocation[i])
               if i < len(allocation) and allocation[i] else "")
            for i, p in enumerate(bp.movement))
        # topical divergence up front (~150 input tokens on the cheap refine
        # model) so passages stop colliding on the embedding channel AFTER the
        # expensive render call; includes recently rejected topics on purpose
        avoid_part = ""
        avoid = self.history.recent_topics(config.REFINE_AVOID_TOPICS)
        if avoid and fidelity:
            avoid_part = ("\nAVOID these recently used topical territories — take an "
                          "angle within the source essay's subject that is distant from "
                          "ALL of them; never leave the essay's subject to escape them:\n  - "
                          + "\n  - ".join(avoid) + "\n")
        elif avoid:
            avoid_part = ("\nAVOID these recently used topical territories — invent "
                          "something semantically distant from ALL of them:\n  - "
                          + "\n  - ".join(avoid) + "\n")
        return policy.user_prompt("refine", f"""STRUCTURAL BLUEPRINT (fixed — invent content for it):
{schema_part}{stance_part}Build the paragraph briefs as ONE argument implementing this plan.
ARGUMENT FAMILY: {family['name']} — {family['core']}
Difficulty must come from: {family['difficulty_source']}
PARAGRAPH MOVEMENT PLAN:
{movement_lines}
THESIS REVELATION: {revelation['name']} — {revelation['mechanism']}
(thesis first becomes visible around paragraph {bp.revelation_detail['planned_para']})
ENDING: {ending['name']} — {ending['gesture']} (aperture: {ending['aperture']})
REQUIRED CLOSING POSTURE: {family['closing_posture']} — {policy.closing_postures(self.registry)[family['closing_posture']]}
(the 'fate' fields in tension_system must be consistent with this posture)
INSTABILITY DEGREE: {bp.instability} (0 = neat closure, 1 = fully suspended; this governs how contested the middle feels — the ending's stance is governed by the closing posture above)
ALLOWED TRAP MECHANISMS: {profile['primary']}, {profile['secondary']}
{seed_part}{avoid_part}
Produce the JSON now.""")
