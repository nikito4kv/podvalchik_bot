from typing import List, Optional, Union
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):
    bot_token: str
    database_url: str
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: Optional[str] = None
    admin_ids: Union[List[int], str] = Field(default_factory=list)
    bug_report_chat_id: Optional[Union[int, str]] = None
    tg_api_server: Optional[str] = None
    tg_media_request_timeout: int = 180
    tg_media_max_attempts: int = 2
    tg_media_retry_backoff_seconds: float = 1.5
    temp_media_enabled: bool = False
    temp_media_upload_url: Optional[str] = None
    temp_media_upload_token: Optional[str] = None
    temp_media_ttl_seconds: int = 300
    temp_media_upload_timeout: int = 30

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip().isdigit()]
        if isinstance(v, int):
            return [v]
        return v


config = Settings()
