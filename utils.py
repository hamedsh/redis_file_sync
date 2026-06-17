import base64
import os
import sys
import time

from initialize import redis_client, logger, settings


def sync_file_to_redis(filepath: str) -> None:
    """Upsert file metadata and content into Redis."""
    if not os.path.exists(filepath):
        return
    try:
        stat = os.stat(filepath)
        with open(filepath, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()
        file_data = {
            "filename": os.path.basename(filepath),
            "size_bytes": str(stat.st_size),
            "mtime": str(stat.st_mtime),
            "content_stub": encoded,
        }
        redis_client.hset(get_redis_key(filepath), mapping=file_data)
        logger.info(f"Runtime Sync -> Updated DB: {filepath}")
    except Exception as e:
        logger.error(f"Runtime Sync Failure -> {filepath}: {e}")


def remove_file_from_redis(filepath: str) -> None:
    """Delete the Redis key for a locally-removed file."""
    redis_client.delete(get_redis_key(filepath))
    logger.info(f"Runtime Sync -> Purged key from DB: {filepath}")


def get_redis_key(filepath: str) -> str:
    return f"{settings.redis_key_prefix}{os.path.abspath(filepath)}"


def load_and_restore_from_redis() -> None:
    logger.info("Boot Phase: Restoring files from Redis to local storage...")
    os.makedirs(settings.watch_dir, exist_ok=True)

    cached_keys = redis_client.keys(f"{settings.redis_key_prefix}*")

    if not cached_keys:
        logger.info("No files found in Redis. Starting fresh.")
        return

    for key in cached_keys:
        physical_path = key.replace(settings.redis_key_prefix, "")
        file_metadata = redis_client.hgetall(key)
        if not file_metadata:
            continue

        file_content = file_metadata.get("content_stub", "")
        os.makedirs(os.path.dirname(physical_path), exist_ok=True)

        if os.path.exists(physical_path):
            cached_size = int(file_metadata.get("size_bytes", 0))
            if os.path.getsize(physical_path) == cached_size:
                logger.info(f"File matches DB state. Skipping: {physical_path}")
                continue

        try:
            with open(physical_path, "wb") as f:
                f.write(base64.b64decode(file_content))
            logger.info(f"Restored from Redis: {physical_path}")

            if "mtime" in file_metadata:
                mtime = float(file_metadata["mtime"])
                os.utime(physical_path, (time.time(), mtime))
        except Exception as e:
            logger.error(f"Failed to restore {physical_path}: {e}")

    logger.info("Boot reconstruction phase complete.")


def write_pid(pid_file: str) -> None:
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))


def read_pid(pid_file: str) -> int | None:
    try:
        with open(pid_file) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def daemonize() -> None:
    """
    Double-fork daemonization.
    Detaches the process from the controlling terminal so it runs in the
    background without any TTY.  Log output goes to settings.log_file.
    """
    # First fork
    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    os.setsid()

    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    sys.stdout.flush()
    sys.stderr.flush()
    devnull = open(os.devnull, "r+")
    os.dup2(devnull.fileno(), sys.stdin.fileno())
    os.dup2(devnull.fileno(), sys.stdout.fileno())
    os.dup2(devnull.fileno(), sys.stderr.fileno())
