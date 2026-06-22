import logging
import os
import signal
import time

import click
import pydanclick
from lagom import Container
from watchdog.observers import Observer

from initialize import build_container
from settings import Settings
from utils import SyncService, daemonize, read_pid, write_pid, FolderWatchHandler, is_running


def run_syncer(container: Container) -> None:
    """Core sync loop — restore from Redis then watch for changes."""
    settings = container[Settings]
    logger = container[logging.Logger]
    service = container[SyncService]

    write_pid(settings.pid_file)
    logger.info(f"Daemon started (PID {os.getpid()})")

    service.load_and_restore()

    handler = FolderWatchHandler(service)
    observer = Observer()
    observer.schedule(handler, settings.watch_dir, recursive=True)
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
        raise click.UsageError("--watch-dir is required.")

    pid = read_pid(settings_overrides.pid_file)
    if pid and is_running(pid):
        click.echo(f"Already running (PID {pid}).")
        raise SystemExit(1)

    if not foreground:
        daemonize()

    container = build_container(settings_overrides)
    run_syncer(container)


@cli.command("stop")
def cmd_stop() -> None:
    """Stop the running daemon."""
    settings = build_container()[Settings]
    pid = read_pid(settings.pid_file)
    if not pid or not is_running(pid):
        click.echo("Daemon is not running.")
        raise SystemExit(1)
    os.kill(pid, signal.SIGTERM)
    click.echo(f"Sent SIGTERM to PID {pid}.")


@cli.command("status")
def cmd_status() -> None:
    """Check whether the daemon is running."""
    settings = build_container()[Settings]
    pid = read_pid(settings.pid_file)
    click.echo(f"Running (PID {pid})." if pid and is_running(pid) else "Not running.")


if __name__ == "__main__":
    cli()
