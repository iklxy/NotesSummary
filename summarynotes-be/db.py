import json
import os
from typing import Any, Optional

import dotenv
import pymysql

from api.project_roles import build_default_role_detail_schema, build_default_role_name, normalize_detail_schema_fields, normalize_role_type
from interview_detail_fields import build_interview_detail_meta, normalize_interview_detail_payload


PROJECT_KEY_BQ_CURRENT_NAME = "__current__"

dotenv.load_dotenv()


def _json_or_none(value: Any) -> Optional[str]:
    """
    将任意值归一化为 JSON 字符串或空值。
    """
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    text = str(value).strip()
    return text or None


def get_connection() -> pymysql.connections.Connection:
    """
    创建并返回一个 MySQL 数据库连接。

    参数:
        无，所有配置均从环境变量中读取:
            - DB_HOST: 数据库主机名或 IP，默认 127.0.0.1。
            - DB_PORT: 数据库端口，默认 3306。
            - DB_USER: 数据库用户名。
            - DB_PASSWORD: 数据库密码。
            - DB_NAME: 数据库名称。

    返回:
        已建立连接的 pymysql Connection 实例。
    """
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = int(os.getenv("DB_PORT", "3306"))
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    db_name = os.getenv("DB_NAME")

    connection = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=db_name,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )
    return connection


def insert_project(
    name: str,
    keywords: Optional[str],
    core_problem: Optional[str],
    created_by_user_id: int,
) -> int:
    """
    插入一条项目记录到 bh_project 表。

    参数:
        name:             项目名称，对应 bh_project.name。
        keywords:         项目关键词，可空，对应 bh_project.keywords。
        core_problem:   访谈核心描述，可空，可映射到表中的核心问题描述字段。

    返回:
        新插入记录的自增 ID。
    """
    sql = """
        INSERT INTO bh_project (name, keywords, core_problem, created_by_user_id)
        VALUES (%s, %s, %s, %s)
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                sql,
                (name, keywords, core_problem, created_by_user_id),
            )
            new_id = cursor.lastrowid
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return new_id


def update_project(
    project_id: int,
    name: Optional[str] = None,
    keywords: Optional[str] = None,
    core_problem: Optional[str] = None,
    created_by_user_id: int | None = None,
) -> int:
    """
    更新项目基础信息。

    参数:
        project_id: 项目主键 ID。
        name: 项目名称，可选。
        keywords: 项目关键词，可选。
        core_problem: 项目背景说明，可选。
        created_by_user_id: 当前用户 ID，可选，用于权限校验。

    返回:
        受影响行数。
    """
    fields: list[str] = []
    params: list[Any] = []

    if name is not None:
        fields.append("name = %s")
        params.append(name)
    if keywords is not None:
        fields.append("keywords = %s")
        params.append(keywords)
    if core_problem is not None:
        fields.append("core_problem = %s")
        params.append(core_problem)

    if not fields:
        return 0

    sql = f"""
        UPDATE bh_project
        SET {", ".join(fields)}
        WHERE id = %s
    """
    params.append(project_id)
    if created_by_user_id is not None:
        sql += " AND created_by_user_id = %s"
        params.append(created_by_user_id)

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            affected = cursor.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return affected


def fetch_projects(created_by_user_id: int | None = None) -> list[dict]:
    """
    从 bh_project 表中查询所有项目的基础信息。

    返回:
        包含每个项目字段的字典列表，字段至少包括:
            - id
            - name
            - keywords
            - core_problem
    """
    sql = """
        SELECT
            p.id,
            p.name,
            p.keywords,
            p.core_problem,
            p.created_by_user_id,
            g.guide_file_name,
            g.guide_file_path,
            g.file_type AS guide_file_type,
            g.guide_files_json AS guide_files_json,
            g.extracted_text AS guide_extracted_text,
            g.summary_text AS guide_summary_text,
            g.status AS guide_status,
            g.error_message AS guide_error_message,
            g.generated_at AS guide_generated_at,
            COALESCE((
                SELECT COUNT(1)
                FROM bh_project_questionnaire q
                WHERE q.project_id = p.id
            ), 0) AS questionnaire_count,
            COALESCE((
                SELECT COUNT(1)
                FROM bh_project_key_bq k
                WHERE k.project_id = p.id
                  AND k.name = %s
            ), CASE WHEN p.key_bq_json IS NULL THEN 0 ELSE 1 END) AS key_bq_count,
            COALESCE((
                SELECT k.key_bq_json
                FROM bh_project_key_bq k
                WHERE k.project_id = p.id
                  AND k.name = %s
                LIMIT 1
            ), p.key_bq_json) AS key_bq_json,
            COALESCE((
                SELECT COUNT(1)
                FROM bh_project_interview i
                WHERE i.parse_project_id = p.id
            ), 0) AS interview_count
        FROM bh_project p
        LEFT JOIN bh_project_guide g ON g.project_id = p.id
        WHERE (%s IS NULL OR p.created_by_user_id = %s)
        ORDER BY p.id DESC
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    PROJECT_KEY_BQ_CURRENT_NAME,
                    PROJECT_KEY_BQ_CURRENT_NAME,
                    created_by_user_id,
                    created_by_user_id,
                ),
            )
            rows: list[dict] = cursor.fetchall()
    finally:
        conn.close()
    return rows


def fetch_project_by_id(
    project_id: int,
    created_by_user_id: int | None = None,
) -> dict | None:
    """
    根据项目 ID 查询单条项目记录。

    参数:
        project_id: 项目主键 ID，对应 bh_project.id。

    返回:
        如果存在则返回项目记录字典，否则返回 None。
    """
    sql = """
        SELECT
            p.id,
            p.name,
            p.keywords,
            p.core_problem,
            p.created_by_user_id,
            g.guide_file_name,
            g.guide_file_path,
            g.file_type AS guide_file_type,
            g.guide_files_json AS guide_files_json,
            g.extracted_text AS guide_extracted_text,
            g.summary_text AS guide_summary_text,
            g.status AS guide_status,
            g.error_message AS guide_error_message,
            g.generated_at AS guide_generated_at,
            COALESCE((
                SELECT COUNT(1)
                FROM bh_project_questionnaire q
                WHERE q.project_id = p.id
            ), 0) AS questionnaire_count,
            COALESCE((
                SELECT COUNT(1)
                FROM bh_project_key_bq k
                WHERE k.project_id = p.id
                  AND k.name = %s
            ), CASE WHEN p.key_bq_json IS NULL THEN 0 ELSE 1 END) AS key_bq_count,
            COALESCE((
                SELECT k.key_bq_json
                FROM bh_project_key_bq k
                WHERE k.project_id = p.id
                  AND k.name = %s
                LIMIT 1
            ), p.key_bq_json) AS key_bq_json,
            COALESCE((
                SELECT COUNT(1)
                FROM bh_project_interview i
                WHERE i.parse_project_id = p.id
            ), 0) AS interview_count
        FROM bh_project p
        LEFT JOIN bh_project_guide g ON g.project_id = p.id
        WHERE p.id = %s
          AND (%s IS NULL OR p.created_by_user_id = %s)
        LIMIT 1
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    PROJECT_KEY_BQ_CURRENT_NAME,
                    PROJECT_KEY_BQ_CURRENT_NAME,
                    project_id,
                    created_by_user_id,
                    created_by_user_id,
                ),
            )
            row = cursor.fetchone()
    finally:
        conn.close()
    return row


def fetch_user_by_username(username: str) -> dict | None:
    """
    根据用户名查询单条用户记录。

    参数:
        username: 登录用户名，对应 bh_user.username。

    返回:
        如果存在则返回用户记录字典，否则返回 None。
    """
    sql = """
        SELECT
            id,
            username,
            password_hash,
            created_at,
            updated_at
        FROM bh_user
        WHERE username = %s
        LIMIT 1
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (username,))
            row = cursor.fetchone()
    finally:
        conn.close()
    return row


def fetch_user_by_id(user_id: int) -> dict | None:
    """
    根据用户 ID 查询单条用户记录。

    参数:
        user_id: 用户主键 ID，对应 bh_user.id。

    返回:
        如果存在则返回用户记录字典，否则返回 None。
    """
    sql = """
        SELECT
            id,
            username,
            password_hash,
            created_at,
            updated_at
        FROM bh_user
        WHERE id = %s
        LIMIT 1
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (user_id,))
            row = cursor.fetchone()
    finally:
        conn.close()
    return row


def fetch_question_intents() -> list[dict]:
    """
    查询所有可用的 question intent。
    """
    sql = """
        SELECT
            id,
            code,
            name,
            description,
            schema_name,
            status
        FROM bh_question_intent
        ORDER BY id ASC
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            rows: list[dict] = cursor.fetchall()
    finally:
        conn.close()
    return rows


