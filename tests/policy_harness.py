"""Deterministic end-to-end mock scenario for generation-policy regressions.

Written 2026-09-13 for section 3 of 2026-09-13-cat-pyq-implementation-plan.md.
The golden file tests/fixtures/generation_policy_legacy_golden.json was
captured from the engine BEFORE the policy layer existed (commit 23e3d49,
rc_engine/ unmodified), so "legacy behaviour is unchanged" is checked against
real pre-change output rather than the new code's own idea of legacy.

Runs in a SUBPROCESS with PYTHONHASHSEED=0. The composer's pool order is not a
pure function of its RNG: `_eligible` re-admits missing arc shapes by iterating
a set of shape names, and set order follows per-process string hashing, which
changes `rng.choices` outcomes. That is existing behaviour and is deliberately
not changed here; the harness pins the hash seed instead.

What is pinned: blueprint ids (uuid4 and the composer clock), every RNG the
pipeline owns, the mock LLM, the hash seed and a temporary DB. RC ids carry
the date from HistoryStore, so dates are normalised out of what is recorded.

Recorded per LLM call: stage, model, max_tokens and SHA-1 of the system and
user prompts. Per attempt: status, notes, bans, and the persisted blueprint's
component choices, move plan, effective question slots and stem shapes. Also a
forced question failure + resume, a forced topology re-pick per tier, and
composer probes on near-exhausted family pools.

    python tests/policy_harness.py OUT.json WORKDIR [OPTIONS.json]

Regenerate the golden ONLY from a commit whose legacy behaviour is known-good:
    RC_REGEN_POLICY_GOLDEN=1 python -m pytest tests/test_generation_policy.py -k golden
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import subprocess
import sys
from datetime import datetime, timezone

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

_RC = re.compile(r"RC-(MEDIUM|HARD|ELITE)-\d{6}-(\d{4})")
_DATE = re.compile(r"\b20\d\d-\d\d-\d\dT[\d:.+]+")

SOURCES = [
    "Clockmakers in the seventeenth century regulated escapements by ear, and the guild records "
    "show that a master's certificate was granted for a correction procedure rather than a finished clock.",
    "The survey of river gauges in the delta placed instruments where the district offices already "
    "kept files, so the recorded flood map follows administration as much as water.",
    "Hospital discharge rules written for bed turnover measured the length of stay precisely and "
    "recorded nothing about who was waiting at home to receive the patient.",
    "A fishing cooperative that pooled its catch data found that the boats reporting the most "
    "were not the most productive but the ones whose skippers had the time to write.",
    "The municipal library's decision to stop fining late returns increased the number of books "
    "that came back, because the fines had been deterring the return rather than the delay.",
]

SEQUENCE = ["hard", "medium", "elite", "hard", "medium", "elite", "hard", "medium",
            "hard", "elite", "medium", "hard", "elite", "medium"]
RESUME_AT = 3


def norm(text: str) -> str:
    text = _RC.sub(lambda m: f"RC-{m.group(1)}-DATE-{m.group(2)}", text or "")
    return _DATE.sub("TIMESTAMP", text)


def sha(text: str) -> str:
    return hashlib.sha1(norm(text).encode("utf-8")).hexdigest()


class Patcher:
    """Minimal setattr/restore, so the scenario does not need pytest."""

    def __init__(self):
        self._undo = []

    def setattr(self, target, name, value):
        self._undo.append((target, name, getattr(target, name)))
        setattr(target, name, value)

    def undo(self):
        while self._undo:
            target, name, old = self._undo.pop()
            setattr(target, name, old)


def _pin_clock_and_ids(patch: Patcher):
    import rc_engine.composer as composer_mod
    counter = {"n": 0}

    class _U:
        # The composer keeps hex[:8], so the counter must lead.
        def __init__(self, n):
            self.hex = f"{n:08x}" + "0" * 24

    def uuid4():
        counter["n"] += 1
        return _U(counter["n"])

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 13, 12, 0, 0, tzinfo=tz or timezone.utc)

    patch.setattr(composer_mod.uuid, "uuid4", uuid4)
    patch.setattr(composer_mod, "datetime", _DT)


def _recording_llm():
    from rc_engine.llm import MockLLMClient

    class RecordingLLM(MockLLMClient):
        def __init__(self):
            self.calls: list[dict] = []

        def call(self, ledger, stage, model, max_tokens, system, user, context=None):
            self.calls.append({"stage": stage, "model": model, "max_tokens": max_tokens,
                               "system": sha(system), "user": sha(user)})
            return super().call(ledger, stage, model, max_tokens, system, user, context)

    return RecordingLLM()


def _policy_module():
    """None on an engine from before generation policies (golden capture)."""
    try:
        from rc_engine import generation_policy
    except ImportError:
        return None
    return generation_policy


def _blueprint_snapshot(pipe, bp_id: str) -> dict:
    from rc_engine.models import Blueprint
    row = pipe.history.conn.execute(
        "SELECT blueprint_json, status FROM blueprints WHERE blueprint_id = ?", (bp_id,)).fetchone()
    if not row:
        return {}
    bp = Blueprint.from_json(row[0])
    eng = pipe.qengine
    gp = _policy_module()
    if gp is None:
        slots = eng._scale_slots(eng._assign_traps(eng._retarget_thesis(
            pipe.registry.get("topology", bp.topology_id)["slots"], bp), bp), bp.tier)
        shapes = eng._stem_shapes(slots, bp)
    else:
        slots = eng.effective_slots(bp)
        shapes = eng._stem_shapes(slots, bp, gp.policy_for_blueprint(bp))
    snap = {
        "status": row[1], "components": bp.component_ids, "topic_shape": bp.topic_shape_id,
        "schema": bp.argument_schema_id, "move_plan": bp.move_plan,
        "closing_register": bp.closing_register, "movement": bp.movement_string(),
        "revelation_detail": bp.revelation_detail, "letter_plan": bp.letter_plan,
        "instability": bp.instability, "effective_slots": slots,
        "stem_shapes": shapes,
    }
    # Only non-legacy plans add these keys, so legacy snapshots keep the
    # pre-policy golden's shape.
    if getattr(bp, "generation_policy", ""):
        snap["generation_policy"] = bp.generation_policy
        snap["question_slots_stored"] = bool(bp.question_slots)
    return snap


def run_scenario(workdir: str, sequence=SEQUENCE, resume_at=RESUME_AT, seed=20260913,
                 probes=True, setup=None, switch_at=None, on_switch=None, between=None,
                 probe_tiers=("medium", "hard", "elite")) -> dict:
    """setup(patch) runs after imports and before the pipeline is built, so a
    caller can install a policy configuration or a component directory.

    on_switch(patch) runs once, before attempt `switch_at`; between(patch, i,
    tier) runs before every attempt from `switch_at` on. Both are how a test
    turns a policy on part-way through, with the history, RNG state and ids
    at that point identical to a run that never turns it on."""
    from rc_engine import config
    from rc_engine.history import HistoryStore
    from rc_engine.models import Blueprint, SeedEssay
    from rc_engine.pipeline import RCPipeline
    from rc_engine.question_engine import QuestionEngineError

    patch = Patcher()
    _pin_clock_and_ids(patch)
    if setup:
        setup(patch)
    history = HistoryStore(os.path.join(workdir, "policy-scenario.db"))
    llm = _recording_llm()
    pipe = RCPipeline(history, llm, embed=False, rng=random.Random(seed))
    out: dict = {"attempts": [], "resume": None, "topology_repick": [], "probes": []}

    real_build = pipe.qengine.build
    fail_once = {"armed": False, "fired": False}

    def build(*a, **kw):
        if fail_once["armed"] and not fail_once["fired"]:
            fail_once["fired"] = True
            raise QuestionEngineError("forced failure for the resume scenario")
        return real_build(*a, **kw)

    patch.setattr(pipe.qengine, "build", build)
    try:
        for i, tier in enumerate(sequence):
            if switch_at is not None and i == switch_at and on_switch:
                on_switch(patch)
            if switch_at is not None and i >= switch_at and between:
                between(patch, i, tier)
            fail_once["armed"] = i >= resume_at
            seed_essay = SeedEssay(url=f"https://example.org/source-{i}", title=f"Source {i}",
                                   text=SOURCES[i % len(SOURCES)])
            start = len(llm.calls)
            res = pipe.generate_one(tier, seed_essay)
            out["attempts"].append({
                "tier": tier, "status": res.status, "rc_id": norm(res.rc_id or ""),
                "blueprint_id": res.blueprint_id, "notes": [norm(n) for n in res.notes],
                "ban_families": res.ban_families, "ban_movements": res.ban_movements,
                "calls": llm.calls[start:],
                "blueprint": _blueprint_snapshot(pipe, res.blueprint_id) if res.blueprint_id else {},
            })
            if res.status == "failed_questions" and out["resume"] is None:
                start = len(llm.calls)
                again = pipe.resume_questions(res.blueprint_id)
                out["resume"] = {"attempt": i, "tier": tier,
                                 "status": again.status, "rc_id": norm(again.rc_id or ""),
                                 "notes": [norm(n) for n in again.notes],
                                 "calls": llm.calls[start:],
                                 "blueprint": _blueprint_snapshot(pipe, res.blueprint_id)}

        if probes:
            rows = history.conn.execute("SELECT blueprint_json FROM blueprints ORDER BY rowid").fetchall()
            seen = set()
            for (raw,) in rows:
                probe = Blueprint.from_json(raw)
                if probe.tier in seen or probe.tier not in probe_tiers:
                    continue
                seen.add(probe.tier)
                original = probe.topology_id
                real = pipe._topology_collisions
                patch.setattr(pipe, "_topology_collisions",
                              lambda tid, o=original, real=real:
                              [(0.99, "RC-FORCED")] if tid == o else real(tid))
                probe.blueprint_id = f"BP_PROBE_TOPOLOGY_{probe.tier}"
                bp2, notes, ok = pipe._resolve_topology(probe)
                setattr(pipe, "_topology_collisions", real)
                out["topology_repick"].append({"tier": probe.tier, "from": original,
                                               "to": bp2.topology_id, "ok": ok,
                                               "notes": [norm(n) for n in notes]})
            comp = pipe.composer
            gp = _policy_module()
            for tier in probe_tiers:
                # New-plan policy for the tier, as generate_one would use it.
                kw = {"policy": gp.policy_for_new_plan(tier)} if gp else {}
                fams = comp._eligible("family", tier, **kw)
                ban = set(fams[:-2])
                for schema in sorted(config.ARGUMENT_SCHEMAS):
                    comp.rng = random.Random(f"{seed}:{tier}:{schema}")
                    try:
                        got = {"ids": comp.sample_skeleton(tier, ban_families=set(ban),
                                                           argument_schema_id=schema, **kw)}
                    except Exception as e:                       # noqa: BLE001
                        got = {"error": type(e).__name__}
                    out["probes"].append({"tier": tier, "schema": schema,
                                          "eligible_families": fams, **got})
    finally:
        patch.undo()
        history.close()
    return out


def tier_view(result: dict, tier: str) -> dict:
    """The part of a scenario that belongs to one tier."""
    return {"attempts": [a for a in result["attempts"] if a["tier"] == tier],
            "topology_repick": [t for t in result["topology_repick"] if t["tier"] == tier],
            "probes": [p for p in result["probes"] if p["tier"] == tier]}


def run_in_subprocess(out_path: str, workdir: str, options: dict | None = None) -> dict:
    env = dict(os.environ, PYTHONHASHSEED="0", RC_ENGINE_NEW_PLAN_POLICY="",
               RC_ENGINE_DB=os.path.join(workdir, "default.db"))
    args = [sys.executable, os.path.join(REPO, "tests", "policy_harness.py"), out_path, workdir]
    if options is not None:
        opt_path = os.path.join(workdir, "options.json")
        with open(opt_path, "w", encoding="utf-8") as f:
            json.dump(options, f)
        args.append(opt_path)
    proc = subprocess.run(args, cwd=REPO, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=900)
    if proc.returncode != 0:
        raise RuntimeError(f"scenario subprocess failed:\n{proc.stdout[-4000:]}\n{proc.stderr[-4000:]}")
    with open(out_path, encoding="utf-8") as f:
        return json.load(f)


def _hook(options: dict, key: str):
    """options[key] = "module:function" from tests/; called with (patch,
    options, *args). Lets tests install a policy configuration without a
    second copy of this scenario."""
    if not options.get(key):
        return None
    mod_name, fn_name = options[key].split(":")
    sys.path.insert(0, os.path.join(REPO, "tests"))
    fn = getattr(__import__(mod_name), fn_name)
    return lambda patch, *args: fn(patch, options, *args)


def _main():
    # RC_POLICY_ENGINE_ROOT points at another checkout's rc_engine — used only
    # to capture a golden from a pre-policy commit.
    sys.path.insert(0, os.environ.get("RC_POLICY_ENGINE_ROOT") or REPO)
    out_path, workdir = sys.argv[1], sys.argv[2]
    options = {}
    if len(sys.argv) > 3:
        with open(sys.argv[3], encoding="utf-8") as f:
            options = json.load(f)
    result = run_scenario(workdir,
                          sequence=options.get("sequence", SEQUENCE),
                          resume_at=options.get("resume_at", RESUME_AT),
                          probes=options.get("probes", True),
                          setup=_hook(options, "setup"),
                          switch_at=options.get("switch_at"),
                          on_switch=_hook(options, "switch"),
                          between=_hook(options, "between"),
                          probe_tiers=tuple(options.get("probe_tiers",
                                                        ("medium", "hard", "elite"))))
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, indent=1, sort_keys=True)


if __name__ == "__main__":
    _main()
