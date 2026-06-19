import logging
import os
import signal
import time

import click
import pydanclick
from lagom import Container
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from initialize import build_container
from settings import Settings
from utils import SyncService, daemonize, read_pid, write_pid


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


def run_syncer(container: Container) -> None:
    """Core sync loop — restore from Redis then watch for changes."""
    settings = container[Settings]
    logger = container[logging.Logger]
    service = container[SyncService]

    write_pid(settings.pid_file)
    logger.info(f"Daemon started (PID {os.getpid()})")

    service.load_and_restore()

    event_handler = FolderWatchHandler(service)
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


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@click.group()
def cli():
    """Folder Syncer — watches a directory and syncs files to Redis."""


@cli.command("start")
@click.option("--fg", "foreground", is_flag=True, default=False,
              help="Run in the foreground instead of daemonizing.")
@pydanclick.from_pydantic("settings_overrides", Settings)
def cmd_start(foreground: bool, settings_overrides: Settings) -> None:
    """Start the syncer (background daemon by default)."""
    if settings_overrides.watch_dir is None:
        raise Exception("watch-dir is required.")
    container = build_container(settings_overrides)

    pid = read_pid(settings_overrides.pid_file)
    if pid and _is_running(pid):
        click.echo(f"Already running (PID {pid}).")
        raise SystemExit(1)

    if foreground:
        run_syncer(container)
    else:
        daemonize()
        run_syncer(container)


@cli.command("stop")
def cmd_stop() -> None:
    """Stop the running daemon."""
    container = build_container()
    settings = container[Settings]
    pid = read_pid(settings.pid_file)
    if not pid or not _is_running(pid):
        click.echo("Daemon is not running.")
        raise SystemExit(1)
    os.kill(pid, signal.SIGTERM)
    click.echo(f"Sent SIGTERM to PID {pid}.")


@cli.command("status")
def cmd_status() -> None:
    """Check whether the daemon is running."""
    container = build_container()
    settings = container[Settings]
    pid = read_pid(settings.pid_file)
    if pid and _is_running(pid):
        click.echo(f"Running (PID {pid}).")
    else:
        click.echo("Not running.")


if __name__ == "__main__":
    cli()
