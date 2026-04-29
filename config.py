"""
@Date: 2026-04-29
@Author: lixinyang

工程运行时配置读取与刷新模块。
"""

from dataclasses import dataclass, field
from pathlib import Path
import os

from dotenv import load_dotenv


ENV_PATH = Path(__file__).resolve().parent / ".env"


def _get_env_str(name: str, default: str | None = None) -> str | None:
    """
    从环境变量中读取字符串配置。

    参数:
        name: 环境变量名称，例如 `DB_HOST` 或 `LLM_PROVIDER`。
        default: 当环境变量不存在时使用的默认值；允许为 `None`。

    返回:
        读取到的字符串值；若环境变量不存在，则返回 `default`。
    """
    return os.getenv(name, default)


def _get_env_int(name: str, default: int) -> int:
    """
    从环境变量中读取整数配置。

    参数:
        name: 环境变量名称，例如 `DB_PORT` 或 `QDRANT_PORT`。
        default: 当环境变量不存在时使用的默认整数值。

    返回:
        解析后的整数值。

    异常:
        ValueError: 当环境变量存在但不是合法整数时抛出。
    """
    return int(os.getenv(name, str(default)))


@dataclass
class RuntimeConfig:
    """
    统一管理 engine 运行时配置。

    配置值来源统一为项目根目录下的 `.env` 文件。
    `reload()` 会重新读取 `.env`，并把结果回填到当前实例。
    """

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
        """
        重新加载 `.env` 文件，并刷新当前配置对象中的所有字段。

        参数:
            无。配置默认从 `ENV_PATH` 指向的 `.env` 文件读取。

        返回:
            刷新后的 `RuntimeConfig` 自身实例，便于链式调用或直接赋值。
        """
        load_dotenv(dotenv_path=ENV_PATH, override=True)

        # 数据库配置
        self.DB_HOST = _get_env_str("DB_HOST", "127.0.0.1") or "127.0.0.1"
        self.DB_PORT = _get_env_int("DB_PORT", 3306)
        self.DB_USER = _get_env_str("DB_USER")
        self.DB_PASSWORD = _get_env_str("DB_PASSWORD")
        self.DB_NAME = _get_env_str("DB_NAME")

        # 大模型配置
        self.LLM_API_KEY = _get_env_str("LLM_API_KEY")
        self.LLM_BASE_URL = _get_env_str("LLM_BASE_URL")
        self.LLM_MODEL_NAME = _get_env_str("LLM_MODEL_NAME")
        self.LLM_PROVIDER = _get_env_str("LLM_PROVIDER", "anthropic") or "anthropic"

        # Embedding / Ollama 配置
        self.OLLAMA_HOST = _get_env_str("OLLAMA_HOST", "http://localhost:11434") or "http://localhost:11434"
        self.OLLAMA_MODEL_NAME = _get_env_str("OLLAMA_MODEL_NAME", "bge-m3:latest") or "bge-m3:latest"
        self.TERM_HINTS_FILE = _get_env_str("TERM_HINTS_FILE")

        # ASR 配置
        self.ASR_APP_KEY = _get_env_str("ASR_APP_KEY")
        self.ASR_ACCESS_KEY = _get_env_str("ASR_ACCESS_KEY")
        self.VOLCANO_CLUSTER = _get_env_str("VOLCANO_CLUSTER")
        self.VOLCANO_SERVICE_URL = _get_env_str("VOLCANO_SERVICE_URL")

        # TOS 配置
        self.TOS_ACCESS_KEY = _get_env_str("TOS_ACCESS_KEY")
        self.TOS_SECRET_KEY = _get_env_str("TOS_SECRET_KEY")
        self.TOS_ENDPOINT = _get_env_str("TOS_ENDPOINT", "https://tos-cn-shanghai.volces.com") or "https://tos-cn-shanghai.volces.com"
        self.TOS_REGION = _get_env_str("TOS_REGION", "cn-shanghai") or "cn-shanghai"
        self.TOS_BUCKET_NAME = _get_env_str("TOS_BUCKET_NAME", "benhealth") or "benhealth"
        self.LOCAL_AUDIO_ROOT = _get_env_str("LOCAL_AUDIO_ROOT", ".") or "."
        self.TOS_AUDIO_PREFIX = _get_env_str("TOS_AUDIO_PREFIX", "audio") or "audio"
        self.TOS_URL_EXPIRE_SECONDS = _get_env_int("TOS_URL_EXPIRE_SECONDS", 3600)

        # Qdrant 配置
        self.QDRANT_HOST = _get_env_str("QDRANT_HOST", "localhost") or "localhost"
        self.QDRANT_PORT = _get_env_int("QDRANT_PORT", 6333)
        self.QDRANT_COLLECTION_SUMMARY = _get_env_str("QDRANT_COLLECTION_SUMMARY", "interview_summary") or "interview_summary"

        # 内部服务配置
        self.INTERNAL_SERVICE_BASE = _get_env_str("INTERNAL_SERVICE_BASE", "http://127.0.0.1:8000") or "http://127.0.0.1:8000"

        self.revision += 1
        return self


config = RuntimeConfig().reload()


def refresh_runtime_config() -> RuntimeConfig:
    """
    重新读取 `.env`，并刷新全局运行时配置对象。

    参数:
        无。内部直接复用模块级 `config` 实例执行 `reload()`。

    返回:
        已重新加载后的全局 `RuntimeConfig` 实例。
    """
    return config.reload()
