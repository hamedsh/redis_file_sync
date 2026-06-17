import os
import sys
import time
import signal
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from initialize import settings, logger
from utils import (
    sync_file_to_redis,
    remove_file_from_redis,
    load_and_restore_from_redis,
    write_pid,
    read_pid,
    daemonize,
)


class FolderWatchHandler(FileSystemEventHandler):
    """Propagates real-time file-system events to Redis."""

    def on_created(self, event):
        if not event.is_directory:
            sync_file_to_redis(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            sync_file_to_redis(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            remove_file_from_redis(event.src_path)


def run_syncer() -> None:
    """Core sync loop — restore from Redis then watch for changes."""
    write_pid(settings.pid_file)
    logger.info(f"Daemon started (PID {os.getpid()})")

    load_and_restore_from_redis()

    event_handler = FolderWatchHandler()
    observer = Observer()
    observer.schedule(event_handler, settings.watch_dir, recursive=True)
    observer.start()
    logger.info(f"Watching: {settings.watch_dir}")

    def _shutdown(signum, frame):
        logger.info("Shutdown signal received.")
        observer.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        while observer.is_alive():
            time.sleep(1)
    finally:
        observer.join()
        if os.path.exists(settings.pid_file):
            os.remove(settings.pid_file)
        logger.info("Daemon stopped.")


def cmd_start(foreground: bool = False) -> None:
    pid = read_pid(settings.pid_file)
    if pid and _is_running(pid):
        print(f"Already running (PID {pid}).")
        sys.exit(1)

    if foreground:
        run_syncer()
    else:
        daemonize()
        run_syncer()


def cmd_stop() -> None:
    pid = read_pid(settings.pid_file)
    if not pid or not _is_running(pid):
        print("Daemon is not running.")
        sys.exit(1)
    os.kill(pid, signal.SIGTERM)
    print(f"Sent SIGTERM to PID {pid}.")


def cmd_status() -> None:
    pid = read_pid(settings.pid_file)
    if pid and _is_running(pid):
        print(f"Running (PID {pid}).")
    else:
        print("Not running.")


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


USAGE = """
Usage: python main.py <command> [options]

Commands:
  start          Start as a background daemon
  start --fg     Start in the foreground (useful for debugging / Docker)
  stop           Stop the running daemon
  status         Check whether the daemon is running
""".strip()


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        print(USAGE)
        sys.exit(1)

    command = args[0]

    if command == "start":
        foreground = "--fg" in args
        cmd_start(foreground=foreground)
    elif command == "stop":
        cmd_stop()
    elif command == "status":
        cmd_status()
    else:
        print(f"Unknown command: {command}\n")
        print(USAGE)
        sys.exit(1)
