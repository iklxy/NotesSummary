"@Date: 2026-04-13"
"@Author: lixinyang"


import hashlib
from typing import Any, Dict, List

import requests
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from DbAccess import DbAccess
from EmbeddingClient import embed_texts
from config import config


class RagSearcher:
    """
    统一封装 summary 向量化与检索逻辑。

    当前文件按单文件分层组织，不拆子模块，但在类内明确区分以下职责：
    1. Qdrant 客户端初始化与集合管理
    2. summary 数据读取
    3. chunk 组装与 point payload 构造
    4. summary 索引写入
    5. 问题检索
    """

    _client: QdrantClient | None = None
    _base_url: str | None = None
    _collection_name: str | None = None
    _loaded_host: str | None = None
    _loaded_port: int | None = None
    _loaded_collection: str | None = None

    # ------------------------------------------------------------------
    # Qdrant 客户端与集合管理
    # ------------------------------------------------------------------
    @classmethod
    def _ensure_client(cls) -> None:
        """
        根据当前配置初始化 Qdrant 客户端，并在配置变化时自动刷新缓存。

        参数:
            无。所有配置均从 `config` 中读取：
                - config.QDRANT_HOST: Qdrant 主机名、IP 或完整 URL。
                - config.QDRANT_PORT: Qdrant 端口。
                - config.QDRANT_COLLECTION_SUMMARY: summary 使用的集合名称。

        返回:
            无返回值。初始化完成后，类属性 `_client`、`_base_url`、`_collection_name`
            会处于可用状态。
        """
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
        解析当前 summary 向量使用的 Qdrant collection 名称。

        参数:
            无。函数内部会确保客户端已初始化。

        返回:
            当前配置下实际使用的 collection 名称字符串。

        异常:
            RuntimeError: 当 `config.QDRANT_COLLECTION_SUMMARY` 未配置时抛出。
        """
        cls._ensure_client()
        if not cls._collection_name:
            raise RuntimeError("QDRANT_COLLECTION_SUMMARY is not configured")
        return cls._collection_name

    @classmethod
    def ensure_collection(cls, vector_size: int) -> None:
        """
        确保用于 summary 向量的 Qdrant collection 已存在。

        参数:
            vector_size: 向量维度大小，应与 embedding 模型输出维度一致。

        返回:
            无返回值。若 collection 已存在则直接返回；不存在则按余弦距离创建。
        """
        collection_name = cls._resolve_collection_name()
        if cls._client.collection_exists(collection_name):
            return

        cls._client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )

    # ------------------------------------------------------------------
    # summary 数据读取
    # ------------------------------------------------------------------
    @classmethod
    def fetch_summary_rows(cls, interview_id: int) -> List[Dict[str, Any]]:
        """
        查询指定访谈下的 summary 明细记录。

        参数:
            interview_id: 访谈主键 ID，对应 `bh_project_interview.id`，
                用于过滤 `bh_project_interview_summary.project_interview_id`。

        返回:
            summary 记录列表。每条记录至少包含：
                - id: summary 行主键 ID。
                - project_interview_id: 所属访谈 ID。
                - timestamp: 原始时间范围字符串。
                - speaker: 说话人标识。
                - text: 清洗后的 summary 文本。
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

    # ------------------------------------------------------------------
    # chunk 组装与 payload 构造
    # ------------------------------------------------------------------
    @classmethod
    def _build_summary_chunk_text(cls, rows: List[Dict[str, Any]]) -> str:
        """
        将连续的 summary 行合并成一个可向量化的 chunk 文本。

        参数:
            rows: 一组连续的 summary 记录，通常为 1 到 2 条。每条记录应包含：
                - speaker: 说话人标识。
                - timestamp: 时间范围字符串。
                - text: summary 文本。

        返回:
            适合 embedding 的 chunk 文本。每条记录会以
            `speaker · timestamp + 正文` 的形式拼接，并使用空行分隔。
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
        基于访谈 ID 与 summary 行 ID 列表生成稳定的 Qdrant point id。

        参数:
            project_interview_id: 访谈 ID，用于区分不同访谈下相同 summary 组合。
            summary_ids: 当前 chunk 覆盖的 summary 行 ID 列表，通常为 1 到 2 个整数。

        返回:
            Qdrant 可接受的 64 位无符号整数 point id。
        """
        raw = f"{project_interview_id}:{','.join(map(str, summary_ids))}".encode("utf-8")
        digest = hashlib.sha1(raw).hexdigest()[:16]
        return int(digest, 16)

    @classmethod
    def _build_chunk_payload(cls, chunk: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据 chunk 信息构造写入 Qdrant 的 payload。

        参数:
            chunk: 单个 chunk 字典，通常来自 `_chunk_summary_rows`，至少包含：
                - project_interview_id
                - summary_id / summary_ids
                - speaker / speaker_names
                - timestamp_start / timestamp_end
                - text

        返回:
            适合写入 Qdrant 的 payload 字典。
        """
        return {
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

    @classmethod
    def _chunk_summary_rows(cls, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        将 summary 行按两条一组切分为语义 chunk。

        参数:
            rows: 按顺序排列的 summary 记录列表，通常来自 `fetch_summary_rows`。

        返回:
            chunk 列表。每个 chunk 至少包含：
                - id: Qdrant point id。
                - project_interview_id: 访谈 ID。
                - summary_id / summary_ids: 原始 summary 行 ID。
                - speaker / speaker_names: 说话人信息。
                - timestamp_start / timestamp_end: 覆盖时间范围。
                - text: 合并后的 chunk 正文。
        """
        chunks: List[Dict[str, Any]] = []
        for idx in range(0, len(rows), 2):
            group = rows[idx : idx + 2]
            if not group:
                continue

            summary_ids = [row.get("id") for row in group if row.get("id") is not None]
            if not summary_ids:
                continue

            project_interview_id = int(group[0].get("project_interview_id") or 0)
            speaker_names = [str(row.get("speaker") or "").strip() or "unknown" for row in group]
            timestamp_start = str(group[0].get("timestamp") or "").strip()
            timestamp_end = str(group[-1].get("timestamp") or "").strip()

            chunks.append(
                {
                    "id": cls._build_point_id(project_interview_id, [int(sid) for sid in summary_ids]),
                    "project_interview_id": project_interview_id,
                    "summary_ids": summary_ids,
                    "summary_id": summary_ids[0] if len(summary_ids) == 1 else summary_ids,
                    "speaker": " + ".join(speaker_names),
                    "speaker_names": speaker_names,
                    "timestamp_start": timestamp_start,
                    "timestamp_end": timestamp_end,
                    "text": cls._build_summary_chunk_text(group),
                }
            )
        return chunks

    @classmethod
    def _build_points(
        cls,
        chunks: List[Dict[str, Any]],
        vectors: List[List[float]],
    ) -> List[PointStruct]:
        """
        将 chunk 与 embedding 向量组装为 Qdrant point 列表。

        参数:
            chunks: chunk 列表，通常来自 `_chunk_summary_rows`。
            vectors: 与 `chunks` 一一对应的 embedding 向量列表。

        返回:
            Qdrant `PointStruct` 列表，可直接用于 `upsert`。
        """
        points: List[PointStruct] = []
        for chunk, vec in zip(chunks, vectors):
            points.append(
                PointStruct(
                    id=chunk["id"],
                    vector=vec,
                    payload=cls._build_chunk_payload(chunk),
                )
            )
        return points

    # ------------------------------------------------------------------
    # query 构造与检索请求
    # ------------------------------------------------------------------
    @classmethod
    def _build_query_text(
        cls,
        question_text: str,
        question_type: str | None = None,
        intent_name: str | None = None,
    ) -> str:
        """
        将题目原文、题目类型与意图名称拼接成更强约束的检索 query。

        参数:
            question_text: 题目正文。
            question_type: 可选题目类型，用于强化检索语义。
            intent_name: 可选意图名称，用于补充题目语境。

        返回:
            拼接后的 query 文本。若附加字段均为空，则退回题目原文。
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
    def _search_points(
        cls,
        interview_id: int,
        query_vector: List[float],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """
        在指定访谈范围内执行 Qdrant 检索请求。

        参数:
            interview_id: 访谈主键 ID，仅检索该访谈对应的向量点。
            query_vector: 由问题 query 生成的 embedding 向量。
            top_k: 返回结果数量上限。

        返回:
            Qdrant 原始检索结果列表；每个元素通常包含 `payload` 和 `score`。
            若请求失败，则返回空列表。
        """
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
            return data.get("result") or []
        except Exception:
            return []

    @classmethod
    def _normalize_search_results(cls, search_result: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        将 Qdrant 原始检索结果转换为 engine 内统一使用的片段结构。

        参数:
            search_result: Qdrant 返回的原始结果列表，每个元素一般包含：
                - payload: 自定义 payload 字典。
                - score: 相似度得分。

        返回:
            标准化后的片段列表，每个元素至少包含：
                - summary_id / summary_ids
                - project_interview_id
                - speaker
                - text
                - timestamp_start / timestamp_end
                - chunk_type
                - score
        """
        segments: List[Dict[str, Any]] = []
        for item in search_result:
            payload = item.get("payload") or {}
            segments.append(
                {
                    "summary_id": payload.get("summary_id"),
                    "summary_ids": payload.get("summary_ids"),
                    "project_interview_id": payload.get("project_interview_id"),
                    "speaker": payload.get("speaker"),
                    "text": payload.get("text"),
                    "timestamp_start": payload.get("timestamp_start"),
                    "timestamp_end": payload.get("timestamp_end"),
                    "chunk_type": payload.get("chunk_type"),
                    "score": item.get("score", 0.0),
                }
            )
        return segments

    # ------------------------------------------------------------------
    # 索引写入
    # ------------------------------------------------------------------
    @classmethod
    def index_interview_summary(cls, interview_id: int) -> int:
        """
        将指定访谈的 summary 文本向量化并写入 Qdrant。

        参数:
            interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。

        返回:
            实际写入或更新到 Qdrant 的向量点数量。
            若该访谈没有 summary，或 embedding 失败，则返回 0。
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

        vectors = embed_texts([chunk["text"] for chunk in chunks])
        if not vectors:
            print(f"[RAG] 未能为访谈 {interview_id} 生成任何向量结果")
            return 0

        vector_size = len(vectors[0])
        print(f"[RAG] 向量维度为 {vector_size}")

        collection_name = cls._resolve_collection_name()
        print(f"[RAG] 连接 Qdrant 成功，准备检查/创建集合 {collection_name}")
        cls.ensure_collection(vector_size)

        points = cls._build_points(chunks, vectors)
        cls._client.upsert(collection_name=collection_name, points=points)
        print(f"[RAG] 已写入或更新 {len(points)} 条向量到集合 {collection_name}")
        return len(points)

    # ------------------------------------------------------------------
    # 问题检索
    # ------------------------------------------------------------------
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
        在指定访谈范围内，根据题目信息检索最相关的 summary 片段。

        参数:
            interview_id: 访谈主键 ID，仅检索该访谈范围内的向量点。
            question_text: 题目原文，用于构造检索 query。
            top_k: 返回结果数量上限，默认 5。
            question_type: 可选题目类型，用于增强 query 语义。
            intent_name: 可选意图名称，用于增强 query 语义。

        返回:
            标准化后的片段列表。若 query 向量生成失败或检索失败，则返回空列表。
        """
        query_text = cls._build_query_text(
            question_text=question_text,
            question_type=question_type,
            intent_name=intent_name,
        )

        vectors = embed_texts([query_text])
        if not vectors:
            return []

        search_result = cls._search_points(
            interview_id=interview_id,
            query_vector=vectors[0],
            top_k=top_k,
        )
        return cls._normalize_search_results(search_result)


def index_interview_summary(interview_id: int) -> int:
    """
    使用默认 `RagSearcher` 为指定访谈构建或更新 summary 向量索引。

    参数:
        interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。

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
    使用默认 `RagSearcher` 在指定访谈范围内执行问题检索。

    参数:
        interview_id: 访谈主键 ID，仅检索该访谈对应的 summary 向量。
        question_text: 题目原文，作为检索 query 的核心文本。
        top_k: 返回结果数量上限，默认 5。
        question_type: 可选题目类型，用于增强 query。
        intent_name: 可选意图名称，用于增强 query。

    返回:
        检索结果列表，字段结构与 `RagSearcher.retrieve_segments_for_question` 返回值一致。
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
