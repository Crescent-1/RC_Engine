"""Reproduce local checks; read the seed store without modifying it.

Run from the project root. This is not a semantic novelty or independent solver audit.
"""
from pathlib import Path
from collections import Counter
import hashlib
import json
import re
import sqlite3
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from rc_engine.cli import _parse_rc_txt
from rc_engine.question_engine import length_bias_report, passage_word_report


def tokens(text):
    return re.findall(r"\b\w+(?:['’-]\w+)*\b", text.lower())


def grams(text, n=8):
    words = tokens(text)
    return {tuple(words[i:i+n]) for i in range(len(words)-n+1)}


report = {"method": "Local deterministic checks plus author editorial review; no independent cold solver.",
          "limitations": ["Full CLI vet failed in NoveltyScorer when rounding a None channel value.",
                           "sentence_transformers and RAG loader dependency feedparser unavailable.",
                           "No production ingestion, seed reservation, tracker update or paid API call.",
                           "Exact text overlap is not semantic or structural novelty validation."],
          "sets": []}
db = sqlite3.connect((ROOT / "essay_rc_db/chroma.sqlite3").as_uri() + "?mode=ro", uri=True)
for suffix, seed_row in [("LIT", 96), ("PHI", 365)]:
    path = HERE / f"RC-MANUAL-260919-{suffix}.txt"
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    parsed = _parse_rc_txt(text)
    passage, questions, key = parsed["passage"], parsed["questions"], parsed["letters"]
    assert len(questions) == len(key) == 8
    assert Counter(key) == Counter(dict.fromkeys("ABCD", 2))
    assert len(passage.split("\n\n")) == 5
    assert 500 <= len(tokens(passage)) <= 550
    assert b"\r" not in raw
    reasons = re.findall(r"^  \(([A-D])\) (.+)$", text, re.M)
    assert len(reasons) == 32
    rows = []
    for i, (q, correct) in enumerate(zip(questions, key)):
        q["correct"] = correct
        if i == 0:
            q["slot_type"] = "thesis"
        opts = q["options"]
        assert set(opts) == set("ABCD")
        assert all(s[0].isupper() and s.endswith(".") for s in opts.values())
        assert [letter for letter, reason in reasons[i*4:i*4+4] if reason.startswith("CORRECT")] == [correct]
        wc = {k: len(v.split()) for k, v in opts.items()}
        cc = {k: len(v) for k, v in opts.items()}
        assert max(wc.values()) - min(wc.values()) <= 3
        assert max(wc.values()) / min(wc.values()) < 1.30
        assert max(cc.values()) / min(cc.values()) < 1.30
        row = {"question": i+1, "correct": correct, "word_counts": wc, "character_counts": cc}
        for unit, counts in [("word", wc), ("character", cc)]:
            others = [v for k, v in counts.items() if k != correct]
            row[unit + "_correct_strictly_longest"] = counts[correct] > max(others)
            row[unit + "_correct_strictly_shortest"] = counts[correct] < min(others)
        rows.append(row)
    length = length_bias_report({"questions": questions})
    assert not length["warnings"], length
    assert not passage_word_report(passage)["warnings"]
    for unit in ["word", "character"]:
        for extreme in ["longest", "shortest"]:
            assert sum(row[f"{unit}_correct_strictly_{extreme}"] for row in rows) <= 2
        assert not rows[0][f"{unit}_correct_strictly_longest"]
    meta = {k: next((v for v in values if v is not None), None)
            for k, *values in db.execute(
                "SELECT key,string_value,int_value,float_value,bool_value FROM embedding_metadata WHERE id=?",
                (seed_row,))}
    seed = {k: meta.get(k) for k in ["title", "url", "seed_domain", "seed_subject", "seed_genre", "used"]}
    seed["doc_id"] = db.execute("SELECT embedding_id FROM embeddings WHERE id=?", (seed_row,)).fetchone()[0]
    seed["text_sha256"] = hashlib.sha256(meta["chroma:document"].encode("utf-8")).hexdigest()
    local_matches = []
    checked = 0
    target = grams(passage)
    for base in [ROOT / "exported_rc_sets", ROOT / "manual_rc_sets"]:
        for other in base.rglob("*.txt"):
            if other == path:
                continue
            other_text = other.read_text(encoding="utf-8", errors="replace")
            if "[PASSAGE]" not in other_text or "[QUESTIONS]" not in other_text:
                continue
            other_passage = other_text.split("[PASSAGE]", 1)[1].split("[QUESTIONS]", 1)[0]
            checked += 1
            overlap = target & grams(other_passage)
            if overlap:
                local_matches.append({"file": str(other.relative_to(ROOT)), "eight_word_matches": len(overlap)})
    report["sets"].append({"id": path.stem, "sha256": hashlib.sha256(raw).hexdigest(),
                           "passage_words": len(passage.split()), "lexical_words": len(tokens(passage)),
                           "key": key, "seed": seed, "engine_length_report": length,
                           "questions": rows, "local_passage_files_checked": checked,
                           "local_eight_word_matches": local_matches,
                           "seed_eight_word_matches": len(target & grams(meta["chroma:document"]))})
db.close()
(HERE / "audit.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
for result in report["sets"]:
    print(result["id"], result["passage_words"], result["key"],
          "length checks passed; local exact-overlap matches:", len(result["local_eight_word_matches"]))
