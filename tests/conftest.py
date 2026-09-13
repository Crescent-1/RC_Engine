"""Keep legacy tests that use HistoryStore's default away from production."""

import os
import tempfile


def pytest_configure(config):
    config._original_rc_db = os.environ.get("RC_ENGINE_DB")
    os.environ["RC_ENGINE_DB"] = os.path.join(
        tempfile.mkdtemp(prefix="rc-test-default-"), "history.db")
    # 2026-09-13: a shell (or .env) that opts new plans into a generation
    # policy must not silently change what the suite composes. Set, not
    # popped, so config's .env loader cannot fill it back in.
    config._original_plan_policy = os.environ.get("RC_ENGINE_NEW_PLAN_POLICY")
    os.environ["RC_ENGINE_NEW_PLAN_POLICY"] = ""


def pytest_unconfigure(config):
    original = config._original_rc_db
    if original is None:
        os.environ.pop("RC_ENGINE_DB", None)
    else:
        os.environ["RC_ENGINE_DB"] = original
    if config._original_plan_policy is None:
        os.environ.pop("RC_ENGINE_NEW_PLAN_POLICY", None)
    else:
        os.environ["RC_ENGINE_NEW_PLAN_POLICY"] = config._original_plan_policy