def update_project_guide(
    project_id: int,
    guide_file_name: Optional[str] = None,
    guide_file_path: Optional[str] = None,
    file_type: Optional[str] = None,
    guide_files_json: Any = None,
    extracted_text: Any = None,
    summary_text: Any = None,
    status: Optional[str] = None,
    error_message: Optional[str] = None,
    generated_at: Optional[str] = None,
) -> int:
    """
    更新项目级指南信息。
    """
    sql = """
        INSERT INTO bh_project_guide
            (project_id, guide_file_name, guide_file_path, file_type, guide_files_json, extracted_text, summary_text, status, error_message, generated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            guide_file_name = VALUES(guide_file_name),
            guide_file_path = VALUES(guide_file_path),
            file_type = VALUES(file_type),
            guide_files_json = VALUES(guide_files_json),
            extracted_text = VALUES(extracted_text),
            summary_text = VALUES(summary_text),
            status = VALUES(status),
            error_message = VALUES(error_message),
            generated_at = VALUES(generated_at)
    """

    def _text_or_none(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    project_id,
                    _text_or_none(guide_file_name),
                    _text_or_none(guide_file_path),
                    _text_or_none(file_type) or "pdf",
                    _json_or_none(guide_files_json),
                    _text_or_none(extracted_text),
                    _text_or_none(summary_text),
                    _text_or_none(status) or "queued",
                    _text_or_none(error_message),
                    generated_at,
                ),
            )
            affected = cursor.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return affected


def fetch_project_guide_by_project_id(project_id: int) -> dict | None:
    """
    查询项目级指南记录。
    """
    sql = """
        SELECT
            id,
            project_id,
            guide_file_name,
            guide_file_path,
            file_type,
            guide_files_json,
            extracted_text,
            summary_text,
            status,
            error_message,
            generated_at,
            created_at,
            updated_at
        FROM bh_project_guide
        WHERE project_id = %s
        LIMIT 1
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (project_id,))
            row = cursor.fetchone()
    finally:
        conn.close()
    return row


def _json_or_none(value: Any) -> Optional[str]:
    """
    将任意值归一化为 JSON 字符串或空值。
    """
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    text = str(value).strip()
    return text or None


def _normalize_object_type(value: Any) -> Optional[str]:
    """
    将访谈对象类型归一化为系统内置枚举值。
    """
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"patient", "患者"}:
        return "patient"
    if text in {"doctor", "医生"}:
        return "doctor"
    return None


def _json_loads_or_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def upsert_interview_detail(
    interview_id: int,
    detail: Any = None,
    legacy_values: Optional[dict[str, Any]] = None,
) -> int:
    """
    写入或更新访谈细节记录。
    """
    normalized = normalize_interview_detail_payload(detail, legacy_values)
    detail_json = json.dumps(normalized, ensure_ascii=False)
    sql = """
        INSERT INTO bh_interview_detail
            (interview_id, detail_json, doctor_level, doctor_title, city, hospital, department, hospital_decile)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            detail_json = VALUES(detail_json),
            doctor_level = VALUES(doctor_level),
            doctor_title = VALUES(doctor_title),
            city = VALUES(city),
            hospital = VALUES(hospital),
            department = VALUES(department),
            hospital_decile = VALUES(hospital_decile)
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    interview_id,
                    detail_json,
                    normalized.get("doctor_level"),
                    normalized.get("doctor_title"),
                    normalized.get("city"),
                    normalized.get("hospital"),
                    normalized.get("department"),
                    normalized.get("hospital_decile"),
                ),
            )
            rowcount = cursor.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return rowcount


def update_interview_name(interview_id: int, name: str) -> int:
    """
    更新访谈名称。
    """
    sql = """
        UPDATE bh_project_interview
        SET name = %s
        WHERE id = %s
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (name, interview_id))
            affected = cursor.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return affected


def insert_questionnaire(
    project_id: int,
    name: str,
    role_id: Optional[int] = None,
    object_type: Optional[str] = None,
    file_name: Optional[str] = None,
    docx_path: Optional[str] = None,
    md_path: Optional[str] = None,
    json_path: Optional[str] = None,
    hotwords: Any = None,
    status: str = "hotword_review_pending",
) -> int:
    """
    插入一条项目问卷记录。
    """
    sql = """
        INSERT INTO bh_project_questionnaire
            (project_id, role_id, name, object_type, file_name, docx_path, md_path, json_path, hotwords, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    project_id,
                    role_id,
                    name,
                    _normalize_object_type(object_type),
                    file_name,
                    docx_path,
                    md_path,
                    json_path,
                    _json_or_none(hotwords),
                    status,
                ),
            )
            new_id = cursor.lastrowid
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return new_id


def update_questionnaire(
    questionnaire_id: int,
    project_id: int,
    role_id: Optional[int] = None,
    name: Optional[str] = None,
    object_type: Optional[str] = None,
    file_name: Optional[str] = None,
    docx_path: Optional[str] = None,
    md_path: Optional[str] = None,
    json_path: Optional[str] = None,
    hotwords: Any = None,
    status: Optional[str] = None,
) -> dict | None:
    """
    更新项目问卷记录。
    """
    fields: list[str] = []
    params: list[Any] = []
    for column, value in (
        ("role_id", role_id),
        ("name", name),
        ("object_type", _normalize_object_type(object_type) if object_type is not None else None),
        ("file_name", file_name),
        ("docx_path", docx_path),
        ("md_path", md_path),
        ("json_path", json_path),
        ("hotwords", _json_or_none(hotwords) if hotwords is not None else None),
        ("status", status),
    ):
        if value is None:
            continue
        fields.append(f"{column} = %s")
        params.append(value)
    if not fields:
        return fetch_questionnaire_by_id(questionnaire_id, project_id)

    sql = f"""
        UPDATE bh_project_questionnaire
        SET {", ".join(fields)}
        WHERE id = %s AND project_id = %s
    """
    params.extend([questionnaire_id, project_id])
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            if cursor.rowcount == 0:
                conn.rollback()
                return None
            cursor.execute(
                """
                SELECT
                    q.id,
                    q.project_id,
                    q.role_id,
                    q.name,
                    q.object_type,
                    q.file_name,
                    q.docx_path,
                    q.md_path,
                    q.json_path,
                    r.role_name,
                    r.role_type,
                    r.detail_schema_json,
                    q.hotwords,
                    q.status,
                    q.created_at,
                    q.updated_at
                FROM bh_project_questionnaire q
                LEFT JOIN bh_project_role r ON r.id = q.role_id
                WHERE q.id = %s AND q.project_id = %s
                LIMIT 1
                """,
                (questionnaire_id, project_id),
            )
            row = cursor.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return row


def fetch_questionnaire_by_id(
    questionnaire_id: int,
    project_id: int | None = None,
    created_by_user_id: int | None = None,
) -> dict | None:
    """
    查询单条问卷记录。
    """
    sql = """
        SELECT
                    q.id,
                    q.project_id,
                    q.role_id,
                    q.name,
                    q.object_type,
                    q.file_name,
                    q.docx_path,
                    q.md_path,
                    q.json_path,
                    r.role_name,
                    r.role_type,
                    r.detail_schema_json,
            q.hotwords,
            q.status,
            q.created_at,
            q.updated_at,
            p.created_by_user_id
        FROM bh_project_questionnaire q
        INNER JOIN bh_project p ON p.id = q.project_id
        LEFT JOIN bh_project_role r ON r.id = q.role_id
        WHERE q.id = %s
          AND (%s IS NULL OR q.project_id = %s)
          AND (%s IS NULL OR p.created_by_user_id = %s)
        LIMIT 1
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    questionnaire_id,
                    project_id,
                    project_id,
                    created_by_user_id,
                    created_by_user_id,
                ),
            )
            row = cursor.fetchone()
    finally:
        conn.close()
    return row


def fetch_questionnaires_by_project(
    project_id: int,
    created_by_user_id: int | None = None,
) -> list[dict]:
    """
    查询项目下的问卷列表。
    """
    sql = """
        SELECT
                    q.id,
                    q.project_id,
                    q.role_id,
                    q.name,
                    q.object_type,
                    q.file_name,
                    q.docx_path,
                    q.md_path,
                    q.json_path,
                    r.role_name,
                    r.role_type,
                    r.detail_schema_json,
            q.hotwords,
            q.status,
            q.created_at,
            q.updated_at,
            COALESCE((
                SELECT COUNT(1)
                FROM bh_project_interview i
                WHERE i.parse_project_id = q.project_id
                  AND i.questionnaire_id = q.id
            ), 0) AS referenced_interview_count
        FROM bh_project_questionnaire q
        INNER JOIN bh_project p ON p.id = q.project_id
        LEFT JOIN bh_project_role r ON r.id = q.role_id
        WHERE q.project_id = %s
          AND (%s IS NULL OR p.created_by_user_id = %s)
        ORDER BY COALESCE(r.role_name, q.object_type, q.name), q.id DESC
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (project_id, created_by_user_id, created_by_user_id))
            rows: list[dict] = cursor.fetchall()
    finally:
        conn.close()
    return rows


