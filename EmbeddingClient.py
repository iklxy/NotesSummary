"@Date:2026-04-13"
"@author:lixinyang"

import ollama
import os
import dotenv

dotenv.load_dotenv()

client = ollama.Client(host="http://localhost:11434")

MODEL_NAME = os.getenv("OLLAMA_MODEL_NAME", "bge-m3:latest")  # 可替换为ollama的其他embedding模型名

def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    使用 Ollama 对一组文本生成向量。
    参数:
        texts: 文本列表
    返回:
        向量列表，对应每条文本的 embedding
    """
    embeddings = []
    for t in texts:
        resp = client.embeddings(model=MODEL_NAME, prompt=t)
        embeddings.append(resp["embedding"])
    return embeddings