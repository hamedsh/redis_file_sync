"""
Tests for FolderWatchHandler in main.py.
Verifies that watchdog events are routed to the correct utils functions.
"""

import pytest
from unittest.mock import patch, MagicMock

from main import FolderWatchHandler


def _file_event(path: str) -> MagicMock:
    event = MagicMock()
    event.is_directory = False
    event.src_path = path
    return event


def _dir_event(path: str) -> MagicMock:
    event = MagicMock()
    event.is_directory = True
    event.src_path = path
    return event


class TestFolderWatchHandler:
    def setup_method(self):
        self.handler = FolderWatchHandler()

    def test_on_created_file_calls_sync(self):
        with patch("main.sync_file_to_redis") as mock_sync:
            self.handler.on_created(_file_event("/data/new.txt"))
        mock_sync.assert_called_once_with("/data/new.txt")

    def test_on_created_directory_ignored(self):
        with patch("main.sync_file_to_redis") as mock_sync:
            self.handler.on_created(_dir_event("/data/subdir"))
        mock_sync.assert_not_called()

    def test_on_modified_file_calls_sync(self):
        with patch("main.sync_file_to_redis") as mock_sync:
            self.handler.on_modified(_file_event("/data/updated.txt"))
        mock_sync.assert_called_once_with("/data/updated.txt")

    def test_on_modified_directory_ignored(self):
        with patch("main.sync_file_to_redis") as mock_sync:
            self.handler.on_modified(_dir_event("/data/subdir"))
        mock_sync.assert_not_called()

    def test_on_deleted_file_calls_remove(self):
        with patch("main.remove_file_from_redis") as mock_remove:
            self.handler.on_deleted(_file_event("/data/gone.txt"))
        mock_remove.assert_called_once_with("/data/gone.txt")

    def test_on_deleted_directory_ignored(self):
        with patch("main.remove_file_from_redis") as mock_remove:
            self.handler.on_deleted(_dir_event("/data/subdir"))
        mock_remove.assert_not_called()
