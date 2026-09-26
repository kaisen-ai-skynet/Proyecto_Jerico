from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from jerico.textutil import normalize

PLACEHOLDER_TOKENS = frozenset({"", "changeme"})


def _csv(raw: str) -> tuple[str, ...]:
    return tuple(normalize(part) for part in raw.split(",") if part.strip())


def _reject_floating_alias(value: str) -> str:
    low = value.lower()
    if low.endswith("-latest") or low.endswith("-preview"):
        raise ValueError(f"alias flotante prohibido: {value}")
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JERICO_", env_file=".env", extra="ignore")

    llm_base_url: str = "https://api.example.com/v1"
    llm_api_key: str = "changeme"
    llm_base_url_l1: str = ""
    llm_api_key_l1: str = ""
    llm_base_url_l2: str = ""
    llm_api_key_l2: str = ""
    llm_base_url_l3: str = ""
    llm_api_key_l3: str = ""
    llm_model_l1: str = "glm-5.3-flash"
    llm_model_l2: str = "deepseek-flash"
    llm_model_l3: str = ""
    llm_model_voice: str = ""
    llm_timeout_s: float = 30.0
    llm_max_retries: int = 2

    router_l2_keywords: str = "codigo,auditoria,arquitectura,refactor,devops,sql,bug"
    router_l3_keywords: str = "finanzas,contrato,legal,juridico,rentabilidad,demanda"
    router_l2_exceptions: str = "codigo postal,codigo de area,codigo de barras"

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    api_token: str = "changeme"
    rate_limit_per_min: int = 30
    allowed_telegram_ids: str = ""

    redis_url: str = ""
    postgres_url: str = ""
    memory_ttl_hours: int = 24
    memory_max_sessions: int = 100

    voices_dir: str = "voices"
    stt_model: str = "small"
    tts_engine: str = "fish-s1-mini"

    @field_validator("llm_model_l1", "llm_model_l2", "llm_model_l3", "llm_model_voice")
    @classmethod
    def pin_model(cls, value: str) -> str:
        return _reject_floating_alias(value)

    @property
    def l2_keywords(self) -> tuple[str, ...]:
        return _csv(self.router_l2_keywords)

    @property
    def l3_keywords(self) -> tuple[str, ...]:
        return _csv(self.router_l3_keywords)

    @property
    def l2_exceptions(self) -> tuple[str, ...]:
        return _csv(self.router_l2_exceptions)

    @property
    def telegram_ids(self) -> frozenset[str]:
        raw = self.allowed_telegram_ids.split(",")
        return frozenset(part.strip() for part in raw if part.strip())

    def model_for_level(self, level: int) -> str:
        if level <= 0:
            return "none"
        if level >= 3 and self.llm_model_l3:
            return self.llm_model_l3
        if level >= 2:
            return self.llm_model_l2
        return self.llm_model_l1

    def endpoint_for(self, level: int) -> tuple[str, str, str]:
        base = getattr(self, f"llm_base_url_l{level}", "") or self.llm_base_url
        key = getattr(self, f"llm_api_key_l{level}", "") or self.llm_api_key
        return base, key, self.model_for_level(level)


def token_configured(token: str) -> bool:
    return token.strip() not in PLACEHOLDER_TOKENS


@lru_cache
def get_settings() -> Settings:
    return Settings()