def fetch_questionnaire_by_project_and_object_type(
    project_id: int,
    object_type: str,
    created_by_user_id: int | None = None,
) -> dict | None:
    """
    根据项目和对象类型查询问卷。
    """
    sql = """
        SELECT
            q.id,
            q.project_id,
            q.role_id,
            q.name,
            q.object_type,
            q.file_name,
            q.docx_path,
            q.md_path,
            q.json_path,
            r.role_name,
            r.role_type,
            r.detail_schema_json,
            q.hotwords,
            q.status,
            q.created_at,
            q.updated_at,
            p.created_by_user_id
        FROM bh_project_questionnaire q
        INNER JOIN bh_project p ON p.id = q.project_id
        LEFT JOIN bh_project_role r ON r.id = q.role_id
        WHERE q.project_id = %s
          AND (q.object_type = %s OR r.role_type = %s)
          AND (%s IS NULL OR p.created_by_user_id = %s)
        ORDER BY q.updated_at DESC, q.id DESC
        LIMIT 1
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            normalized_type = _normalize_object_type(object_type)
            cursor.execute(
                sql,
                (
                    project_id,
                    normalized_type,
                    normalized_type,
                    created_by_user_id,
                    created_by_user_id,
                ),
            )
            row = cursor.fetchone()
    finally:
        conn.close()
    return row


def insert_project_role(
    project_id: int,
    role_name: str,
    role_type: str,
    detail_schema_json: Any,
) -> int:
    sql = """
        INSERT INTO bh_project_role
            (project_id, role_name, role_type, detail_schema_json)
        VALUES (%s, %s, %s, %s)
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    project_id,
                    role_name,
                    normalize_role_type(role_type) or "custom",
                    _json_or_none(normalize_detail_schema_fields(detail_schema_json, role_type)),
                ),
            )
            new_id = cursor.lastrowid
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return new_id


def fetch_project_role_by_id(
    role_id: int,
    project_id: int | None = None,
    created_by_user_id: int | None = None,
) -> dict | None:
    sql = """
        SELECT
            r.id,
            r.project_id,
            r.role_name,
            r.role_type,
            r.detail_schema_json,
            r.created_at,
            r.updated_at,
            p.created_by_user_id
        FROM bh_project_role r
        INNER JOIN bh_project p ON p.id = r.project_id
        WHERE r.id = %s
          AND (%s IS NULL OR r.project_id = %s)
          AND (%s IS NULL OR p.created_by_user_id = %s)
        LIMIT 1
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (role_id, project_id, project_id, created_by_user_id, created_by_user_id))
            row = cursor.fetchone()
    finally:
        conn.close()
    return row


def fetch_project_role_by_name(
    project_id: int,
    role_name: str,
    created_by_user_id: int | None = None,
) -> dict | None:
    sql = """
        SELECT
            r.id,
            r.project_id,
            r.role_name,
            r.role_type,
            r.detail_schema_json,
            r.created_at,
            r.updated_at,
            p.created_by_user_id
        FROM bh_project_role r
        INNER JOIN bh_project p ON p.id = r.project_id
        WHERE r.project_id = %s
          AND r.role_name = %s
          AND (%s IS NULL OR p.created_by_user_id = %s)
        LIMIT 1
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (project_id, role_name, created_by_user_id, created_by_user_id))
            row = cursor.fetchone()
    finally:
        conn.close()
    return row


def fetch_project_roles_by_project(
    project_id: int,
    created_by_user_id: int | None = None,
) -> list[dict]:
    sql = """
        SELECT
            r.id,
            r.project_id,
            r.role_name,
            r.role_type,
            r.detail_schema_json,
            r.created_at,
            r.updated_at,
            p.created_by_user_id
        FROM bh_project_role r
        INNER JOIN bh_project p ON p.id = r.project_id
        WHERE r.project_id = %s
          AND (%s IS NULL OR p.created_by_user_id = %s)
        ORDER BY r.id ASC
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (project_id, created_by_user_id, created_by_user_id))
            rows: list[dict] = cursor.fetchall()
    finally:
        conn.close()
    return rows


def ensure_project_builtin_roles(
    project_id: int,
    created_by_user_id: int | None = None,
) -> list[dict]:
    existing = fetch_project_roles_by_project(project_id, created_by_user_id)
    by_type = {
        normalize_role_type(row.get("role_type")): row
        for row in existing
        if normalize_role_type(row.get("role_type")) in {"doctor", "patient"}
    }
    created: list[dict] = []
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            for role_type in ("doctor", "patient"):
                if role_type in by_type:
                    continue
                role_name = build_default_role_name(role_type)
                detail_schema_json = _json_or_none(build_default_role_detail_schema(role_type))
                cursor.execute(
                    """
                        INSERT INTO bh_project_role (project_id, role_name, role_type, detail_schema_json)
                        VALUES (%s, %s, %s, %s)
                    """,
                    (project_id, role_name, role_type, detail_schema_json),
                )
                created.append(
                    {
                        "id": cursor.lastrowid,
                        "project_id": project_id,
                        "role_name": role_name,
                        "role_type": role_type,
                        "detail_schema_json": detail_schema_json,
                    }
                )
            cursor.execute(
                """
                    SELECT
                        r.id,
                        r.project_id,
                        r.role_name,
                        r.role_type,
                        r.detail_schema_json,
                        r.created_at,
                        r.updated_at
                    FROM bh_project_role r
                    WHERE r.project_id = %s
                    ORDER BY r.id ASC
                """,
                (project_id,),
            )
            rows = cursor.fetchall()
            role_map = {normalize_role_type(row.get("role_type")): int(row["id"]) for row in rows if normalize_role_type(row.get("role_type"))}
            for role_type, role_id in role_map.items():
                cursor.execute(
                    """
                        UPDATE bh_project_questionnaire
                        SET role_id = %s
                        WHERE project_id = %s
                          AND role_id IS NULL
                          AND object_type = %s
                    """,
                    (role_id, project_id, role_type),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return fetch_project_roles_by_project(project_id, created_by_user_id)


def delete_questionnaire(
    questionnaire_id: int,
    project_id: int,
    created_by_user_id: int | None = None,
) -> dict | None:
    """
    删除项目问卷记录。
    """
    row = fetch_questionnaire_by_id(questionnaire_id, project_id, created_by_user_id)
    if not row:
        return None

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM bh_project_questionnaire
                WHERE id = %s AND project_id = %s
                """,
                (questionnaire_id, project_id),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return None
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return row


def count_questionnaire_usage(questionnaire_id: int, project_id: int) -> int:
    """
    查询问卷被多少访谈引用。
    """
    sql = """
        SELECT COUNT(1) AS cnt
        FROM bh_project_interview
        WHERE parse_project_id = %s
          AND questionnaire_id = %s
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (project_id, questionnaire_id))
            row = cursor.fetchone() or {}
    finally:
        conn.close()
    return int(row.get("cnt") or 0)


def insert_key_bq(
    project_id: int,
    name: str,
    key_bq_json: Any,
) -> int:
    """
    插入一组项目级 Key BQ。
    """
    sql = """
        INSERT INTO bh_project_key_bq
            (project_id, name, key_bq_json)
        VALUES (%s, %s, %s)
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (project_id, name, _json_or_none(key_bq_json)))
            new_id = cursor.lastrowid
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return new_id


def upsert_project_key_bq(
    project_id: int,
    key_bq_json: Any,
) -> int:
    """
    保存项目级单例 Key BQ。
    """
    sql = """
        INSERT INTO bh_project_key_bq
            (project_id, name, key_bq_json)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            key_bq_json = VALUES(key_bq_json)
    """
    project_sql = """
        UPDATE bh_project
        SET key_bq_json = %s
        WHERE id = %s
    """
    normalized_json = _json_or_none(key_bq_json)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (project_id, PROJECT_KEY_BQ_CURRENT_NAME, normalized_json))
            affected = cursor.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    try:
        mirror_conn = get_connection()
        try:
            with mirror_conn.cursor() as cursor:
                cursor.execute(project_sql, (normalized_json, project_id))
            mirror_conn.commit()
        except Exception:
            mirror_conn.rollback()
        finally:
            mirror_conn.close()
    except Exception:
        pass

    return affected


