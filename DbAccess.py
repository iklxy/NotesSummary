"@Date: 2026-04-10"
"@Author: lixinyang"


import json
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

import pymysql

from config import config
from interview_detail_fields import build_interview_detail_meta


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
    def _get_data_root() -> Path:
        """
        获取项目数据目录。

        返回:
            仓库根目录下的 `data` 目录路径。
        """
        return Path(__file__).resolve().parent / "data"

    @classmethod
    def _resolve_data_path(cls, raw_path: str) -> Optional[Path]:
        """
        将数据库里保存的相对路径解析为本地绝对路径。

        参数:
            raw_path: 数据库中保存的路径字符串。

        返回:
            解析后的本地文件路径；若输入为空则返回 `None`。
        """
        text = str(raw_path or "").strip()
        if not text:
            return None
        path = Path(text)
        if not path.is_absolute():
            path = cls._get_data_root() / path
        return path

    @staticmethod
    def _normalize_mysql_datetime(value: Any) -> Optional[str]:
        """
        将 ISO8601 / datetime 字符串归一化为 MySQL DATETIME 可接受的格式。
        """
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")

        text = str(value).strip()
        if not text:
            return None

        normalized_text = text.replace("Z", "+00:00") if text.endswith("Z") else text
        try:
            parsed = datetime.fromisoformat(normalized_text)
        except ValueError:
            return text

        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed.strftime("%Y-%m-%d %H:%M:%S")

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

    @staticmethod
    def _normalize_json_value(value: Any) -> Any:
        """
        将可序列化字段规范化为适合写入数据库的值。

        参数:
            value: 原始字段值，允许为 dict、list、datetime 或普通标量。

        返回:
            可直接写入 MySQL 的值。
        """
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value

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
                i.id,
                i.parse_project_id,
                i.name,
                i.interview_date,
                i.file_name,
                i.core_problem,
                i.questionnaire_id,
                i.key_bq_id,
                i.file_content,
                i.note_content,
                i.file_path,
                i.status,
                COALESCE(d.city, i.hospital_city) AS city,
                COALESCE(d.city, i.hospital_city) AS hospital_city,
                COALESCE(d.hospital_decile, i.hospital_decile) AS hospital_decile,
                COALESCE(d.doctor_level, i.doctor_level) AS doctor_level,
                d.doctor_title,
                d.hospital,
                d.department
            FROM bh_project_interview i
            LEFT JOIN bh_interview_detail d ON d.interview_id = i.id
            WHERE i.id = %s
            LIMIT 1
        """
        row = cls._fetch_one(sql, (interview_id,))
        if row:
            row["detail"] = build_interview_detail_meta(row)
        return row

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
    def fetch_questionnaire_markdown_text_by_id(cls, questionnaire_id: int) -> Optional[str]:
        """
        根据问卷 ID 加载其 Markdown 文本内容。

        参数:
            questionnaire_id: 问卷主键 ID，对应 `bh_project_questionnaire.id`。

        返回:
            若 `md_path` 存在且文件可读，返回 Markdown 文本；否则返回 `None`。
        """
        questionnaire = cls.get_questionnaire_by_id(questionnaire_id)
        if not questionnaire:
            return None

        md_path = str(questionnaire.get("md_path") or "").strip()
        if not md_path:
            return None

        resolved_path = cls._resolve_data_path(md_path)
        if resolved_path is None or not resolved_path.exists() or not resolved_path.is_file():
            return None

        try:
            markdown_text = resolved_path.read_text(encoding="utf-8")
        except Exception:
            return None

        cleaned_text = markdown_text.strip()
        return cleaned_text or None

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
                p.id,
                p.name,
                p.keywords,
                p.core_problem,
                g.guide_file_name,
                g.guide_file_path,
                g.file_type AS guide_file_type,
                g.extracted_text AS guide_extracted_text,
                g.summary_text AS guide_summary_text,
                g.status AS guide_status,
                g.error_message AS guide_error_message,
                g.generated_at AS guide_generated_at
            FROM bh_project p
            LEFT JOIN bh_project_guide g ON g.project_id = p.id
            WHERE p.id = %s
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
                i.core_problem,
                i.status,
                COALESCE(d.city, i.hospital_city) AS city,
                COALESCE(d.city, i.hospital_city) AS hospital_city,
                COALESCE(d.hospital_decile, i.hospital_decile) AS hospital_decile,
                COALESCE(d.doctor_level, i.doctor_level) AS doctor_level,
                d.doctor_title,
                d.hospital,
                d.department
            FROM bh_project_interview i
            LEFT JOIN bh_interview_detail d ON d.interview_id = i.id
            WHERE i.parse_project_id = %s
            ORDER BY i.id DESC
        """
        rows = cls._fetch_all(sql, (project_id,))
        for row in rows:
            row["detail"] = build_interview_detail_meta(row)
        return rows

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
                i.core_problem,
                i.status,
                COALESCE(d.city, i.hospital_city) AS city,
                COALESCE(d.city, i.hospital_city) AS hospital_city,
                COALESCE(d.hospital_decile, i.hospital_decile) AS hospital_decile,
                COALESCE(d.doctor_level, i.doctor_level) AS doctor_level,
                d.doctor_title,
                d.hospital,
                d.department
            FROM bh_project_interview i
            LEFT JOIN bh_interview_detail d ON d.interview_id = i.id
            WHERE i.parse_project_id = %s
              AND i.status = 2
              {extra_filter}
            ORDER BY i.id ASC
        """
        rows = cls._fetch_all(sql, params)
        for row in rows:
            row["detail"] = build_interview_detail_meta(row)
        return rows

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
                - confidence
        """
        sql = """
            SELECT
                id,
                project_interview_id,
                timestamp,
                speaker,
                text,
                confidence
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

    # ------------------------------------------------------------------
    # 工作流任务状态
    # ------------------------------------------------------------------
    @classmethod
    def get_workflow_job_by_interview(
        cls,
        interview_id: int,
        workflow_type: str = "transcription",
    ) -> Optional[Dict[str, Any]]:
        """
        根据访谈 ID 读取对应的工作流任务。

        参数:
            interview_id: 访谈主键 ID。
            workflow_type: 工作流类型，默认 `transcription`。

        返回:
            单条任务记录；若不存在则返回 `None`。
        """
        sql = """
            SELECT
                id,
                project_id,
                project_interview_id,
                workflow_type,
                status,
                stage,
                object_key,
                audio_url,
                volc_task_id,
                task_submitted_at,
                next_poll_at,
                last_polled_at,
                task_expires_at,
                retry_count,
                poll_count,
                lease_owner,
                lease_expires_at,
                checkpoint_json,
                asr_result_json,
                cleaned_json,
                error_stage,
                error_message,
                error_traceback,
                started_at,
                finished_at,
                created_at,
                updated_at
            FROM bh_interview_workflow_jobs
            WHERE project_interview_id = %s
              AND workflow_type = %s
            LIMIT 1
        """
        return cls._fetch_one(sql, (interview_id, workflow_type))

    @classmethod
    def list_recoverable_workflow_jobs(
        cls,
        workflow_type: str = "transcription",
        statuses: Optional[Sequence[str]] = None,
        stages: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        列出可恢复的工作流任务，供启动时恢复扫描使用。

        参数:
            workflow_type: 工作流类型，默认 `transcription`。
            statuses: 可恢复状态集合；为空时使用默认值。
            stages: 可恢复阶段集合；为空时使用默认值。

        返回:
            满足恢复条件的任务列表。
        """
        status_list = list(statuses or ("queued", "running", "waiting_asr", "recovering"))
        stage_list = list(
            stages
            or (
                "created",
                "audio_ready",
                "asr_submitting",
                "asr_polling",
                "asr_done",
                "cleaning",
                "cleaned",
                "summary_written",
                "overall_note_written",
                "minutes_written",
                "cards_written",
                "kbq_written",
            )
        )
        if not status_list or not stage_list:
            return []

        status_placeholders = ",".join(["%s"] * len(status_list))
        stage_placeholders = ",".join(["%s"] * len(stage_list))
        sql = f"""
            SELECT
                id,
                project_id,
                project_interview_id,
                workflow_type,
                status,
                stage,
                object_key,
                audio_url,
                volc_task_id,
                task_submitted_at,
                next_poll_at,
                last_polled_at,
                task_expires_at,
                retry_count,
                poll_count,
                lease_owner,
                lease_expires_at,
                checkpoint_json,
                asr_result_json,
                cleaned_json,
                error_stage,
                error_message,
                error_traceback,
                started_at,
                finished_at,
                created_at,
                updated_at
            FROM bh_interview_workflow_jobs
            WHERE workflow_type = %s
              AND status IN ({status_placeholders})
              AND stage IN ({stage_placeholders})
            ORDER BY updated_at ASC, id ASC
        """
        params: List[Any] = [workflow_type, *status_list, *stage_list]
        return cls._fetch_all(sql, params)

    @classmethod
    def upsert_workflow_job(
        cls,
        project_id: int,
        interview_id: int,
        workflow_type: str = "transcription",
        **fields: Any,
    ) -> None:
        """
        插入或更新工作流任务记录。

        参数:
            project_id: 项目 ID。
            interview_id: 访谈 ID。
            workflow_type: 工作流类型。
            **fields: 允许写入的任务字段。

        返回:
            无返回值；失败时抛出异常。
        """
        allowed_fields = [
            "status",
            "stage",
            "object_key",
            "audio_url",
            "volc_task_id",
            "task_submitted_at",
            "next_poll_at",
            "last_polled_at",
            "task_expires_at",
            "retry_count",
            "poll_count",
            "lease_owner",
            "lease_expires_at",
            "checkpoint_json",
            "asr_result_json",
            "cleaned_json",
            "error_stage",
            "error_message",
            "error_traceback",
            "started_at",
            "finished_at",
        ]

        payload: Dict[str, Any] = {
            "project_id": project_id,
            "project_interview_id": interview_id,
            "workflow_type": workflow_type,
        }
        for field in allowed_fields:
            if field in fields:
                payload[field] = cls._normalize_json_value(fields[field])

        columns = list(payload.keys())
        placeholders = ", ".join(["%s"] * len(columns))
        update_columns = [column for column in columns if column not in {"project_id", "project_interview_id", "workflow_type"}]
        update_clause = ", ".join(f"{column} = VALUES({column})" for column in update_columns)
        sql = f"""
            INSERT INTO bh_interview_workflow_jobs
                ({", ".join(columns)})
            VALUES
                ({placeholders})
            ON DUPLICATE KEY UPDATE
                {update_clause}
        """
        params = [payload[column] for column in columns]
        cls._execute_write(sql, params)

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
            """
            _json_or_none 函数。

            参数:
                value: value 的输入值。

            返回:
                见函数返回值。
            """

            if value is None:
                return None
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            text = str(value).strip()
            return text or None

        def _datetime_or_none(value: Any) -> Optional[str]:
            return DbAccess._normalize_mysql_datetime(value)

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
            """
            _json_or_none 函数。

            参数:
                value: value 的输入值。

            返回:
                见函数返回值。
            """

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
            """
            _json_or_none 函数。

            参数:
                value: value 的输入值。

            返回:
                见函数返回值。
            """

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
    def fetch_interview_cards_by_interview(cls, interview_id: int) -> Optional[Dict[str, Any]]:
        """
        查询某个访谈下的全文模块卡片父记录。
        """
        sql = """
            SELECT
                id,
                project_id,
                project_interview_id,
                status,
                error_message,
                created_at,
                updated_at
            FROM bh_project_interview_cards
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
        questionnaire_id: Optional[int] = None,
        framework_json: Any = None,
        final_json: Any = None,
        framework_status: Optional[str] = None,
        final_status: Optional[str] = None,
        framework_generated_at: Optional[str] = None,
        final_generated_at: Optional[str] = None,
        reviewed_at: Optional[str] = None,
    ) -> int:
        """
        将项目级 CA 结果写入 `bh_project_ca_table`。

        参数:
            project_id: 项目主键 ID。
            ca_json: CA 结果对象或 JSON 字符串。
            status: 记录状态，默认 `done`。
            error_message: 可选错误说明。
            generated_at: 可选生成时间字符串；为空时写入 NULL。
            questionnaire_id: 关联的问卷 ID。
            framework_json: CA 框架 JSON。
            final_json: CA 最终 JSON。
            framework_status: 框架状态。
            final_status: 最终状态。
            framework_generated_at: 框架生成时间。
            final_generated_at: 最终生成时间。
            reviewed_at: 人工确认时间。

        返回:
            `cursor.rowcount`。
        """
        sql = """
            INSERT INTO bh_project_ca_table
                (project_id, questionnaire_id, ca_json, framework_json, final_json, framework_status, final_status, error_message, generated_at, framework_generated_at, final_generated_at, reviewed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                questionnaire_id = VALUES(questionnaire_id),
                ca_json = VALUES(ca_json),
                framework_json = VALUES(framework_json),
                final_json = VALUES(final_json),
                framework_status = VALUES(framework_status),
                final_status = VALUES(final_status),
                error_message = VALUES(error_message),
                generated_at = VALUES(generated_at),
                framework_generated_at = VALUES(framework_generated_at),
                final_generated_at = VALUES(final_generated_at),
                reviewed_at = VALUES(reviewed_at)
        """

        def _json_or_none(value: Any) -> Optional[str]:
            """
            _json_or_none 函数。

            参数:
                value: value 的输入值。

            返回:
                见函数返回值。
            """

            if value is None:
                return None
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            text = str(value).strip()
            return text or None

        def _datetime_or_none(value: Any) -> Optional[str]:
            return DbAccess._normalize_mysql_datetime(value)

        active_json = ca_json if ca_json is not None else framework_json if framework_json is not None else final_json
        effective_framework_json = framework_json if framework_json is not None else active_json
        effective_final_json = final_json
        effective_framework_status = framework_status or ("reviewed" if effective_framework_json is not None else "draft")
        effective_final_status = final_status or ("done" if effective_final_json is not None else "pending")
        conn = cls.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    sql,
                    (
                        project_id,
                        questionnaire_id,
                        _json_or_none(active_json),
                        _json_or_none(effective_framework_json),
                        _json_or_none(effective_final_json),
                        str(effective_framework_status or "draft"),
                        str(effective_final_status or "done"),
                        error_message,
                        _datetime_or_none(generated_at),
                        _datetime_or_none(framework_generated_at),
                        _datetime_or_none(final_generated_at),
                        _datetime_or_none(reviewed_at),
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
    def fetch_ca_table_by_project(
        cls,
        project_id: int,
        questionnaire_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        查询项目级 CA 表记录。

        参数:
            project_id: 项目主键 ID。
            questionnaire_id: 可选问卷 ID。

        返回:
            若存在则返回单条 CA 记录字典，否则返回 `None`。
        """
        sql = """
            SELECT
                id,
                project_id,
                questionnaire_id,
                ca_json,
                framework_json,
                final_json,
                framework_status,
                final_status,
                error_message,
                generated_at,
                framework_generated_at,
                final_generated_at,
                reviewed_at,
                created_at,
                updated_at
            FROM bh_project_ca_table
            WHERE project_id = %s
        """
        params: list[Any] = [project_id]
        if questionnaire_id is not None:
            sql += " AND questionnaire_id = %s"
            params.append(questionnaire_id)
        sql += " ORDER BY updated_at DESC, id DESC LIMIT 1"
        return cls._fetch_one(sql, tuple(params))

    @classmethod
    def fetch_ca_tables_by_project(cls, project_id: int) -> List[Dict[str, Any]]:
        """
        查询项目下全部 CA 表记录。
        """
        sql = """
            SELECT
                id,
                project_id,
                questionnaire_id,
                ca_json,
                framework_json,
                final_json,
                framework_status,
                final_status,
                error_message,
                generated_at,
                framework_generated_at,
                final_generated_at,
                reviewed_at,
                created_at,
                updated_at
            FROM bh_project_ca_table
            WHERE project_id = %s
            ORDER BY updated_at DESC, id DESC
        """
        return cls._fetch_all(sql, (project_id,))

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

        def _normalize_confidence(value: Any) -> Optional[float]:
            if value is None or isinstance(value, bool):
                return None
            try:
                confidence = float(value)
            except (TypeError, ValueError):
                return None
            if confidence < 0:
                return 0.0
            if confidence > 1:
                return 1.0
            return confidence

        sql = """
            INSERT INTO bh_project_interview_summary
                (project_interview_id, timestamp, speaker, text, confidence, modify)
            VALUES (%s, %s, %s, %s, %s, %s)
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
                    cursor.execute(
                        sql,
                        (
                            interview_id,
                            timestamp,
                            speaker_id,
                            clean_text,
                            _normalize_confidence(seg.get("confidence")),
                            0,
                        ),
                    )
                    inserted += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        return inserted

    @classmethod
    def delete_interview_summary_by_interview(cls, interview_id: int) -> int:
        """
        删除某个访谈下的 summary 明细。
        """
        sql = """
            DELETE FROM bh_project_interview_summary
            WHERE project_interview_id = %s
        """
        return cls._execute_write(sql, (interview_id,))

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
