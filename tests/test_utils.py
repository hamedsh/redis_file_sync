"""
Tests for SyncService (utils.py) and PID helpers.
"""

import base64
import os
import time
import pytest

from utils import write_pid, read_pid


# ---------------------------------------------------------------------------
# SyncService._redis_key  (via sync_file / remove_file behaviour)
# ---------------------------------------------------------------------------

class TestRedisKey:
    def test_uses_prefix_and_absolute_path(self, make_service, tmp_path):
        f = tmp_path / "sample.txt"
        f.write_bytes(b"x")
        service = make_service()
        service.sync_file(str(f))
        key_used = service._redis.hset.call_args[0][0]
        assert key_used == f"file_cache:{os.path.abspath(f)}"

    def test_relative_path_is_resolved(self, make_service, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "rel.txt").write_text("hi")
        service = make_service(watch_dir=str(tmp_path))
        service.sync_file("rel.txt")
        key_used = service._redis.hset.call_args[0][0]
        assert key_used == f"file_cache:{tmp_path}/rel.txt"


# ---------------------------------------------------------------------------
# SyncService.sync_file
# ---------------------------------------------------------------------------

class TestSyncFile:
    def test_stores_correct_fields(self, make_service, tmp_path, mock_redis):
        f = tmp_path / "hello.txt"
        f.write_bytes(b"hello world")
        make_service().sync_file(str(f))

        mock_redis.hset.assert_called_once()
        mapping = mock_redis.hset.call_args[1]["mapping"]
        assert mapping["filename"] == "hello.txt"
        assert mapping["size_bytes"] == str(len(b"hello world"))
        assert mapping["content_stub"] == base64.b64encode(b"hello world").decode()

    def test_skips_nonexistent_file(self, make_service, tmp_path, mock_redis):
        make_service().sync_file(str(tmp_path / "ghost.txt"))
        mock_redis.hset.assert_not_called()

    def test_handles_read_error_gracefully(self, make_service, tmp_path, mock_redis):
        f = tmp_path / "locked.txt"
        f.write_bytes(b"data")
        from unittest.mock import patch
        with patch("builtins.open", side_effect=PermissionError("no access")):
            make_service().sync_file(str(f))  # must not raise
        mock_redis.hset.assert_not_called()

    def test_binary_file_content_is_preserved(self, make_service, tmp_path, mock_redis):
        binary_data = bytes(range(256))
        f = tmp_path / "binary.bin"
        f.write_bytes(binary_data)
        make_service().sync_file(str(f))

        mapping = mock_redis.hset.call_args[1]["mapping"]
        assert base64.b64decode(mapping["content_stub"]) == binary_data


# ---------------------------------------------------------------------------
# SyncService.remove_file
# ---------------------------------------------------------------------------

class TestRemoveFile:
    def test_deletes_correct_key(self, make_service, tmp_path, mock_redis):
        filepath = str(tmp_path / "gone.txt")
        make_service().remove_file(filepath)
        expected_key = f"file_cache:{os.path.abspath(filepath)}"
        mock_redis.delete.assert_called_once_with(expected_key)

    def test_delete_called_even_when_file_missing_locally(self, make_service, tmp_path, mock_redis):
        """Redis delete should still fire for files already removed from disk."""
        make_service().remove_file(str(tmp_path / "never_existed.txt"))
        mock_redis.delete.assert_called_once()


# ---------------------------------------------------------------------------
# SyncService.load_and_restore
# ---------------------------------------------------------------------------

class TestLoadAndRestore:
    def _metadata(self, content: bytes, path: str) -> dict:
        mtime = os.stat(path).st_mtime if os.path.exists(path) else time.time()
        return {
            "filename": os.path.basename(path),
            "size_bytes": str(len(content)),
            "mtime": str(mtime),
            "content_stub": base64.b64encode(content).decode(),
        }

    def test_restores_missing_file(self, make_service, tmp_path, mock_redis):
        content = b"restored content"
        watch = tmp_path / "watch"
        physical_path = str(watch / "restored.txt")
        prefix = "file_cache:"

        mock_redis.keys.return_value = [f"{prefix}{physical_path}"]
        mock_redis.hgetall.return_value = {
            "filename": "restored.txt",
            "size_bytes": str(len(content)),
            "mtime": str(time.time()),
            "content_stub": base64.b64encode(content).decode(),
        }

        make_service(watch_dir=str(watch)).load_and_restore()

        assert os.path.exists(physical_path)
        assert open(physical_path, "rb").read() == content

    def test_skips_file_with_matching_size(self, make_service, tmp_path, mock_redis):
        content = b"existing content"
        watch = tmp_path / "watch"
        watch.mkdir()
        existing = watch / "existing.txt"
        existing.write_bytes(content)
        prefix = "file_cache:"

        mock_redis.keys.return_value = [f"{prefix}{existing}"]
        mock_redis.hgetall.return_value = {
            "filename": "existing.txt",
            "size_bytes": str(len(content)),
            "mtime": str(existing.stat().st_mtime),
            "content_stub": base64.b64encode(content).decode(),
        }

        original_mtime = existing.stat().st_mtime
        make_service(watch_dir=str(watch)).load_and_restore()
        assert existing.stat().st_mtime == original_mtime

    def test_overwrites_file_with_different_size(self, make_service, tmp_path, mock_redis):
        watch = tmp_path / "watch"
        watch.mkdir()
        target = watch / "changed.txt"
        target.write_bytes(b"old")
        new_content = b"brand new content"
        prefix = "file_cache:"

        mock_redis.keys.return_value = [f"{prefix}{target}"]
        mock_redis.hgetall.return_value = {
            "filename": "changed.txt",
            "size_bytes": str(len(new_content)),
            "mtime": str(time.time()),
            "content_stub": base64.b64encode(new_content).decode(),
        }

        make_service(watch_dir=str(watch)).load_and_restore()
        assert target.read_bytes() == new_content

    def test_no_keys_does_nothing(self, make_service, mock_redis):
        mock_redis.keys.return_value = []
        make_service().load_and_restore()
        mock_redis.hgetall.assert_not_called()

    def test_sets_mtime_after_restore(self, make_service, tmp_path, mock_redis):
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

        make_service(watch_dir=str(watch)).load_and_restore()
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
