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


def insert_project(name: str, keywords: Optional[str], core_problem: Optional[str]) -> int:
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
        INSERT INTO bh_project (name, keywords, core_problem)
        VALUES (%s, %s, %s)
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (name, keywords, core_problem))
            new_id = cursor.lastrowid
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return new_id


def fetch_projects() -> list[dict]:
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
            core_problem
        FROM bh_project
        ORDER BY id DESC
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
) -> int:
    """
    插入一条访谈记录到 bh_project_interview 表。

    参数:
        parse_project_id: 项目 ID，对应 bh_project_interview.parse_project_id。
        name:             访谈名称，对应 bh_project_interview.name。
        interview_date:   访谈时间字符串（例如 '2026-04-15'），对应 bh_project_interview.interview_date。
        file_name:        音频文件名，对应 bh_project_interview.file_name。

    返回:
        新插入访谈记录的自增 ID。
    """
    sql = """
        INSERT INTO bh_project_interview (parse_project_id, name, interview_date, file_name, status)
        VALUES (%s, %s, %s, %s, %s)
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (parse_project_id, name, interview_date, file_name, 0))
            new_id = cursor.lastrowid
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return new_id


def fetch_interviews_by_project(parse_project_id: int) -> list[dict]:
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
    """
    sql = """
        SELECT
            id,
            parse_project_id,
            name,
            interview_date,
            file_name
        FROM bh_project_interview
        WHERE parse_project_id = %s
        ORDER BY id DESC
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (parse_project_id,))
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

