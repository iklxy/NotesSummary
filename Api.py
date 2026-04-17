"@Date: 2026-04-15"
"@Author: lixinyang"

import json
from typing import Any, Dict, List
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException

from DbAccess import DbAccess
from RagIndex import index_interview_summary
from Workflow import run_notes_generation_for_interview, run_workflow, step_fetch_questions


app = FastAPI()
TRANSCRIBE_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="transcribe")


def _submit_transcribe_job(interview_id: int) -> Dict[str, Any]:
    """
    将转录工作提交给线程池，立即返回受理结果。
    """

    def _job() -> None:
        try:
            result = run_workflow(interview_id)
            print(f"[TRANSCRIBE] interview_id={interview_id} finished: {json.dumps(result, ensure_ascii=False)}")
        except Exception as e:
            try:
                DbAccess.update_interview_status(interview_id, 3)
            except Exception:
                pass
            print(f"[TRANSCRIBE] interview_id={interview_id} unexpected error: {e}")

    try:
        TRANSCRIBE_EXECUTOR.submit(_job)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"submit transcribe job failed: {e}")
    return {
        "success": True,
        "queued": True,
        "interview_id": interview_id,
    }


@app.post("/internal/interviews/{interview_id}/transcribe")
@app.post("/internal/interviews/{interview_id}/run-workflow")
def api_run_workflow(interview_id: int) -> Dict[str, Any]:
    """
    对指定访谈 ID 执行“转录 -> 清洗 -> 写 summary”的工作流。

    包含步骤：
        1) 本地音频上云（或直接生成预签名 URL）
        2) 云上音频转文字（ASR）
        3) 组装并写入 bh_project_interview.file_content
        4) LLM 清洗并写入 bh_project_interview_summary
        5) 将访谈状态标记为“可分析”

    参数:
        interview_id: 访谈主键 ID，对应 bh_project_interview.id。

    返回:
        立即返回受理结果；真正的工作流在后台线程池中执行。
    """
    return _submit_transcribe_job(interview_id)


@app.post("/internal/interviews/{interview_id}/generate-notes")
def api_generate_notes(interview_id: int, question_id: int | None = None) -> Dict[str, Any]:
    """
    针对指定访谈，按题目生成 Notes 并写入数据库。

    参数:
        interview_id: 访谈主键 ID。
        question_id:   可选，只为单个题目生成 Notes；不传则为该访谈下全部题目生成。
    """
    try:
        result = run_notes_generation_for_interview(interview_id, question_id=question_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"generate notes failed: {e}")
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


@app.post("/internal/interviews/{interview_id}/reindex-rag")
def api_reindex_rag(interview_id: int) -> Dict[str, Any]:
    """
    重新构建指定访谈的 RAG 向量索引。
    """
    interview = DbAccess.get_interview_by_id(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="interview not found")

    try:
        indexed = index_interview_summary(interview_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"reindex rag failed: {e}")

    return {
        "success": True,
        "interview_id": interview_id,
        "indexed": indexed,
    }
