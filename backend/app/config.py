from __future__ import annotations

from pydantic import BaseModel
from pydantic import Field
from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ai_scientist_db_path: str = Field(
        default="ai_scientist.sqlite",
        alias="AI_SCIENTIST_DB_PATH",
    )

    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    tavily_api_key: SecretStr | None = Field(default=None, alias="TAVILY_API_KEY")

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()


class HealthResponse(BaseModel):
    ok: bool = True

