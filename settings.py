from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    watch_dir: str|None = None
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_key_prefix: str = "file_cache:"
    pid_file: str = "/tmp/folder_syncer.pid"
    log_file: str = "/tmp/folder_syncer.log"

    @field_validator("watch_dir")
    @classmethod
    def validate_api_key(cls, value):
        if not value:
            raise ValueError("WATCH_DIR environment variable must be set.")
        return value
