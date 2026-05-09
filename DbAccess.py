"@Date: 2026-04-10"
"@Author: lixinyang"


import json
from typing import Any, Dict, List, Optional, Sequence

import pymysql

from config import config


class DbAccess:
    """
    统一封装 engine 侧数据库访问逻辑。

    当前文件不再按“功能散落”的方式组织，而是在单文件内按职责分层：
    1. 连接与基础读写辅助方法
    2. 项目与访谈读取
    3. 访谈更新
    4. Summary 落库
    5. Notes 落库
    """

    # ------------------------------------------------------------------
    # 连接与基础读写辅助方法
    # ------------------------------------------------------------------
    @staticmethod
    def _format_summary_timestamp(seg: Dict[str, Any]) -> str:
        """
        将 ASR 分段时间信息格式化为 summary 表使用的时间范围字符串。

        参数:
            seg: 单条说话轮次记录。允许包含以下任意时间字段：
                - timestamp: 已格式化好的时间区间字符串，若存在则直接复用。
                - start_time / end_time: 原始 ASR 的起止时间，通常为毫秒。
                - start_ms / end_ms: 备用毫秒字段，供纠错/清洗后的结构继续复用。

        返回:
            标准化后的时间区间字符串，格式为 `start_ms-end_ms`。
            若只有一端时间存在，则退化为 `start_ms-start_ms`。
            若所有时间字段均缺失，则返回空字符串。
        """
        raw_timestamp = seg.get("timestamp")
        if isinstance(raw_timestamp, str) and raw_timestamp.strip():
            return raw_timestamp.strip()

        start_time = seg.get("start_time")
        if start_time is None:
            start_time = seg.get("start_ms")
        end_time = seg.get("end_time")
        if end_time is None:
            end_time = seg.get("end_ms")
        try:
            start_ms = int(start_time) if start_time is not None else None
        except (TypeError, ValueError):
            start_ms = None
        try:
            end_ms = int(end_time) if end_time is not None else None
        except (TypeError, ValueError):
            end_ms = None

        if start_ms is None and end_ms is None:
            return ""
        if start_ms is None:
            start_ms = end_ms
        if end_ms is None:
            end_ms = start_ms
        if start_ms is None or end_ms is None:
            return ""
        if end_ms < start_ms:
            start_ms, end_ms = end_ms, start_ms
        return f"{start_ms}-{end_ms}"

    @classmethod
    def get_connection(cls) -> pymysql.connections.Connection:
        """
        创建并返回一个 MySQL 数据库连接。

        参数:
            无。数据库连接参数统一从 `config` 中读取：
                - config.DB_HOST: MySQL 主机名或 IP。
                - config.DB_PORT: MySQL 端口。
                - config.DB_USER: 数据库用户名。
                - config.DB_PASSWORD: 数据库密码。
                - config.DB_NAME: 数据库名称。

        返回:
            一个已建立连接的 `pymysql.connections.Connection` 实例。
        """
        return pymysql.connect(
            host=config.DB_HOST,
            port=config.DB_PORT,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            database=config.DB_NAME,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )

    @classmethod
    def _fetch_one(
        cls,
        sql: str,
        params: Sequence[Any],
    ) -> Optional[Dict[str, Any]]:
        """
        执行单行查询并返回第一条结果。

        参数:
            sql: 需要执行的 SQL 查询语句，应返回至多一行结果。
            params: SQL 参数序列，顺序需与语句中的占位符 `%s` 一致。

        返回:
            查询到数据时返回字典形式的单条记录；没有数据时返回 `None`。
        """
        conn = cls.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchone()
        finally:
            conn.close()

    @classmethod
    def _fetch_all(
        cls,
        sql: str,
        params: Sequence[Any],
    ) -> List[Dict[str, Any]]:
        """
        执行多行查询并返回完整结果集。

        参数:
            sql: 需要执行的 SQL 查询语句。
            params: SQL 参数序列，顺序需与语句中的占位符 `%s` 一致。

        返回:
            结果列表；每个元素为一行记录的字典。
            若查询无结果，返回空列表。
        """
        conn = cls.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                rows: List[Dict[str, Any]] = cursor.fetchall()
                return rows
        finally:
            conn.close()

    @classmethod
    def _execute_write(
        cls,
        sql: str,
        params: Sequence[Any],
    ) -> int:
        """
        执行单条写操作 SQL，并统一处理事务提交与回滚。

        参数:
            sql: 需要执行的 INSERT / UPDATE / DELETE 语句。
            params: SQL 参数序列，顺序需与语句中的占位符 `%s` 一致。

        返回:
            受影响的行数，即 `cursor.rowcount` 的值。
        """
        conn = cls.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                affected_rows = cursor.rowcount
            conn.commit()
            return affected_rows
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 项目与访谈读取
    # ------------------------------------------------------------------
    @classmethod
    def get_interview_by_id(cls, interview_id: int) -> Optional[Dict[str, Any]]:
        """
        根据访谈 ID 查询 `bh_project_interview` 表中的单条记录。

        参数:
            interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。

        返回:
            若查询成功，返回访谈记录字典，字段至少包含：
                - id
                - parse_project_id
                - file_name
                - file_content
                - file_path
                - status
            若不存在对应记录，则返回 `None`。
        """
        sql = """
            SELECT
                id,
                parse_project_id,
                file_name,
                core_problem,
                questionnaire_id,
                key_bq_id,
                file_content,
                note_content,
                file_path,
                status
            FROM bh_project_interview
            WHERE id = %s
            LIMIT 1
        """
        return cls._fetch_one(sql, (interview_id,))

    @classmethod
    def get_questionnaire_by_id(cls, questionnaire_id: int) -> Optional[Dict[str, Any]]:
        """
        根据问卷 ID 查询 `bh_project_questionnaire` 表中的单条记录。

        参数:
            questionnaire_id: 问卷主键 ID，对应 `bh_project_questionnaire.id`。

        返回:
            若查询成功，返回问卷记录字典，字段至少包含：
                - id
                - project_id
                - name
                - file_name
                - md_path
                - json_path
                - hotwords
                - status
            若不存在对应记录，则返回 `None`。
        """
        sql = """
            SELECT
                id,
                project_id,
                name,
                file_name,
                docx_path,
                md_path,
                json_path,
                hotwords,
                status
            FROM bh_project_questionnaire
            WHERE id = %s
            LIMIT 1
        """
        return cls._fetch_one(sql, (questionnaire_id,))

    @classmethod
    def get_project_by_id(cls, project_id: int) -> Optional[Dict[str, Any]]:
        """
        根据项目 ID 查询 `bh_project` 表中的单条记录。

        参数:
            project_id: 项目主键 ID，对应 `bh_project.id`。

        返回:
            若查询成功，返回项目记录字典，字段至少包含：
                - id
                - name
                - keywords
                - core_problem
            若不存在对应记录，则返回 `None`。
        """
        sql = """
            SELECT
                id,
                name,
                keywords,
                core_problem
            FROM bh_project
            WHERE id = %s
            LIMIT 1
        """
        return cls._fetch_one(sql, (project_id,))

    @classmethod
    def fetch_interviews_by_project(
        cls,
        project_id: int,
    ) -> List[Dict[str, Any]]:
        """
        查询指定项目下的全部访谈。

        参数:
            project_id: 项目主键 ID，对应 `bh_project.id`。

        返回:
            访谈记录列表，按 `id DESC` 排序；每条记录至少包含：
                - id
                - parse_project_id
                - name
                - interview_date
                - file_name
                - hospital_city
                - hospital_decile
                - doctor_level
                - core_problem
                - status
        """
        sql = """
            SELECT
                i.id,
                i.parse_project_id,
                i.name,
                i.interview_date,
                i.file_name,
                i.hospital_city,
                i.hospital_decile,
                i.doctor_level,
                i.core_problem,
                i.status
            FROM bh_project_interview i
            WHERE i.parse_project_id = %s
            ORDER BY i.id DESC
        """
        return cls._fetch_all(sql, (project_id,))

    @classmethod
    def fetch_completed_interviews_for_project(
        cls,
        project_id: int,
        interview_ids: Optional[List[int]] = None,
    ) -> List[Dict[str, Any]]:
        """
        查询指定项目下状态为 2 的已完成访谈。

        参数:
            project_id: 项目主键 ID，对应 `bh_project.id`。
            interview_ids: 可选的访谈 ID 子集；若传入，则仅返回这些访谈中已完成的记录。

        返回:
            已完成访谈记录列表，按 `id ASC` 排序。
        """
        params: List[Any] = [project_id]
        extra_filter = ""
        if interview_ids:
            normalized_ids = [int(item) for item in interview_ids if item is not None]
            if not normalized_ids:
                return []
            extra_filter = f" AND i.id IN ({','.join(['%s'] * len(normalized_ids))})"
            params.extend(normalized_ids)
        sql = f"""
            SELECT
                i.id,
                i.parse_project_id,
                i.name,
                i.interview_date,
                i.file_name,
                i.hospital_city,
                i.hospital_decile,
                i.doctor_level,
                i.core_problem,
                i.status
            FROM bh_project_interview i
            WHERE i.parse_project_id = %s
              AND i.status = 2
              {extra_filter}
            ORDER BY i.id ASC
        """
        return cls._fetch_all(sql, params)

    @classmethod
    def fetch_questions_for_interview(cls, interview_id: int) -> List[Dict[str, Any]]:
        """
        查询某个访谈配置的题目列表。

        参数:
            interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。

        返回:
            题目记录列表。每条记录至少包含：
                - id: 题目主键 ID。
                - project_interview_id: 所属访谈 ID。
                - question_order: 题目排序序号。
                - question_text: 题目正文。
                - question_type: 题目类型。
                - research_phase: 研究阶段信息。
                - intent_id: 关联意图 ID。
        """
        sql = """
            SELECT
                id,
                project_interview_id,
                question_order,
                question_text,
                question_type,
                research_phase,
                meta,
                intent_id
            FROM bh_project_question
            WHERE project_interview_id = %s
            ORDER BY question_order ASC, id ASC
        """
        return cls._fetch_all(sql, (interview_id,))

    @classmethod
    def fetch_interview_summary(cls, interview_id: int) -> List[Dict[str, Any]]:
        """
        查询某个访谈的 summary 明细。

        参数:
            interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。

        返回:
            summary 明细记录列表。每条记录至少包含：
                - id
                - project_interview_id
                - timestamp
                - speaker
                - text
        """
        sql = """
            SELECT
                id,
                project_interview_id,
                timestamp,
                speaker,
                text
            FROM bh_project_interview_summary
            WHERE project_interview_id = %s
            ORDER BY id ASC
        """
        return cls._fetch_all(sql, (interview_id,))

    @classmethod
    def fetch_intent_name_map(cls, intent_ids: List[int]) -> Dict[int, str]:
        """
        根据意图 ID 列表构造 `intent_id -> name` 映射。

        参数:
            intent_ids: 意图 ID 列表。允许混入 `None` 或不可用值，函数内部会做过滤。

        返回:
            一个字典，键为意图 ID，值优先取 `bh_question_intent.name`，
            若 name 为空则退回 `code`。
        """
        normalized_ids = [int(i) for i in intent_ids if i is not None]
        if not normalized_ids:
            return {}

        placeholders = ",".join(["%s"] * len(normalized_ids))
        sql = f"""
            SELECT id, name, code
            FROM bh_question_intent
            WHERE id IN ({placeholders})
        """
        rows = cls._fetch_all(sql, normalized_ids)

        intent_name_map: Dict[int, str] = {}
        for row in rows:
            intent_id = row.get("id")
            if intent_id is None:
                continue
            name = str(row.get("name") or row.get("code") or "").strip()
            intent_name_map[int(intent_id)] = name
        return intent_name_map

    # ------------------------------------------------------------------
    # 访谈更新
    # ------------------------------------------------------------------
    @classmethod
    def update_interview_after_upload(
        cls,
        interview_id: int,
        object_key: str,
        status: int,
        file_id: Optional[str] = None,
        audio_url: Optional[str] = None,
    ) -> None:
        """
        在音频上传完成后，更新访谈记录中的文件路径与状态字段。

        参数:
            interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。
            object_key: 上传到 TOS 后的对象 key，写入 `file_path` 字段。
            status: 上传完成后的访谈状态码，例如“已上传待 ASR”。
            file_id: 可选的文件唯一标识，若存在则写入 `file_id` 字段。
            audio_url: 预留参数，当前版本未写入数据库，仅用于保留接口兼容性。

        返回:
            无返回值。数据库更新失败时抛出异常。
        """
        fields = ["file_path = %s", "status = %s"]
        params: List[Any] = [object_key, status]

        if file_id is not None:
            fields.append("file_id = %s")
            params.append(file_id)

        params.append(interview_id)
        sql = f"""
            UPDATE bh_project_interview
            SET {", ".join(fields)}
            WHERE id = %s
        """
        cls._execute_write(sql, params)

    @classmethod
    def update_interview_status(cls, interview_id: int, status: int) -> None:
        """
        更新访谈状态字段。

        参数:
            interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。
            status: 需要写入的状态码，含义由业务状态枚举定义。

        返回:
            无返回值。数据库更新失败时抛出异常。
        """
        sql = """
            UPDATE bh_project_interview
            SET status = %s
            WHERE id = %s
        """
        cls._execute_write(sql, (status, interview_id))

    @classmethod
    def update_interview_file_content(
        cls,
        interview_id: int,
        file_content_json: str,
    ) -> None:
        """
        将转录或纠错后的完整 JSON 结果写入访谈记录。

        参数:
            interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。
            file_content_json: 已序列化的 JSON 字符串，通常包含 ASR、纠错、清洗等结果。

        返回:
            无返回值。数据库更新失败时抛出异常。
        """
        sql = """
            UPDATE bh_project_interview
            SET file_content = %s
            WHERE id = %s
        """
        cls._execute_write(sql, (file_content_json, interview_id))

    @classmethod
    def update_interview_note_content(
        cls,
        interview_id: int,
        note_content: str,
    ) -> None:
        """
        将访谈级整体 summary 写入 `bh_project_interview.note_content`。

        参数:
            interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。
            note_content: 需要写入的整体总结文本。

        返回:
            无返回值。数据库更新失败时抛出异常。
        """
        sql = """
            UPDATE bh_project_interview
            SET note_content = %s
            WHERE id = %s
        """
        cls._execute_write(sql, (note_content, interview_id))

    @classmethod
    def upsert_key_bq_rows_for_interview(
        cls,
        project_id: int,
        interview_id: int,
        key_bq_items: List[Dict[str, Any]],
    ) -> int:
        """
        将访谈的 key BQ 明细写入或更新到 `bh_project_interview_key_bq`。

        参数:
            project_id: 项目主键 ID，对应 `bh_project.id`。
            interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。
            key_bq_items: key BQ 明细列表。每条记录至少应包含：
                - order: 顺序号
                - text: key BQ 原文
                可选包含：
                - dimension_json
                - note_json
                - status

        返回:
            实际写入或更新的条数。
        """
        if not key_bq_items:
            return 0

        sql = """
            INSERT INTO bh_project_interview_key_bq
                (project_id, project_interview_id, bq_order, bq_text, dimension_json, note_json, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                project_id = VALUES(project_id),
                bq_text = VALUES(bq_text),
                dimension_json = VALUES(dimension_json),
                note_json = VALUES(note_json),
                status = VALUES(status)
        """

        def _json_or_none(value: Any) -> Optional[str]:
            if value is None:
                return None
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            text = str(value).strip()
            return text or None

        conn = cls.get_connection()
        written = 0
        try:
            with conn.cursor() as cursor:
                for item in key_bq_items:
                    order_value = item.get("order")
                    text_value = str(item.get("text") or "").strip()
                    if order_value is None or not text_value:
                        continue
                    cursor.execute(
                        sql,
                        (
                            project_id,
                            interview_id,
                            int(order_value),
                            text_value,
                            _json_or_none(item.get("dimension_json")),
                            _json_or_none(item.get("note_json")),
                            str(item.get("status") or "pending"),
                        ),
                    )
                    written += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return written

    @classmethod
    def delete_key_bq_rows_for_interview(cls, interview_id: int) -> int:
        """
        删除指定访谈下全部 key BQ 明细。

        参数:
            interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。

        返回:
            实际删除的行数。
        """
        sql = """
            DELETE FROM bh_project_interview_key_bq
            WHERE project_interview_id = %s
        """
        return cls._execute_write(sql, (interview_id,))

    @classmethod
    def replace_key_bq_rows_for_interview(
        cls,
        project_id: int,
        interview_id: int,
        key_bq_items: List[Dict[str, Any]],
    ) -> int:
        """
        原子性替换指定访谈的 key BQ 明细。

        参数:
            project_id: 项目主键 ID。
            interview_id: 访谈主键 ID。
            key_bq_items: 新的 key BQ 明细列表。

        返回:
            最终写入或更新的条数。
        """
        if not key_bq_items:
            return 0

        delete_sql = """
            DELETE FROM bh_project_interview_key_bq
            WHERE project_interview_id = %s
        """
        insert_sql = """
            INSERT INTO bh_project_interview_key_bq
                (project_id, project_interview_id, bq_order, bq_text, dimension_json, note_json, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """

        def _json_or_none(value: Any) -> Optional[str]:
            if value is None:
                return None
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            text = str(value).strip()
            return text or None

        conn = cls.get_connection()
        written = 0
        try:
            with conn.cursor() as cursor:
                cursor.execute(delete_sql, (interview_id,))
                for item in key_bq_items:
                    order_value = item.get("order")
                    text_value = str(item.get("text") or "").strip()
                    if order_value is None or not text_value:
                        continue
                    cursor.execute(
                        insert_sql,
                        (
                            project_id,
                            interview_id,
                            int(order_value),
                            text_value,
                            _json_or_none(item.get("dimension_json")),
                            _json_or_none(item.get("note_json")),
                            str(item.get("status") or "pending"),
                        ),
                    )
                    written += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return written

    @classmethod
    def fetch_key_bq_rows_by_interview(cls, interview_id: int) -> List[Dict[str, Any]]:
        """
        查询某个访谈下的 key BQ 明细。

        参数:
            interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。

        返回:
            key BQ 明细记录列表，按 `bq_order` 升序排列。
        """
        sql = """
            SELECT
                id,
                project_id,
                project_interview_id,
                bq_order,
                bq_text,
                dimension_json,
                note_json,
                status,
                created_at,
                updated_at
            FROM bh_project_interview_key_bq
            WHERE project_interview_id = %s
            ORDER BY bq_order ASC, id ASC
        """
        return cls._fetch_all(sql, (interview_id,))

    @classmethod
    def upsert_interview_minutes(
        cls,
        project_id: int,
        interview_id: int,
        outline_json: Any,
        minutes_json: Any,
        status: str = "done",
        error_message: Optional[str] = None,
        generated_at: Optional[str] = None,
    ) -> int:
        """
        将访谈智能纪要大纲与最终结果写入 `bh_project_interview_minutes`。

        参数:
            project_id: 项目主键 ID。
            interview_id: 访谈主键 ID。
            outline_json: 智能纪要大纲对象或 JSON 字符串。
            minutes_json: 智能纪要最终结果对象或 JSON 字符串。
            status: 记录状态，默认 `done`。
            error_message: 可选错误说明。
            generated_at: 可选生成时间字符串；为空时由数据库接受 NULL。

        返回:
            实际插入或更新的行数逻辑结果；upsert 场景下返回 `cursor.rowcount`。
        """
        sql = """
            INSERT INTO bh_project_interview_minutes
                (project_id, project_interview_id, outline_json, minutes_json, status, error_message, generated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                project_id = VALUES(project_id),
                outline_json = VALUES(outline_json),
                minutes_json = VALUES(minutes_json),
                status = VALUES(status),
                error_message = VALUES(error_message),
                generated_at = VALUES(generated_at)
        """

        def _json_or_none(value: Any) -> Optional[str]:
            if value is None:
                return None
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            text = str(value).strip()
            return text or None

        conn = cls.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    sql,
                    (
                        project_id,
                        interview_id,
                        _json_or_none(outline_json),
                        _json_or_none(minutes_json),
                        str(status or "done"),
                        error_message,
                        generated_at,
                    ),
                )
                rowcount = cursor.rowcount
            conn.commit()
            return rowcount
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @classmethod
    def fetch_interview_minutes_by_interview(cls, interview_id: int) -> Optional[Dict[str, Any]]:
        """
        查询某个访谈下的智能纪要记录。

        参数:
            interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。

        返回:
            若存在则返回单条纪要记录字典，否则返回 `None`。
        """
        sql = """
            SELECT
                id,
                project_id,
                project_interview_id,
                outline_json,
                minutes_json,
                status,
                error_message,
                generated_at,
                created_at,
                updated_at
            FROM bh_project_interview_minutes
            WHERE project_interview_id = %s
            LIMIT 1
        """
        return cls._fetch_one(sql, (interview_id,))

    @classmethod
    def upsert_ca_table(
        cls,
        project_id: int,
        ca_json: Any,
        status: str = "done",
        error_message: Optional[str] = None,
        generated_at: Optional[str] = None,
    ) -> int:
        """
        将项目级 CA 结果写入 `bh_project_ca_table`。

        参数:
            project_id: 项目主键 ID。
            ca_json: CA 结果对象或 JSON 字符串。
            status: 记录状态，默认 `done`。
            error_message: 可选错误说明。
            generated_at: 可选生成时间字符串；为空时写入 NULL。

        返回:
            `cursor.rowcount`。
        """
        sql = """
            INSERT INTO bh_project_ca_table
                (project_id, ca_json, status, error_message, generated_at)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                ca_json = VALUES(ca_json),
                status = VALUES(status),
                error_message = VALUES(error_message),
                generated_at = VALUES(generated_at)
        """

        def _json_or_none(value: Any) -> Optional[str]:
            if value is None:
                return None
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            text = str(value).strip()
            return text or None

        conn = cls.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    sql,
                    (
                        project_id,
                        _json_or_none(ca_json),
                        str(status or "done"),
                        error_message,
                        generated_at,
                    ),
                )
                rowcount = cursor.rowcount
            conn.commit()
            return rowcount
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @classmethod
    def fetch_ca_table_by_project(cls, project_id: int) -> Optional[Dict[str, Any]]:
        """
        查询项目级 CA 表记录。

        参数:
            project_id: 项目主键 ID。

        返回:
            若存在则返回单条 CA 记录字典，否则返回 `None`。
        """
        sql = """
            SELECT
                id,
                project_id,
                ca_json,
                status,
                error_message,
                generated_at,
                created_at,
                updated_at
            FROM bh_project_ca_table
            WHERE project_id = %s
            LIMIT 1
        """
        return cls._fetch_one(sql, (project_id,))

    # ------------------------------------------------------------------
    # Summary 落库
    # ------------------------------------------------------------------
    @classmethod
    def insert_summary_from_cleaned_speakers(
        cls,
        interview_id: int,
        speakers: List[Dict[str, Any]],
    ) -> int:
        """
        将清洗后的说话轮次批量写入 `bh_project_interview_summary`。

        参数:
            interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。
            speakers: 清洗后的说话轮次列表。每个元素至少应包含：
                - speaker_id: 说话人 ID，写入 `speaker` 字段。
                - speaker_content_clean: 清洗后的文本正文，写入 `text` 字段。
                - start_time / end_time: 原始 ASR 的起止毫秒时间。
                - 或 timestamp: 已预格式化好的时间区间字符串。

        返回:
            实际插入到 `bh_project_interview_summary` 表中的记录条数。
            为空文本的分段会被自动跳过。
        """
        if not speakers:
            return 0

        sql = """
            INSERT INTO bh_project_interview_summary
                (project_interview_id, timestamp, speaker, text, modify)
            VALUES (%s, %s, %s, %s, %s)
        """

        conn = cls.get_connection()
        inserted = 0
        try:
            with conn.cursor() as cursor:
                for seg in speakers:
                    speaker_id = str(seg.get("speaker_id", ""))
                    clean_text = seg.get("speaker_content_clean", "")
                    if not clean_text:
                        clean_text = seg.get("speaker_content_corrected", "")
                    if not clean_text:
                        clean_text = seg.get("text", "")
                    if not clean_text:
                        clean_text = seg.get("speaker_content", "")
                    if not clean_text:
                        continue
                    timestamp = cls._format_summary_timestamp(seg)
                    cursor.execute(sql, (interview_id, timestamp, speaker_id, clean_text, 0))
                    inserted += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        return inserted

    # ------------------------------------------------------------------
    # Notes 落库
    # ------------------------------------------------------------------
    @classmethod
    def insert_notes_result(
        cls,
        project_id: int,
        interview_id: int,
        question_id: int,
        intent_id: int,
        note_json_str: str,
        confidence: float,
        status: int,
        error_message: Optional[str] = None,
    ) -> int:
        """
        将单条 Notes 结果写入 `bh_project_interview_notes` 表，并在重复键场景下更新旧记录。

        参数:
            project_id: 项目 ID，对应 `bh_project.id`。
            interview_id: 访谈 ID，对应 `bh_project_interview.id`。
            question_id: 题目 ID，对应 `bh_project_question.id`。
            intent_id: 意图 ID，对应 `bh_question_intent.id`。
            note_json_str: 已序列化的 Notes JSON 字符串，写入 `note_json` 字段。
            confidence: 模型输出置信度，通常为 0 到 1 之间的小数。
            status: Notes 状态码，例如自动生成、已通过、已编辑、已拒绝、错误。
            error_message: 可选错误说明；当生成失败或需要记录异常信息时写入。

        返回:
            插入或更新后的记录 ID。
            当命中唯一键并走 upsert 更新时，返回已有记录的主键 ID。
        """
        sql = """
            INSERT INTO bh_project_interview_notes
                (project_id, project_interview_id, question_id, intent_id,
                 note_json, confidence, status, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                note_json = VALUES(note_json),
                confidence = VALUES(confidence),
                status = VALUES(status),
                error_message = VALUES(error_message),
                id = LAST_INSERT_ID(id)
        """

        conn = cls.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    sql,
                    (
                        project_id,
                        interview_id,
                        question_id,
                        intent_id,
                        note_json_str,
                        confidence,
                        status,
                        error_message,
                    ),
                )
                record_id = cursor.lastrowid
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        return record_id
