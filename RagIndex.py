"@Date:2026-04-13"
"@author:lixinyang"

import os
from typing import Any, Dict, List

import dotenv
import requests
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
)

from DbAccess import get_connection
from EmbeddingClient import embed_texts


dotenv.load_dotenv()


class RagSearcher:
    """
    封装与 Qdrant 交互的 RAG 检索类，负责：
    1) 将 bh_project_interview_summary 的文本写入向量索引；
    2) 根据问题在指定访谈范围内检索最相关的 summary 片段。
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        collection_name: str | None = None,
    ) -> None:
        """
        初始化 RagSearcher 实例。

        参数:
            host: Qdrant 服务主机名或 IP，如果为 None 则从环境变量 QDRANT_HOST 读取，默认 "localhost"。
            port: Qdrant 服务端口，如果为 None 则从环境变量 QDRANT_PORT 读取，默认 6333。
            collection_name: 用于存放 summary 向量的集合名称，如果为 None 则从环境变量 QDRANT_COLLECTION_SUMMARY 读取，默认 "interview_summary"。

        返回:
            无返回值，内部会创建 QdrantClient 客户端并记录基础配置。
        """
        host_env = host or os.getenv("QDRANT_HOST", "localhost")
        port_env = port or int(os.getenv("QDRANT_PORT", "6333"))
        collection_env = collection_name or os.getenv(
            "QDRANT_COLLECTION_SUMMARY", "interview_summary"
        )

        self.host = host_env
        self.port = port_env
        self.collection_name = collection_env

        if host_env.startswith("http://") or host_env.startswith("https://"):
            self.base_url = host_env
        else:
            self.base_url = f"http://{host_env}:{port_env}"

        self.client = QdrantClient(host=host_env, port=port_env)

    def fetch_summary_rows(self, interview_id: int) -> List[Dict[str, Any]]:
        """
        根据访谈 ID 查询 bh_project_interview_summary 表中的明细记录。

        参数:
            interview_id: 访谈主键 ID，对应 bh_project_interview.id，用于过滤 project_interview_id 字段。

        返回:
            查询到的记录列表，每个元素为字典，至少包含:
                - id: 明细行主键 ID。
                - project_interview_id: 访谈 ID。
                - speaker: 说话人标识。
                - text: 清洗后的文本内容。
            如果没有记录，返回空列表。
        """
        sql = """
            SELECT id, project_interview_id, speaker, text
            FROM bh_project_interview_summary
            WHERE project_interview_id = %s
            ORDER BY id ASC
        """
        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, (interview_id,))
                rows: List[Dict[str, Any]] = cursor.fetchall()
                return rows
        finally:
            conn.close()

    def ensure_collection(self, vector_size: int) -> None:
        """
        确保用于存放 summary 向量的 Qdrant collection 已创建。

        参数:
            vector_size: 向量维度大小，通常为 embedding 模型输出向量的长度。

        返回:
            无返回值，如果 collection 不存在则会创建，已存在则直接返回。
        """
        if self.client.collection_exists(self.collection_name):
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )

    def index_interview_summary(self, interview_id: int) -> int:
        """
        将指定访谈的 summary 文本嵌入为向量并写入 Qdrant。

        参数:
            interview_id: 访谈主键 ID，对应 bh_project_interview.id，用于选择要索引的 summary 行。

        返回:
            实际写入或更新到 Qdrant 的向量点数量。
        """
        print(f"[RAG] 开始为访谈 {interview_id} 构建向量索引")

        rows = self.fetch_summary_rows(interview_id)
        if not rows:
            print(f"[RAG] 访谈 {interview_id} 在 bh_project_interview_summary 中没有任何记录")
            return 0

        print(f"[RAG] 共读取到 {len(rows)} 条 summary 记录，准备生成向量")

        texts = [row["text"] for row in rows]
        vectors = embed_texts(texts)
        if not vectors:
            print(f"[RAG] 未能为访谈 {interview_id} 生成任何向量结果")
            return 0

        vector_size = len(vectors[0])
        print(f"[RAG] 向量维度为 {vector_size}")

        print(f"[RAG] 连接 Qdrant 成功，准备检查/创建集合 {self.collection_name}")
        self.ensure_collection(vector_size)

        points = []
        for row, vec in zip(rows, vectors):
            payload = {
                "project_interview_id": row["project_interview_id"],
                "summary_id": row["id"],
                "speaker": row["speaker"],
                "text": row["text"],
            }
            points.append(
                PointStruct(
                    id=row["id"],
                    vector=vec,
                    payload=payload,
                )
            )

        self.client.upsert(collection_name=self.collection_name, points=points)
        print(f"[RAG] 已写入或更新 {len(points)} 条向量到集合 {self.collection_name}")
        return len(points)

    def retrieve_segments_for_question(
        self,
        interview_id: int,
        question_text: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        针对一个问题文本，在指定访谈范围内检索最相似的 summary 片段。

        参数:
            interview_id: 访谈主键 ID，仅在该访谈的 summary 向量集合中进行检索。
            question_text: 问题原文，将作为查询向量的文本输入。
            top_k: 返回的相似片段数量上限，默认 5。

        返回:
            检索结果列表，每个元素为字典，包含:
                - summary_id: 对应 bh_project_interview_summary.id。
                - project_interview_id: 访谈 ID。
                - speaker: 说话人标识。
                - text: summary 文本内容。
                - score: 相似度得分，数值越大代表越相关。
            如果无法生成查询向量或没有检索结果，返回空列表。
        """
        vectors = embed_texts([question_text])
        if not vectors:
            return []

        query_vector = vectors[0]

        url = f"{self.base_url}/collections/{self.collection_name}/points/search"
        body = {
            "vector": query_vector,
            "limit": top_k,
            "filter": {
                "must": [
                    {
                        "key": "project_interview_id",
                        "match": {"value": interview_id},
                    }
                ]
            },
            "with_payload": True,
            "with_vectors": False,
        }

        try:
            resp = requests.post(url, json=body, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            search_result = data.get("result") or []
        except Exception:
            return []

        segments: List[Dict[str, Any]] = []
        for r in search_result:
            payload = r.get("payload") or {}
            segments.append(
                {
                    "summary_id": payload.get("summary_id"),
                    "project_interview_id": payload.get("project_interview_id"),
                    "speaker": payload.get("speaker"),
                    "text": payload.get("text"),
                    "score": r.get("score", 0.0),
                }
            )
        return segments


_default_searcher = RagSearcher()


def index_interview_summary(interview_id: int) -> int:
    """
    便捷函数，使用默认 RagSearcher 实例为指定访谈构建向量索引。

    参数:
        interview_id: 访谈主键 ID，对应 bh_project_interview.id。

    返回:
        实际写入或更新到 Qdrant 的向量点数量。
    """
    return _default_searcher.index_interview_summary(interview_id)


def retrieve_segments_for_question(
    interview_id: int,
    question_text: str,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """
    便捷函数，使用默认 RagSearcher 实例在指定访谈范围内进行 RAG 检索。

    参数:
        interview_id: 访谈主键 ID，仅检索该访谈的 summary 向量。
        question_text: 问题原文，作为查询向量的文本输入。
        top_k: 返回的相似片段数量上限，默认 5。

    返回:
        检索结果列表，每个元素为字典，字段意义与 RagSearcher.retrieve_segments_for_question 一致。
    """
    return _default_searcher.retrieve_segments_for_question(
        interview_id=interview_id,
        question_text=question_text,
        top_k=top_k,
    )


if __name__ == "__main__":
    interview_id_str = os.getenv("TEST_INTERVIEW_ID")
    if interview_id_str:
        interview_id = int(interview_id_str)
        count = index_interview_summary(interview_id)
        print(f"indexed {count} rows for interview {interview_id}")
    else:
        print("TEST_INTERVIEW_ID not set")
