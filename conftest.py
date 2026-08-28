import os
import sys

import pytest

from loguru import logger

# Puts the repo root on sys.path so tests can import batch.py and main.py,
# which live at the root rather than in a package.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def log_messages():
    """Collect loguru output as a list of strings.

    pytest's capsys/capfd do not see these: loguru's default handler holds the
    sys.stderr object from import time, before pytest installs its capture.
    Adding a sink is the supported way to read log output back.
    """
    messages = []
    sink_id = logger.add(messages.append, level='DEBUG', format='{level} {message}')

    yield messages

    logger.remove(sink_id)
