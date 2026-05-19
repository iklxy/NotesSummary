"@Date: 2026-04-15"
"@Author: lixinyang"

import json
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
from pathlib import Path
import sys

from fastapi import Body, FastAPI, HTTPException

# `Api.py` 是根目录下的 engine 入口，但数据库模块实际放在 `summarynotes-be/` 目录。
# 启动引擎时把该目录加入 `sys.path`，避免 `from db import ...` 找不到模块。
ROOT_DIR = Path(__file__).resolve().parent
BE_DIR = ROOT_DIR / "summarynotes-be"
if str(BE_DIR) not in sys.path:
    sys.path.insert(0, str(BE_DIR))

from DbAccess import DbAccess
from InterviewLogger import log_interview, log_project
from KBQNotesWorkflow import run_kbq_notes_generation_for_interview
from CAWorkflow import generate_ca_table_for_project
from MinutesWorkflow import generate_minutes_for_interview
from NotesWorkflow import fetch_questions_step, run_notes_generation_for_interview
from RagIndex import index_interview_summary
from Workflow import run_workflow
from db import fetch_project_by_id


app = FastAPI()
TRANSCRIBE_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="transcribe")


def _load_interview_or_404(interview_id: int) -> Dict[str, Any]:
    """
    读取访谈记录；若不存在则直接抛出 404。

    参数:
        interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。

    返回:
        访谈记录字典，内容来自 `DbAccess.get_interview_by_id`。

    异常:
        HTTPException: 当访谈不存在时抛出 404。
    """
    interview = DbAccess.get_interview_by_id(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="interview not found")
    return interview


def _submit_transcribe_job(interview_id: int) -> Dict[str, Any]:
    """
    将转录工作流提交到后台线程池，并立即返回受理结果。

    参数:
        interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。

    返回:
        受理结果字典，包含：
            - success: 是否已成功提交到线程池。
            - queued: 是否已进入后台队列。
            - interview_id: 本次提交对应的访谈 ID。

    异常:
        HTTPException: 当线程池提交失败时抛出 500。
    """

    def _job() -> None:
        """
        在线程池中实际执行完整工作流，并在异常时回写失败状态。

        参数:
            无。闭包内部直接使用外层 `interview_id`。

        返回:
            无返回值。执行结果仅用于日志输出。
        """
        try:
            log_interview("TRANSCRIBE", interview_id, "job start")
            result = run_workflow(interview_id)
            log_interview("TRANSCRIBE", interview_id, f"job done: {json.dumps(result, ensure_ascii=False)}")
        except Exception as e:
            try:
                DbAccess.update_interview_status(interview_id, 3)
            except Exception:
                pass
            log_interview("TRANSCRIBE", interview_id, f"job failed: {e}\n{traceback.format_exc()}")

    try:
        TRANSCRIBE_EXECUTOR.submit(_job)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"submit transcribe job failed: {e}")

    return {
        "success": True,
        "queued": True,
        "interview_id": interview_id,
    }


def _load_interview_notes_rows(interview_id: int) -> List[Dict[str, Any]]:
    """
    查询某个访谈下题目与 Notes 的联表结果。

    参数:
        interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。

    返回:
        联表查询结果列表。每条记录同时包含题目信息与对应 Notes 信息；
        若某题尚未生成 Notes，则 Notes 相关字段可能为 `None`。

    异常:
        HTTPException: 当数据库查询失败时抛出 500。
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
    conn = DbAccess.get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (interview_id,))
            rows: List[Dict[str, Any]] = cursor.fetchall()
            return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"query notes failed: {e}")
    finally:
        conn.close()


def _parse_note_json(note_json_raw: Any) -> Any:
    """
    将数据库中的 `note_json` 字段尽量解析为 Python 对象。

    参数:
        note_json_raw: 数据库原始返回值。可能是 JSON 字符串，也可能已经是字典、
            列表，或其他基础类型。

    返回:
        若输入是合法 JSON 字符串，则返回反序列化后的 Python 对象；
        若解析失败，则原样返回输入字符串或原始对象。
    """
    if isinstance(note_json_raw, str):
        try:
            return json.loads(note_json_raw)
        except Exception:
            return note_json_raw
    return note_json_raw


def _build_interview_notes_response(
    interview_id: int,
    project_id: Optional[int],
    rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    将题目与 Notes 的联表结果整理成 API 对外返回结构。

    参数:
        interview_id: 访谈主键 ID，用于回填响应中的 `interview_id`。
        project_id: 所属项目 ID，通常来自访谈记录中的 `parse_project_id`。
        rows: 数据库联表结果列表，来自 `_load_interview_notes_rows`。

    返回:
        标准化后的响应字典，结构包含：
            - interview_id
            - project_id
            - questions: 按题目聚合后的列表，每题下挂载对应 Notes 列表。
    """
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
        if notes_id is None:
            continue

        questions_map[question_id]["notes"].append(
            {
                "notes_id": notes_id,
                "intent_id": row.get("notes_intent_id"),
                "note_json": _parse_note_json(row.get("note_json")),
                "confidence": row.get("confidence"),
                "status": row.get("status"),
            }
        )

    questions_list = sorted(
        questions_map.values(),
        key=lambda item: (item["question_order"], item["question_id"]),
    )
    return {
        "interview_id": interview_id,
        "project_id": project_id,
        "questions": questions_list,
    }


