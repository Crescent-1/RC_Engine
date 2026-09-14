"""Seed-store labels (2026-09-14): classify once, draw by subject and genre."""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine import config, seed_labels  # noqa: E402
from rc_engine.llm import CostLedger, MockLLMClient  # noqa: E402
from rc_engine.models import SeedEssay  # noqa: E402
from rc_engine.registry import ComponentRegistry  # noqa: E402

TEXT = "An essay about the ethics of attention and what it costs to look away. " * 40


class FakeDB:
    """The slice of the Chroma wrapper seed_labels uses."""

    def __init__(self, docs):
        self.docs = docs                 # id -> {"text", "meta"}
        self._collection = self

    def get(self, ids=None, include=None):
        keys = [i for i in (ids or self.docs) if i in self.docs]
        return {"ids": keys, "documents": [self.docs[k]["text"] for k in keys],
                "metadatas": [dict(self.docs[k]["meta"]) for k in keys]}

    def update(self, ids, metadatas):
        for i, m in zip(ids, metadatas):
            self.docs[i]["meta"] = m


def _info(**over):
    base = {"genre": "criticism", "domain": "literature", "one_line": "a novel's silences",
            "concrete_particulars": ["Riley", "London"], "bipolar_dispute_available": False,
            "carriable_shapes": ["TS02", "TS04", "TS08"], "natural_shapes": ["TS02", "TS04", "TS08"],
            "possible_shapes": ["TS01"]}
    return {**base, **over}


def test_metadata_round_trip_is_scalar_and_versioned():
    meta = seed_labels.to_metadata(_info())
    assert all(isinstance(v, (str, bool, int, float)) for v in meta.values())
    back = seed_labels.from_metadata({"title": "x", **meta})
    assert back["genre"] == "criticism" and back["domain"] == "literature"
    assert back["carriable_shapes"] == ["TS02", "TS04", "TS08"]
    assert back["concrete_particulars"] == ["Riley", "London"]
    assert seed_labels.from_metadata({**meta, "seed_label_version": "old"}) is None
    assert seed_labels.from_metadata({"title": "unlabelled"}) is None


def test_labelled_pool_filters_subject_genre_used_and_breadth():
    db = FakeDB({
        "lit": {"text": TEXT, "meta": {"used": False, **seed_labels.to_metadata(_info())}},
        "phil": {"text": TEXT, "meta": {"used": False, **seed_labels.to_metadata(
            _info(domain="philosophy", genre="conceptual_essay"))}},
        "narrow": {"text": TEXT, "meta": {"used": False, **seed_labels.to_metadata(
            _info(carriable_shapes=["TS01"]))}},
        "used": {"text": TEXT, "meta": {"used": True, **seed_labels.to_metadata(_info())}},
        "raw": {"text": TEXT, "meta": {"used": False}},
    })
    assert set(seed_labels.labelled_pool(db, ["literature", "philosophy"], None, 3)) == {"lit", "phil"}
    assert seed_labels.labelled_pool(db, None, ["conceptual_essay"], 3) == ["phil"]
    assert "narrow" in seed_labels.labelled_pool(db, ["literature"], None, 0)
    assert seed_labels.pending(db) == ["raw"]
    assert any("literature" in line for line in seed_labels.report(db))


def test_classify_store_writes_labels_resumably_and_skips_unusable_replies():
    db = FakeDB({f"d{i}": {"text": TEXT, "meta": {"used": False, "title": f"t{i}"}}
                 for i in range(4)})

    class Llm(MockLLMClient):
        def _seed_classify(self, ctx):
            out = json.loads(super()._seed_classify(ctx))
            if ctx["seed"].doc_id == "d3":
                out.pop("shape_verdicts")          # no verdicts: not a label
            return json.dumps(out)

    result = seed_labels.classify_store(db, Llm(), ComponentRegistry(), seed_labels.pending(db),
                                        max_usd=1.0, workers=2, log=lambda *_: None)
    assert result["labelled"] == 3 and result["failed"] == 1
    assert db.docs["d0"]["meta"]["title"] == "t0"                       # merged, not replaced
    assert db.docs["d0"]["meta"]["seed_label_version"] == seed_labels.LABEL_VERSION
    assert seed_labels.pending(db) == ["d3"]                              # rerun retries it


def test_a_labelled_seed_is_not_classified_again_at_draw_time(tmp_path, monkeypatch):
    from rc_engine.generation_policy import get_policy
    from rc_engine.history import HistoryStore
    from rc_engine.pipeline import RCPipeline

    class Spy(MockLLMClient):
        calls = []

        def call(self, ledger, stage, model, max_tokens, system, user, context=None):
            self.calls.append(stage)
            return super().call(ledger, stage, model, max_tokens, system, user, context)

    history = HistoryStore(str(tmp_path / "labels.db"))
    pipe = RCPipeline(history, Spy(), embed=False, rng=random.Random(4))
    labels = seed_labels.from_metadata(seed_labels.to_metadata(_info()))
    seed = SeedEssay(doc_id="lit", title="t", text=TEXT, labels=labels)
    info, shape = pipe.composer.classify_and_pick_shape(seed, CostLedger(budget_usd=1.0), "hard",
                                                       policy=get_policy("cat-pyq-f3"))
    assert "seed_classify" not in Spy.calls
    assert info["domain"] == "literature" and shape in labels["carriable_shapes"]
    history.close()


def test_generate_has_subject_and_genre_flags_and_a_breadth_floor():
    from rc_engine import cli
    parser_help = cli.main.__code__.co_consts  # noqa: F841  (import check)
    assert config.SEED_MIN_CARRIABLE_SHAPES == 3
    src = open(cli.__file__, encoding="utf-8").read()
    assert '"--subject"' in src and '"--genre"' in src and '"seeds"' in src
