import logging
import sys

from lagom import Container
from redis import Redis

from settings import Settings


def build_container(settings: Settings | None = None) -> Container:
    """Build and return a fully-wired DI container.

    Pass a pre-built ``Settings`` instance (e.g. from CLI args) to override
    the default env/file-based one.
    """
    container = Container()

    if settings is None:
        settings = Settings()
    container.define(Settings, lambda: settings)

    def _make_logger() -> logging.Logger:
        handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
        if settings.log_file:
            handlers.append(logging.FileHandler(settings.log_file))
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=handlers,
        )
        return logging.getLogger("FileSynchronizer")

    container.define(logging.Logger, _make_logger)

    container.define(
        Redis,
        lambda: Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password,
            db=settings.redis_db,
            decode_responses=True,
        ),
    )

    return container
