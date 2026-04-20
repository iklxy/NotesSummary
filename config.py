from dataclasses import dataclass, field
from pathlib import Path
import os

from dotenv import load_dotenv


ENV_PATH = Path(__file__).resolve().parent / ".env"


@dataclass
class RuntimeConfig:
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str | None = None
    DB_PASSWORD: str | None = None
    DB_NAME: str | None = None

    LLM_API_KEY: str | None = None
    LLM_BASE_URL: str | None = None
    LLM_MODEL_NAME: str | None = None
    LLM_PROVIDER: str = "anthropic"

    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_MODEL_NAME: str = "bge-m3:latest"
    TERM_HINTS_FILE: str | None = None

    ASR_APP_KEY: str | None = None
    ASR_ACCESS_KEY: str | None = None
    VOLCANO_CLUSTER: str | None = None
    VOLCANO_SERVICE_URL: str | None = None

    TOS_ACCESS_KEY: str | None = None
    TOS_SECRET_KEY: str | None = None
    TOS_ENDPOINT: str = "https://tos-cn-shanghai.volces.com"
    TOS_REGION: str = "cn-shanghai"
    TOS_BUCKET_NAME: str = "benhealth"
    LOCAL_AUDIO_ROOT: str = "."
    TOS_AUDIO_PREFIX: str = "audio"
    TOS_URL_EXPIRE_SECONDS: int = 3600

    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_COLLECTION_SUMMARY: str = "interview_summary"

    INTERNAL_SERVICE_BASE: str = "http://127.0.0.1:8000"

    revision: int = field(default=0, init=False)

    def reload(self) -> "RuntimeConfig":
        load_dotenv(dotenv_path=ENV_PATH, override=True)
        self.DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
        self.DB_PORT = int(os.getenv("DB_PORT", "3306"))
        self.DB_USER = os.getenv("DB_USER")
        self.DB_PASSWORD = os.getenv("DB_PASSWORD")
        self.DB_NAME = os.getenv("DB_NAME")

        self.LLM_API_KEY = os.getenv("LLM_API_KEY")
        self.LLM_BASE_URL = os.getenv("LLM_BASE_URL")
        self.LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME")
        self.LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")

        self.OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.OLLAMA_MODEL_NAME = os.getenv("OLLAMA_MODEL_NAME", "bge-m3:latest")
        self.TERM_HINTS_FILE = os.getenv("TERM_HINTS_FILE")

        self.ASR_APP_KEY = os.getenv("ASR_APP_KEY")
        self.ASR_ACCESS_KEY = os.getenv("ASR_ACCESS_KEY")
        self.VOLCANO_CLUSTER = os.getenv("VOLCANO_CLUSTER")
        self.VOLCANO_SERVICE_URL = os.getenv("VOLCANO_SERVICE_URL")

        self.TOS_ACCESS_KEY = os.getenv("TOS_ACCESS_KEY")
        self.TOS_SECRET_KEY = os.getenv("TOS_SECRET_KEY")
        self.TOS_ENDPOINT = os.getenv("TOS_ENDPOINT", "https://tos-cn-shanghai.volces.com")
        self.TOS_REGION = os.getenv("TOS_REGION", "cn-shanghai")
        self.TOS_BUCKET_NAME = os.getenv("TOS_BUCKET_NAME", "benhealth")
        self.LOCAL_AUDIO_ROOT = os.getenv("LOCAL_AUDIO_ROOT", ".")
        self.TOS_AUDIO_PREFIX = os.getenv("TOS_AUDIO_PREFIX", "audio")
        self.TOS_URL_EXPIRE_SECONDS = int(os.getenv("TOS_URL_EXPIRE_SECONDS", "3600"))

        self.QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
        self.QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
        self.QDRANT_COLLECTION_SUMMARY = os.getenv("QDRANT_COLLECTION_SUMMARY", "interview_summary")

        self.INTERNAL_SERVICE_BASE = os.getenv("INTERNAL_SERVICE_BASE", "http://127.0.0.1:8000")

        self.revision += 1
        return self


config = RuntimeConfig().reload()


def refresh_runtime_config() -> RuntimeConfig:
    """
    重新加载 .env 并刷新运行时配置。
    """
    return config.reload()
