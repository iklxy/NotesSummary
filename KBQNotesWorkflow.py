from __future__ import annotations

import json
import traceback
from typing import Any, Dict, List, Optional

from DbAccess import DbAccess
from Model import ModelClient
from ProjectContext import load_project_context_by_id
from RagIndex import index_interview_summary, retrieve_segments_for_question


def fetch_kbq_items_step(interview_id: int) -> Dict[str, Any]:
    """
    查询指定访谈下的 key BQ 明细。

    参数:
        interview_id: 访谈主键 ID。

    返回:
        标准化 step 结构，包含 success、kbq_items 和 message。
    """
    try:
        rows = DbAccess.fetch_key_bq_rows_by_interview(interview_id)
    except Exception as exc:
        return {"success": False, "kbq_items": [], "message": f"fetch key bq failed: {exc}"}

    if not rows:
        return {
            "success": False,
            "kbq_items": [],
            "message": f"no key bq found for interview {interview_id}",
        }
    return {"success": True, "kbq_items": rows}


def _build_kbq_query_text(key_bq_text: str, dimensions: List[Dict[str, Any]]) -> str:
    """
    根据 key BQ 和抽取维度构造检索 query。

    参数:
        key_bq_text: 单条 key BQ 原文。
        dimensions: 第一步抽取出的维度列表。

    返回:
        用于向量检索的组合文本。
    """
    dimension_lines: List[str] = []
    for item in dimensions:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        description = str(item.get("description") or "").strip()
        if not name:
            continue
        dimension_lines.append(f"{name} {description}".strip())
    if dimension_lines:
        return f"{key_bq_text}\n" + "\n".join(dimension_lines)
    return key_bq_text


def _get_kbq_status(payload: Dict[str, Any]) -> str:
    """
    根据 KBQ 生成结果判断写库状态。

    参数:
        payload: 维度或最终 KBQ Notes 结果。

    返回:
        done / failed。
    """
    if "llm_raw_output" in payload:
        return "failed"
    if "error" in payload:
        return "failed"
    return "done"


