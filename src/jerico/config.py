from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JERICO_", env_file=".env", extra="ignore")

    llm_base_url: str = "https://api.example.com/v1"
    llm_api_key: str = "changeme"
    llm_model_l1: str = "glm-5.3-flash"
    llm_model_l2: str = "deepseek-flash"
    router_l2_keywords: str = "codigo,auditoria,finanzas,arquitectura"

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    api_token: str = "changeme"
    allowed_telegram_ids: str = ""

    redis_url: str = ""
    postgres_url: str = ""

    voices_dir: str = "voices"
    stt_model: str = "small"
    tts_engine: str = "fish-s1-mini"

    @property
    def l2_keywords(self) -> tuple[str, ...]:
        return tuple(k.strip().lower() for k in self.router_l2_keywords.split(",") if k.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