def update_key_bq(
    key_bq_id: int,
    project_id: int,
    name: Optional[str] = None,
    key_bq_json: Any = None,
) -> dict | None:
    """
    更新一组项目级 Key BQ。
    """
    fields: list[str] = []
    params: list[Any] = []
    if name is not None:
        fields.append("name = %s")
        params.append(name)
    if key_bq_json is not None:
        fields.append("key_bq_json = %s")
        params.append(_json_or_none(key_bq_json))
    if not fields:
        return fetch_key_bq_by_id(key_bq_id, project_id)

    sql = f"""
        UPDATE bh_project_key_bq
        SET {", ".join(fields)}
        WHERE id = %s AND project_id = %s
    """
    params.extend([key_bq_id, project_id])
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            if cursor.rowcount == 0:
                conn.rollback()
                return None
            cursor.execute(
                """
                SELECT
                    id,
                    project_id,
                    name,
                    key_bq_json,
                    created_at,
                    updated_at
                FROM bh_project_key_bq
                WHERE id = %s AND project_id = %s
                LIMIT 1
                """,
                (key_bq_id, project_id),
            )
            row = cursor.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return row


def fetch_key_bq_by_id(
    key_bq_id: int,
    project_id: int | None = None,
    created_by_user_id: int | None = None,
) -> dict | None:
    """
    查询单条项目级 Key BQ。
    """
    sql = """
        SELECT
            k.id,
            k.project_id,
            k.name,
            k.key_bq_json,
            k.created_at,
            k.updated_at,
            p.created_by_user_id
        FROM bh_project_key_bq k
        INNER JOIN bh_project p ON p.id = k.project_id
        WHERE k.id = %s
          AND (%s IS NULL OR k.project_id = %s)
          AND (%s IS NULL OR p.created_by_user_id = %s)
        LIMIT 1
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    key_bq_id,
                    project_id,
                    project_id,
                    created_by_user_id,
                    created_by_user_id,
                ),
            )
            row = cursor.fetchone()
    finally:
        conn.close()
    return row


def fetch_key_bq_by_project(
    project_id: int,
    created_by_user_id: int | None = None,
) -> list[dict]:
    """
    查询项目下所有 Key BQ 组。
    """
    sql = """
        SELECT
            k.id,
            k.project_id,
            k.name,
            k.key_bq_json,
            k.created_at,
            k.updated_at,
            COALESCE((
                SELECT COUNT(1)
                FROM bh_project_interview i
                WHERE i.parse_project_id = k.project_id
                  AND i.key_bq_id = k.id
            ), 0) AS referenced_interview_count
        FROM bh_project_key_bq k
        INNER JOIN bh_project p ON p.id = k.project_id
        WHERE k.project_id = %s
          AND k.name <> %s
          AND (%s IS NULL OR p.created_by_user_id = %s)
        ORDER BY k.id DESC
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                sql,
                (project_id, PROJECT_KEY_BQ_CURRENT_NAME, created_by_user_id, created_by_user_id),
            )
            rows: list[dict] = cursor.fetchall()
    finally:
        conn.close()
    return rows


def delete_key_bq(
    key_bq_id: int,
    project_id: int,
    created_by_user_id: int | None = None,
) -> dict | None:
    """
    删除项目级 Key BQ。
    """
    row = fetch_key_bq_by_id(key_bq_id, project_id, created_by_user_id)
    if not row:
        return None

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM bh_project_key_bq
                WHERE id = %s AND project_id = %s
                """,
                (key_bq_id, project_id),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return None
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return row


def count_key_bq_usage(key_bq_id: int, project_id: int) -> int:
    """
    查询 Key BQ 被多少访谈引用。
    """
    sql = """
        SELECT COUNT(1) AS cnt
        FROM bh_project_interview
        WHERE parse_project_id = %s
          AND key_bq_id = %s
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (project_id, key_bq_id))
            row = cursor.fetchone() or {}
    finally:
        conn.close()
    return int(row.get("cnt") or 0)


def fetch_project_stats(project_id: int) -> dict:
    """
    查询项目下的问卷、Key BQ、访谈数量。
    """
    sql = """
        SELECT
            (SELECT COUNT(1) FROM bh_project_questionnaire WHERE project_id = %s) AS questionnaire_count,
            (SELECT COUNT(1) FROM bh_project_key_bq WHERE project_id = %s AND name = %s) AS key_bq_count,
            (SELECT COUNT(1) FROM bh_project_interview WHERE parse_project_id = %s) AS interview_count
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (project_id, project_id, PROJECT_KEY_BQ_CURRENT_NAME, project_id))
            row = cursor.fetchone() or {}
    finally:
        conn.close()
    return row


def insert_interview(
    parse_project_id: int,
    name: str,
    interview_date: Optional[str],
    file_name: str,
    hospital_city: Optional[str],
    hospital_decile: Optional[int],
    doctor_level: Optional[str],
    core_problem: Optional[str],
    questionnaire_id: Optional[int] = None,
    key_bq_id: Optional[int] = None,
) -> int:
    """
    插入一条访谈记录到 bh_project_interview 表。

    参数:
        parse_project_id: 项目 ID，对应 bh_project_interview.parse_project_id。
        name:             访谈名称，对应 bh_project_interview.name。
        interview_date:   访谈时间字符串（例如 '2026-04-15'），对应 bh_project_interview.interview_date。
        file_name:        音频文件名，对应 bh_project_interview.file_name。
        hospital_city:    医院所在城市，对应 bh_project_interview.hospital_city。
        hospital_decile:  医院 Decile，对应 bh_project_interview.hospital_decile。
        doctor_level:     医生级别，对应 bh_project_interview.doctor_level。
        core_problem:     访谈 key BQ 的 JSON 字符串，对应 bh_project_interview.core_problem。
        questionnaire_id: 关联问卷 ID，可空，写入 bh_project_interview.questionnaire_id。
        key_bq_id:        关联 Key BQ ID，可空，写入 bh_project_interview.key_bq_id。

    返回:
        新插入访谈记录的自增 ID。
    """
    sql = """
        INSERT INTO bh_project_interview (
            parse_project_id,
            name,
            interview_date,
            file_name,
            hospital_city,
            hospital_decile,
            doctor_level,
            core_problem,
            questionnaire_id,
            key_bq_id,
            status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    parse_project_id,
                    name,
                    interview_date,
                    file_name,
                    hospital_city,
                    hospital_decile,
                    doctor_level,
                    core_problem,
                    questionnaire_id,
                    key_bq_id,
                    0,
                ),
            )
            new_id = cursor.lastrowid
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return new_id


def fetch_interview_detail_by_interview_id(interview_id: int) -> dict | None:
    """
    查询单条访谈细节记录。
    """
    sql = """
        SELECT
            id,
            interview_id,
            detail_json,
            doctor_level,
            doctor_title,
            city,
            hospital,
            department,
            hospital_decile,
            created_at,
            updated_at
        FROM bh_interview_detail
        WHERE interview_id = %s
        LIMIT 1
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (interview_id,))
            row = cursor.fetchone()
    finally:
        conn.close()
    return row


def insert_key_bq_rows_for_interview(
    project_id: int,
    project_interview_id: int,
    key_bq_items: list[dict],
) -> int:
    """
    为指定访谈批量写入 key BQ 明细到 `bh_project_interview_key_bq`。

    参数:
        project_id: 项目 ID，对应 `bh_project.id`。
        project_interview_id: 访谈 ID，对应 `bh_project_interview.id`。
        key_bq_items: key BQ 列表，每项至少应包含:
            - order: 顺序号
            - text: key BQ 文本
            可选包含:
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

    conn = get_connection()
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
                        project_interview_id,
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


