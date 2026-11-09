import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    provider_base_url: str = "http://localhost:3001"
    provider_api_key: str = "test-dev-2026"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            provider_base_url=os.getenv(
                "PROVIDER_BASE_URL",
                "http://localhost:3001",
            ).rstrip("/"),
            provider_api_key=os.getenv("PROVIDER_API_KEY", "test-dev-2026"),
        )
