"""Keep legacy tests that use HistoryStore's default away from production."""

import os
import tempfile


def pytest_configure(config):
    config._original_rc_db = os.environ.get("RC_ENGINE_DB")
    os.environ["RC_ENGINE_DB"] = os.path.join(
        tempfile.mkdtemp(prefix="rc-test-default-"), "history.db")


def pytest_unconfigure(config):
    original = config._original_rc_db
    if original is None:
        os.environ.pop("RC_ENGINE_DB", None)
    else:
        os.environ["RC_ENGINE_DB"] = original
