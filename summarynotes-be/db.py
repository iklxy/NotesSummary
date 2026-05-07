import json
import os
from typing import Any, Optional

import dotenv
import pymysql

dotenv.load_dotenv()


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
            cursor.execute(sql, (name, keywords, core_problem, created_by_user_id))
            new_id = cursor.lastrowid
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return new_id


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
            id,
            name,
            keywords,
            core_problem,
            created_by_user_id
        FROM bh_project
        WHERE (%s IS NULL OR created_by_user_id = %s)
        ORDER BY id DESC
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (created_by_user_id, created_by_user_id))
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
            id,
            name,
            keywords,
            core_problem,
            created_by_user_id
        FROM bh_project
        WHERE id = %s
          AND (%s IS NULL OR created_by_user_id = %s)
        LIMIT 1
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (project_id, created_by_user_id, created_by_user_id))
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


def insert_interview(
    parse_project_id: int,
    name: str,
    interview_date: Optional[str],
    file_name: str,
    hospital_city: Optional[str],
    hospital_decile: Optional[int],
    doctor_level: Optional[str],
    core_problem: Optional[str],
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
            status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            i.hospital_city,
            i.hospital_decile,
            i.doctor_level,
            i.core_problem,
            i.note_content,
            i.file_path,
            i.status
        FROM bh_project_interview i
        INNER JOIN bh_project p ON p.id = i.parse_project_id
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
            i.file_name
            , i.hospital_city
            , i.hospital_decile
            , i.doctor_level
            , i.core_problem
        FROM bh_project_interview i
        INNER JOIN bh_project p ON p.id = i.parse_project_id
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
