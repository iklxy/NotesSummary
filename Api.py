"@Date: 2026-04-15"
"@Author: lixinyang"

import json
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException

from DbAccess import DbAccess
from Workflow import run_workflow, step_fetch_questions


app = FastAPI()


@app.post("/internal/interviews/{interview_id}/run-workflow")
def api_run_workflow(interview_id: int) -> Dict[str, Any]:
    """
    对指定访谈 ID 执行完整的 Python 工作流。

    包含步骤：
        1) 本地音频上云（或直接生成预签名 URL）
        2) 云上音频转文字（ASR）
        3) 组装并写入 bh_project_interview.file_content
        4) LLM 清洗并写入 bh_project_interview_summary
        5) 读取题目列表并基于 RAG + few-shot 生成 Notes
        6) 将 Notes 结果写入 bh_project_interview_notes

    参数:
        interview_id: 访谈主键 ID，对应 bh_project_interview.id。

    返回:
        run_workflow 的完整结果字典，将被 FastAPI 自动序列化为 JSON。
    """
    try:
        result = run_workflow(interview_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"run_workflow failed: {e}")
    return result


@app.get("/internal/interviews/{interview_id}/notes")
def api_get_interview_notes(interview_id: int) -> Dict[str, Any]:
    """
    按题目维度获取某个访谈对应的 Notes 列表。

    参数:
        interview_id: 访谈主键 ID，对应 bh_project_interview.id。

    返回:
        {
            "interview_id": ...,
            "project_id": ...,
            "questions": [
                {
                    "question_id": ...,
                    "question_order": ...,
                    "question_text": "...",
                    "question_type": "...",
                    "intent_id": ...,
                    "research_phase": "...",
                    "notes": [
                        {
                            "notes_id": ...,
                            "intent_id": ...,
                            "note_json": {...},  # 已尝试反序列化为 JSON
                            "confidence": ...,
                            "status": ...,
                        },
                        ...
                    ],
                },
                ...
            ],
        }
    """
    interview = DbAccess.get_interview_by_id(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="interview not found")

    project_id = interview.get("parse_project_id")

    conn = DbAccess.get_connection()
    try:
        with conn.cursor() as cursor:
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
            cursor.execute(sql, (interview_id,))
            rows: List[Dict[str, Any]] = cursor.fetchall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"query notes failed: {e}")
    finally:
        conn.close()

    questions_map: Dict[int, Dict[str, Any]] = {}

    for row in rows:
        question_id = row["question_id"]
        if question_id not in questions_map:
            questions_map[question_id] = {
                "question_id": question_id,
                "question_order": row["question_order"],
                "question_text": row["question_text"],
                "question_type": row["question_type"],
                "intent_id": row["question_intent_id"],
                "research_phase": row.get("research_phase"),
                "notes": [],
            }

        notes_id = row.get("notes_id")
        if notes_id is not None:
            note_json_raw = row.get("note_json")
            if isinstance(note_json_raw, str):
                try:
                    note_parsed: Any = json.loads(note_json_raw)
                except Exception:
                    note_parsed = note_json_raw
            else:
                note_parsed = note_json_raw

            questions_map[question_id]["notes"].append(
                {
                    "notes_id": notes_id,
                    "intent_id": row.get("notes_intent_id"),
                    "note_json": note_parsed,
                    "confidence": row.get("confidence"),
                    "status": row.get("status"),
                }
            )

    questions_list = sorted(
        questions_map.values(),
        key=lambda x: (x["question_order"], x["question_id"]),
    )

    return {
        "interview_id": interview_id,
        "project_id": project_id,
        "questions": questions_list,
    }


@app.get("/internal/interviews/{interview_id}/questions")
def api_get_interview_questions(interview_id: int) -> Dict[str, Any]:
    """
    获取某个访谈下配置的题目列表。

    参数:
        interview_id: 访谈主键 ID，对应 bh_project_interview.id。

    返回:
        {
            "interview_id": ...,
            "questions": [
                {
                    "id": ...,
                    "project_interview_id": ...,
                    "question_order": ...,
                    "question_text": "...",
                    "question_type": "...",
                    "research_phase": "...",
                    "intent_id": ...,
                },
                ...
            ],
        }
    """
    result = step_fetch_questions(interview_id)
    if not result.get("success"):
        message = result.get("message") or "questions not found"
        raise HTTPException(status_code=404, detail=message)

    return {
        "interview_id": interview_id,
        "questions": result.get("questions") or [],
    }