def delete_key_bq_rows_for_interview(project_interview_id: int) -> int:
    """
    删除指定访谈下全部 key BQ 明细。

    参数:
        project_interview_id: 访谈 ID，对应 `bh_project_interview.id`。

    返回:
        实际删除的行数。
    """
    sql = """
        DELETE FROM bh_project_interview_key_bq
        WHERE project_interview_id = %s
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (project_interview_id,))
            affected = cursor.rowcount
        conn.commit()
        return affected
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def replace_key_bq_rows_for_interview(
    project_id: int,
    project_interview_id: int,
    key_bq_items: list[dict],
) -> int:
    """
    原子性替换指定访谈下全部 key BQ 明细。

    参数:
        project_id: 项目 ID。
        project_interview_id: 访谈 ID，对应 `bh_project_interview.id`。
        key_bq_items: 新的 key BQ 列表。

    返回:
        实际写入或更新的条数。
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

    conn = get_connection()
    written = 0
    try:
        with conn.cursor() as cursor:
            cursor.execute(delete_sql, (project_interview_id,))
            for item in key_bq_items:
                order_value = item.get("order")
                text_value = str(item.get("text") or "").strip()
                if order_value is None or not text_value:
                    continue
                cursor.execute(
                    insert_sql,
                    (
                        project_id,
                        project_interview_id,
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


def update_interview_status(interview_id: int, status: int) -> None:
    """
    更新访谈处理状态。

    参数:
        interview_id: 访谈 ID，对应 bh_project_interview.id。
        status:       处理状态，0/1/2/3 等。
    """
    sql = """
        UPDATE bh_project_interview
        SET status = %s
        WHERE id = %s
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (status, interview_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_interview_note_content(interview_id: int, note_content: str) -> None:
    """
    更新访谈级整体 summary notes 文本。

    参数:
        interview_id: 访谈 ID，对应 bh_project_interview.id。
        note_content: 需要写入的整体 summary notes 文本。
    """
    sql = """
        UPDATE bh_project_interview
        SET note_content = %s
        WHERE id = %s
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (note_content, interview_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_interview_kbq_note_json(
    interview_id: int,
    kbq_id: int,
    note_json: Any,
) -> dict | None:
    """
    更新单条 KBQ Notes 的 note_json 内容。

    参数:
        interview_id: 访谈 ID。
        kbq_id: KBQ 记录 ID。
        note_json: 更新后的 JSON 内容。

    返回:
        更新后的记录字典；若记录不存在则返回 None。
    """
    sql = """
        UPDATE bh_project_interview_key_bq
        SET note_json = %s
        WHERE id = %s AND project_interview_id = %s
    """

    def _json_or_none(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        text = str(value).strip()
        return text or None

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (_json_or_none(note_json), kbq_id, interview_id))
            if cursor.rowcount == 0:
                conn.rollback()
                return None
            cursor.execute(
                """
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
                WHERE id = %s AND project_interview_id = %s
                LIMIT 1
                """,
                (kbq_id, interview_id),
            )
            row = cursor.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return row


def fetch_interview_minutes_by_interview(interview_id: int) -> dict | None:
    """
    查询某个访谈下的智能纪要记录。

    参数:
        interview_id: 访谈 ID，对应 bh_project_interview.id。

    返回:
        若存在则返回单条智能纪要记录字典，否则返回 None。
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
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (interview_id,))
            row = cursor.fetchone()
    finally:
        conn.close()
    return row


def update_interview_minutes_json(
    interview_id: int,
    project_id: int,
    minutes_json: Any,
) -> dict | None:
    """
    更新访谈智能纪要的 minutes_json。

    参数:
        interview_id: 访谈 ID。
        project_id: 项目 ID。
        minutes_json: 更新后的 JSON 内容。

    返回:
        更新后的记录字典；若没有记录则会尝试插入并返回新记录。
    """
    def _json_or_none(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        text = str(value).strip()
        return text or None

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE bh_project_interview_minutes
                SET minutes_json = %s,
                    status = COALESCE(status, 'done')
                WHERE project_interview_id = %s
                """,
                (_json_or_none(minutes_json), interview_id),
            )
            if cursor.rowcount == 0:
                cursor.execute(
                    """
                    INSERT INTO bh_project_interview_minutes
                        (project_id, project_interview_id, outline_json, minutes_json, status, error_message, generated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        project_id = VALUES(project_id),
                        minutes_json = VALUES(minutes_json),
                        status = VALUES(status),
                        error_message = VALUES(error_message),
                        generated_at = VALUES(generated_at)
                    """,
                    (
                        project_id,
                        interview_id,
                        None,
                        _json_or_none(minutes_json),
                        "done",
                        None,
                        None,
                    ),
                )
            cursor.execute(
                """
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
                """,
                (interview_id,),
            )
            row = cursor.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return row


def fetch_interview_cards_by_interview(interview_id: int) -> dict | None:
    """
    查询某个访谈下的卡片主记录。
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
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (interview_id,))
            row = cursor.fetchone()
    finally:
        conn.close()
    return row


def upsert_interview_cards(
    project_id: int,
    interview_id: int,
    status: str = "pending",
    error_message: Optional[str] = None,
) -> dict | None:
    """
    插入或更新访谈卡片主记录。
    """
    sql = """
        INSERT INTO bh_project_interview_cards
            (project_id, project_interview_id, status, error_message)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            project_id = VALUES(project_id),
            status = VALUES(status),
            error_message = VALUES(error_message)
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (project_id, interview_id, status, error_message))
            cursor.execute(
                """
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
                """,
                (interview_id,),
            )
            row = cursor.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return row


def fetch_interview_cards_items_by_cards_id(cards_id: int) -> list[dict]:
    """
    查询某个卡片主记录下的全部卡片明细。
    """
    sql = """
        SELECT
            id,
            cards_id,
            project_id,
            project_interview_id,
            card_order,
            card_title,
            card_summary,
            generated_json,
            final_json,
            review_status,
            review_comment,
            reviewed_by,
            reviewed_at,
            updated_by,
            updated_at
        FROM bh_project_interview_cards_items
        WHERE cards_id = %s
        ORDER BY card_order ASC, id ASC
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (cards_id,))
            rows = cursor.fetchall()
    finally:
        conn.close()
    return rows


def fetch_interview_cards_bundle(interview_id: int) -> dict | None:
    """
    查询指定访谈的卡片主表与明细。
    """
    cards_row = fetch_interview_cards_by_interview(interview_id)
    if not cards_row:
        return None
    items = fetch_interview_cards_items_by_cards_id(int(cards_row["id"]))
    return {
        **cards_row,
        "items": items,
    }


def ensure_interview_cards(project_id: int, interview_id: int) -> dict | None:
    """
    确保访谈卡片主记录存在，不存在时创建一条。
    """
    row = fetch_interview_cards_by_interview(interview_id)
    if row:
        return row
    return upsert_interview_cards(project_id=project_id, interview_id=interview_id, status="pending")


def insert_interview_cards_item(
    cards_id: int,
    project_id: int,
    project_interview_id: int,
    card_order: int,
    card_title: str,
    card_summary: Optional[str],
    generated_json: Any,
    final_json: Any = None,
    review_status: str = "pending",
    review_comment: Optional[str] = None,
    reviewed_by: Optional[int] = None,
    reviewed_at: Optional[str] = None,
    updated_by: Optional[int] = None,
) -> dict | None:
    """
    插入一条卡片明细。
    """
    sql = """
        INSERT INTO bh_project_interview_cards_items
            (cards_id, project_id, project_interview_id, card_order, card_title, card_summary,
             generated_json, final_json, review_status, review_comment, reviewed_by, reviewed_at, updated_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    final_payload = final_json if final_json is not None else generated_json
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    cards_id,
                    project_id,
                    project_interview_id,
                    card_order,
                    card_title,
                    card_summary,
                    _json_or_none(generated_json),
                    _json_or_none(final_payload),
                    review_status,
                    review_comment,
                    reviewed_by,
                    reviewed_at,
                    updated_by,
                ),
            )
            new_id = cursor.lastrowid
            cursor.execute(
                """
                SELECT
                    id,
                    cards_id,
                    project_id,
                    project_interview_id,
                    card_order,
                    card_title,
                    card_summary,
                    generated_json,
                    final_json,
                    review_status,
                    review_comment,
                    reviewed_by,
                    reviewed_at,
                    updated_by,
                    updated_at
                FROM bh_project_interview_cards_items
                WHERE id = %s
                LIMIT 1
                """,
                (new_id,),
            )
            row = cursor.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return row


