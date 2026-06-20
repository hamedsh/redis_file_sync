"""
Shared fixtures for the folder_syncer test suite.

Redis is replaced with a MagicMock so tests run without a live Redis instance.
``make_service`` builds a ``SyncService`` wired to the mock Redis and a real
Settings object pointing at a temporary directory.
"""

import logging
import os
import pytest
from unittest.mock import MagicMock

from settings import Settings
from utils import SyncService


@pytest.fixture()
def mock_redis():
    """A fresh MagicMock that replaces the Redis client."""
    client = MagicMock()
    client.hset.return_value = 1
    client.delete.return_value = 1
    client.keys.return_value = []
    client.hgetall.return_value = {}
    return client


@pytest.fixture()
def logger():
    return logging.getLogger("test")


@pytest.fixture()
def make_service(mock_redis, logger, tmp_path):
    """Factory: returns a SyncService using the given (or default tmp) watch_dir."""
    def _factory(watch_dir: str | None = None):
        settings = Settings(
            watch_dir=watch_dir or str(tmp_path / "watch"),
            redis_key_prefix="file_cache:",
        )
        return SyncService(settings=settings, logger=logger, redis=mock_redis)
    return _factory
