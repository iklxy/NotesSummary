"@Date:2026-04-13"
"@author:lixinyang"

import ollama

from config import config


_client: ollama.Client | None = None
_client_host: str | None = None


def _ensure_client() -> ollama.Client:
    global _client, _client_host
    host = config.OLLAMA_HOST
    if _client is None or _client_host != host:
        _client = ollama.Client(host=host)
        _client_host = host
    return _client

def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    使用 Ollama 对一组文本生成向量。
    参数:
        texts: 文本列表
    返回:
        向量列表，对应每条文本的 embedding
    """
    embeddings = []
    client = _ensure_client()
    for t in texts:
        resp = client.embeddings(model=config.OLLAMA_MODEL_NAME, prompt=t)
        embeddings.append(resp["embedding"])
    return embeddings
