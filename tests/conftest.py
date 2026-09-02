from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _no_dotenv_in_tests():
    """Never let a real .env file at the repo root leak into test runs.

    cli.analyze.main() calls load_dotenv() so a developer's real .env
    (LLM_API_KEY etc) works without manual export - but pytest's cwd is the
    repo root, so without this, tests that monkeypatch.delenv the LLM vars
    to assert "no LLM configured" behavior get silently overridden by
    whatever's actually in the developer's .env.
    """
    with patch('sosmed_sentiment.cli.analyze.load_dotenv'):
        yield
