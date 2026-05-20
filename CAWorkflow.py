#!/usr/bin/env python3
"""
@Date: 2026-05-08
@Author: lixinyang

CA 表格生成工作流。

该模块负责：
1. 读取当前项目下已完成的访谈；
2. 为每个访谈组装全文 Notes Markdown；
3. 让模型生成跨访谈对比维度；
4. 基于本地全文 Notes 片段为每个小点填充对比单元格；
5. 将最终 CA JSON 落库并缓存到本地文件。
"""

from __future__ import annotations

import json
import re
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from DbAccess import DbAccess
from InterviewLogger import log_interview, log_project
from Model import ModelClient
from ModelCA import generate_ca_cells_for_question
from NotesMarkdownBuilder import build_interview_full_notes_markdown, build_project_full_notes_markdowns
from MinutesWorkflow import _score_segment, _tokenize_for_search
from ProjectContext import load_project_context_by_id
from QuestionTree import expand_questionnaire_document
from interview_detail_fields import INTERVIEW_DETAIL_FIELD_DEFINITIONS
from db import fetch_interviews_by_project as fetch_project_interviews


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_CA_JSON_NAME = "ca_table.json"
DEFAULT_CA_FULL_NOTES_NAME = "full_notes.md"
DEFAULT_COLUMN_META_FIELDS = [str(item["key"]) for item in INTERVIEW_DETAIL_FIELD_DEFINITIONS]


def log(message: str, project_id: int | None = None) -> None:
    """
    输出 CA 进度日志。

    参数:
        message: 日志内容。
        project_id: 可选项目 ID。
    """
    log_project("CA", project_id, message)


def _get_data_root() -> Path:
    """
    获取项目根目录下的 data 目录。
    """
    return ROOT_DIR / "data"


def _get_project_data_dir(project_id: int) -> Path:
    """
    获取项目级 data 目录。
    """
    return _get_data_root() / f"project_{project_id}"


def _get_interview_data_dir(project_id: int, interview_id: int) -> Path:
    """
    获取访谈级 data 目录。
    """
    return _get_project_data_dir(project_id) / f"interview_{interview_id}"


def _split_markdown_segments(markdown_text: str) -> List[Dict[str, Any]]:
    """
    将全文 Notes Markdown 切分为检索片段。

    参数:
        markdown_text: Markdown 文本。

    返回:
        片段列表。
    """
    text = markdown_text.strip()
    if not text:
        return []

    blocks = re.split(r"\n\s*\n+", text)
    segments: List[Dict[str, Any]] = []
    for index, block in enumerate(blocks, start=1):
        block_text = block.strip()
        if not block_text:
            continue
        segments.append(
            {
                "summary_id": index,
                "speaker": "notes",
                "text": block_text,
            }
        )
    return segments


def _retrieve_segments_from_markdown(
    segments: List[Dict[str, Any]],
    query_text: str,
    top_k: int,
) -> List[Dict[str, Any]]:
    """
    从全文 Notes 片段中检索最相关的内容。
    """
    ranked: List[Tuple[float, Dict[str, Any]]] = []
    for seg in segments:
        score = _score_segment(str(seg.get("text") or ""), query_text)
        if score <= 0:
            continue
        ranked.append((score, seg))

    ranked.sort(key=lambda item: (-item[0], int(item[1].get("summary_id") or 0)))
    selected = ranked[: max(1, top_k)]
    results: List[Dict[str, Any]] = []
    for score, seg in selected:
        results.append(
            {
                "summary_id": seg.get("summary_id"),
                "speaker": seg.get("speaker"),
                "text": seg.get("text"),
                "score": score,
            }
        )
    return results


