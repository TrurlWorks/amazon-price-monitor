from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MONITOR_")

    amazon_client_id: SecretStr = Field(
        default=SecretStr(""), alias="AMAZON_CLIENT_ID", repr=False, exclude=True,
    )
    amazon_client_secret: SecretStr = Field(
        default=SecretStr(""), alias="AMAZON_CLIENT_SECRET", repr=False, exclude=True,
    )
    amazon_partner_tag: SecretStr = Field(
        default=SecretStr(""), alias="AMAZON_PARTNER_TAG", repr=False, exclude=True,
    )
    data_dir: Path = Path("./data")
    product_provider: Literal["mock", "amazon_page"] = Field(
        default="mock", alias="PRODUCT_PROVIDER",
    )
    mock_scenario: Literal["stable", "decreasing", "increasing", "temporary", "recovered"] = "stable"
    not_found_threshold: int = Field(default=3, ge=1)
    unavailable_threshold: int = Field(default=2, ge=1)
    poll_interval_seconds: int = Field(
        default=21600, ge=60, alias="POLL_INTERVAL_SECONDS",
    )
    failed_retry_seconds: int = Field(
        default=60, ge=60, alias="FAILED_RETRY_SECONDS",
    )
    queue_gap_seconds: int = Field(default=180, ge=60, alias="QUEUE_GAP_SECONDS")
