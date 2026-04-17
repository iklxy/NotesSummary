"@Date:2026-04-10"
"@author:lixinyang"

from typing import Any, Dict, Optional
import pymysql

from config import config

class DbAccess:
    @classmethod
    def get_connection(cls) -> pymysql.connections.Connection:
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
        host = config.DB_HOST
        port = config.DB_PORT
        user = config.DB_USER
        password = config.DB_PASSWORD
        db_name = config.DB_NAME

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

    @classmethod
    def get_interview_by_id(cls, interview_id: int) -> Optional[Dict[str, Any]]:
        """
        根据访谈 ID 查询 bh_project_interview 表中的单条记录。

        参数:
            interview_id: 访谈主键 ID，对应 bh_project_interview.id。

        返回:
            如果存在，返回一行记录的字典形式，字段至少包含:
                - id
                - parse_project_id
                - file_name
                - file_content
                - file_path
                - status
            如果不存在，返回 None。
        """
        sql = """
            SELECT
                id,
                parse_project_id,
                file_name,
                file_content,
                file_path,
                status
            FROM bh_project_interview
            WHERE id = %s
            LIMIT 1
        """
        conn = cls.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, (interview_id,))
                row = cursor.fetchone()
                return row
        finally:
            conn.close()

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
        在音频上传完成后，更新 bh_project_interview 中的文件相关字段。

        参数:
            interview_id: 访谈主键 ID，对应 bh_project_interview.id。
            object_key:   上传到 TOS 的对象 key，写入 file_path 字段。
            status:       访谈处理状态，例如 1 表示“已上传待 ASR”。
            file_id:      可选，写入 file_id 字段，可与 object_key 或 TOS 返回的 ID 对应。
            audio_url:    预留参数，当前实现未写入数据库。

        返回:
            无返回值，更新失败时会抛出数据库异常。
        """
        fields = ["file_path = %s", "status = %s"]
        params: list[Any] = [object_key, status]

        if file_id is not None:
            fields.append("file_id = %s")
            params.append(file_id)

        params.append(interview_id)

        sql = f"""
            UPDATE bh_project_interview
            SET {", ".join(fields)}
            WHERE id = %s
        """

        conn = cls.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @classmethod
    def update_interview_status(cls, interview_id: int, status: int) -> None:
        """
        仅更新访谈状态字段。
        """
        sql = """
            UPDATE bh_project_interview
            SET status = %s
            WHERE id = %s
        """

        conn = cls.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, (status, interview_id))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @classmethod
    def update_interview_file_content(
        cls,
        interview_id: int,
        file_content_json: str,
    ) -> None:
        """
        将转录后的 JSON 结果写入 bh_project_interview.file_content 字段。

        参数:
            interview_id:      访谈主键 ID，对应 bh_project_interview.id。
            file_content_json: 已经序列化好的 JSON 字符串。

        返回:
            无返回值，更新失败时会抛出数据库异常。
        """
        sql = """
            UPDATE bh_project_interview
            SET file_content = %s
            WHERE id = %s
        """

        conn = cls.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, (file_content_json, interview_id))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @classmethod
    def insert_summary_from_cleaned_speakers(
        cls,
        interview_id: int,
        speakers: list[dict],
    ) -> int:
        """
        将清洗后的 speakers 列表写入 bh_project_interview_summary 表。

        参数:
            interview_id: 访谈主键 ID，对应 bh_project_interview.id。
            speakers:     清洗后的说话轮次列表，每个元素至少包含:
                          - speaker_id: 说话人 ID
                          - speaker_content_clean: 清洗后的文本内容

        返回:
            实际插入的记录条数。
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
                        continue
                    cursor.execute(sql, (interview_id, "", speaker_id, clean_text, 0))
                    inserted += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        return inserted

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
        将单条 Notes 结果写入 bh_project_interview_notes 表。

        参数:
            project_id:    项目 ID，对应 bh_project.id。
            interview_id:  访谈 ID，对应 bh_project_interview.id。
            question_id:   题目 ID，对应 bh_project_question.id。
            intent_id:     意图 ID，对应 bh_question_intent.id。
            note_json_str: 已序列化的 Notes JSON 字符串。
            confidence:    模型置信度，0–1 之间的小数。
            status:        Notes 状态：0自动生成/1已通过/2已编辑/3已拒绝/4错误。
            error_message: 可选的错误说明。

        返回:
            新插入记录的自增 ID。
        """
        sql = """
            INSERT INTO bh_project_interview_notes
                (project_id, project_interview_id, question_id, intent_id,
                 note_json, confidence, status, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
                new_id = cursor.lastrowid
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        return new_id
