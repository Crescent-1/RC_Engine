"""The CAT PYQ baseline tools (tools/cat_pyq), 2026-09-13.

These rules decide the published negation and task shares, so the corrections
made during the hand review are pinned here: quoted passage text never counts
as a negation, task and polarity are scanned independently, the 2IIM
navigation strip is not a question, and shipped engine stems are read once.
No PDF or database is needed.

2026-09-13: every example below is invented to exercise the same rule (a quoted
negation, an apostrophe, an operator form); none is copied from a PYQ, so the
file can live in git while the PDF's text stays out of it.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "cat_pyq"))

from engine_baseline import stems  # noqa: E402
from parse_pyq import merge_paragraphs, split_options  # noqa: E402
from question_records import OVERRIDES, classify_polarity, classify_task, strip_quotes  # noqa: E402


def test_quoted_negation_is_not_a_negated_question():
    stem = ("\"It's rather like a kettle on a stove. A louder kettle doesn't mean "
            "the water is any hotter . . .\" What is the purpose of this example?")
    assert "doesn't" not in strip_quotes(stem)
    assert classify_polarity(stem)["polarity"] == "affirmative"
    assert classify_task(stem) == "purpose_of_part"


def test_apostrophe_does_not_open_a_quote():
    stem = "The author's claim that 'a map is an argument' is used to show that"
    assert "author's claim" in strip_quotes(stem)


def test_single_and_multiple_negation():
    assert classify_polarity("All of the following are true, EXCEPT:")["polarity"] == "negated"
    assert classify_polarity("All of the following are true, EXCEPT:")["negation_mode"] == "except_scan"
    p = classify_polarity("Which claim below is NOT inconsistent with the passage?")
    assert p["polarity"] == "multiple_negation" and p["relation_inverted"]
    p = classify_polarity("None of these claims can be inferred from the passage EXCEPT that:")
    assert p["polarity"] == "multiple_negation" and p["negation_mode"] == "negated_except"
    assert classify_polarity("Which claim, if false, would count as supporting the passage?")[
        "negation_mode"] == "false_condition"


def test_task_ignores_polarity():
    affirmative = classify_task("The author would be most supportive of which one of these proposals?")
    negated = classify_task("The author is least likely to agree with which one of these views?")
    assert affirmative == negated == "author_endorse"


def test_content_negations_are_overridden_with_reasons():
    content = [k for k, v in OVERRIDES.items() if v.get("content_negation")]
    assert len(content) == 10
    assert all(OVERRIDES[k]["reason"] for k in content)


def test_split_options_and_paragraph_merge():
    stem, opts = split_options("Which is true? A. the U.S. case B. two C. three D. four")
    assert stem == "Which is true?" and opts == ["the U.S. case", "two", "three", "four"]
    assert merge_paragraphs(["A sentence that runs", "on to here.", "Next one."]) == [
        "A sentence that runs on to here.", "Next one."]


def test_engine_stems_read_once():
    text = "[PASSAGE]\n\nprose\n\nQ1. First stem?\n(A) a\nQ2. Second stem?\n(B) b\n\nANSWERS\nQ1. First stem?\n"
    assert stems(text) == ["First stem?", "Second stem?"]
