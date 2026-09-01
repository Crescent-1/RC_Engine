"""Parser tolerance tests for `rc_engine.cli vet` uploads.

Covers the canonical [PASSAGE]/[QUESTIONS] engine format and the markdown
shapes real uploads arrive in (## headings, **bold** stems, A)/A. options).
Run: python -m pytest tests/test_vet_parser.py -q
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine.cli import _parse_rc_txt
from rc_engine.fingerprints import parse_answer_letters


from rc_engine import config

# The canonical fixture tracks QUESTIONS_PER_SET so the parser tests exercise the
# set size the engine actually emits (6 -> 8 on 2026-08-10).
N_Q = config.QUESTIONS_PER_SET
# One letter per question, cycling B C A D — arbitrary but fixed, so `letters`
# stays assertable without hand-editing the fixture when the count changes.
LETTERS = "".join("BCAD"[i % 4] for i in range(N_Q))


def _canonical_questions(n=N_Q):
    blocks = []
    for i in range(1, n + 1):
        blocks.append(f"Q{i}. What does paragraph {i} claim?\n"
                      "(A) first option text\n(B) second option text\n"
                      "(C) third option text\n(D) fourth option text\n")
    return "\n".join(blocks)


CANONICAL = f"""[PASSAGE]

Institutions fail by continuing to work. This is the first paragraph.

A second paragraph follows with more argument.

[QUESTIONS]

{_canonical_questions()}
[ANSWER KEY & ELIMINATION LOGIC]

Q1 — Correct answer: ({LETTERS[0]})
  ({LETTERS[0]}) CORRECT — stated in para 1
  (A) scope_creep — tempting overreach
{chr(10).join(f"Q{i + 1} — Correct answer: ({LETTERS[i]})" for i in range(1, N_Q))}

[BLUEPRINT NOTE]
Structure: x | Posture: earned_confidence | Thesis visible: para 1 | Traps: scope_creep
"""


MARKDOWN_CHAT = """# CAT-Style Reading Comprehension

**Domain: Sociology of Institutions**

---

## Passage

We tend to imagine that institutions fail when they stop working, but the
troubling possibility is that they fail by continuing to work.

The standard diagnosis blames rigidity. There is something to this.

---

## Questions

**Q1. Which of the following best captures the central thesis of the passage?**

(A) Institutions fail chiefly because rules resist revision.

(B) Institutional dysfunction is a constitutive consequence of a trade-off.

(C) The most dangerous institutions are the flexible ones.

(D) The remedy is organizations that revise their own categories.

**Q2. The second paragraph primarily functions to:**

(A) concede a partial truth.

(B) mark a pivot to prescription.

(C) reject a consoling implication.

(D) summarize reform efforts.

---

## Answer Key

**Q1 — Correct answer: (B)**

**Q2 — Correct answer: (A)**
"""


NO_MARKERS = """Institutions encode a theory of what matters. That theory
functions as blinders. In 1984, one census missed entire households.

Q1) Which claim does the author make?
A) the first candidate answer
B) the second candidate answer
C) the third candidate answer
D) the fourth candidate answer

Q2: The example of the census serves to:
A. illustrate a perceptual boundary
B. blame administrators
C. defend metrics
D. praise flexibility

Q1: A
Q2: (B)
"""


def test_canonical_format():
    p = _parse_rc_txt(CANONICAL)
    assert len(p["questions"]) == N_Q
    assert all(len(q["options"]) == 4 for q in p["questions"])
    assert p["letters"] == LETTERS
    assert p["posture"] == "earned_confidence"
    assert "scope_creep" in p["mechanisms"]
    assert p["passage"].startswith("Institutions fail")
    assert "Q1" not in p["passage"]


def test_markdown_chat_format():
    p = _parse_rc_txt(MARKDOWN_CHAT)
    assert len(p["questions"]) == 2
    assert all(len(q["options"]) == 4 for q in p["questions"])
    assert p["letters"] == "BA"
    assert p["passage"].startswith("We tend to imagine")
    assert "Domain" not in p["passage"]
    assert "Q1" not in p["passage"]


def test_no_markers_fallback_with_loose_options():
    p = _parse_rc_txt(NO_MARKERS)
    assert len(p["questions"]) == 2
    assert all(len(q["options"]) == 4 for q in p["questions"])
    # "In 1984," in the passage must not be mistaken for a question
    assert p["passage"].startswith("Institutions encode")
    assert "1984" in p["passage"]
    assert p["letters"] == "AB"


def test_export_header_stripped():
    text = ("RC ID: RC_E_1 | Tier: elite\n" + "=" * 70 + "\n\n" + CANONICAL)
    p = _parse_rc_txt(text)
    assert p["passage"].startswith("Institutions fail")
    assert len(p["questions"]) == N_Q


def test_answer_letter_variants():
    assert parse_answer_letters("Q1 — Correct answer: (B)") == "B"
    assert parse_answer_letters("**Q1 — Correct answer: (B)**") == "B"
    assert parse_answer_letters("**Q1 — Correct: (B)**") == "B"
    assert parse_answer_letters("**1. Correct: (C)**") == "C"
    assert parse_answer_letters("Q1: B\nQ2 — (C)\nQ3. D") == "BCD"
    # a question stem must never be read as a key line
    assert parse_answer_letters("Q1. Which of the following is right?") == ""
    assert parse_answer_letters("no key here at all") == ""
