"@Date:2026-04-17"
"@author:lixinyang"

import os
import sys
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import config, refresh_runtime_config


def _print_selected_config() -> None:
    print("[CONFIG] revision =", config.revision)
    print("[CONFIG] DB_HOST =", config.DB_HOST)
    print("[CONFIG] DB_NAME =", config.DB_NAME)
    print("[CONFIG] LLM_PROVIDER =", config.LLM_PROVIDER)
    print("[CONFIG] LLM_MODEL_NAME =", config.LLM_MODEL_NAME)
    print("[CONFIG] QDRANT_COLLECTION_SUMMARY =", config.QDRANT_COLLECTION_SUMMARY)
    print("[CONFIG] TOS_BUCKET_NAME =", config.TOS_BUCKET_NAME)
    print("[CONFIG] OLLAMA_MODEL_NAME =", config.OLLAMA_MODEL_NAME)
    print("[CONFIG] INTERNAL_SERVICE_BASE =", config.INTERNAL_SERVICE_BASE)


def run_test_config() -> None:
    """
    验证统一配置文件是否能正确读取 .env，并且 refresh_runtime_config()
    能把运行时配置重新加载到内存中。
    """
    print("[CONFIG-TEST] 初始配置：")
    _print_selected_config()

    required = {
        "DB_HOST": config.DB_HOST,
        "DB_NAME": config.DB_NAME,
        "LLM_PROVIDER": config.LLM_PROVIDER,
        "LLM_MODEL_NAME": config.LLM_MODEL_NAME,
        "QDRANT_COLLECTION_SUMMARY": config.QDRANT_COLLECTION_SUMMARY,
        "TOS_BUCKET_NAME": config.TOS_BUCKET_NAME,
    }

    missing = [key for key, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"以下配置项缺失: {', '.join(missing)}")


    print("[CONFIG-TEST] 配置测试完成。")


if __name__ == "__main__":
    run_test_config()
