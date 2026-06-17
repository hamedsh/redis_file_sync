"""
Tests for utils.py:
  - get_redis_key
  - sync_file_to_redis
  - remove_file_from_redis
  - load_and_restore_from_redis
  - write_pid / read_pid
"""

import base64
import os
import time
import pytest
from unittest.mock import MagicMock, patch, call

import utils
from utils import get_redis_key, sync_file_to_redis, remove_file_from_redis, write_pid, read_pid


# ---------------------------------------------------------------------------
# get_redis_key
# ---------------------------------------------------------------------------

class TestGetRedisKey:
    def test_uses_prefix_and_absolute_path(self, tmp_path):
        filepath = str(tmp_path / "sample.txt")
        with patch("utils.settings") as s:
            s.redis_key_prefix = "file_cache:"
            key = get_redis_key(filepath)
        assert key == f"file_cache:{os.path.abspath(filepath)}"

    def test_relative_path_is_resolved(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "rel.txt").write_text("hi")
        with patch("utils.settings") as s:
            s.redis_key_prefix = "ns:"
            key = get_redis_key("rel.txt")
        assert key == f"ns:{tmp_path}/rel.txt"


# ---------------------------------------------------------------------------
# sync_file_to_redis
# ---------------------------------------------------------------------------

class TestSyncFileToRedis:
    def test_stores_correct_fields(self, tmp_path, mock_redis):
        f = tmp_path / "hello.txt"
        f.write_bytes(b"hello world")

        with patch("utils.settings") as s:
            s.redis_key_prefix = "file_cache:"
            sync_file_to_redis(str(f))

        mock_redis.hset.assert_called_once()
        _, kwargs = mock_redis.hset.call_args
        mapping = kwargs["mapping"]

        assert mapping["filename"] == "hello.txt"
        assert mapping["size_bytes"] == str(len(b"hello world"))
        assert mapping["content_stub"] == base64.b64encode(b"hello world").decode()

    def test_skips_nonexistent_file(self, tmp_path, mock_redis):
        with patch("utils.settings") as s:
            s.redis_key_prefix = "file_cache:"
            sync_file_to_redis(str(tmp_path / "ghost.txt"))

        mock_redis.hset.assert_not_called()

    def test_handles_read_error_gracefully(self, tmp_path, mock_redis):
        f = tmp_path / "locked.txt"
        f.write_bytes(b"data")

        with patch("builtins.open", side_effect=PermissionError("no access")):
            with patch("utils.settings") as s:
                s.redis_key_prefix = "file_cache:"
                # Should not raise
                sync_file_to_redis(str(f))

        mock_redis.hset.assert_not_called()

    def test_binary_file_content_is_preserved(self, tmp_path, mock_redis):
        binary_data = bytes(range(256))
        f = tmp_path / "binary.bin"
        f.write_bytes(binary_data)

        with patch("utils.settings") as s:
            s.redis_key_prefix = "file_cache:"
            sync_file_to_redis(str(f))

        _, kwargs = mock_redis.hset.call_args
        decoded = base64.b64decode(kwargs["mapping"]["content_stub"])
        assert decoded == binary_data


# ---------------------------------------------------------------------------
# remove_file_from_redis
# ---------------------------------------------------------------------------

class TestRemoveFileFromRedis:
    def test_deletes_correct_key(self, tmp_path, mock_redis):
        filepath = str(tmp_path / "gone.txt")
        with patch("utils.settings") as s:
            s.redis_key_prefix = "file_cache:"
            remove_file_from_redis(filepath)

        expected_key = f"file_cache:{os.path.abspath(filepath)}"
        mock_redis.delete.assert_called_once_with(expected_key)

    def test_delete_called_even_when_file_missing_locally(self, tmp_path, mock_redis):
        """Redis delete should still fire for files already removed from disk."""
        filepath = str(tmp_path / "never_existed.txt")
        with patch("utils.settings") as s:
            s.redis_key_prefix = "file_cache:"
            remove_file_from_redis(filepath)

        mock_redis.delete.assert_called_once()


# ---------------------------------------------------------------------------
# load_and_restore_from_redis
# ---------------------------------------------------------------------------