def _extract_key_bq_items(core_problem: Any) -> List[Dict[str, Any]]:
    """
    从访谈 core_problem 中提取 key BQ 明细。

    参数:
        core_problem: 访谈记录里的 `core_problem` 字段，通常是 JSON 字符串。

    返回:
        可直接写入 `bh_project_interview_key_bq` 的 key BQ 明细列表。
    """
    def _normalize_dimensions(raw_dimensions: Any) -> List[Dict[str, Any]]:
        if not isinstance(raw_dimensions, list):
            return []
        normalized: List[Dict[str, Any]] = []
        for item in raw_dimensions:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                dimension: Dict[str, Any] = {"name": name}
                description = str(item.get("description") or "").strip()
                if description:
                    dimension["description"] = description
                normalized.append(dimension)
            else:
                text = str(item or "").strip()
                if text:
                    normalized.append({"name": text})
        return normalized

    def _normalize_dimension_bundle(raw_value: Any) -> Dict[str, List[Dict[str, Any]]]:
        if not isinstance(raw_value, dict):
            return {"user_demension": [], "llm_demension": [], "demension": []}

        user_demension = _normalize_dimensions(
            raw_value.get("user_demension")
            if raw_value.get("user_demension") is not None
            else raw_value.get("user_dimensions")
        )
        llm_demension = _normalize_dimensions(
            raw_value.get("llm_demension")
            if raw_value.get("llm_demension") is not None
            else raw_value.get("llm_dimensions")
            if raw_value.get("llm_dimensions") is not None
            else raw_value.get("supplemental_dimensions")
        )
        demension = _normalize_dimensions(
            raw_value.get("demension") if raw_value.get("demension") is not None else raw_value.get("dimensions")
        )
        if not demension:
            demension = list(user_demension) + [item for item in llm_demension if item not in user_demension]

        return {
            "user_demension": user_demension,
            "llm_demension": llm_demension,
            "demension": demension,
        }

    if core_problem is None:
        return []
    obj: Any = core_problem
    if isinstance(core_problem, str):
        try:
            obj = json.loads(core_problem)
        except Exception:
            return []
    if not isinstance(obj, dict):
        return []
    items = obj.get("key_bq_list") or []
    result: List[Dict[str, Any]] = []
    for idx, item in enumerate(items, start=1):
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            order = item.get("order") or idx
            dimension_bundle = _normalize_dimension_bundle(item)
        else:
            text = str(item or "").strip()
            order = idx
            dimension_bundle = {"user_demension": [], "llm_demension": [], "demension": []}
        if not text:
            continue
        dimension_json = dimension_bundle if any(dimension_bundle.values()) else None
        result.append(
            {
                "order": int(order),
                "text": text,
                "dimension_json": dimension_json,
                "status": "pending",
            }
        )
    return result


# ----------------------------------------------------------------------
# 转录与工作流路由
# ----------------------------------------------------------------------
@app.post("/internal/interviews/{interview_id}/transcribe")
@app.post("/internal/interviews/{interview_id}/run-workflow")
def api_run_workflow(interview_id: int) -> Dict[str, Any]:
    """
    异步触发指定访谈的“转录 -> 纠错 -> summary”工作流。

    参数:
        interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。

    返回:
        后台任务受理结果，表示任务已提交到线程池，而不是工作流已完成。
    """
    return _submit_transcribe_job(interview_id)


