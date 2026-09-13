from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class AppSettings:
    provider: str = "custom"
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    timeout: int = 60
    tavily_api_key: str = ""

    @classmethod
    def from_environment(cls) -> "AppSettings":
        base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.deepseek.com"
        provider = os.getenv("LLM_PROVIDER") or cls._infer_provider(base_url)
        try:
            timeout = max(5, min(600, int(float(os.getenv("LLM_TIMEOUT") or "60"))))
        except ValueError:
            timeout = 60
        return cls(
            provider=provider,
            model=(
                os.getenv("LLM_MODEL_ID")
                or os.getenv("ACADEMIC_AGENT_MODEL")
                or "deepseek-chat"
            ),
            base_url=base_url,
            api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "",
            timeout=timeout,
            tavily_api_key=os.getenv("TVLY_API_KEY") or os.getenv("TAVILY_API_KEY") or "",
        )

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "AppSettings":
        defaults = cls.from_environment()
        return cls(
            provider=str(values.get("provider", defaults.provider)),
            model=str(values.get("model", defaults.model)),
            base_url=str(values.get("base_url", defaults.base_url)),
            api_key=str(values.get("api_key", defaults.api_key)),
            timeout=max(5, min(600, int(values.get("timeout", defaults.timeout)))),
            tavily_api_key=str(values.get("tavily_api_key", defaults.tavily_api_key)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def apply_to_environment(self) -> None:
        values = {
            "LLM_PROVIDER": self.provider,
            "LLM_MODEL_ID": self.model,
            "LLM_BASE_URL": self.base_url,
            "LLM_API_KEY": self.api_key,
            "LLM_TIMEOUT": str(self.timeout),
            "TVLY_API_KEY": self.tavily_api_key,
        }
        for name, value in values.items():
            if value:
                os.environ[name] = value
            else:
                os.environ.pop(name, None)

    @staticmethod
    def _infer_provider(base_url: str) -> str:
        lowered = base_url.lower()
        if "api.deepseek.com" in lowered:
            return "deepseek"
        if "api.openai.com" in lowered:
            return "openai"
        return "custom"
