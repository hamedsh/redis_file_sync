"""
Tests for FolderWatchHandler in main.py.
Verifies that watchdog events are routed to the correct SyncService methods.
"""

from unittest.mock import MagicMock
import pytest

from utils import FolderWatchHandler


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


@pytest.fixture()
def handler():
    service = MagicMock()
    return FolderWatchHandler(service), service


class TestFolderWatchHandler:
    def test_on_created_file_calls_sync(self, handler):
        h, service = handler
        h.on_created(_file_event("/data/new.txt"))
        service.sync_file.assert_called_once_with("/data/new.txt")

    def test_on_created_directory_ignored(self, handler):
        h, service = handler
        h.on_created(_dir_event("/data/subdir"))
        service.sync_file.assert_not_called()

    def test_on_modified_file_calls_sync(self, handler):
        h, service = handler
        h.on_modified(_file_event("/data/updated.txt"))
        service.sync_file.assert_called_once_with("/data/updated.txt")

    def test_on_modified_directory_ignored(self, handler):
        h, service = handler
        h.on_modified(_dir_event("/data/subdir"))
        service.sync_file.assert_not_called()

    def test_on_deleted_file_calls_remove(self, handler):
        h, service = handler
        h.on_deleted(_file_event("/data/gone.txt"))
        service.remove_file.assert_called_once_with("/data/gone.txt")

    def test_on_deleted_directory_ignored(self, handler):
        h, service = handler
        h.on_deleted(_dir_event("/data/subdir"))
        service.remove_file.assert_not_called()
