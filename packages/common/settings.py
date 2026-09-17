"""Central configuration (A-TO-Z-PLAN.md §Phase 1). Pydantic-settings; env in dev, secret
manager in prod. Import `settings` everywhere — never read os.environ directly."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["dev", "test", "staging", "prod"] = "dev"

    # ── Phase 0 ──
    database_url: str = "postgresql+psycopg://seo:seo@localhost:5432/seo"
    database_url_migrator: str = "postgresql+psycopg://seo_migrator:seo@localhost:5432/seo"
    redis_url: str = "redis://localhost:6379/0"

    # ── Phase 1 ──
    gemini_api_key: str = ""
    openrouter_api_key: str = ""
    zhipu_api_key: str = ""
    perplexity_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    model_registry_path: str = "./config/model_registry.yaml"
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""  # noqa: S105
    google_oauth_redirect_uri: str = "http://localhost:8000/v1/oauth/google/callback"
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""
    supabase_jwt_secret: str = ""  # noqa: S105 - HS256 verification key for Supabase-issued JWTs
    jwt_secret: str = "dev-only-change-me"  # noqa: S105 - dev default; prod comes from secret manager
    app_secret_key: str = "dev-only-change-me"  # noqa: S105
    webhook_signing_secret: str = "dev-only-change-me"  # noqa: S105
    encryption_key: str = "dev-only-change-me"  # noqa: S105
    sentry_dsn: str = ""
    otel_exporter_otlp_endpoint: str = ""
    otel_exporter_otlp_headers: str = ""

    # ── Phase 3–4 ──
    pagespeed_api_key: str = ""
    crux_api_key: str = ""
    serpapi_api_key: str = ""
    dataforseo_login: str = ""
    dataforseo_password: str = ""  # noqa: S105
    voyage_api_key: str = ""
    proxy_url: str = ""
    proxy_username: str = ""
    proxy_password: str = ""  # noqa: S105

    # ── Phase 7–12 ── (declared so `secret_field_names` below actually redacts them —
    # a name listed there with no matching field silently never redacts, since
    # `getattr(self, name, "")` falls through to "" and secret_values() drops empties)
    ahrefs_api_key: str = ""
    semrush_api_key: str = ""
    moz_access_id: str = ""
    moz_secret: str = ""  # noqa: S105
    github_app_id: str = ""
    github_token: str = ""  # noqa: S105
    github_app_private_key: str = ""  # noqa: S105
    vercel_token: str = ""  # noqa: S105
    temporal_address: str = ""
    temporal_namespace: str = ""
    temporal_api_key: str = ""  # noqa: S105
    resend_api_key: str = ""  # noqa: S105
    slack_bot_token: str = ""  # noqa: S105
    slack_signing_secret: str = ""  # noqa: S105

    # ── Phase 2 ──
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"  # noqa: S105
    s3_bucket: str = "seo-evidence"

    # Secret env var names — used by the redaction layer to scrub prompts/logs.
    secret_field_names: tuple[str, ...] = Field(
        default=(
            "anthropic_api_key", "openai_api_key", "gemini_api_key", "openrouter_api_key",
            "zhipu_api_key", "perplexity_api_key",
            "voyage_api_key", "serpapi_api_key", "dataforseo_password", "ahrefs_api_key",
            "semrush_api_key", "moz_secret",
            "github_token", "github_app_private_key", "vercel_token", "temporal_api_key",
            "resend_api_key", "slack_bot_token", "slack_signing_secret",
            "jwt_secret", "app_secret_key", "webhook_signing_secret", "encryption_key",
            "s3_secret_key", "proxy_password", "supabase_service_key", "supabase_anon_key",
            "supabase_jwt_secret",
            # Found missing while building the OAuth credential-storage feature (Phase 12/13) —
            # all three are secret-shaped fields that predate this change and were silently never
            # redacted; the exact class of bug this list exists to prevent.
            "pagespeed_api_key", "crux_api_key", "google_oauth_client_secret",
        ),
        exclude=True,
    )

    @staticmethod
    def _db_password(url: str) -> str:
        # postgresql+psycopg://user:PASSWORD@host/db -> PASSWORD
        if "://" not in url or "@" not in url:
            return ""
        creds = url.split("://", 1)[1].split("@", 1)[0]
        return creds.split(":", 1)[1] if ":" in creds else ""

    def secret_values(self) -> list[str]:
        out: list[str] = []
        for name in self.secret_field_names:
            val = getattr(self, name, "") or ""
            if isinstance(val, str) and len(val) >= 8:
                out.append(val)
        for url in (self.database_url, self.database_url_migrator, self.redis_url):
            pw = self._db_password(url)
            if len(pw) >= 8:
                out.append(pw)
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