class TestLoadAndRestoreFromRedis:
    def _make_metadata(self, content: bytes, path: str) -> dict:
        stat = os.stat(path) if os.path.exists(path) else None
        return {
            "filename": os.path.basename(path),
            "size_bytes": str(len(content)),
            "mtime": str(stat.st_mtime if stat else time.time()),
            "content_stub": base64.b64encode(content).decode(),
        }

    def test_restores_missing_file(self, tmp_path, mock_redis):
        content = b"restored content"
        physical_path = str(tmp_path / "watch" / "restored.txt")
        prefix = "file_cache:"

        mock_redis.keys.return_value = [f"{prefix}{physical_path}"]
        mock_redis.hgetall.return_value = {
            "filename": "restored.txt",
            "size_bytes": str(len(content)),
            "mtime": str(time.time()),
            "content_stub": base64.b64encode(content).decode(),
        }

        with patch("utils.settings") as s:
            s.watch_dir = str(tmp_path / "watch")
            s.redis_key_prefix = prefix
            utils.load_and_restore_from_redis()

        assert os.path.exists(physical_path)
        assert open(physical_path, "rb").read() == content

    def test_skips_file_with_matching_size(self, tmp_path, mock_redis):
        content = b"existing content"
        watch = tmp_path / "watch"
        watch.mkdir()
        existing = watch / "existing.txt"
        existing.write_bytes(content)
        prefix = "file_cache:"

        mock_redis.keys.return_value = [f"{prefix}{existing}"]
        mock_redis.hgetall.return_value = {
            "filename": "existing.txt",
            "size_bytes": str(len(content)),  # same size → should skip
            "mtime": str(existing.stat().st_mtime),
            "content_stub": base64.b64encode(content).decode(),
        }

        original_mtime = existing.stat().st_mtime

        with patch("utils.settings") as s:
            s.watch_dir = str(watch)
            s.redis_key_prefix = prefix
            utils.load_and_restore_from_redis()

        # file should be untouched
        assert existing.stat().st_mtime == original_mtime

    def test_overwrites_file_with_different_size(self, tmp_path, mock_redis):
        watch = tmp_path / "watch"
        watch.mkdir()
        target = watch / "changed.txt"
        target.write_bytes(b"old")  # 3 bytes on disk
        new_content = b"brand new content"  # different size
        prefix = "file_cache:"

        mock_redis.keys.return_value = [f"{prefix}{target}"]
        mock_redis.hgetall.return_value = {
            "filename": "changed.txt",
            "size_bytes": str(len(new_content)),
            "mtime": str(time.time()),
            "content_stub": base64.b64encode(new_content).decode(),
        }

        with patch("utils.settings") as s:
            s.watch_dir = str(watch)
            s.redis_key_prefix = prefix
            utils.load_and_restore_from_redis()

        assert target.read_bytes() == new_content

    def test_no_keys_does_nothing(self, tmp_path, mock_redis):
        mock_redis.keys.return_value = []

        with patch("utils.settings") as s:
            s.watch_dir = str(tmp_path / "watch")
            s.redis_key_prefix = "file_cache:"
            utils.load_and_restore_from_redis()

        mock_redis.hgetall.assert_not_called()

    def test_sets_mtime_after_restore(self, tmp_path, mock_redis):
        content = b"timestamped"
        watch = tmp_path / "watch"
        watch.mkdir()
        target = watch / "ts.txt"
        expected_mtime = 1_700_000_000.0
        prefix = "file_cache:"

        mock_redis.keys.return_value = [f"{prefix}{target}"]
        mock_redis.hgetall.return_value = {
            "filename": "ts.txt",
            "size_bytes": str(len(content)),
            "mtime": str(expected_mtime),
            "content_stub": base64.b64encode(content).decode(),
        }

        with patch("utils.settings") as s:
            s.watch_dir = str(watch)
            s.redis_key_prefix = prefix
            utils.load_and_restore_from_redis()

        assert abs(target.stat().st_mtime - expected_mtime) < 1.0


# ---------------------------------------------------------------------------
# write_pid / read_pid
# ---------------------------------------------------------------------------

class TestPidHelpers:
    def test_write_and_read_roundtrip(self, tmp_path):
        pid_file = str(tmp_path / "test.pid")
        write_pid(pid_file)
        assert read_pid(pid_file) == os.getpid()

    def test_read_pid_missing_file_returns_none(self, tmp_path):
        assert read_pid(str(tmp_path / "no.pid")) is None

    def test_read_pid_corrupt_file_returns_none(self, tmp_path):
        pid_file = tmp_path / "bad.pid"
        pid_file.write_text("not-a-number")
        assert read_pid(str(pid_file)) is None

    def test_write_pid_overwrites_existing(self, tmp_path):
        pid_file = str(tmp_path / "overwrite.pid")
        with open(pid_file, "w") as f:
            f.write("99999")
        write_pid(pid_file)
        assert read_pid(pid_file) == os.getpid()
