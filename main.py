import base64
import os
import time
import logging
from redis import Redis
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("FileSynchronizer")

WATCH_DIR = os.getenv("WATCH_DIR", "data")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_KEY_PREFIX = "file_cache:"

redis_client = Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def get_redis_key(filepath: str) -> str:
    return f"{REDIS_KEY_PREFIX}{os.path.abspath(filepath)}"


def sync_file_to_redis(filepath: str):
    """Updates database when file changes during runtime."""
    if not os.path.exists(filepath):
        return
    try:
        stat = os.stat(filepath)
        with open(filepath, "rb") as f:
            base_64_content = base64.b64encode(f.read())
        file_data = {
            "filename": os.path.basename(filepath),
            "size_bytes": str(stat.st_size),
            "mtime": str(stat.st_mtime),
            "content_stub": base_64_content
        }
        redis_client.hset(get_redis_key(filepath), mapping=file_data)
        logger.info(f"Runtime Sync -> Updated DB: {filepath}")
    except Exception as e:
        logger.error(f"Runtime Sync Failure -> {filepath}: {e}")


def remove_file_from_redis(filepath: str):
    """Removes key from Redis if deleted locally at runtime."""
    redis_client.delete(get_redis_key(filepath))
    logger.info(f"Runtime Sync -> Purged key from DB: {filepath}")


class FolderWatchHandler(FileSystemEventHandler):
    """Handles real-time file updates AFTER initialization."""

    def on_created(self, event):
        if not event.is_directory:
            sync_file_to_redis(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            sync_file_to_redis(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            remove_file_from_redis(event.src_path)


def load_and_restore_from_redis():
    """
    Step 1 & 4: Reads Redis state on boot, then creates or overwrites
    local files to match the DB state perfectly.
    """
    logger.info("Boot Phase: Restoring files from Redis to local storage...")
    os.makedirs(WATCH_DIR, exist_ok=True)

    cached_keys = redis_client.keys(f"{REDIS_KEY_PREFIX}*")

    if not cached_keys:
        logger.info(
            "No files found in Redis. Starting with an empty directory tracking space."
        )
        return

    for key in cached_keys:
        physical_path = key.replace(REDIS_KEY_PREFIX, "")

        file_metadata = redis_client.hgetall(key)
        if not file_metadata:
            continue

        file_content = file_metadata.get("content_stub", "")

        os.makedirs(os.path.dirname(physical_path), exist_ok=True)

        if os.path.exists(physical_path):
            cached_size = int(file_metadata.get("size_bytes", 0))
            if os.path.getsize(physical_path) == cached_size:
                logger.info(f"File matches DB state. Skipping write: {physical_path}")
                continue

        try:
            with open(physical_path, "bw") as f:
                f.write(base64.b64decode(file_content))
            logger.info(f"Successfully restored file from Redis: {physical_path}")

            # Sync back up modification times if necessary to align OS timestamps
            if "mtime" in file_metadata:
                mtime = float(file_metadata["mtime"])
                os.utime(physical_path, (time.time(), mtime))

        except Exception as e:
            logger.error(f"Failed to restore file {physical_path}: {e}")

    logger.info("Boot reconstruction phase complete.")


if __name__ == "__main__":
    load_and_restore_from_redis()

    event_handler = FolderWatchHandler()
    observer = Observer()
    observer.schedule(event_handler, WATCH_DIR, recursive=True)
    observer.start()
    logger.info(f"Live engine monitoring active on: {WATCH_DIR}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
