"""Question layout is reported, not gated; the task mix is measured (2026-09-14)."""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine import config  # noqa: E402
from rc_engine.question_mix import (EXAM_TASK_SHARES, TASK_OF_SLOT, format_mix,  # noqa: E402
                                    mix)
from rc_engine.registry import ComponentRegistry  # noqa: E402


def test_exam_shares_are_the_baseline_table_and_every_mapping_is_a_known_task():
    assert abs(sum(EXAM_TASK_SHARES.values()) - 1.0) < 0.01
    assert set(TASK_OF_SLOT.values()) <= set(EXAM_TASK_SHARES)
    reg = ComponentRegistry()
    unmapped = set(reg.slot_type_definitions) - set(TASK_OF_SLOT)
    assert unmapped == {"closure_reading", "decoy_escape", "counterfactual_structure"}


def test_mix_counts_stored_slots_else_topology_slots_and_flags_skew():
    reg = ComponentRegistry()
    topo = reg.ids("topology")[0]
    stored = {"tier": "hard", "question_slots": [{"type": "thesis"}] * 8}
    from_topology = {"tier": "medium", "topology_id": topo}
    report = mix([json.dumps(stored), json.dumps(from_topology)], reg)
    assert report["sets"] == 2 and report["questions"] == 8 + len(
        reg.get("topology", topo)["slots"])
    hard = mix([json.dumps(stored)], reg, "hard")
    assert hard["tasks"]["gist"]["share"] == 1.0 and hard["tasks"]["gist"]["flag"] == "over"
    assert hard["tasks"]["detail"]["flag"] == "under"
    assert hard["tasks"]["consistency"]["flag"] == "no engine type"
    assert any("gist" in line for line in format_mix(hard, "hard"))


def test_shared_question_layout_is_reported_not_rejected(monkeypatch):
    from rc_engine.models import Fingerprint
    from rc_engine.novelty import NoveltyScorer

    sig = [{"type": "thesis", "target": "global", "difficulty": 0.5}] * 8
    rng = random.Random(3)

    def fp(rc_id):
        # distinct on every other channel, identical question layout
        return Fingerprint(rc_id=rc_id, blueprint_id="b" + rc_id, persona_id="P01",
                           movement_string="-".join(rng.choice("ABCDEFG") for _ in range(6)),
                           commitment_curve=[rng.random() for _ in range(5)],
                           rhythm_vector=[rng.random() for _ in range(8)],
                           topology_signature=sig, trap_histogram={},
                           letter_sequence="ABCDABCD", stylometry={})

    class History:
        old = fp("RC-OLD")

        def fingerprint_window(self, n):
            return [self.old]

        def letter_sequences_trailing(self, n):
            return []

    for enforce, rejected in ((True, True), (False, False)):
        monkeypatch.setattr(config, "TOPOLOGY_GATE_ENFORCE", enforce)
        report = NoveltyScorer(History()).score(fp("RC-NEW"), {}, include_question_channels=True)
        hit = any(b.startswith("topology") for b in report.breached)
        assert hit is rejected, report.breached
        if not enforce:
            assert any("topology" in f and "not gated" in f for f in report.corpus_flags)


def test_topology_gate_is_off_by_operator_decision():
    assert config.TOPOLOGY_GATE_ENFORCE is False
