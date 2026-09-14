"""Prompt hygiene (2026-09-14).

A review of the exact prompts sent for RC-HARD-260914-0099 found the questions
system prompt telling the model its reply must begin and end with "'" (an
f-string had eaten the braces), plus internal history reaching the model: dated
measurements, rule-numbering notes, a banned phrase quoted as an example, and an
operator's name in a slot description. Evidence belongs in code comments.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rc_engine.generation_policy import registered  # noqa: E402
from rc_engine.registry import ComponentRegistry  # noqa: E402

LEAKS = re.compile(r"20\d\d-\d\d-\d\d|Lokesh|chi-square|no: more precisely|"
                   r"[Mm]easured (over|across|\d)")


def _system_prompts():
    from rc_engine.composer import REFINE_SYSTEM
    from rc_engine.question_engine import QUESTION_SYSTEM
    from rc_engine.renderer import RENDER_SYSTEM
    bases = {"render": RENDER_SYSTEM, "questions": QUESTION_SYSTEM, "refine": REFINE_SYSTEM}
    out = {}
    for version, policy in registered().items():
        for stage, base in bases.items():
            out[f"{version or 'legacy'}/{stage}"] = policy.system_prompt(stage, base)
    return out


def test_questions_prompt_asks_for_json_braces():
    from rc_engine.question_engine import QUESTION_SYSTEM
    assert "must be '{' and the last must be '}'" in QUESTION_SYSTEM
    assert "must be ' and the last" not in QUESTION_SYSTEM


@pytest.mark.parametrize("name,prompt", sorted(_system_prompts().items()))
def test_no_internal_history_in_generation_prompts(name, prompt):
    assert not LEAKS.search(prompt), (name, LEAKS.findall(prompt))


def test_slot_descriptions_and_stems_carry_no_internal_notes():
    reg = ComponentRegistry()
    for slot, text in reg.slot_type_definitions.items():
        assert not LEAKS.search(text), (slot, text)
    for slot, forms in reg.stem_forms.items():
        for form in forms:
            assert not LEAKS.search(form), (slot, form)


def test_render_contract_keeps_the_banned_phrase_only_in_the_forbidden_list(tmp_path):
    """The forbidden list is the one place a banned phrase must be named."""
    from rc_engine.renderer import RENDER_SYSTEM
    assert "no: more precisely" not in RENDER_SYSTEM
