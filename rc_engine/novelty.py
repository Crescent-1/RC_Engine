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
                           jensen_shannon, movement_similarity, pearson,
                           topology_similarity, zscored_cosine)
from .models import Fingerprint, NoveltyReport
from .registry import posture_class


class NoveltyScorer:
    def __init__(self, history):
        self.history = history

    # ------------------------------------------------------------- channels

    def _pairwise(self, fp: Fingerprint, other: Fingerprint,
                  rhythm_stats: tuple[list, list] | None,
                  stylometry_corpus: list[dict],
                  include_question_channels: bool) -> dict:
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
        parts = [
            ("blueprint", blueprint_sim),
            ("movement", movement),
            ("curve", max(0.0, s["curve_pearson"])),
            ("rhythm", max(0.0, s["rhythm_cosine"])),
            ("stylometry", s["stylometry_sim"]),
            ("embedding", s["embedding_cosine"]),
        ]
        if include_question_channels:
            parts.append(("topology", s["topology_similarity"]))
            # LOW distractor JSD = repetitive; invert into similarity
            parts.append(("distractor_jsd", max(0.0, 1.0 - s["distractor_jsd"] * 4)))
        total_w = sum(w[k] for k, _ in parts)
        return sum(w[k] * v for k, v in parts) / total_w

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

        caps = config.NOVELTY_CAPS
        # see CURVE_CAP_MIN_CORPUS: the curve breach check needs corpus mass
        # before near-1.0 pearson on 4-6 point curves means anything
        curve_cap_active = len(window) >= config.CURVE_CAP_MIN_CORPUS
        worst_composite, worst_rc = 0.0, None
        breached: list[str] = []
        channel_report: dict = {}

        for other in window:
            s = self._pairwise(fp, other, (means, stds), stylometry_corpus,
                               include_question_channels)
            bp_sim = blueprint_sims.get(other.rc_id, 0.0)
            comp = self._composite(s, bp_sim, include_question_channels)
            if comp > worst_composite:
                worst_composite, worst_rc = comp, other.rc_id
                channel_report = {k: round(v, 3) for k, v in s.items()}
                channel_report["blueprint_sim"] = round(bp_sim, 3)

            if s["movement_levenshtein"] > caps["movement_levenshtein"]:
                breached.append(f"movement_levenshtein {s['movement_levenshtein']:.2f} vs {other.rc_id}")
            if s["movement_bigram_jaccard"] > caps["movement_bigram_jaccard"]:
                breached.append(f"movement_bigram_jaccard {s['movement_bigram_jaccard']:.2f} vs {other.rc_id}")
            coarse_supported = self._coarse_channel_supported(s, bp_sim)
            if curve_cap_active and s["curve_pearson"] > caps["curve_pearson"]:
                if (coarse_supported
                        or s["curve_pearson"] >= config.NOVELTY_SUPPORT_CAPS["curve_pearson_extreme"]):
                    breached.append(f"curve_pearson {s['curve_pearson']:.2f} vs {other.rc_id}")
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
                # A stylometric echo alone is the generator's house voice, not a
                # duplicate essay; only reject when a structural channel agrees
                # (coarse_supported) or the voices are near-identical (extreme).
                breached.append(f"persona_leak delta={s['stylometry_delta']:.2f} vs {other.rc_id}")
            if include_question_channels and \
                    s["topology_similarity"] > caps["topology_similarity"]:
                breached.append(f"topology {s['topology_similarity']:.2f} vs {other.rc_id}")

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
