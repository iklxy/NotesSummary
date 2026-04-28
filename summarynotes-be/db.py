import json
import os
from typing import Optional

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
            status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
            (project_interview_id, question_order, question_text, question_type, research_phase, intent_id)
        VALUES (%s, %s, %s, %s, %s, %s)
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
