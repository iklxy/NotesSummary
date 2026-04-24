"@Date:2026-04-13"
"@author:lixinyang"

import ollama

from config import config


_client: ollama.Client | None = None
_client_host: str | None = None


def _ensure_client() -> ollama.Client:
    """
    按当前配置初始化或复用 Ollama 客户端。

    参数:
        无。客户端地址统一从 `config.OLLAMA_HOST` 读取。

    返回:
        已可用的 `ollama.Client` 实例。
        当 `OLLAMA_HOST` 发生变化时，会自动创建新的客户端并替换缓存。
    """
    global _client, _client_host
    host = config.OLLAMA_HOST
    if _client is None or _client_host != host:
        _client = ollama.Client(host=host)
        _client_host = host
    return _client


def _embed_single_text(text: str) -> list[float]:
    """
    使用当前配置的 Ollama embedding 模型为单条文本生成向量。

    参数:
        text: 需要向量化的单条文本内容。

    返回:
        单条文本对应的 embedding 向量列表。
    """
    client = _ensure_client()
    response = client.embeddings(model=config.OLLAMA_MODEL_NAME, prompt=text)
    return response["embedding"]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    使用 Ollama 为一组文本生成 embedding 向量。

    参数:
        texts: 待向量化的文本列表。列表中的每个元素会按顺序逐条调用 Ollama。

    返回:
        向量列表，顺序与输入 `texts` 一一对应。
        当输入为空列表时，返回空列表。
    """
    if not texts:
        return []
    return [_embed_single_text(text) for text in texts]
