import base64
import logging
import os
import sys
import time

from redis import Redis
from watchdog.events import FileSystemEventHandler

from settings import Settings


class SyncService:
    """Encapsulates all Redis sync operations.

    Dependencies (settings, logger, redis) are injected at construction time.
    """

    def __init__(self, settings: Settings, logger: logging.Logger, redis: Redis) -> None:
        self._settings = settings
        self._logger = logger
        self._redis = redis

    def _redis_key(self, filepath: str) -> str:
        return f"{self._settings.redis_key_prefix}{os.path.abspath(filepath)}"

    def sync_file(self, filepath: str) -> None:
        """Upsert file metadata and content into Redis."""
        if not os.path.exists(filepath):
            return
        try:
            stat = os.stat(filepath)
            content = base64.b64encode(filepath_bytes := open(filepath, "rb").read()).decode()
            self._redis.hset(
                self._redis_key(filepath),
                mapping={
                    "filename": os.path.basename(filepath),
                    "size_bytes": str(stat.st_size),
                    "mtime": str(stat.st_mtime),
                    "content_stub": content,
                },
            )
            self._logger.info(f"Synced: {filepath}")
        except Exception as e:
            self._logger.error(f"Sync failed — {filepath}: {e}")

    def remove_file(self, filepath: str) -> None:
        """Delete the Redis key for a locally-removed file."""
        self._redis.delete(self._redis_key(filepath))
        self._logger.info(f"Purged from Redis: {filepath}")

    def load_and_restore(self) -> None:
        """On startup: restore every cached file from Redis back to disk."""
        self._logger.info("Restoring files from Redis…")
        os.makedirs(self._settings.watch_dir, exist_ok=True)

        keys = self._redis.keys(f"{self._settings.redis_key_prefix}*")
        if not keys:
            self._logger.info("No cached files found — starting fresh.")
            return

        for key in keys:
            physical_path = key.removeprefix(self._settings.redis_key_prefix)
            metadata = self._redis.hgetall(key)
            if not metadata:
                continue

            os.makedirs(os.path.dirname(physical_path), exist_ok=True)

            if os.path.exists(physical_path):
                cached_size = int(metadata.get("size_bytes", 0))
                if os.path.getsize(physical_path) == cached_size:
                    self._logger.info(f"Up-to-date, skipping: {physical_path}")
                    continue

            try:
                with open(physical_path, "wb") as fh:
                    fh.write(base64.b64decode(metadata.get("content_stub", "")))
                self._logger.info(f"Restored: {physical_path}")

                if mtime := metadata.get("mtime"):
                    os.utime(physical_path, (time.time(), float(mtime)))
            except Exception as e:
                self._logger.error(f"Failed to restore {physical_path}: {e}")

        self._logger.info("Restore complete.")


# ---------------------------------------------------------------------------
# Process utilities — stay as plain functions (no external dependencies)
# ---------------------------------------------------------------------------

def write_pid(pid_file: str) -> None:
    with open(pid_file, "w") as fh:
        fh.write(str(os.getpid()))


def read_pid(pid_file: str) -> int | None:
    try:
        with open(pid_file) as fh:
            return int(fh.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def daemonize() -> None:
    """Double-fork daemonization — detaches from the controlling terminal."""
    if os.fork() > 0:
        sys.exit(0)

    os.setsid()

    if os.fork() > 0:
        sys.exit(0)

    sys.stdout.flush()
    sys.stderr.flush()
    with open(os.devnull, "r+") as devnull:
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            os.dup2(devnull.fileno(), stream.fileno())


class FolderWatchHandler(FileSystemEventHandler):
    """Propagates real-time file-system events to Redis via the SyncService."""

    def __init__(self, service: SyncService) -> None:
        super().__init__()
        self._service = service

    def on_created(self, event):
        if not event.is_directory:
            self._service.sync_file(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._service.sync_file(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self._service.remove_file(event.src_path)


def is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
