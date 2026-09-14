"""Stage 4 — NoveltyScorer: multi-channel structural similarity against the
trailing corpus window, plus corpus-level distribution checks.

Two entry points, matched to cost topology:
  score_passage(...)  — channels available BEFORE question generation
                        (movement, curve, rhythm, stylometry, embedding).
                        Rejecting here saves the most expensive call.
  score_full(...)     — adds topology + distractor channels after questions.
"""

from __future__ import annotations

import statistics

from . import config
from .fingerprints import (UNKNOWN_MOVEMENT, burrows_delta, cosine,
                           curve_similarity, jensen_shannon,
                           move_signature_similarity, movement_similarity,
                           pearson, topology_similarity, zscored_cosine)
from .models import Fingerprint, NoveltyReport
from .registry import posture_class


def _is_placeholder_curve(c) -> bool:
    """True for the [0.0, 0.0, 0.0] stand-in cli.py writes for legacy backfill
    and manual ingest, where no classifier ever read the prose. Distinguishing
    'unknown' from 'measured as neutral' is the whole point: they were being
    compared as real data and matching each other perfectly."""
    return bool(c) and all(abs(float(x)) < 1e-9 for x in c)


class NoveltyScorer:
    def __init__(self, history):
        self.history = history

    # ------------------------------------------------------------- channels

    def _pairwise(self, fp: Fingerprint, other: Fingerprint,
                  rhythm_stats: tuple[list, list] | None,
                  stylometry_corpus: list[dict],
                  include_question_channels: bool,
                  move_freq: dict | None = None, move_n: int = 0) -> dict:
        scores: dict[str, float] = {}

        if (fp.movement_string in UNKNOWN_MOVEMENT
                or other.movement_string in UNKNOWN_MOVEMENT):
            # no compliance annotation on one side — unknown structure is not
            # evidence of similar structure
            scores["movement_levenshtein"] = 0.0
            scores["movement_bigram_jaccard"] = 0.0
        else:
            lev, jac = movement_similarity(fp.movement_string, other.movement_string)
            scores["movement_levenshtein"] = lev
            scores["movement_bigram_jaccard"] = jac

        # Level-aware curve distance is the gating channel. Pearson is retained
        # ONLY as a diagnostic in the channel report — it is scale/location
        # invariant, so it cannot tell "opens hostile, ends convinced" from
        # "opens warm, ends warmer" and scored those a perfect 1.00. See
        # fingerprints.curve_similarity.
        # ---- move_signature: the rhetorical grammar of the PROSE ------------
        # Independent of the blueprint by construction (the extractor never sees
        # it), which is what movement_* is not. An empty signature means "never
        # extracted", and unknown structure is not evidence of similar
        # structure — same convention as UNKNOWN_MOVEMENT above.
        if fp.move_signature and other.move_signature:
            scores["move_signature_sim"] = move_signature_similarity(
                fp.move_signature.split("|"), other.move_signature.split("|"),
                move_freq, move_n)
        else:
            scores["move_signature_sim"] = 0.0

        # An all-zero curve is a PLACEHOLDER, not a measurement: cli.py writes
        # [0.0, 0.0, 0.0] for legacy backfill and manually ingested sets, whose
        # prose was never scored by the compliance classifier. 39 of the 113
        # active fingerprints carry one, and they matched each other at exactly
        # 1.000 — 741 of 6328 pairs in the baseline, every single exact match in
        # the corpus. Scoring "unknown" as "flat neutral" manufactured collisions
        # out of missing data. Skip the channel instead; _composite renormalises
        # over the weights it actually has.
        if _is_placeholder_curve(fp.commitment_curve) or                 _is_placeholder_curve(other.commitment_curve):
            scores["curve_similarity"] = None
            scores["curve_pearson"] = None
        else:
            scores["curve_similarity"] = curve_similarity(
                fp.commitment_curve, other.commitment_curve)
            r = pearson(fp.commitment_curve, other.commitment_curve)
            same_sign_ends = (fp.commitment_curve and other.commitment_curve and
                              fp.commitment_curve[-1] * other.commitment_curve[-1] > 0)
            scores["curve_pearson"] = r if same_sign_ends else min(r, 0.0)

        if rhythm_stats:
            means, stds = rhythm_stats
            scores["rhythm_cosine"] = zscored_cosine(fp.rhythm_vector,
                                                     other.rhythm_vector, means, stds)
        else:
            scores["rhythm_cosine"] = cosine(fp.rhythm_vector, other.rhythm_vector)

        if fp.embedding and other.embedding:
            scores["embedding_cosine"] = cosine(fp.embedding, other.embedding)
        else:
            scores["embedding_cosine"] = 0.0

        delta = burrows_delta(fp.stylometry, other.stylometry, stylometry_corpus)
        # convert to similarity in [0,1]: delta 0 -> 1.0 ; delta >= 2 -> 0
        scores["stylometry_delta"] = delta
        scores["stylometry_sim"] = max(0.0, 1.0 - delta / 2.0)

        if include_question_channels:
            if fp.topology_signature and other.topology_signature:
                scores["topology_similarity"] = topology_similarity(
                    fp.topology_signature, other.topology_signature)
            else:
                # backfilled/manual fingerprints carry no topology annotation;
                # empty-vs-empty would otherwise score as identical
                scores["topology_similarity"] = 0.0
            scores["distractor_jsd"] = jensen_shannon(fp.trap_histogram,
                                                      other.trap_histogram)
        return scores

    def _composite(self, s: dict, blueprint_sim: float,
                   include_question_channels: bool) -> float:
        w = config.COMPOSITE_WEIGHTS
        movement = max(s["movement_levenshtein"], s["movement_bigram_jaccard"])
        move_sig = s["move_signature_sim"]
        parts = [
            ("blueprint", blueprint_sim),
            ("movement", movement),
            ("move_signature", move_sig),
            ("curve", None if s["curve_similarity"] is None
                      else max(0.0, s["curve_similarity"])),
            ("rhythm", max(0.0, s["rhythm_cosine"])),
            ("stylometry", s["stylometry_sim"]),
            ("embedding", s["embedding_cosine"]),
        ]
        if include_question_channels:
            # 2026-09-14 review: with the topology gate off (question layout is
            # reported, not gated) a shared layout must not still push a set
            # toward a composite reject at weight 0.14. The mix is watched in
            # `health` instead.
            if getattr(config, "TOPOLOGY_GATE_ENFORCE", True):
                parts.append(("topology", s["topology_similarity"]))
            # LOW distractor JSD = repetitive; invert into similarity
            parts.append(("distractor_jsd", max(0.0, 1.0 - s["distractor_jsd"] * 4)))
        # A None channel is unmeasurable for this pair (see the placeholder-curve
        # note in _pairwise). Drop it and renormalise rather than scoring it 0,
        # which would read as "maximally novel" on missing data.
        parts = [(k, v) for k, v in parts if v is not None]
        total_w = sum(w[k] for k, _ in parts)
        return sum(w[k] * v for k, v in parts) / total_w if total_w else 0.0

    # ----------------------------------------------------------------- gates

    def _coarse_channel_supported(self, s: dict, blueprint_sim: float) -> bool:
        support = config.NOVELTY_SUPPORT_CAPS
        movement = max(s["movement_levenshtein"], s["movement_bigram_jaccard"])
        return (
            blueprint_sim >= support["blueprint_sim"]
            or movement >= support["movement_similarity"]
            or s["rhythm_cosine"] >= support["rhythm_cosine"]
        )

    def score(self, fp: Fingerprint, blueprint_sims: dict[str, float],
              include_question_channels: bool) -> NoveltyReport:
        window = self.history.fingerprint_window(config.FINGERPRINT_WINDOW)
        window = [w for w in window if w.rc_id != fp.rc_id]
        if not window:
            return NoveltyReport(verdict="pass", composite=1.0)

        # rhythm z-scoring stats + stylometry corpus over the window
        dims = len(fp.rhythm_vector)
        means = [statistics.mean([w.rhythm_vector[i] for w in window
                                  if len(w.rhythm_vector) > i] or [0.0]) for i in range(dims)]
        stds = [statistics.pstdev([w.rhythm_vector[i] for w in window
                                   if len(w.rhythm_vector) > i] or [0.0]) for i in range(dims)]
        stylometry_corpus = [w.stylometry for w in window]

        # Corpus move frequencies for the rarity weighting: a shared move that
        # most of the corpus performs is weak evidence; a shared rare one is
        # strong. Computed over the same window the gates score against.
        move_freq: dict[str, int] = {}
        move_n = 0
        for w in window:
            if w.move_signature:
                move_n += 1
                for m in set(w.move_signature.split("|")):
                    move_freq[m] = move_freq.get(m, 0) + 1

        caps = config.NOVELTY_CAPS
        # see CURVE_CAP_MIN_CORPUS: the curve breach check needs corpus mass
        # before near-1.0 pearson on 4-6 point curves means anything
        curve_cap_active = len(window) >= config.CURVE_CAP_MIN_CORPUS
        worst_composite, worst_rc = 0.0, None
        breached: list[str] = []
        persona_candidates: list[tuple[str, str, float]] = []
        channel_report: dict = {}
        topology_note = ""

        # window is newest-first, so the index doubles as recency
        for idx, other in enumerate(window):
            s = self._pairwise(fp, other, (means, stds), stylometry_corpus,
                               include_question_channels, move_freq, move_n)
            bp_sim = blueprint_sims.get(other.rc_id, 0.0)
            comp = self._composite(s, bp_sim, include_question_channels)
            if comp > worst_composite:
                worst_composite, worst_rc = comp, other.rc_id
                channel_report = {k: round(v, 3) for k, v in s.items()}
                channel_report["blueprint_sim"] = round(bp_sim, 3)

            # Movement, like topology below, only counts as a breach against the
            # RECENT corpus — same window the free precheck uses, so the two
            # agree. They MUST agree: the precheck exists to catch a movement
            # collision before a paid render, and when Gate B looked further
            # back than the precheck did, candidates cleared the free gate and
            # were then rejected after the render. That is strictly worse than
            # no precheck (2026-08-10: three hard attempts, $0.20, all paid,
            # all rejected on movement vs sets older than the precheck window).
            # It stays in the composite score at every distance either way.
            movement_recent = idx < config.MOVEMENT_RECENCY_WINDOW
            if movement_recent and s["movement_levenshtein"] > caps["movement_levenshtein"]:
                breached.append(f"movement_levenshtein {s['movement_levenshtein']:.2f} vs {other.rc_id}")
            if movement_recent and s["movement_bigram_jaccard"] > caps["movement_bigram_jaccard"]:
                breached.append(f"movement_bigram_jaccard {s['movement_bigram_jaccard']:.2f} vs {other.rc_id}")
            coarse_supported = self._coarse_channel_supported(s, bp_sim)
            if curve_cap_active and s["curve_similarity"] is not None                     and s["curve_similarity"] > caps["curve_similarity"]:
                if (coarse_supported
                        or s["curve_similarity"] >= config.NOVELTY_SUPPORT_CAPS["curve_similarity_extreme"]):
                    breached.append(f"curve_similarity {s['curve_similarity']:.2f} vs {other.rc_id}")
            # move_signature is checked against the WHOLE window, not just the
            # recent slice the movement channels use. Recycling a movement token
            # after its exclusion window is deliberate composer policy; repeating
            # the rhetorical grammar is a defect at any distance — the pair that
            # motivated this channel (RC-ELITE-260712-0028 / RC_E_0706_1) is six
            # days apart and every other channel called them maximally novel.
            if s["move_signature_sim"] > config.MOVE_SIGNATURE_CAPS["move_signature_sim"]:
                breached.append(f"move_signature {s['move_signature_sim']:.2f} "
                                f"vs {other.rc_id}")
            if s["rhythm_cosine"] > caps["rhythm_cosine"]:
                breached.append(f"rhythm_cosine {s['rhythm_cosine']:.2f} vs {other.rc_id}")
            if s["embedding_cosine"] > caps["embedding_cosine"]:
                if (coarse_supported
                        or s["embedding_cosine"] >= config.NOVELTY_SUPPORT_CAPS["embedding_cosine_extreme"]):
                    breached.append(f"embedding_cosine {s['embedding_cosine']:.2f} vs {other.rc_id}")
            if (fp.persona_id and other.persona_id and fp.persona_id != other.persona_id
                    and s["stylometry_delta"] < caps["stylometry_delta_floor"]
                    and (coarse_supported
                         or s["stylometry_delta"]
                            < config.NOVELTY_SUPPORT_CAPS["stylometry_delta_extreme"])):
                # Candidate only — the leak/house-voice call needs the whole
                # window, so it is decided after the loop (see below).
                persona_candidates.append(
                    (other.persona_id, other.rc_id, s["stylometry_delta"]))
            # Topology only counts as a breach against the RECENT corpus. The
            # composer recycles a topology on purpose once
            # EXCLUSION_WINDOWS["topology"] sets have passed, and with a
            # 20-item library and a larger corpus that recycling is mandatory —
            # scoring it against the whole window made a reused topology a
            # guaranteed 1.00 breach, contradicting the composer's own policy.
            # Inside the window it is still a hard reject (that would be a
            # composer bug). It stays in the composite score either way.
            #
            # 2026-09-14 (operator decision): a question layout shared with a
            # recent set is coincidence, not a duplicate; what matters is the
            # question-type MIX across the corpus (question_mix.py, `health`).
            # With TOPOLOGY_GATE_ENFORCE off it is reported, never a reject.
            if (include_question_channels
                    and idx < config.EXCLUSION_WINDOWS["topology"]
                    and s["topology_similarity"] > caps["topology_similarity"]):
                line = f"topology {s['topology_similarity']:.2f} vs {other.rc_id}"
                if getattr(config, "TOPOLOGY_GATE_ENFORCE", True):
                    breached.append(line)
                elif not topology_note:
                    topology_note = f"{line} (reported, not gated)"

        # ---- persona_leak: a leak is SPECIFIC, the house voice is DIFFUSE ----
        # A real leak means "this passage reads like persona X" — one voice
        # bleeding through. A render that sits equally close to many different
        # personas is not leaking any of them; it is sitting near the corpus
        # centroid, which is the single generator's house voice. The old
        # per-pair test could not tell those apart and rejected both.
        #
        # The corpus separates them cleanly (2026-08-11): shipped sets that trip
        # the gate breach exactly 1 distinct persona, while the render that
        # burned three paid attempts breached 7 at once (P03/P05/P06/P07/P14/
        # P15/P16, deltas 0.59-0.69). persona_leak was in 11 of 22 paid
        # rejections that day — the largest single source of wasted spend.
        #
        # Diffuse cases become a corpus flag instead: the voice IS converging and
        # that is worth surfacing, but a blind re-roll cannot fix it, so
        # rejecting the render only burns money.
        # 2026-08-22: persona_leak REPORTS, it no longer rejects.
        #
        # The diffuse case was already only a flag, on the reasoning that a blind
        # re-roll cannot move the house voice. That reasoning applies just as
        # well to the specific case, and the bill proved it: across three live
        # batches persona_leak was the single largest source of wasted spend
        # (~$0.72 of $1.05 in the 2026-08-21 batch alone), and none of the
        # re-rolls it forced produced a materially different voice.
        #
        # What made it defensible as a gate was that nothing else measured
        # structural repetition. move_signature does now — from the prose,
        # blind, and acted on by a beat plan the renderer obeys — so the
        # stylometric reading survives as the corpus signal it always was.
        house_voice_flag = None
        if persona_candidates:
            personas = {p for p, _, _ in persona_candidates}
            worst_d = min(d for _, _, d in persona_candidates)
            nearest = min(persona_candidates, key=lambda c: c[2])[1]
            if len(personas) >= config.PERSONA_LEAK_DIFFUSE_MIN:
                house_voice_flag = (
                    f"house_voice: stylometry within the persona-leak band of "
                    f"{len(personas)} distinct personas (worst delta {worst_d:.2f}) "
                    f"— generator voice converging, not a leak of any one persona")
            else:
                house_voice_flag = (
                    f"persona_leak (reported, not gated): delta {worst_d:.2f} vs "
                    f"{nearest} across {len(personas)} persona(s)")

        posture_flag = self._posture_run_check(fp, window, breached)

        novelty = 1.0 - worst_composite
        if breached:
            verdict = "reject_pairwise"
        elif novelty < config.MIN_COMPOSITE_NOVELTY:
            verdict = "reject_composite"
        else:
            verdict = "pass"
        corpus_flags = self._corpus_flags(fp) if include_question_channels else []
        if posture_flag:
            corpus_flags = corpus_flags + [posture_flag]
        if house_voice_flag:
            corpus_flags = corpus_flags + [house_voice_flag]
        if topology_note:
            corpus_flags = corpus_flags + [topology_note]
        return NoveltyReport(
            verdict=verdict, composite=round(novelty, 3),
            channel_scores={"nearest": worst_rc, **channel_report},
            breached=breached[:8],
            corpus_flags=corpus_flags)

    def _posture_run_check(self, fp: Fingerprint, window: list[Fingerprint],
                           breached: list[str]) -> str | None:
        """Closing-posture run backstop. Rejects (via `breached`) ONLY when the
        realized posture class both saturates the recent corpus AND mismatches
        the blueprint's planned posture — i.e., the render LLM disobeyed, the
        one case generation cannot prevent. Blueprint-consistent runs are
        flagged, never rejected (returned string -> corpus_flags)."""
        mine = fp.stylometry.get("_closing_posture") or ""
        planned = fp.stylometry.get("_planned_posture") or ""
        if not mine or not planned:
            return None   # legacy fingerprint or unusable classifier output
        my_class = posture_class(mine)
        keyed = [w for w in window
                 if w.stylometry.get("_closing_posture")][:config.POSTURE_RUN_M]
        same = sum(1 for w in keyed
                   if posture_class(w.stylometry["_closing_posture"]) == my_class)
        if same < config.POSTURE_RUN_K:
            return None
        if my_class != posture_class(planned):
            breached.append(
                f"posture_run_disobedient: realized '{mine}' matches "
                f"{same}/{len(keyed)} recent, blueprint planned '{planned}'")
            return None
        return (f"posture run: {same}/{len(keyed)} recent share class "
                f"'{my_class}' (blueprint-consistent)")

    def _corpus_flags(self, fp: Fingerprint) -> list[str]:
        """Corpus-level distributional checks (flag, don't reject)."""
        flags = []
        seqs = self.history.letter_sequences_trailing(20)
        if len(seqs) >= 10:
            counts = {c: 0 for c in "ABCD"}
            total = 0
            for s in seqs:
                for c in s:
                    if c in counts:
                        counts[c] += 1
                        total += 1
            if total:
                expected = total / 4
                chi2 = sum((counts[c] - expected) ** 2 / expected for c in "ABCD")
                if chi2 > 11.34:  # p < 0.01, df=3
                    flags.append(f"letter distribution chi2={chi2:.1f} over trailing 20 sets")

        # aphorism-ending drift: baseline under the register rotation is ~12.5%;
        # APHORISM_FLAG_MIN of a full window is a deep binomial tail, not noise
        fps = self.history.fingerprint_window(config.APHORISM_FLAG_WINDOW)
        keyed = [w for w in fps if w.stylometry.get("_aphorism_ending") is not None]
        if len(keyed) >= 5:
            n_aph = sum(1 for w in keyed if w.stylometry["_aphorism_ending"])
            if n_aph >= config.APHORISM_FLAG_MIN:
                flags.append(f"aphorism endings: {n_aph}/{len(keyed)} of trailing "
                             f"{len(keyed)} keyed sets")

        # thesis-longest budget: the candidate's thesis answer is the strictly
        # longest option AND the trailing window is already at its 1-in-3 cap
        if fp.stylometry.get("_thesis_longest"):
            th_keyed = [w for w in self.history.fingerprint_window(
                            config.THESIS_LONGEST_WINDOW * 3)
                        if w.rc_id != fp.rc_id
                        and w.stylometry.get("_thesis_longest") is not None]
            th_keyed = th_keyed[:config.THESIS_LONGEST_WINDOW - 1]
            n_th = 1 + sum(1 for w in th_keyed if w.stylometry["_thesis_longest"])
            if n_th > config.THESIS_LONGEST_MAX:
                flags.append(
                    f"thesis-longest budget: {n_th}/{len(th_keyed) + 1} recent keyed "
                    f"sets (max {config.THESIS_LONGEST_MAX} in "
                    f"{config.THESIS_LONGEST_WINDOW})")
        return flags


def kl_divergence(observed: dict[str, int], uniform_over: list[str]) -> float:
    import math
    total = sum(observed.values())
    if not total or not uniform_over:
        return 0.0
    q = 1.0 / len(uniform_over)
    kl = 0.0
    for k in uniform_over:
        p = observed.get(k, 0) / total
        if p > 0:
            kl += p * math.log2(p / q)
    return kl