def _normalize_meta_value(value: Any) -> Any:
    """
    归一化访谈元数据值。
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text if text else None
    return value


def _json_safe_value(value: Any) -> Any:
    """
    将任意值转换为可 JSON 序列化的安全值。

    参数:
        value: 任意 Python 对象。

    返回:
        可直接传给 json.dumps 的值。
    """
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe_value(item) for item in value]
    return value


def _build_project_full_notes_markdown(
    project_id: int,
    interview_ids: List[int],
) -> List[Dict[str, Any]]:
    """
    为项目下多个访谈组装全文 Notes Markdown。
    """
    backup_items = build_project_full_notes_markdowns(project_id, interview_ids)
    return backup_items


def _normalize_dimension_items(raw_dimensions: Any) -> List[Dict[str, Any]]:
    """
    规范化 CA 维度结构。
    """
    if not isinstance(raw_dimensions, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for index, item in enumerate(raw_dimensions, start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        summary = str(item.get("summary") or "").strip()
        raw_sub_points = item.get("sub_points") or item.get("items") or item.get("points") or []
        sub_points: List[Dict[str, Any]] = []
        if isinstance(raw_sub_points, list):
            for sub_index, sub in enumerate(raw_sub_points, start=1):
                if not isinstance(sub, dict):
                    continue
                sub_title = str(sub.get("title") or sub.get("name") or "").strip()
                sub_summary = str(sub.get("summary") or "").strip()
                if not sub_title and not sub_summary:
                    continue
                sub_points.append(
                    {
                        "order": int(sub.get("order") or sub_index),
                        "title": sub_title,
                        "summary": sub_summary,
                        "cells": {},
                    }
                )
        if not title:
            continue
        normalized.append(
            {
                "order": int(item.get("order") or index),
                "title": title,
                "summary": summary,
                "sub_points": sub_points,
            }
        )
    return normalized


def _build_ca_cache_path(project_id: int, questionnaire_id: int | None = None) -> Path:
    """
    获取 CA 表的本地缓存路径。
    """
    project_dir = _get_project_data_dir(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)
    if questionnaire_id is not None:
        ca_dir = project_dir / "ca"
        ca_dir.mkdir(parents=True, exist_ok=True)
        return ca_dir / f"questionnaire_{questionnaire_id}.json"
    return project_dir / DEFAULT_CA_JSON_NAME


def _load_questionnaire_document(questionnaire_id: int) -> tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    """
    从数据库和磁盘加载问卷文档。
    """
    questionnaire_row = DbAccess.get_questionnaire_by_id(questionnaire_id)
    if not questionnaire_row:
        return None, None
    json_path = str(questionnaire_row.get("json_path") or "").strip()
    if not json_path:
        return questionnaire_row, None
    resolved_path = ROOT_DIR / "data" / json_path
    if not resolved_path.exists() or not resolved_path.is_file():
        return questionnaire_row, None
    try:
        document = json.loads(resolved_path.read_text(encoding="utf-8"))
    except Exception:
        return questionnaire_row, None
    if not isinstance(document, dict):
        return questionnaire_row, None
    return questionnaire_row, document


def _resolve_interview_rows(
    project_id: int,
    questionnaire_id: int,
    interview_ids: Optional[List[int]],
) -> List[Dict[str, Any]]:
    """
    读取并过滤当前 CA 使用的访谈行。
    """
    selected_rows: List[Dict[str, Any]] = []
    if interview_ids:
        for interview_id in interview_ids:
            row = DbAccess.get_interview_by_id(int(interview_id))
            if not row:
                continue
            if int(row.get("parse_project_id") or 0) != project_id:
                continue
            row_questionnaire_id = row.get("questionnaire_id")
            if row_questionnaire_id is not None and int(row_questionnaire_id) != questionnaire_id:
                continue
            selected_rows.append(row)
        return selected_rows

    for row in fetch_project_interviews(project_id):
        row_questionnaire_id = row.get("questionnaire_id")
        if row_questionnaire_id is None:
            continue
        if int(row_questionnaire_id) != questionnaire_id:
            continue
        selected_rows.append(row)
    selected_rows.sort(key=lambda item: int(item.get("id") or 0))
    return selected_rows


def _build_ca_meta(
    row: Dict[str, Any],
    selected_fields: List[str],
) -> Dict[str, Any]:
    """
    从访谈记录提取 CA 行头元数据。
    """
    detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
    meta: Dict[str, Any] = {}
    for field in selected_fields:
        value = detail.get(field) if isinstance(detail, dict) else None
        if value is None:
            value = row.get(field)
        meta[field] = _normalize_meta_value(value)
    return meta


def _build_ca_framework(
    project_id: int,
    project_name: str,
    questionnaire_row: Dict[str, Any],
    questionnaire_document: Dict[str, Any],
    interview_rows: List[Dict[str, Any]],
    selected_fields: List[str],
) -> Dict[str, Any]:
    """
    将问卷叶子问题和访谈行拼成 CA 框架。
    """
    expanded = expand_questionnaire_document(questionnaire_document)
    flat_questions = expanded.get("flat_questions") or []
    column_meta_field_labels = {
        str(item["key"]): str(item["label"]) for item in INTERVIEW_DETAIL_FIELD_DEFINITIONS if str(item["key"]) in selected_fields
    }
    questionnaire_name = str(questionnaire_row.get("name") or f"questionnaire_{questionnaire_row.get('id')}").strip()

    rows: List[Dict[str, Any]] = []
    selected_interview_ids: List[int] = []
    for row in interview_rows:
        interview_id = int(row.get("id") or 0)
        if interview_id <= 0:
            continue
        selected_interview_ids.append(interview_id)
        rows.append(
            {
                "interview_id": interview_id,
                "name": str(row.get("name") or f"访谈 {interview_id}").strip(),
                "interview_date": row.get("interview_date"),
                "meta": _build_ca_meta(row, selected_fields),
                "hidden": False,
            }
        )

    columns: List[Dict[str, Any]] = []
    cells: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for item in flat_questions:
        column_id = str(item.get("uid") or item.get("id") or item.get("order") or "").strip()
        if not column_id:
            continue
        question_text = str(item.get("text") or "").strip()
        display_text = question_text
        order = int(item.get("order") or len(columns) + 1)
        columns.append(
            {
                "column_id": column_id,
                "order": order,
                "question_uid": str(item.get("uid") or column_id).strip(),
                "question_text": question_text,
                "display_text": display_text,
                "hidden": False,
            }
        )
        for row in rows:
            interview_id = str(row["interview_id"])
            cells.setdefault(interview_id, {})
            cells[interview_id][column_id] = {"value": "", "locked": False, "source": "framework"}

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "project_id": project_id,
        "questionnaire_id": int(questionnaire_row["id"]),
        "project_name": project_name,
        "questionnaire_name": questionnaire_name,
        "column_meta_fields": selected_fields,
        "column_meta_field_labels": column_meta_field_labels,
        "selected_interview_ids": selected_interview_ids,
        "interviews": [
            {
                "interview_id": row["interview_id"],
                "name": row["name"],
                "interview_date": row["interview_date"],
                "meta": row["meta"],
            }
            for row in rows
        ],
        "rows": rows,
        "columns": columns,
        "cells": cells,
        "framework_status": "draft",
        "final_status": "pending",
        "status": "draft",
        "generated_at": generated_at,
        "framework_generated_at": generated_at,
        "final_generated_at": None,
        "reviewed_at": None,
        "error_message": None,
        "project_context": None,
        "questionnaire_json": questionnaire_document,
    }


def _collect_interview_blocks_for_question(
    interview_rows: List[Dict[str, Any]],
    notes_markdowns: Dict[int, str],
    query_text: str,
) -> List[Dict[str, Any]]:
    """
    为某个问卷问题收集每个访谈的相关片段。
    """
    interview_blocks: List[Dict[str, Any]] = []
    for row in interview_rows:
        interview_id = int(row.get("id") or 0)
        notes_markdown = str(notes_markdowns.get(interview_id) or "").strip()
        segments = _retrieve_segments_from_markdown(
            segments=_split_markdown_segments(notes_markdown),
            query_text=query_text,
            top_k=6,
        )
        interview_blocks.append(
            {
                "interview_id": interview_id,
                "name": row.get("name"),
                "meta": row.get("detail") or {},
                "segments": segments,
                "notes_markdown": notes_markdown,
            }
        )
    return interview_blocks


def generate_ca_table_for_project(
    project_id: int,
    interview_ids: Optional[List[int]] = None,
    column_meta_fields: Optional[List[str]] = None,
    questionnaire_id: Optional[int] = None,
    mode: str = "framework",
    framework_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    为指定项目生成 CA 表。
    """
    normalized_mode = str(mode or "framework").strip().lower() or "framework"
    log(
        "CA generation start "
        f"project_id={project_id} "
        f"questionnaire_id={questionnaire_id} "
        f"interview_ids={interview_ids} "
        f"column_meta_fields={column_meta_fields} "
        f"mode={normalized_mode}",
        project_id=project_id,
    )
    project = DbAccess.get_project_by_id(project_id)
    if not project:
        log("CA generation failed: project not found", project_id=project_id)
        return {
            "success": False,
            "stage": "fetch_project",
            "detail": {"message": f"project {project_id} not found"},
            "project_id": project_id,
        }

    project_context = load_project_context_by_id(project_id)
    project_name = str(project.get("name") or f"project_{project_id}").strip()
    selected_fields = [str(item).strip() for item in (column_meta_fields or DEFAULT_COLUMN_META_FIELDS) if str(item).strip()]
    if not selected_fields:
        selected_fields = DEFAULT_COLUMN_META_FIELDS[:]
    log(
        f"project context loaded project_name={project_name}, selected_fields={selected_fields}",
        project_id=project_id,
    )

    requested_interview_ids = [int(item) for item in (interview_ids or []) if item is not None]
    resolved_questionnaire_id = questionnaire_id
    if resolved_questionnaire_id is None and requested_interview_ids:
        first_row = DbAccess.get_interview_by_id(requested_interview_ids[0])
        if first_row and first_row.get("questionnaire_id") is not None:
            resolved_questionnaire_id = int(first_row["questionnaire_id"])
    if resolved_questionnaire_id is None:
        log("CA generation failed: questionnaire_id could not be resolved", project_id=project_id)
        return {
            "success": False,
            "stage": "resolve_questionnaire",
            "detail": {"message": "questionnaire_id is required for ca generation"},
            "project_id": project_id,
        }

    log(
        f"CA generation questionnaire resolved questionnaire_id={resolved_questionnaire_id} "
        f"requested_interview_count={len(requested_interview_ids)}",
        project_id=project_id,
    )
    questionnaire_row, questionnaire_document = _load_questionnaire_document(resolved_questionnaire_id)
    if not questionnaire_row or not isinstance(questionnaire_document, dict):
        log(
            f"CA generation failed: questionnaire load failed questionnaire_id={resolved_questionnaire_id}",
            project_id=project_id,
        )
        return {
            "success": False,
            "stage": "load_questionnaire",
            "detail": {"message": f"questionnaire {resolved_questionnaire_id} not found or unreadable"},
            "project_id": project_id,
            "questionnaire_id": resolved_questionnaire_id,
        }

    questionnaire_name = str(questionnaire_row.get("name") or f"questionnaire_{resolved_questionnaire_id}").strip()
    interview_rows = _resolve_interview_rows(project_id, resolved_questionnaire_id, requested_interview_ids)
    skipped_interview_ids: List[int] = []
    if requested_interview_ids:
        resolved_ids = {int(row.get("id") or 0) for row in interview_rows}
        skipped_interview_ids = [item for item in requested_interview_ids if item not in resolved_ids]

    if not interview_rows:
        log(
            f"CA generation failed: no interviews found questionnaire_id={resolved_questionnaire_id} "
            f"requested_interview_ids={requested_interview_ids} skipped_interview_ids={skipped_interview_ids}",
            project_id=project_id,
        )
        return {
            "success": False,
            "stage": "fetch_interviews",
            "detail": {"message": "no interviews found for questionnaire", "skipped_interview_ids": skipped_interview_ids},
            "project_id": project_id,
            "questionnaire_id": resolved_questionnaire_id,
        }

    notes_items = build_project_full_notes_markdowns(project_id, [int(row.get("id") or 0) for row in interview_rows])
    notes_by_id = {
        int(item["interview_id"]): item
        for item in notes_items
        if item.get("interview_id") is not None
    }
    interview_notes: List[Dict[str, Any]] = []
    for row in interview_rows:
        interview_id = int(row.get("id") or 0)
        note_item = notes_by_id.get(interview_id, {})
        notes_markdown = str(note_item.get("notes_markdown") or "").strip()
        interview_notes.append(
            {
                "interview_id": interview_id,
                "name": str(row.get("name") or note_item.get("name") or f"访谈 {interview_id}").strip(),
                "interview_date": row.get("interview_date"),
                "meta": row.get("detail") if isinstance(row.get("detail"), dict) else {},
                "notes_markdown": notes_markdown,
                "segments": _split_markdown_segments(notes_markdown),
            }
        )
    log(
        f"CA generation interview notes prepared questionnaire_id={resolved_questionnaire_id} "
        f"interview_count={len(interview_notes)} notes_items={len(notes_items)}",
        project_id=project_id,
    )

    if normalized_mode in {"framework", "draft"}:
        log(
            f"CA framework build start questionnaire_id={resolved_questionnaire_id} "
            f"interview_count={len(interview_rows)} selected_fields={selected_fields}",
            project_id=project_id,
        )
        framework_payload = _build_ca_framework(
            project_id=project_id,
            project_name=project_name,
            questionnaire_row=questionnaire_row,
            questionnaire_document=questionnaire_document,
            interview_rows=interview_rows,
            selected_fields=selected_fields,
        )
        framework_payload["project_context"] = project_context if isinstance(project_context, dict) else None
        framework_payload["questionnaire_id"] = resolved_questionnaire_id
        framework_payload["questionnaire_name"] = questionnaire_name
        framework_payload["status"] = "reviewing"
        framework_payload["framework_status"] = "reviewing"
        existing_row = DbAccess.fetch_ca_table_by_project(project_id, resolved_questionnaire_id)
        existing_final_json = existing_row.get("final_json") if existing_row else None
        existing_final_status = existing_row.get("final_status") if existing_row else None
        existing_final_generated_at = existing_row.get("final_generated_at") if existing_row else None
        existing_reviewed_at = existing_row.get("reviewed_at") if existing_row else None
        framework_payload["final_status"] = existing_final_status or "pending"
        framework_payload["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        framework_payload["framework_generated_at"] = framework_payload["generated_at"]
        framework_payload["final_generated_at"] = existing_final_generated_at
        framework_payload["reviewed_at"] = existing_reviewed_at
        framework_payload["final_json"] = existing_final_json
        framework_payload["selected_interview_ids"] = [row["interview_id"] for row in framework_payload.get("rows", [])]
        log(
            f"CA framework built questionnaire_id={resolved_questionnaire_id} "
            f"row_count={len(framework_payload.get('rows') or [])} "
            f"column_count={len(framework_payload.get('columns') or [])} "
            f"selected_interview_ids={framework_payload.get('selected_interview_ids')}",
            project_id=project_id,
        )
        safe_framework_payload = _json_safe_value(framework_payload)
        cache_path = _build_ca_cache_path(project_id, resolved_questionnaire_id)
        log(f"Writing CA framework cache file: {cache_path}", project_id=project_id)
        cache_path.write_text(json.dumps(safe_framework_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            log(
                f"Writing CA framework to db questionnaire_id={resolved_questionnaire_id} "
                f"framework_status=reviewing final_status={existing_final_status or 'pending'}",
                project_id=project_id,
            )
            DbAccess.upsert_ca_table(
                project_id=project_id,
                questionnaire_id=resolved_questionnaire_id,
                ca_json=safe_framework_payload,
                framework_json=safe_framework_payload,
                final_json=existing_final_json,
                framework_status="reviewing",
                final_status=existing_final_status or "pending",
                error_message=None,
                generated_at=safe_framework_payload["generated_at"],
                framework_generated_at=safe_framework_payload["framework_generated_at"],
                final_generated_at=existing_final_generated_at,
                reviewed_at=existing_reviewed_at,
            )
            log(
                f"CA framework persisted questionnaire_id={resolved_questionnaire_id} "
                f"cache_path={cache_path}",
                project_id=project_id,
            )
        except Exception as exc:
            log(f"CA framework table write failed: {exc}\n{traceback.format_exc()}", project_id=project_id)
            return {
                "success": False,
                "stage": "upsert_ca_table",
                "detail": {
                    "message": f"upsert ca framework failed: {exc}",
                    "traceback": traceback.format_exc(),
                    "skipped_interview_ids": skipped_interview_ids,
                },
                "project_id": project_id,
                "questionnaire_id": resolved_questionnaire_id,
            }

        return {
            "success": True,
            "project_id": project_id,
            "questionnaire_id": resolved_questionnaire_id,
            "mode": "framework",
            "generated_at": safe_framework_payload["generated_at"],
            "framework_generated_at": safe_framework_payload["framework_generated_at"],
            "final_generated_at": None,
            "column_meta_fields": selected_fields,
            "interview_count": len(interview_rows),
            "dimension_count": len(safe_framework_payload.get("columns") or []),
            "requested_interview_ids": requested_interview_ids,
            "skipped_interview_ids": skipped_interview_ids,
            "framework_json": safe_framework_payload,
            "ca_json": safe_framework_payload,
            "ca_json_path": str(cache_path),
        }

    base_framework = framework_json
    if not isinstance(base_framework, dict):
        row = DbAccess.fetch_ca_table_by_project(project_id, resolved_questionnaire_id)
        if row:
            base_framework = _hydrate_ca_payload_from_row(row, project_name)
    if not isinstance(base_framework, dict):
        log(
            f"CA final generation failed: framework not found questionnaire_id={resolved_questionnaire_id}",
            project_id=project_id,
        )
        return {
            "success": False,
            "stage": "load_framework",
            "detail": {"message": "framework not found, please generate framework first"},
            "project_id": project_id,
            "questionnaire_id": resolved_questionnaire_id,
        }

    log(
        f"CA final generation start questionnaire_id={resolved_questionnaire_id} "
        f"row_count={len([row for row in (base_framework.get('rows') or []) if isinstance(row, dict)])} "
        f"column_count={len([column for column in (base_framework.get('columns') or []) if isinstance(column, dict)])} "
        f"interview_count={len(interview_rows)}",
        project_id=project_id,
    )
    final_payload = json.loads(json.dumps(base_framework, ensure_ascii=False))
    final_payload["project_id"] = project_id
    final_payload["project_name"] = project_name
    final_payload["questionnaire_id"] = resolved_questionnaire_id
    final_payload["questionnaire_name"] = questionnaire_name
    final_payload["project_context"] = project_context if isinstance(project_context, dict) else None
    final_payload["framework_json"] = base_framework
    final_payload["final_json"] = None
    final_payload["final_status"] = "generating"
    final_payload["framework_status"] = str(base_framework.get("framework_status") or base_framework.get("status") or "reviewed")
    final_payload["status"] = "generating"
    final_payload["reviewed_at"] = base_framework.get("reviewed_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    notes_items = build_project_full_notes_markdowns(project_id, [row["interview_id"] for row in interview_notes])
    notes_by_id = {
        int(item["interview_id"]): item
        for item in notes_items
        if item.get("interview_id") is not None
    }
    notes_markdown_map = {
        interview_id: str(item.get("notes_markdown") or "").strip()
        for interview_id, item in notes_by_id.items()
    }

    columns = [column for column in (final_payload.get("columns") or []) if isinstance(column, dict)]
    rows = [row for row in (final_payload.get("rows") or []) if isinstance(row, dict)]
    cells = final_payload.get("cells") if isinstance(final_payload.get("cells"), dict) else {}
    if not isinstance(cells, dict):
        cells = {}

    selected_interview_ids = [int(item.get("interview_id") or 0) for item in rows if int(item.get("interview_id") or 0) > 0]
    if not selected_interview_ids:
        selected_interview_ids = [int(row.get("id") or 0) for row in interview_rows if int(row.get("id") or 0) > 0]

    for column in columns:
        column_id = str(column.get("column_id") or "").strip()
        if not column_id:
            continue
        question_text = str(column.get("display_text") or column.get("question_text") or "").strip()
        question_uid = str(column.get("question_uid") or column_id).strip()
        question_order = int(column.get("order") or 0)
        log(
            f"CA final column generation start questionnaire_id={resolved_questionnaire_id} "
            f"question_uid={question_uid} question_order={question_order} "
            f"interview_block_count={len(interview_rows)}",
            project_id=project_id,
        )
        interview_blocks = _collect_interview_blocks_for_question(
            interview_rows=interview_rows,
            notes_markdowns=notes_markdown_map,
            query_text=question_text,
        )
        try:
            cell_payload = ModelClient.generate_ca_cells_for_question(
                project_context=project_context,
                questionnaire_title=questionnaire_name,
                question_uid=question_uid,
                question_order=question_order,
                question_text=question_text,
                interview_blocks=interview_blocks,
            )
            cell_map = cell_payload.get("cells") or {}
            log(
                f"CA final column generation done questionnaire_id={resolved_questionnaire_id} "
                f"question_uid={question_uid} returned_cell_count={len(cell_map) if isinstance(cell_map, dict) else 0}",
                project_id=project_id,
            )
        except Exception as exc:
            log(
                f"CA cell failed question_uid={question_uid} question_text={question_text} error={exc}",
                project_id=project_id,
            )
            cell_map = {}

        if not isinstance(cell_map, dict):
            cell_map = {}

        for interview_id in selected_interview_ids:
            interview_key = str(interview_id)
            cells.setdefault(interview_key, {})
            current_cell = cells[interview_key].get(column_id)
            current_value = ""
            current_locked = False
            current_source = "framework"
            if isinstance(current_cell, dict):
                current_value = str(current_cell.get("value") or "").strip()
                current_locked = bool(current_cell.get("locked"))
                current_source = str(current_cell.get("source") or "framework")
            elif current_cell is not None:
                current_value = str(current_cell).strip()

            if current_locked or (current_source == "manual" and current_value and current_value != "/"):
                continue

            raw_value = cell_map.get(interview_key)
            if isinstance(raw_value, dict):
                next_value = str(raw_value.get("value") or raw_value.get("text") or "").strip()
            else:
                next_value = str(raw_value or "").strip()
            if not next_value:
                next_value = "/"
            cells[interview_key][column_id] = {
                "value": next_value,
                "locked": bool(current_locked),
                "source": "llm",
            }
        log(
            f"CA final column applied questionnaire_id={resolved_questionnaire_id} "
            f"question_uid={question_uid} interview_count={len(selected_interview_ids)}",
            project_id=project_id,
        )

    final_payload["cells"] = cells
    final_payload["final_json"] = {
        **{key: value for key, value in final_payload.items() if key != "final_json"},
    }
    final_payload["final_status"] = "done"
    final_payload["status"] = "done"
    final_payload["generated_at"] = final_payload.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    final_payload["final_generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    final_payload["framework_generated_at"] = base_framework.get("framework_generated_at") or base_framework.get("generated_at")
    final_payload["selected_interview_ids"] = selected_interview_ids

    safe_final_payload = _json_safe_value(final_payload)
    cache_path = _build_ca_cache_path(project_id, resolved_questionnaire_id)
    log(f"Writing CA final cache file: {cache_path}", project_id=project_id)
    cache_path.write_text(json.dumps(safe_final_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        log(
            f"Writing CA final to db questionnaire_id={resolved_questionnaire_id} "
            f"final_status=done reviewed_at={final_payload.get('reviewed_at')}",
            project_id=project_id,
        )
        DbAccess.upsert_ca_table(
            project_id=project_id,
            questionnaire_id=resolved_questionnaire_id,
            ca_json=safe_final_payload,
            framework_json=base_framework,
            final_json=safe_final_payload,
            framework_status=str(base_framework.get("framework_status") or "reviewed"),
            final_status="done",
            error_message=None,
            generated_at=safe_final_payload["generated_at"],
            framework_generated_at=base_framework.get("framework_generated_at") or base_framework.get("generated_at"),
            final_generated_at=safe_final_payload["final_generated_at"],
            reviewed_at=final_payload.get("reviewed_at"),
        )
        log(
            f"CA final persisted questionnaire_id={resolved_questionnaire_id} "
            f"cache_path={cache_path} column_count={len(columns)} interview_count={len(selected_interview_ids)}",
            project_id=project_id,
        )
    except Exception as exc:
        log(f"CA final table write failed: {exc}\n{traceback.format_exc()}", project_id=project_id)
        return {
            "success": False,
            "stage": "upsert_ca_table",
            "detail": {
                "message": f"upsert ca table failed: {exc}",
                "traceback": traceback.format_exc(),
                "skipped_interview_ids": skipped_interview_ids,
            },
            "project_id": project_id,
            "questionnaire_id": resolved_questionnaire_id,
        }

    return {
        "success": True,
        "project_id": project_id,
        "questionnaire_id": resolved_questionnaire_id,
        "mode": "final",
        "generated_at": safe_final_payload["generated_at"],
        "framework_generated_at": base_framework.get("framework_generated_at") or base_framework.get("generated_at"),
        "final_generated_at": safe_final_payload["final_generated_at"],
        "column_meta_fields": selected_fields,
        "interview_count": len(interview_rows),
        "dimension_count": len(columns),
        "requested_interview_ids": requested_interview_ids,
        "skipped_interview_ids": skipped_interview_ids,
        "framework_json": _json_safe_value(base_framework),
        "final_json": safe_final_payload,
        "ca_json": safe_final_payload,
        "ca_json_path": str(cache_path),
    }