def update_interview_cards_item(
    item_id: int,
    project_id: int,
    project_interview_id: int,
    card_order: Optional[int] = None,
    card_title: Optional[str] = None,
    card_summary: Optional[str] = None,
    generated_json: Any = None,
    final_json: Any = None,
    review_status: Optional[str] = None,
    review_comment: Optional[str] = None,
    reviewed_by: Optional[int] = None,
    reviewed_at: Optional[str] = None,
    updated_by: Optional[int] = None,
) -> dict | None:
    """
    更新一条卡片明细。
    """
    fields: list[str] = []
    params: list[Any] = []
    if card_order is not None:
        fields.append("card_order = %s")
        params.append(card_order)
    if card_title is not None:
        fields.append("card_title = %s")
        params.append(card_title)
    if card_summary is not None:
        fields.append("card_summary = %s")
        params.append(card_summary)
    if generated_json is not None:
        fields.append("generated_json = %s")
        params.append(_json_or_none(generated_json))
    if final_json is not None:
        fields.append("final_json = %s")
        params.append(_json_or_none(final_json))
    if review_status is not None:
        fields.append("review_status = %s")
        params.append(review_status)
    if review_comment is not None:
        fields.append("review_comment = %s")
        params.append(review_comment)
    if reviewed_by is not None:
        fields.append("reviewed_by = %s")
        params.append(reviewed_by)
    if reviewed_at is not None:
        fields.append("reviewed_at = %s")
        params.append(reviewed_at)
    if updated_by is not None:
        fields.append("updated_by = %s")
        params.append(updated_by)
    if not fields:
        return fetch_interview_cards_item_by_id(item_id, project_interview_id)

    sql = f"""
        UPDATE bh_project_interview_cards_items
        SET {', '.join(fields)}
        WHERE id = %s AND project_id = %s AND project_interview_id = %s
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, cards_id, card_order
                FROM bh_project_interview_cards_items
                WHERE id = %s AND project_interview_id = %s
                LIMIT 1
                """,
                (item_id, project_interview_id),
            )
            current_row = cursor.fetchone()
            if not current_row:
                conn.rollback()
                return None

            current_order = int(current_row.get("card_order") or 0)
            current_cards_id = int(current_row.get("cards_id") or 0)
            target_order = int(card_order) if card_order is not None else current_order

            if card_order is not None and target_order != current_order:
                cursor.execute(
                    """
                    UPDATE bh_project_interview_cards_items
                    SET card_order = 0
                    WHERE id = %s AND project_interview_id = %s
                    """,
                    (item_id, project_interview_id),
                )
                if target_order < current_order:
                    cursor.execute(
                        """
                        UPDATE bh_project_interview_cards_items
                        SET card_order = card_order + 1
                        WHERE cards_id = %s
                          AND project_interview_id = %s
                          AND card_order >= %s
                          AND card_order < %s
                          AND id <> %s
                        """,
                        (current_cards_id, project_interview_id, target_order, current_order, item_id),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE bh_project_interview_cards_items
                        SET card_order = card_order - 1
                        WHERE cards_id = %s
                          AND project_interview_id = %s
                          AND card_order > %s
                          AND card_order <= %s
                          AND id <> %s
                        """,
                        (current_cards_id, project_interview_id, current_order, target_order, item_id),
                    )

            params.extend([item_id, project_id, project_interview_id])
            cursor.execute(sql, params)
            if cursor.rowcount == 0:
                conn.rollback()
                return None
            cursor.execute(
                """
                SELECT
                    id,
                    cards_id,
                    project_id,
                    project_interview_id,
                    card_order,
                    card_title,
                    card_summary,
                    generated_json,
                    final_json,
                    review_status,
                    review_comment,
                    reviewed_by,
                    reviewed_at,
                    updated_by,
                    updated_at
                FROM bh_project_interview_cards_items
                WHERE id = %s
                LIMIT 1
                """,
                (item_id,),
            )
            row = cursor.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return row


def fetch_interview_cards_item_by_id(item_id: int, project_interview_id: int) -> dict | None:
    """
    查询单条卡片明细。
    """
    sql = """
        SELECT
            id,
            cards_id,
            project_id,
            project_interview_id,
            card_order,
            card_title,
            card_summary,
            generated_json,
            final_json,
            review_status,
            review_comment,
            reviewed_by,
            reviewed_at,
            updated_by,
            updated_at
        FROM bh_project_interview_cards_items
        WHERE id = %s AND project_interview_id = %s
        LIMIT 1
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (item_id, project_interview_id))
            row = cursor.fetchone()
    finally:
        conn.close()
    return row


def delete_interview_cards_item(item_id: int, project_interview_id: int) -> dict | None:
    """
    删除单条卡片明细。
    """
    row = fetch_interview_cards_item_by_id(item_id, project_interview_id)
    if not row:
        return None
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            deleted_order = int(row.get("card_order") or 0)
            cards_id = int(row.get("cards_id") or 0)
            cursor.execute(
                """
                DELETE FROM bh_project_interview_cards_items
                WHERE id = %s AND project_interview_id = %s
                """,
                (item_id, project_interview_id),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return None
            if deleted_order > 0:
                cursor.execute(
                    """
                    UPDATE bh_project_interview_cards_items
                    SET card_order = card_order - 1
                    WHERE cards_id = %s
                      AND project_interview_id = %s
                      AND card_order > %s
                    """,
                    (cards_id, project_interview_id, deleted_order),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return row


def upsert_ca_table(
    project_id: int,
    ca_json: Any,
    status: str = "done",
    error_message: Optional[str] = None,
    generated_at: Optional[str] = None,
) -> int:
    """
    将项目 CA 结果写入 `bh_project_ca_table`。

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

    conn = get_connection()
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


def fetch_ca_table_by_project(project_id: int) -> dict | None:
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
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (project_id,))
            row = cursor.fetchone()
    finally:
        conn.close()
    return row


def upsert_interview_minutes(
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

    conn = get_connection()
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


def fetch_interview_by_id(
    interview_id: int,
    created_by_user_id: int | None = None,
) -> dict | None:
    """
    根据访谈 ID 查询访谈基础信息。

    返回字段至少包括:
        - id
        - parse_project_id
        - name
        - interview_date
        - file_name
        - hospital_city
        - hospital_decile
        - doctor_level
        - core_problem
        - file_path
        - status
    """
    sql = """
        SELECT
            i.id,
            i.parse_project_id,
            i.name,
            i.interview_date,
            i.file_name,
            d.detail_json,
            COALESCE(d.city, i.hospital_city) AS city,
            COALESCE(d.city, i.hospital_city) AS hospital_city,
            COALESCE(d.hospital_decile, i.hospital_decile) AS hospital_decile,
            COALESCE(d.doctor_level, i.doctor_level) AS doctor_level,
            d.doctor_title,
            d.hospital,
            d.department,
            i.core_problem,
            i.questionnaire_id,
            q.name AS questionnaire_name,
            q.status AS questionnaire_status,
            q.object_type AS questionnaire_object_type,
            q.role_id AS questionnaire_role_id,
            r.role_name AS questionnaire_role_name,
            r.role_type AS questionnaire_role_type,
            r.detail_schema_json AS questionnaire_role_detail_schema_json,
            i.key_bq_id,
            k.name AS key_bq_name,
            i.note_content,
            i.file_path,
            i.status
        FROM bh_project_interview i
        INNER JOIN bh_project p ON p.id = i.parse_project_id
        LEFT JOIN bh_interview_detail d ON d.interview_id = i.id
        LEFT JOIN bh_project_questionnaire q ON q.id = i.questionnaire_id
        LEFT JOIN bh_project_role r ON r.id = q.role_id
        LEFT JOIN bh_project_key_bq k ON k.id = i.key_bq_id
        WHERE i.id = %s
          AND (%s IS NULL OR p.created_by_user_id = %s)
        LIMIT 1
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (interview_id, created_by_user_id, created_by_user_id))
            row = cursor.fetchone()
    finally:
        conn.close()
    return row


def delete_interview_graph(interview_id: int) -> dict | None:
    """
    删除指定访谈及其关联数据。

    会删除：
        - bh_project_fewshot_sample
        - bh_project_interview_notes
        - bh_project_interview_summary
        - bh_project_question
        - bh_project_interview

    返回：
        删除前的访谈记录，用于后续清理本地音频目录。
    """
    row = fetch_interview_by_id(interview_id)
    if not row:
        return None

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM bh_project_interview_cards_items WHERE project_interview_id = %s",
                (interview_id,),
            )
            cursor.execute(
                "DELETE FROM bh_project_interview_cards WHERE project_interview_id = %s",
                (interview_id,),
            )
            cursor.execute(
                "DELETE FROM bh_project_interview_key_bq WHERE project_interview_id = %s",
                (interview_id,),
            )
            cursor.execute(
                "DELETE FROM bh_project_interview_minutes WHERE project_interview_id = %s",
                (interview_id,),
            )
            cursor.execute(
                "DELETE FROM bh_project_fewshot_sample WHERE project_interview_id = %s",
                (interview_id,),
            )
            cursor.execute(
                "DELETE FROM bh_project_interview_notes WHERE project_interview_id = %s",
                (interview_id,),
            )
            cursor.execute(
                "DELETE FROM bh_project_interview_summary WHERE project_interview_id = %s",
                (interview_id,),
            )
            cursor.execute(
                "DELETE FROM bh_project_question WHERE project_interview_id = %s",
                (interview_id,),
            )
            cursor.execute(
                "DELETE FROM bh_project_interview WHERE id = %s",
                (interview_id,),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return row


def delete_project_graph(
    project_id: int,
    created_by_user_id: int | None = None,
) -> dict | None:
    """
    删除指定项目及其关联数据。

    会删除：
        - bh_project_fewshot_sample
        - bh_project_interview_notes
        - bh_project_interview_summary
        - bh_project_question
        - bh_project_interview
        - bh_project

    参数:
        project_id: 项目 ID，对应 bh_project.id。
        created_by_user_id: 可选用户 ID，用于限制只能删除当前用户创建的项目。

    返回:
        删除前的项目记录，若项目不存在则返回 None。
    """
    project = fetch_project_by_id(project_id, created_by_user_id)
    if not project:
        return None

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT i.id
                FROM bh_project_interview i
                INNER JOIN bh_project p ON p.id = i.parse_project_id
                WHERE i.parse_project_id = %s
                  AND (%s IS NULL OR p.created_by_user_id = %s)
                ORDER BY i.id ASC
                """,
                (project_id, created_by_user_id, created_by_user_id),
            )
            interview_rows = cursor.fetchall()

            for interview_row in interview_rows:
                interview_id = int(interview_row["id"])
                cursor.execute(
                    "DELETE FROM bh_project_interview_key_bq WHERE project_interview_id = %s",
                    (interview_id,),
                )
                cursor.execute(
                    "DELETE FROM bh_project_interview_minutes WHERE project_interview_id = %s",
                    (interview_id,),
                )
                cursor.execute(
                    "DELETE FROM bh_project_fewshot_sample WHERE project_interview_id = %s",
                    (interview_id,),
                )
                cursor.execute(
                    "DELETE FROM bh_project_interview_notes WHERE project_interview_id = %s",
                    (interview_id,),
                )
                cursor.execute(
                    "DELETE FROM bh_project_interview_summary WHERE project_interview_id = %s",
                    (interview_id,),
                )
                cursor.execute(
                    "DELETE FROM bh_project_question WHERE project_interview_id = %s",
                    (interview_id,),
                )
                cursor.execute(
                    "DELETE FROM bh_project_interview WHERE id = %s",
                    (interview_id,),
                )

            cursor.execute(
                "DELETE FROM bh_project_questionnaire WHERE project_id = %s",
                (project_id,),
            )
            cursor.execute(
                "DELETE FROM bh_project_key_bq WHERE project_id = %s",
                (project_id,),
            )

            cursor.execute(
                """
                DELETE FROM bh_project
                WHERE id = %s
                  AND (%s IS NULL OR created_by_user_id = %s)
                """,
                (project_id, created_by_user_id, created_by_user_id),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return None
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return project


def insert_questions_for_interview(
    project_interview_id: int,
    questions: list[dict],
) -> int:
    """
    为指定访谈批量插入题目。

    参数:
        project_interview_id: 访谈 ID，对应 bh_project_question.project_interview_id。
        questions: 题目列表，每项至少包含:
            - question_order
            - question_text
            - question_type

    返回:
        实际插入条数。
    """
    if not questions:
        return 0

    sql = """
        INSERT INTO bh_project_question
            (project_interview_id, question_order, question_text, question_type, research_phase, intent_id, meta)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """

    conn = get_connection()
    inserted = 0
    try:
        with conn.cursor() as cursor:
            for item in questions:
                question_order = item.get("question_order")
                question_text = (item.get("question_text") or "").strip()
                question_type = (item.get("question_type") or "OPEN").strip().upper()
                research_phase = item.get("research_phase")
                intent_id = item.get("intent_id")
                meta = item.get("meta")
                if isinstance(meta, (dict, list)):
                    meta = json.dumps(meta, ensure_ascii=False)

                if question_order is None:
                    raise ValueError("question_order is required")
                if not question_text:
                    raise ValueError("question_text is required")
                if intent_id is None:
                    raise ValueError("intent_id is required")

                cursor.execute(
                    sql,
                    (
                        project_interview_id,
                        int(question_order),
                        question_text,
                        question_type,
                        research_phase,
                        intent_id,
                        meta,
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


def delete_question_and_notes(
    project_interview_id: int,
    question_id: int,
) -> dict | None:
    """
    删除指定访谈下的一条题目及其对应 Notes。

    删除顺序：
        1) bh_project_fewshot_sample
        2) bh_project_interview_notes
        3) bh_project_question

    返回：
        - 删除成功：{"question_deleted": True, "notes_deleted": <int>}
        - 题目不存在：None
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM bh_project_fewshot_sample
                WHERE project_interview_id = %s AND question_id = %s
                """,
                (project_interview_id, question_id),
            )
            fewshot_deleted = cursor.rowcount

            cursor.execute(
                """
                DELETE FROM bh_project_interview_notes
                WHERE project_interview_id = %s AND question_id = %s
                """,
                (project_interview_id, question_id),
            )
            notes_deleted = cursor.rowcount

            cursor.execute(
                """
                DELETE FROM bh_project_question
                WHERE id = %s AND project_interview_id = %s
                """,
                (question_id, project_interview_id),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return None
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "question_deleted": True,
        "fewshot_deleted": fewshot_deleted,
        "notes_deleted": notes_deleted,
    }


def fetch_question_by_id(project_interview_id: int, question_id: int) -> dict | None:
    """
    根据访谈 ID 和题目 ID 查询单条题目。
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
          AND id = %s
        LIMIT 1
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (project_interview_id, question_id))
            row = cursor.fetchone()
    finally:
        conn.close()
    return row


