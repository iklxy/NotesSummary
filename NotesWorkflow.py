"@Date: 2026-04-24"
"@Author: lixinyang"


import json
import traceback
from typing import Any, Dict, List, Optional

from DbAccess import DbAccess
from Fewshot import select_fewshot_samples
from InterviewLogger import log_interview
from Model import ModelClient
from ProjectContext import load_project_context_by_id
from RagIndex import index_interview_summary, retrieve_segments_for_question


def fetch_questions_step(
    interview_id: int,
    source_kind: Optional[str] = None,
) -> Dict[str, Any]:
    """
    查询某个访谈下的题目列表，并返回统一的 step 结果结构。

    参数:
        interview_id: 访谈主键 ID。
        source_kind: 可选题目来源过滤，仅保留指定来源的题目，例如 "auto"。
    """
    try:
        rows = DbAccess.fetch_questions_for_interview(interview_id)
    except Exception as exc:
        return {"success": False, "questions": [], "message": f"fetch questions failed: {exc}"}

    if source_kind:
        normalized_source_kind = source_kind.strip().lower()
        rows = [
            row
            for row in rows
            if _get_question_source_kind(row) == normalized_source_kind
        ]

    if not rows:
        return {
            "success": False,
            "questions": [],
            "message": f"no questions found for interview {interview_id}",
        }
    return {"success": True, "questions": rows}


def _get_question_source_kind(row: Dict[str, Any]) -> str:
    """
    从题目记录的 meta 字段中读取来源类型。

    参数:
        row: 题目记录。

    返回:
        来源类型字符串，默认返回 "manual"。
    """
    raw_meta = row.get("meta")
    meta_obj: Any = raw_meta
    if isinstance(raw_meta, str):
        try:
            meta_obj = json.loads(raw_meta)
        except Exception:
            meta_obj = {}
    if isinstance(meta_obj, dict):
        source_kind = str(meta_obj.get("source_kind") or "").strip().lower()
        if source_kind:
            return source_kind
    return "manual"


def fetch_intent_names_step(intent_ids: List[int]) -> Dict[str, Any]:
    """
    读取意图 ID 到名称的映射，用于拼接更稳定的 RAG query。
    """
    try:
        intent_name_map = DbAccess.fetch_intent_name_map(intent_ids)
    except Exception as exc:
        return {"success": False, "intent_name_map": {}, "message": f"fetch intents failed: {exc}"}
    return {"success": True, "intent_name_map": intent_name_map}


def generate_notes_step(
    project_id: int,
    interview_id: int,
    questions: List[Dict[str, Any]],
    top_k: int = 10,
    project_context: Optional[str] = None,
    ensure_index: bool = True,
) -> Dict[str, Any]:
    """
    对一组题目执行 RAG 检索和 Notes 生成。

    该函数只负责生成内存结果，不负责写库。
    """
    if not questions:
        return {
            "success": False,
            "project_id": project_id,
            "interview_id": interview_id,
            "total_questions": 0,
            "results": [],
            "message": "no questions to generate notes for",
        }

    if not project_context:
        project_context = load_project_context_by_id(project_id)

    index_warning = None
    if ensure_index:
        try:
            log_interview("NOTES", interview_id, f"为访谈 {interview_id} 构建/更新向量索引")
            index_interview_summary(interview_id)
        except Exception as exc:
            index_warning = f"index summary failed: {exc}"
            log_interview("NOTES", interview_id, f"{index_warning}，将降级为不依赖向量索引继续生成 Notes")

    intent_ids = [int(row["intent_id"]) for row in questions if row.get("intent_id") is not None]
    intent_name_map: Dict[int, str] = {}
    if intent_ids:
        intent_result = fetch_intent_names_step(intent_ids)
        if intent_result.get("success"):
            intent_name_map = intent_result.get("intent_name_map") or {}
        else:
            log_interview("NOTES", interview_id, f"读取 intent 名称失败：{intent_result.get('message')}")

    model_client: Optional[ModelClient] = None
    model_client_error: Optional[str] = None
    try:
        model_client = ModelClient()
    except Exception as exc:
        model_client_error = f"init model client failed: {exc}"
        log_interview("NOTES", interview_id, f"{model_client_error}，将写入降级 Notes")

    results: List[Dict[str, Any]] = []
    log_interview("NOTES", interview_id, f"共 {len(questions)} 条题目，开始生成 Notes")

    for row in questions:
        question_id = row.get("id")
        question_text = row.get("question_text", "")
        question_type = row.get("question_type")
        intent_id = row.get("intent_id")
        intent_name = intent_name_map.get(intent_id) if intent_id is not None else None

        log_interview("NOTES", interview_id, f"开始为问题 {question_id} 生成 Notes")
        try:
            segments = retrieve_segments_for_question(
                interview_id=interview_id,
                question_text=question_text,
                top_k=top_k,
                question_type=question_type or None,
                intent_name=intent_name,
            )
            log_interview("NOTES", interview_id, f"问题 {question_id} 检索到 {len(segments)} 条相关片段")

            fewshot_samples = select_fewshot_samples(
                project_id=project_id,
                question_id=question_id,
                question_type=question_type or "",
                research_phase=row.get("research_phase"),
                intent_id=intent_id if intent_id is not None else 0,
                limit=2,
            )
            log_interview("NOTES", interview_id, f"问题 {question_id} 选出 few-shot 样本数量: {len(fewshot_samples)}")

            if model_client is None:
                notes = {
                    "summary": "Notes 生成失败",
                    "analysis": model_client_error or "model client not available",
                    "confidence": 0.0,
                    "error": model_client_error or "model client not available",
                }
            else:
                notes = model_client.generate_notes_for_question_with_fewshot(
                    question_text=question_text,
                    segments=segments,
                    intent_name=intent_name,
                    question_type=question_type,
                    fewshot_samples=fewshot_samples,
                    project_context=project_context,
                )
        except Exception as exc:
            results.append(
                {
                    "project_id": project_id,
                    "project_interview_id": interview_id,
                    "question_id": question_id,
                    "intent_id": intent_id,
                    "question_text": question_text,
                    "question_type": question_type,
                    "segments": [],
                    "fewshot_count": 0,
                    "fewshot_sample_ids": [],
                    "notes": {
                        "error": f"generate notes failed: {exc}",
                        "llm_raw_output": traceback.format_exc(),
                    },
                }
            )
            continue

        results.append(
            {
                "project_id": project_id,
                "project_interview_id": interview_id,
                "question_id": question_id,
                "intent_id": intent_id,
                "question_text": question_text,
                "question_type": question_type,
                "segments": segments,
                "fewshot_count": len(fewshot_samples),
                "fewshot_sample_ids": [sample.get("id") for sample in fewshot_samples],
                "notes": notes,
            }
        )

    return {
        "success": True,
        "project_id": project_id,
        "interview_id": interview_id,
        "total_questions": len(questions),
        "results": results,
        "warnings": [warning for warning in [index_warning, model_client_error] if warning],
    }


