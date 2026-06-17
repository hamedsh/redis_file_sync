"""
Shared fixtures for the folder_syncer test suite.

Redis is replaced with a MagicMock so tests run without a live Redis instance.
The settings object is patched to use a known temporary directory so tests
never touch the real file-system paths configured in .env.
"""

import os
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture()
def mock_redis():
    """A fresh MagicMock that replaces the redis_client used by utils."""
    client = MagicMock()
    # hset / delete / keys / hgetall return sensible defaults unless overridden
    client.hset.return_value = 1
    client.delete.return_value = 1
    client.keys.return_value = []
    client.hgetall.return_value = {}
    with patch("utils.redis_client", client):
        yield client


@pytest.fixture()
def tmp_watch_dir(tmp_path):
    """Patch settings.watch_dir to a temp directory for the duration of a test."""
    watch_dir = str(tmp_path / "watch")
    os.makedirs(watch_dir, exist_ok=True)
    with patch("utils.settings") as mock_settings:
        mock_settings.watch_dir = watch_dir
        mock_settings.redis_key_prefix = "file_cache:"
        yield mock_settings, watch_dir