def insert_fewshot_sample(
    project_id: int,
    project_interview_id: int,
    question_id: int,
    intent_id: int,
    sample_json: dict | list | str,
    quality_score: int = 95,
    source_kind: str = "seed",
    notes_result_id: Optional[int] = None,
) -> int:
    """
    插入一条 few-shot 冷启动样本。
    """
    if isinstance(sample_json, (dict, list)):
        sample_json_str = json.dumps(sample_json, ensure_ascii=False)
    else:
        sample_json_str = str(sample_json)

    sql = """
        INSERT INTO bh_project_fewshot_sample
            (project_id, project_interview_id, question_id, intent_id, notes_result_id,
             sample_json, quality_score, source_kind, created_time)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    project_id,
                    project_interview_id,
                    question_id,
                    intent_id,
                    notes_result_id,
                    sample_json_str,
                    quality_score,
                    source_kind,
                ),
            )
            new_id = cursor.lastrowid
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return new_id


def fetch_fewshot_sample_by_id(project_interview_id: int, sample_id: int) -> dict | None:
    """
    根据访谈 ID 和 sample ID 查询单条 few-shot 样本。
    """
    sql = """
        SELECT
            id,
            project_id,
            project_interview_id,
            question_id,
            intent_id,
            notes_result_id,
            sample_json,
            quality_score,
            source_kind,
            created_time
        FROM bh_project_fewshot_sample
        WHERE project_interview_id = %s
          AND id = %s
        LIMIT 1
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (project_interview_id, sample_id))
            row = cursor.fetchone()
    finally:
        conn.close()
    return row


def fetch_fewshot_samples_by_interview(project_interview_id: int) -> list[dict]:
    """
    根据访谈 ID 查询该访谈下所有 few-shot 样本。
    """
    sql = """
        SELECT
            s.id,
            s.project_id,
            s.project_interview_id,
            s.question_id,
            s.intent_id,
            s.notes_result_id,
            s.sample_json,
            s.quality_score,
            s.source_kind,
            s.created_time,
            q.question_order,
            q.question_text,
            q.question_type,
            q.research_phase
        FROM bh_project_fewshot_sample s
        LEFT JOIN bh_project_question q
          ON q.id = s.question_id
         AND q.project_interview_id = s.project_interview_id
        WHERE s.project_interview_id = %s
        ORDER BY q.question_order ASC, s.quality_score DESC, s.created_time DESC, s.id DESC
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (project_interview_id,))
            rows: list[dict] = cursor.fetchall()
    finally:
        conn.close()
    return rows


def delete_fewshot_sample(
    project_interview_id: int,
    sample_id: int,
) -> dict | None:
    """
    删除指定访谈下的一条 few-shot 样本。
    """
    row = fetch_fewshot_sample_by_id(project_interview_id, sample_id)
    if not row:
        return None

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM bh_project_fewshot_sample
                WHERE id = %s AND project_interview_id = %s
                """,
                (sample_id, project_interview_id),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return None
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return row