def write_notes_results_step(notes_block: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 Notes 生成结果写入数据库。
    """
    results = notes_block.get("results") or []
    if not results:
        return {"success": False, "inserted": 0, "errors": ["no notes results to write"]}

    inserted = 0
    errors: List[str] = []

    for item in results:
        project_id = item.get("project_id")
        interview_id = item.get("project_interview_id")
        question_id = item.get("question_id")
        intent_id = item.get("intent_id")
        notes = item.get("notes") or {}

        if not isinstance(notes, dict):
            errors.append(f"question_id={question_id}: notes is not dict")
            continue
        if project_id is None or interview_id is None or question_id is None or intent_id is None:
            errors.append(f"question_id={question_id}: missing ids for insert")
            continue

        note_json_str = json.dumps(notes, ensure_ascii=False)
        try:
            confidence = float(notes.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        status = 4 if "llm_raw_output" in notes else 0
        error_message = "llm_raw_output present; please inspect note_json" if status == 4 else None

        try:
            DbAccess.insert_notes_result(
                project_id=project_id,
                interview_id=interview_id,
                question_id=question_id,
                intent_id=intent_id,
                note_json_str=note_json_str,
                confidence=confidence,
                status=status,
                error_message=error_message,
            )
            inserted += 1
        except Exception as exc:
            errors.append(f"question_id={question_id}: insert failed: {exc}")

    return {"success": True, "inserted": inserted, "errors": errors}


def run_notes_generation_for_interview(
    interview_id: int,
    question_id: Optional[int] = None,
    top_k: int = 10,
    source_kind: Optional[str] = None,
    ensure_index: bool = True,
) -> Dict[str, Any]:
    """
    对指定访谈执行 RAG + LLM Notes 生成并落库。
    """
    row = DbAccess.get_interview_by_id(interview_id)
    if not row:
        return {
            "success": False,
            "stage": "fetch_interview",
            "detail": {"message": f"interview {interview_id} not found"},
        }

    project_id = row.get("parse_project_id") or 0
    question_result = fetch_questions_step(interview_id, source_kind=source_kind)
    if not question_result.get("success"):
        return {
            "success": False,
            "stage": "fetch_questions",
            "detail": question_result,
            "project_id": project_id,
            "interview_id": interview_id,
            "total_questions": 0,
            "results": [],
        }

    questions: List[Dict[str, Any]] = question_result.get("questions") or []
    if question_id is not None:
        try:
            target_question_id = int(question_id)
        except (TypeError, ValueError):
            return {
                "success": False,
                "stage": "validate_question_id",
                "detail": {"message": f"invalid question_id: {question_id}"},
                "project_id": project_id,
                "interview_id": interview_id,
                "total_questions": 0,
                "results": [],
            }
        questions = [row for row in questions if int(row.get("id") or 0) == target_question_id]
        if not questions:
            return {
                "success": False,
                "stage": "filter_question",
                "detail": {"message": f"question {target_question_id} not found"},
                "project_id": project_id,
                "interview_id": interview_id,
                "total_questions": 0,
                "results": [],
            }

    notes_result = generate_notes_step(
        project_id=project_id,
        interview_id=interview_id,
        questions=questions,
        top_k=top_k,
        ensure_index=ensure_index,
    )
    if not notes_result.get("success"):
        return notes_result

    write_result = write_notes_results_step(notes_result)
    return {
        "success": True,
        "project_id": project_id,
        "interview_id": interview_id,
        "question_id": question_id,
        "total_questions": notes_result.get("total_questions", 0),
        "generated": len(notes_result.get("results") or []),
        "inserted": write_result.get("inserted", 0),
        "results": notes_result.get("results") or [],
        "warnings": [w for w in notes_result.get("warnings", []) if w]
        + [e for e in write_result.get("errors", []) if e],
    }
