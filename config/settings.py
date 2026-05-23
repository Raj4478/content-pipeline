"""
Settings — loads all config from environment variables.
Never hardcode keys. Use a .env file locally, Railway env vars in prod.
"""

from functools import cached_property
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM providers ─────────────────────────────────────────────────
    # Set to "gemini" or "groq" — both free. Avoid "deepseek" unless you add credits.
    llm_provider: Literal["deepseek", "gemini", "groq"] = "gemini"
    llm_max_retries: int = 3
    llm_timeout_seconds: int = 30

    # DeepSeek — requires paid credits. Leave blank if not using.
    deepseek_api_key: str = Field(default="", description="DeepSeek API key (optional)")
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # Gemini — free tier, 15 req/min. Recommended for starting out.
    # Valid model IDs: gemini-2.5-flash-lite, gemini-2.5-flash, gemini-2.0-flash
    gemini_api_key: str = Field(default="", description="Gemini API key")
    gemini_model: str = "gemini-2.5-flash-lite"

    # Groq — extremely cheap ($0.05/1M tokens), OpenAI-compatible, generous free tier.
    # Sign up free at: console.groq.com
    groq_api_key: str = Field(default="", description="Groq API key (optional)")
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "llama-3.1-8b-instant"

    # ── ElevenLabs ────────────────────────────────────────────────────
    elevenlabs_api_key: str = Field(default="", description="ElevenLabs API key")
    elevenlabs_voice_id: str = "pNInz6obpgDQGcFmaJgB"
    elevenlabs_model_id: str = "eleven_multilingual_v2"

    # ── Creatomate ────────────────────────────────────────────────────
    creatomate_api_key: str = Field(default="", description="Creatomate API key")
    creatomate_template_id: str = Field(default="", description="Template UUID from Creatomate")
    creatomate_base_url: str = "https://api.creatomate.com/v1"

    # ── Buffer ────────────────────────────────────────────────────────
    buffer_access_token: str = Field(default="", description="Buffer access token")
    buffer_channels: list[str] = Field(
        default_factory=list,
        description="Comma-separated Buffer channel IDs",
    )

    # ── Pexels (stock video) ──────────────────────────────────────────
    pexels_api_key: str = Field(default="", description="Pexels API key")

    # ── Cloudinary (audio CDN) ────────────────────────────────────────
    cloudinary_cloud_name: str = Field(default="", description="Cloudinary cloud name")
    cloudinary_api_key: str = Field(default="", description="Cloudinary API key")
    cloudinary_api_secret: str = Field(default="", description="Cloudinary API secret")

    # ── App config ────────────────────────────────────────────────────
    db_path: Path = Path("data/runs.db")
    audio_tmp_dir: Path = Path("tmp/audio")
    log_level: str = "INFO"
    environment: Literal["development", "production"] = "development"

    @field_validator("buffer_channels", mode="before")
    @classmethod
    def parse_channels(cls, v):
        if isinstance(v, str):
            return [c.strip() for c in v.split(",") if c.strip()]
        return v

    @cached_property
    def is_production(self) -> bool:
        return self.environment == "production"

    def active_providers(self) -> list[str]:
        """Returns ordered list of LLM providers to try — primary first, then fallbacks."""
        all_keys = {
            "deepseek": self.deepseek_api_key,
            "gemini": self.gemini_api_key,
            "groq": self.groq_api_key,
        }
        result = [self.llm_provider]
        for name, key in all_keys.items():
            if name != self.llm_provider and key:
                result.append(name)
        return result

    def model_post_init(self, __context) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.audio_tmp_dir.mkdir(parents=True, exist_ok=True)
        Path("logs").mkdir(exist_ok=True)