def generate_kbq_notes_step(
    project_id: int,
    interview_id: int,
    kbq_items: List[Dict[str, Any]],
    top_k: int = 10,
    project_context: Optional[str] = None,
    interview_context: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    对访谈 key BQ 执行“维度抽取 + 检索 + KBQ Notes 生成”。

    参数:
        project_id: 项目 ID。
        interview_id: 访谈 ID。
        kbq_items: 从数据库读取的 key BQ 明细列表。
        top_k: 每条 key BQ 的检索片段数量上限。
        project_context: 可选项目背景文本。
        interview_context: 可选访谈背景摘要。

    返回:
        结构化 step 结果，包含 results / warnings。
    """
    if not kbq_items:
        return {
            "success": False,
            "project_id": project_id,
            "interview_id": interview_id,
            "total_kbq": 0,
            "results": [],
            "message": "no key bq to generate notes for",
        }

    if not project_context:
        project_context = load_project_context_by_id(project_id)

    index_warning = None
    try:
        print(f"[KBQ] 为访谈 {interview_id} 构建/更新向量索引")
        index_interview_summary(interview_id)
    except Exception as exc:
        index_warning = f"index summary failed: {exc}"
        print(f"[KBQ] {index_warning}，将降级为不依赖向量索引继续生成 KBQ Notes")

    model_client: Optional[ModelClient] = None
    model_client_error: Optional[str] = None
    try:
        model_client = ModelClient()
    except Exception as exc:
        model_client_error = f"init model client failed: {exc}"
        print(f"[KBQ] {model_client_error}，将写入降级 KBQ Notes")

    results: List[Dict[str, Any]] = []
    print(f"[KBQ] 共 {len(kbq_items)} 条 key BQ，开始生成 KBQ Notes")

    for row in kbq_items:
        kbq_id = row.get("id")
        kbq_order = row.get("bq_order")
        key_bq_text = str(row.get("bq_text") or "").strip()
        if not key_bq_text:
            continue

        print(f"[KBQ] 开始为 key BQ {kbq_id} 生成 KBQ Notes")
        try:
            dimensions_result = (
                model_client.generate_kbq_dimensions(
                    key_bq_text=key_bq_text,
                    project_context=project_context,
                    interview_context=interview_context,
                )
                if model_client is not None
                else {"dimensions": [], "llm_raw_output": model_client_error or "model client not available"}
            )
            dimensions = dimensions_result.get("dimensions") or []
            query_text = _build_kbq_query_text(key_bq_text, dimensions)
            segments = retrieve_segments_for_question(
                interview_id=interview_id,
                question_text=query_text,
                top_k=top_k,
                question_type="OPEN",
                intent_name="KBQ",
            )
            print(f"[KBQ] key BQ {kbq_id} 检索到 {len(segments)} 条相关片段")

            if model_client is None:
                notes = {
                    "key_bq": key_bq_text,
                    "dimension_notes": [],
                    "confidence": 0.0,
                    "error": model_client_error or "model client not available",
                }
            else:
                notes = model_client.generate_kbq_notes(
                    key_bq_text=key_bq_text,
                    dimensions=dimensions,
                    segments=segments,
                    project_context=project_context,
                    interview_context=interview_context,
                )
        except Exception as exc:
            results.append(
                {
                    "project_id": project_id,
                    "project_interview_id": interview_id,
                    "kbq_id": kbq_id,
                    "kbq_order": kbq_order,
                    "kbq_text": key_bq_text,
                    "dimensions": dimensions_result if "dimensions_result" in locals() else {},
                    "segments": [],
                    "notes": {
                        "error": f"generate kbq notes failed: {exc}",
                        "llm_raw_output": traceback.format_exc(),
                    },
                }
            )
            continue

        results.append(
            {
                "project_id": project_id,
                "project_interview_id": interview_id,
                "kbq_id": kbq_id,
                "kbq_order": kbq_order,
                "kbq_text": key_bq_text,
                "dimensions": dimensions_result,
                "segments": segments,
                "notes": notes,
            }
        )

    return {
        "success": True,
        "project_id": project_id,
        "interview_id": interview_id,
        "total_kbq": len(results),
        "results": results,
        "warnings": [warning for warning in [index_warning, model_client_error] if warning],
    }


def write_kbq_notes_results_step(kbq_block: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 KBQ Notes 结果写入数据库。

    参数:
        kbq_block: `generate_kbq_notes_step` 的返回结果。

    返回:
        写库结果，包含 inserted / errors。
    """
    results = kbq_block.get("results") or []
    if not results:
        return {"success": False, "inserted": 0, "errors": ["no kbq results to write"]}

    inserted = 0
    errors: List[str] = []

    for item in results:
        project_id = item.get("project_id")
        interview_id = item.get("project_interview_id")
        kbq_order = item.get("kbq_order")
        kbq_text = item.get("kbq_text")
        dimensions = item.get("dimensions") or {}
        notes = item.get("notes") or {}

        if not isinstance(notes, dict):
            errors.append(f"kbq_order={kbq_order}: notes is not dict")
            continue
        if project_id is None or interview_id is None or kbq_order is None or not kbq_text:
            errors.append(f"kbq_order={kbq_order}: missing ids/text for insert")
            continue

        compact_dimensions = dimensions if isinstance(dimensions, dict) else {"dimensions": dimensions}
        if isinstance(compact_dimensions, dict):
            compact_dimensions = dict(compact_dimensions)
            compact_dimensions.pop("llm_raw_output", None)
        compact_notes = dict(notes)
        compact_notes.pop("llm_raw_output", None)

        dimension_json = json.dumps(compact_dimensions, ensure_ascii=False)
        note_json = json.dumps(compact_notes, ensure_ascii=False)
        status = _get_kbq_status(notes) if isinstance(notes, dict) else "failed"

        try:
            DbAccess.upsert_key_bq_rows_for_interview(
                project_id=project_id,
                interview_id=interview_id,
                key_bq_items=[
                    {
                        "order": kbq_order,
                        "text": kbq_text,
                        "dimension_json": dimension_json,
                        "note_json": note_json,
                        "status": status,
                    }
                ],
            )
            inserted += 1
        except Exception as exc:
            errors.append(f"kbq_order={kbq_order}: insert failed: {exc}")

    return {"success": True, "inserted": inserted, "errors": errors}


def run_kbq_notes_generation_for_interview(
    interview_id: int,
    project_context: Optional[str] = None,
    interview_context: Optional[Any] = None,
    top_k: int = 8,
) -> Dict[str, Any]:
    """
    为指定访谈生成 KBQ Notes 并落库。

    参数:
        interview_id: 访谈 ID。
        project_context: 可选项目背景文本。
        interview_context: 可选访谈背景摘要。
        top_k: 每条 key BQ 的检索片段数量上限。

    返回:
        KBQ Notes 生成与写库的聚合结果。
    """
    interview = DbAccess.get_interview_by_id(interview_id)
    if not interview:
        return {
            "success": False,
            "stage": "fetch_interview",
            "detail": {"message": f"interview {interview_id} not found"},
        }

    project_id = int(interview.get("parse_project_id") or 0)
    kbq_result = fetch_kbq_items_step(interview_id)
    if not kbq_result.get("success"):
        return {
            "success": False,
            "stage": "fetch_kbq",
            "detail": kbq_result,
            "project_id": project_id,
            "interview_id": interview_id,
            "total_kbq": 0,
            "results": [],
        }

    kbq_items: List[Dict[str, Any]] = kbq_result.get("kbq_items") or []
    notes_result = generate_kbq_notes_step(
        project_id=project_id,
        interview_id=interview_id,
        kbq_items=kbq_items,
        top_k=top_k,
        project_context=project_context,
        interview_context=interview_context,
    )
    if not notes_result.get("success"):
        return notes_result

    write_result = write_kbq_notes_results_step(notes_result)
    return {
        "success": True,
        "project_id": project_id,
        "interview_id": interview_id,
        "total_kbq": notes_result.get("total_kbq", 0),
        "generated": len(notes_result.get("results") or []),
        "inserted": write_result.get("inserted", 0),
        "results": notes_result.get("results") or [],
        "warnings": [w for w in notes_result.get("warnings", []) if w]
        + [e for e in write_result.get("errors", []) if e],
    }