# ----------------------------------------------------------------------
# Notes 与题目路由
# ----------------------------------------------------------------------
@app.post("/internal/interviews/{interview_id}/generate-notes")
def api_generate_notes(
    interview_id: int,
    question_id: int | None = None,
    source_kind: str | None = None,
) -> Dict[str, Any]:
    """
    为指定访谈生成 Notes；可选择只生成单题，也可生成全部题目。

    参数:
        interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。
        question_id: 可选题目 ID。传入时只处理该题；为空时处理该访谈下所有题目。

    返回:
        Notes 工作流执行结果，内容由 `run_notes_generation_for_interview` 返回。

    异常:
        HTTPException: 当 Notes 工作流执行失败时抛出 500。
    """
    log_interview(
        "NOTES",
        interview_id,
        f"internal generate-notes start question_id={question_id} source_kind={source_kind}",
    )
    try:
        result = run_notes_generation_for_interview(
            interview_id,
            question_id=question_id,
            source_kind=source_kind,
        )
        if isinstance(result, dict):
            if result.get("success"):
                log_interview(
                    "NOTES",
                    interview_id,
                    f"internal generate-notes done generated={result.get('generated')} inserted={result.get('inserted')} warnings={result.get('warnings')}",
                )
            else:
                log_interview(
                    "NOTES",
                    interview_id,
                    f"internal generate-notes failed stage={result.get('stage')} detail={result.get('detail')}",
                )
        return result
    except Exception as e:
        log_interview("NOTES", interview_id, f"internal generate-notes exception error={e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"generate notes failed: {e}")


@app.post("/internal/interviews/{interview_id}/generate-minutes")
def api_generate_minutes(interview_id: int) -> Dict[str, Any]:
    """
    直接生成并落库指定访谈的智能纪要。

    参数:
        interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。

    返回:
        智能纪要工作流执行结果，包含文本长度、兼容章节数与写库信息。

    异常:
        HTTPException: 当纪要工作流执行失败时抛出 500。
    """
    log_interview("MINUTES", interview_id, "internal generate-minutes start direct_text_generation")
    try:
        interview = _load_interview_or_404(interview_id)
        project_id = int(interview.get("parse_project_id") or 0)
        project_context = None
        if project_id > 0:
            try:
                from ProjectContext import load_project_context_by_id

                project_context = load_project_context_by_id(project_id)
            except Exception:
                project_context = None
        result = generate_minutes_for_interview(
            interview_id,
            project_context=project_context,
        )
        if isinstance(result, dict):
            if result.get("success"):
                log_interview(
                    "MINUTES",
                    interview_id,
                    f"internal generate-minutes done minutes_chars={result.get('minutes_chars')} inserted={result.get('inserted')}",
                )
            else:
                log_interview(
                    "MINUTES",
                    interview_id,
                    f"internal generate-minutes failed stage={result.get('stage')} detail={result.get('detail')}",
                )
        return result
    except Exception as e:
        log_interview("MINUTES", interview_id, f"internal generate-minutes exception error={e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"generate minutes failed: {e}")


@app.post("/internal/projects/{project_id}/generate-ca-table")
def api_generate_ca_table(
    project_id: int,
    payload: Dict[str, Any] | None = Body(default=None),
) -> Dict[str, Any]:
    """
    生成指定项目的 CA 表。

    参数:
        project_id: 项目主键 ID。
        payload: 可选请求体，支持 interview_ids 与 column_meta_fields。
    """
    body = payload or {}
    interview_ids = body.get("interview_ids") or []
    column_meta_fields = body.get("column_meta_fields") or []
    log_project(
        "CA",
        project_id,
        "CA table generation start "
        f"interview_ids={interview_ids} "
        f"column_meta_fields={column_meta_fields}",
    )
    try:
        result = generate_ca_table_for_project(
            project_id=project_id,
            interview_ids=[int(item) for item in interview_ids if item is not None],
            column_meta_fields=[str(item) for item in column_meta_fields if str(item).strip()],
        )
        if isinstance(result, dict):
            if result.get("success"):
                log_project(
                    "CA",
                    project_id,
                    "CA table generation done "
                    f"interview_count={result.get('interview_count')} "
                    f"dimension_count={result.get('dimension_count')} "
                    f"skipped_interview_ids={result.get('skipped_interview_ids')}",
                )
            else:
                log_project(
                    "CA",
                    project_id,
                    "CA table generation returned failure "
                    f"stage={result.get('stage')} "
                    f"detail={result.get('detail')}",
                )
        return result
    except Exception as e:
        log_project(
            "CA",
            project_id,
            "CA table generation exception "
            f"error={e}\n{traceback.format_exc()}",
        )
        raise HTTPException(status_code=500, detail=f"generate ca table failed: {e}")


@app.post("/internal/interviews/{interview_id}/refresh-kbq-notes")
def api_refresh_kbq_notes(interview_id: int) -> Dict[str, Any]:
    """
    重新从访谈所属项目当前 KBQ 回填 key BQ，并立即重建 KBQ Notes。

    参数:
        interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。

    返回:
        KBQ 刷新结果，包含回填条数、生成条数以及 warnings。
    """
    log_interview("KBQ", interview_id, "internal refresh-kbq-notes start")
    interview = _load_interview_or_404(interview_id)
    project_id = int(interview.get("parse_project_id") or 0)
    project = fetch_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")

    project_key_bq_json = project.get("key_bq_json")
    key_bq_items = _extract_key_bq_items(project_key_bq_json)
    if not key_bq_items:
        raise HTTPException(status_code=400, detail="no key BQ found in current project key bq")

    try:
        written = DbAccess.replace_key_bq_rows_for_interview(
            project_id=project_id,
            interview_id=interview_id,
            key_bq_items=key_bq_items,
        )
    except Exception as e:
        log_interview("KBQ", interview_id, f"internal refresh-kbq-notes replace_key_bq failed error={e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"refresh key bq failed: {e}")

    try:
        kbq_result = run_kbq_notes_generation_for_interview(interview_id)
    except Exception as e:
        log_interview("KBQ", interview_id, f"internal refresh-kbq-notes generate failed error={e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"refresh kbq notes failed: {e}")

    if not isinstance(kbq_result, dict):
        kbq_result = {"success": False, "message": "invalid kbq result"}
    kbq_result["key_bq_inserted"] = written
    kbq_result["refreshed_from_core_problem"] = False
    kbq_result["refreshed_from_project_key_bq"] = True
    if kbq_result.get("success"):
        log_interview(
            "KBQ",
            interview_id,
            f"internal refresh-kbq-notes done key_bq_inserted={written} generated={kbq_result.get('generated')} inserted={kbq_result.get('inserted')}",
        )
    else:
        log_interview(
            "KBQ",
            interview_id,
            f"internal refresh-kbq-notes failed stage={kbq_result.get('stage')} detail={kbq_result.get('detail')}",
        )
    return kbq_result


@app.get("/internal/interviews/{interview_id}/notes")
def api_get_interview_notes(interview_id: int) -> Dict[str, Any]:
    """
    按题目维度返回某个访谈下已经生成的 Notes 结果。

    参数:
        interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。

    返回:
        一个按题目聚合后的响应字典。每道题下包含：
            - question_id
            - question_order
            - question_text
            - question_type
            - intent_id
            - research_phase
            - notes: 该题对应的 Notes 列表
    """
    interview = _load_interview_or_404(interview_id)
    rows = _load_interview_notes_rows(interview_id)
    return _build_interview_notes_response(
        interview_id=interview_id,
        project_id=interview.get("parse_project_id"),
        rows=rows,
    )


@app.get("/internal/interviews/{interview_id}/questions")
def api_get_interview_questions(interview_id: int) -> Dict[str, Any]:
    """
    获取某个访谈下配置的题目列表。

    参数:
        interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。

    返回:
        包含 `interview_id` 与 `questions` 列表的响应字典。

    异常:
        HTTPException: 当访谈下没有题目或题目查询失败时抛出 404。
    """
    result = fetch_questions_step(interview_id)
    if not result.get("success"):
        message = result.get("message") or "questions not found"
        raise HTTPException(status_code=404, detail=message)

    return {
        "interview_id": interview_id,
        "questions": result.get("questions") or [],
    }


# ----------------------------------------------------------------------
# RAG 索引路由
# ----------------------------------------------------------------------
@app.post("/internal/interviews/{interview_id}/reindex-rag")
def api_reindex_rag(interview_id: int) -> Dict[str, Any]:
    """
    重新为指定访谈构建 RAG 向量索引。

    参数:
        interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。

    返回:
        重建结果字典，包含：
            - success: 是否执行成功。
            - interview_id: 访谈 ID。
            - indexed: 实际写入或更新的向量数量。

    异常:
        HTTPException: 当访谈不存在时抛出 404；当重建失败时抛出 500。
    """
    _load_interview_or_404(interview_id)

    try:
        indexed = index_interview_summary(interview_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"reindex rag failed: {e}")

    return {
        "success": True,
        "interview_id": interview_id,
        "indexed": indexed,
    }