def fetch_interviews_by_project(
    parse_project_id: int,
    created_by_user_id: int | None = None,
) -> list[dict]:
    """
    根据项目 ID 查询该项目下的所有访谈记录。

    参数:
        parse_project_id: 项目 ID，对应 bh_project_interview.parse_project_id。

    返回:
        访谈记录字典列表，字段至少包括:
            - id
            - parse_project_id
            - name
            - interview_date
            - file_name
        - hospital_city
        - hospital_decile
        - doctor_level
        - core_problem
        - file_path
    """
    sql = """
        SELECT
            i.id,
            i.parse_project_id,
            i.name,
            i.interview_date,
            i.file_name,
            d.detail_json,
            COALESCE(d.city, i.hospital_city) AS city,
            COALESCE(d.city, i.hospital_city) AS hospital_city,
            COALESCE(d.hospital_decile, i.hospital_decile) AS hospital_decile,
            COALESCE(d.doctor_level, i.doctor_level) AS doctor_level,
            d.doctor_title,
            d.hospital,
            d.department,
            i.core_problem,
            i.questionnaire_id,
            q.name AS questionnaire_name,
            q.status AS questionnaire_status,
            q.object_type AS questionnaire_object_type,
            q.role_id AS questionnaire_role_id,
            r.role_name AS questionnaire_role_name,
            r.role_type AS questionnaire_role_type,
            r.detail_schema_json AS questionnaire_role_detail_schema_json,
            i.key_bq_id,
            k.name AS key_bq_name,
            i.status
        FROM bh_project_interview i
        INNER JOIN bh_project p ON p.id = i.parse_project_id
        LEFT JOIN bh_interview_detail d ON d.interview_id = i.id
        LEFT JOIN bh_project_questionnaire q ON q.id = i.questionnaire_id
        LEFT JOIN bh_project_role r ON r.id = q.role_id
        LEFT JOIN bh_project_key_bq k ON k.id = i.key_bq_id
        WHERE i.parse_project_id = %s
          AND (%s IS NULL OR p.created_by_user_id = %s)
        ORDER BY i.id DESC
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (parse_project_id, created_by_user_id, created_by_user_id))
            rows: list[dict] = cursor.fetchall()
    finally:
        conn.close()
    return rows


def fetch_completed_interviews_for_project(
    project_id: int,
    interview_ids: list[int] | None = None,
) -> list[dict]:
    """
    查询项目下状态为 2 的已完成访谈。

    参数:
        project_id: 项目 ID，对应 bh_project.id。
        interview_ids: 可选访谈 ID 子集；若传入，则仅返回这些访谈中已完成的记录。

    返回:
        已完成访谈列表，按 id ASC 排序。
    """
    params: list[Any] = [project_id]
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
            d.detail_json,
            COALESCE(d.city, i.hospital_city) AS city,
            COALESCE(d.city, i.hospital_city) AS hospital_city,
            COALESCE(d.hospital_decile, i.hospital_decile) AS hospital_decile,
            COALESCE(d.doctor_level, i.doctor_level) AS doctor_level,
            d.doctor_title,
            d.hospital,
            d.department,
            i.core_problem,
            i.questionnaire_id,
            q.name AS questionnaire_name,
            q.status AS questionnaire_status,
            q.object_type AS questionnaire_object_type,
            q.role_id AS questionnaire_role_id,
            r.role_name AS questionnaire_role_name,
            r.role_type AS questionnaire_role_type,
            r.detail_schema_json AS questionnaire_role_detail_schema_json,
            i.key_bq_id,
            k.name AS key_bq_name,
            i.status
        FROM bh_project_interview i
        LEFT JOIN bh_interview_detail d ON d.interview_id = i.id
        LEFT JOIN bh_project_questionnaire q ON q.id = i.questionnaire_id
        LEFT JOIN bh_project_role r ON r.id = q.role_id
        LEFT JOIN bh_project_key_bq k ON k.id = i.key_bq_id
        WHERE i.parse_project_id = %s
          AND i.status = 2
          {extra_filter}
        ORDER BY i.id ASC
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            rows: list[dict] = cursor.fetchall()
    finally:
        conn.close()
    return rows


def fetch_interview_summary(project_interview_id: int) -> list[dict]:
    """
    根据访谈 ID 查询 bh_project_interview_summary 中的原文明细。

    参数:
        project_interview_id: 访谈 ID，对应 bh_project_interview_summary.project_interview_id。

    返回:
        明细记录字典列表，字段至少包括:
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
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (project_interview_id,))
            rows: list[dict] = cursor.fetchall()
    finally:
        conn.close()
    return rows


def fetch_interview_summary_by_id(summary_id: int, project_interview_id: int) -> dict | None:
    """
    根据 summary ID 查询单条 summary 记录。

    参数:
        summary_id: summary 主键 ID。
        project_interview_id: 访谈 ID。

    返回:
        匹配时返回单条记录字典，否则返回 None。
    """
    sql = """
        SELECT
            id,
            project_interview_id,
            timestamp,
            speaker,
            text
        FROM bh_project_interview_summary
        WHERE id = %s AND project_interview_id = %s
        LIMIT 1
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (summary_id, project_interview_id))
            row = cursor.fetchone()
    finally:
        conn.close()
    return row


def update_interview_summary_text_with_corrections(
    summary_id: int,
    project_interview_id: int,
    text: str,
    corrections: list[dict] | None,
) -> tuple[dict | None, int]:
    """
    更新某条 summary 的文本，并在同一事务内写入纠错学习记录。

    参数:
        summary_id: summary 主键 ID。
        project_interview_id: 访谈 ID。
        text: 新的 summary 文本。
        corrections: 需要写入 bh_transcription_corrections 的记录列表。

    返回:
        (更新后的 summary 记录, 实际插入的 correction 条数)
    """
    conn = get_connection()
    inserted = 0
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    project_interview_id,
                    timestamp,
                    speaker,
                    text
                FROM bh_project_interview_summary
                WHERE id = %s AND project_interview_id = %s
                LIMIT 1
                """,
                (summary_id, project_interview_id),
            )
            existing = cursor.fetchone()
            if not existing:
                conn.rollback()
                return None, 0

            cursor.execute(
                """
                UPDATE bh_project_interview_summary
                SET text = %s
                WHERE id = %s AND project_interview_id = %s
                """,
                (text, summary_id, project_interview_id),
            )

            if corrections:
                insert_sql = """
                    INSERT INTO bh_transcription_corrections
                        (
                            project_id,
                            project_interview_id,
                            summary_id,
                            wrong_text,
                            correct_text,
                            context_before,
                            context_after,
                            edit_type,
                            confidence,
                            usage_count,
                            status,
                            created_by
                        )
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                for item in corrections:
                    cursor.execute(
                        insert_sql,
                        (
                            item.get("project_id"),
                            item.get("project_interview_id"),
                            item.get("summary_id"),
                            item.get("wrong_text"),
                            item.get("correct_text"),
                            item.get("context_before"),
                            item.get("context_after"),
                            item.get("edit_type"),
                            item.get("confidence"),
                            int(item.get("usage_count") or 0),
                            item.get("status") or "pending",
                            item.get("created_by"),
                        ),
                    )
                    inserted += 1

            cursor.execute(
                """
                SELECT
                    id,
                    project_interview_id,
                    timestamp,
                    speaker,
                    text
                FROM bh_project_interview_summary
                WHERE id = %s AND project_interview_id = %s
                LIMIT 1
                """,
                (summary_id, project_interview_id),
            )
            row = cursor.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return row, inserted


def fetch_key_bq_rows_by_interview(interview_id: int) -> list[dict]:
    """
    根据访谈 ID 查询该访谈下所有 key BQ 明细。

    返回:
        明细记录字典列表，字段至少包括:
            - id
            - project_id
            - project_interview_id
            - bq_order
            - bq_text
            - dimension_json
            - note_json
            - status
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
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (interview_id,))
            rows: list[dict] = cursor.fetchall()
    finally:
        conn.close()
    return rows


def update_interview_summary_text(
    summary_id: int,
    project_interview_id: int,
    text: str,
) -> dict | None:
    """
    更新某条 summary 的文本内容，并返回更新后的记录。
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE bh_project_interview_summary
                SET text = %s
                WHERE id = %s AND project_interview_id = %s
                """,
                (text, summary_id, project_interview_id),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return None
            cursor.execute(
                """
                SELECT
                    id,
                    project_interview_id,
                    timestamp,
                    speaker,
                    text
                FROM bh_project_interview_summary
                WHERE id = %s AND project_interview_id = %s
                LIMIT 1
                """,
                (summary_id, project_interview_id),
            )
            row = cursor.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return row


def fetch_questions_by_interview(project_interview_id: int) -> list[dict]:
    """
    根据访谈 ID 查询该访谈下配置的题目。

    返回:
        题目记录字典列表，字段至少包括:
            - id
            - project_interview_id
            - question_order
            - question_text
            - question_type
            - research_phase
            - intent_id
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
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (project_interview_id,))
            rows: list[dict] = cursor.fetchall()
    finally:
        conn.close()
    return rows


def fetch_notes_rows_by_interview(interview_id: int) -> list[dict]:
    """
    根据访谈 ID 查询该访谈对应的 Notes 原始行。

    返回:
        原始联表结果字典列表，字段至少包括:
            - question_id
            - question_order
            - question_text
            - question_type
            - question_intent_id
            - research_phase
            - notes_id
            - notes_intent_id
            - note_json
            - confidence
            - status
    """
    sql = """
        SELECT
            q.id AS question_id,
            q.question_order,
            q.question_text,
            q.question_type,
            q.intent_id AS question_intent_id,
            q.research_phase,
            q.meta,
            n.id AS notes_id,
            n.intent_id AS notes_intent_id,
            n.note_json,
            n.confidence,
            n.status
        FROM bh_project_question q
        LEFT JOIN bh_project_interview_notes n
          ON n.project_interview_id = q.project_interview_id
         AND n.question_id = q.id
        WHERE q.project_interview_id = %s
        ORDER BY q.question_order ASC, q.id ASC, n.id ASC
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (interview_id,))
            rows: list[dict] = cursor.fetchall()
    finally:
        conn.close()
    return rows
