"@Date:2026-04-13"
"@author:lixinyang"

import hashlib
from typing import Any, Dict, List

import requests
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
)

from DbAccess import DbAccess
from EmbeddingClient import embed_texts
from config import config


class RagSearcher:
    """
    封装与 Qdrant 交互的 RAG 检索类，负责：
    1) 将 bh_project_interview_summary 的文本写入向量索引；
    2) 根据问题在指定访谈范围内检索最相关的 summary 片段。
    """

    _client: QdrantClient | None = None
    _base_url: str | None = None
    _collection_name: str | None = None
    _loaded_host: str | None = None
    _loaded_port: int | None = None
    _loaded_collection: str | None = None

    @classmethod
    def _ensure_client(cls) -> None:
        host_env = config.QDRANT_HOST
        port_env = config.QDRANT_PORT
        collection_env = config.QDRANT_COLLECTION_SUMMARY
        if (
            cls._client is not None
            and cls._base_url
            and cls._collection_name
            and cls._loaded_host == host_env
            and cls._loaded_port == port_env
            and cls._loaded_collection == collection_env
        ):
            return
        if host_env.startswith("http://") or host_env.startswith("https://"):
            cls._base_url = host_env
        else:
            cls._base_url = f"http://{host_env}:{port_env}"

        cls._client = QdrantClient(host=host_env, port=port_env)
        cls._collection_name = collection_env
        cls._loaded_host = host_env
        cls._loaded_port = port_env
        cls._loaded_collection = collection_env

    @classmethod
    def _resolve_collection_name(cls) -> str:
        """
        确保 Qdrant collection 名称已初始化，并返回实际使用的名称。
        """
        cls._ensure_client()
        if not cls._collection_name:
            raise RuntimeError("QDRANT_COLLECTION_SUMMARY is not configured")
        return cls._collection_name

    @classmethod
    def fetch_summary_rows(cls, interview_id: int) -> List[Dict[str, Any]]:
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
            SELECT id, project_interview_id, timestamp, speaker, text
            FROM bh_project_interview_summary
            WHERE project_interview_id = %s
            ORDER BY id ASC
        """
        conn = DbAccess.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, (interview_id,))
                rows: List[Dict[str, Any]] = cursor.fetchall()
                return rows
        finally:
            conn.close()

    @classmethod
    def _build_summary_chunk_text(cls, rows: List[Dict[str, Any]]) -> str:
        """
        将连续的 summary 行合并成一个 chunk 文本。

        目标是把一问一答的相邻两条信息放在一起，提升语义完整度。
        """
        parts: List[str] = []
        for row in rows:
            speaker = str(row.get("speaker") or "").strip() or "unknown"
            text = str(row.get("text") or "").strip()
            timestamp = str(row.get("timestamp") or "").strip()

            header_bits = [speaker]
            if timestamp:
                header_bits.append(timestamp)
            header = " · ".join(header_bits)
            parts.append(f"{header}\n{text}" if text else header)
        return "\n\n".join(parts)

    @classmethod
    def _build_point_id(cls, project_interview_id: int, summary_ids: List[int]) -> int:
        """
        生成 Qdrant 可接受的无符号整数 point id。

        Qdrant 不接受任意字符串作为 point id，这里用稳定哈希将
        interview_id + summary_ids 映射成 64 位整数。
        """
        raw = f"{project_interview_id}:{','.join(map(str, summary_ids))}".encode("utf-8")
        digest = hashlib.sha1(raw).hexdigest()[:16]
        return int(digest, 16)

    @classmethod
    def _chunk_summary_rows(cls, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        将 summary 行按两条一组合并为 chunk。

        如果最后剩余一条，则单独成为一个 chunk。
        """
        chunks: List[Dict[str, Any]] = []
        for idx in range(0, len(rows), 2):
            group = rows[idx : idx + 2]
            if not group:
                continue

            summary_ids = [row.get("id") for row in group if row.get("id") is not None]
            if not summary_ids:
                continue

            text = cls._build_summary_chunk_text(group)
            speaker_names = [
                str(row.get("speaker") or "").strip() or "unknown"
                for row in group
            ]
            timestamp_start = str(group[0].get("timestamp") or "").strip()
            timestamp_end = str(group[-1].get("timestamp") or "").strip()
            point_id = cls._build_point_id(int(group[0].get("project_interview_id") or 0), [int(sid) for sid in summary_ids])

            chunks.append(
                {
                    "id": point_id,
                    "project_interview_id": group[0].get("project_interview_id"),
                    "summary_ids": summary_ids,
                    "summary_id": summary_ids[0] if len(summary_ids) == 1 else summary_ids,
                    "speaker": " + ".join(speaker_names),
                    "speaker_names": speaker_names,
                    "timestamp_start": timestamp_start,
                    "timestamp_end": timestamp_end,
                    "text": text,
                }
            )

        return chunks

    @classmethod
    def _build_query_text(
        cls,
        question_text: str,
        question_type: str | None = None,
        intent_name: str | None = None,
    ) -> str:
        """
        将问题文本、问题类型和意图名称拼成更强约束的检索 query。
        """
        parts: List[str] = []
        qtype = (question_type or "").strip()
        intent = (intent_name or "").strip()
        qtext = (question_text or "").strip()

        if qtype:
            parts.append(f"问题类型: {qtype}")
        if intent:
            parts.append(f"问题意图: {intent}")
        if qtext:
            parts.append(f"问题原文: {qtext}")
        return "\n".join(parts) if parts else qtext

    @classmethod
    def ensure_collection(cls, vector_size: int) -> None:
        """
        确保用于存放 summary 向量的 Qdrant collection 已创建。

        参数:
            vector_size: 向量维度大小，通常为 embedding 模型输出向量的长度。

        返回:
            无返回值，如果 collection 不存在则会创建，已存在则直接返回。
        """
        collection_name = cls._resolve_collection_name()
        if cls._client.collection_exists(collection_name):
            return
        cls._client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )

    @classmethod
    def index_interview_summary(cls, interview_id: int) -> int:
        """
        将指定访谈的 summary 文本嵌入为向量并写入 Qdrant。

        参数:
            interview_id: 访谈主键 ID，对应 bh_project_interview.id，用于选择要索引的 summary 行。

        返回:
            实际写入或更新到 Qdrant 的向量点数量。
        """
        print(f"[RAG] 开始为访谈 {interview_id} 构建向量索引")

        rows = cls.fetch_summary_rows(interview_id)
        if not rows:
            print(f"[RAG] 访谈 {interview_id} 在 bh_project_interview_summary 中没有任何记录")
            return 0

        print(f"[RAG] 共读取到 {len(rows)} 条 summary 记录，准备按两条合并 chunk")

        chunks = cls._chunk_summary_rows(rows)
        if not chunks:
            print(f"[RAG] 访谈 {interview_id} 没有可用于索引的 chunk")
            return 0

        print(f"[RAG] 共生成 {len(chunks)} 个 chunk，准备生成向量")

        texts = [chunk["text"] for chunk in chunks]
        vectors = embed_texts(texts)
        if not vectors:
            print(f"[RAG] 未能为访谈 {interview_id} 生成任何向量结果")
            return 0

        vector_size = len(vectors[0])
        print(f"[RAG] 向量维度为 {vector_size}")

        collection_name = cls._resolve_collection_name()
        print(f"[RAG] 连接 Qdrant 成功，准备检查/创建集合 {collection_name}")
        cls.ensure_collection(vector_size)

        points = []
        for chunk, vec in zip(chunks, vectors):
            payload = {
                "project_interview_id": chunk["project_interview_id"],
                "summary_id": chunk["summary_id"],
                "summary_ids": chunk["summary_ids"],
                "speaker": chunk["speaker"],
                "speaker_names": chunk["speaker_names"],
                "timestamp_start": chunk["timestamp_start"],
                "timestamp_end": chunk["timestamp_end"],
                "text": chunk["text"],
                "chunk_type": "pair",
            }
            points.append(
                PointStruct(
                    id=chunk["id"],
                    vector=vec,
                    payload=payload,
                )
            )

        cls._client.upsert(collection_name=collection_name, points=points)
        print(f"[RAG] 已写入或更新 {len(points)} 条向量到集合 {collection_name}")
        return len(points)

    @classmethod
    def retrieve_segments_for_question(
        cls,
        interview_id: int,
        question_text: str,
        top_k: int = 5,
        question_type: str | None = None,
        intent_name: str | None = None,
    ) -> List[Dict[str, Any]]:
        """
        针对一个问题文本，在指定访谈范围内检索最相似的 summary 片段。

        参数:
            interview_id: 访谈主键 ID，仅在该访谈的 summary 向量集合中进行检索。
            question_text: 问题原文，将作为查询向量的文本输入。
            top_k: 返回的相似片段数量上限，默认 5。
            question_type: 可选，问题类型，用于增强 query。
            intent_name: 可选，意图名称，用于增强 query。

        返回:
            检索结果列表，每个元素为字典，包含:
                - summary_id: 对应 bh_project_interview_summary.id。
                - project_interview_id: 访谈 ID。
                - speaker: 说话人标识。
                - text: summary 文本内容。
                - score: 相似度得分，数值越大代表越相关。
            如果无法生成查询向量或没有检索结果，返回空列表。
        """
        query_text = cls._build_query_text(
            question_text=question_text,
            question_type=question_type,
            intent_name=intent_name,
        )

        vectors = embed_texts([query_text])
        if not vectors:
            return []

        query_vector = vectors[0]
        collection_name = cls._resolve_collection_name()
        url = f"{cls._base_url}/collections/{collection_name}/points/search"
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
            summary_ids = payload.get("summary_ids")
            segments.append(
                {
                    "summary_id": payload.get("summary_id"),
                    "summary_ids": summary_ids,
                    "project_interview_id": payload.get("project_interview_id"),
                    "speaker": payload.get("speaker"),
                    "text": payload.get("text"),
                    "timestamp_start": payload.get("timestamp_start"),
                    "timestamp_end": payload.get("timestamp_end"),
                    "chunk_type": payload.get("chunk_type"),
                    "score": r.get("score", 0.0),
                }
            )
        return segments


def index_interview_summary(interview_id: int) -> int:
    """
    便捷函数，使用 RagSearcher 类为指定访谈构建向量索引。

    参数:
        interview_id: 访谈主键 ID，对应 bh_project_interview.id。

    返回:
        实际写入或更新到 Qdrant 的向量点数量。
    """
    return RagSearcher.index_interview_summary(interview_id)


def retrieve_segments_for_question(
    interview_id: int,
    question_text: str,
    top_k: int = 5,
    question_type: str | None = None,
    intent_name: str | None = None,
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
    return RagSearcher.retrieve_segments_for_question(
        interview_id=interview_id,
        question_text=question_text,
        top_k=top_k,
        question_type=question_type,
        intent_name=intent_name,
    )


if __name__ == "__main__":
    interview_id_str = config.TEST_INTERVIEW_ID
    if interview_id_str:
        interview_id = int(interview_id_str)
        count = index_interview_summary(interview_id)
        print(f"indexed {count} rows for interview {interview_id}")
    else:
        print("TEST_INTERVIEW_ID not set")
