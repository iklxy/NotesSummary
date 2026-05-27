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
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import perf_counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from DbAccess import DbAccess
from InterviewLogger import log_interview, log_project
from Model import ModelClient
from MinutesWorkflow import DEFAULT_MINUTES_TXT_NAME, _score_segment, _tokenize_for_search
from ProjectContext import load_project_context_by_id
from QuestionTree import expand_questionnaire_document
from interview_detail_fields import INTERVIEW_DETAIL_FIELD_DEFINITIONS
from db import fetch_interviews_by_project as fetch_project_interviews


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_CA_JSON_NAME = "ca_table.json"
DEFAULT_CA_FULL_NOTES_NAME = "full_notes.md"
CA_SCHEMA_VERSION = 4
CA_LEGACY_SCHEMA_VERSION = 2
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


def _get_interview_minutes_text_path(project_id: int, interview_id: int) -> Path:
    """
    获取访谈全文 Notes 的落盘路径。
    """
    return _get_interview_data_dir(project_id, interview_id) / DEFAULT_MINUTES_TXT_NAME


def _load_interview_minutes_text(project_id: int, interview_id: int) -> str:
    """
    读取访谈全文 Notes。
    """
    path = _get_interview_minutes_text_path(project_id, interview_id)
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _split_markdown_segments(markdown_text: str) -> List[Dict[str, Any]]:
    """
    将全文 trans / text 切分为检索片段。

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


def _load_project_interview_minutes_texts(
    project_id: int,
    interview_rows: List[Dict[str, Any]],
) -> tuple[Dict[int, str], List[int]]:
    """
    读取当前项目下各访谈的 minutes.txt。
    """
    source_texts: Dict[int, str] = {}
    missing_ids: List[int] = []
    for row in interview_rows:
        interview_id = int(row.get("id") or 0)
        if interview_id <= 0:
            continue
        source_text = _load_interview_minutes_text(project_id, interview_id)
        if not source_text.strip():
            missing_ids.append(interview_id)
            continue
        source_texts[interview_id] = source_text.strip()
    return source_texts, missing_ids


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
    project_context: Any = None,
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
    simplified_question_map: Dict[str, str] = {}
    simplified_question_uids: set[str] = set()
    simplification_successful = False
    if flat_questions:
        try:
            simplification_payload = ModelClient.generate_ca_question_display_texts(
                project_context=project_context,
                questionnaire_title=questionnaire_name,
                questions=flat_questions,
            )
            for item in simplification_payload.get("questions") or []:
                if not isinstance(item, dict):
                    continue
                uid = str(item.get("uid") or "").strip()
                display_text = str(item.get("display_text") or "").strip()
                if uid and display_text:
                    simplified_question_map[uid] = display_text
                    simplified_question_uids.add(uid)
            simplification_successful = True
        except Exception as exc:
            log(
                f"CA question simplification failed questionnaire_id={questionnaire_row.get('id')} error={exc}",
                project_id=project_id,
            )

    filtered_questions = [item for item in flat_questions if str(item.get("uid") or item.get("question_uid") or item.get("column_id") or "").strip() in simplified_question_uids]
    if simplification_successful:
        flat_questions = filtered_questions
        log(
            f"CA question simplification filtered questionnaire_id={questionnaire_row.get('id')} "
            f"input_count={len(expanded.get('flat_questions') or [])} output_count={len(flat_questions)}",
            project_id=project_id,
        )

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
        display_text = simplified_question_map.get(column_id) or question_text
        order = int(item.get("order") or len(columns) + 1)
        columns.append(
            {
                "column_id": column_id,
                "order": order,
                "question_uid": str(item.get("uid") or column_id).strip(),
                "question_text": question_text,
                "display_text": display_text,
                "summary_text": "/",
                "hidden": False,
            }
        )
        for row in rows:
            interview_id = str(row["interview_id"])
            cells.setdefault(interview_id, {})
            cells[interview_id][column_id] = {"value": "", "evidence": [], "locked": False, "source": "framework"}

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "schema_version": CA_SCHEMA_VERSION,
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
        "diff_row": {},
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
    source_texts: Dict[int, str],
    query_text: str,
) -> List[Dict[str, Any]]:
    """
    为某个问卷问题收集每个访谈的相关片段。
    """
    interview_blocks: List[Dict[str, Any]] = []
    for row in interview_rows:
        interview_id = int(row.get("id") or 0)
        source_text = str(source_texts.get(interview_id) or "").strip()
        segments = _retrieve_segments_from_markdown(
            segments=_split_markdown_segments(source_text),
            query_text=query_text,
            top_k=6,
        )
        interview_blocks.append(
            {
                "interview_id": interview_id,
                "name": row.get("name"),
                "meta": row.get("detail") or {},
                "segments": segments,
                "source_text": source_text,
            }
        )
    return interview_blocks


def _group_ca_columns_for_generation(
    columns: List[Dict[str, Any]],
    groups: Any,
) -> List[Dict[str, Any]]:
    """
    按主题分组整理 CA 列，用于分组并发生成。
    """
    grouped_columns: List[Dict[str, Any]] = []
    if isinstance(groups, list) and groups:
        sorted_groups = [item for item in groups if isinstance(item, dict)]
        sorted_groups.sort(key=lambda item: int(item.get("order") or 0))
        consumed: set[str] = set()

        for group_index, group in enumerate(sorted_groups, start=1):
            group_label = str(group.get("title") or group.get("name") or f"主题分组 {group_index}").strip() or f"主题分组 {group_index}"
            group_summary = str(group.get("summary") or "").strip()
            row_uids = [
                str(uid or "").strip()
                for uid in (group.get("row_uids") or [])
                if str(uid or "").strip()
            ]
            group_columns: List[Dict[str, Any]] = []
            if row_uids:
                row_uid_set = set(row_uids)
                for column in columns:
                    if not isinstance(column, dict):
                        continue
                    question_uid = str(column.get("question_uid") or column.get("column_id") or "").strip()
                    if question_uid in row_uid_set:
                        group_columns.append(column)
                        consumed.add(question_uid)
            else:
                group_columns = [
                    column
                    for column in columns
                    if isinstance(column, dict) and str(column.get("group") or "").strip() == group_label
                ]
                for column in group_columns:
                    question_uid = str(column.get("question_uid") or column.get("column_id") or "").strip()
                    if question_uid:
                        consumed.add(question_uid)
            if group_columns:
                grouped_columns.append(
                    {
                        "group_label": group_label,
                        "group_summary": group_summary,
                        "columns": group_columns,
                    }
                )

        leftovers = [
            column
            for column in columns
            if isinstance(column, dict)
            and str(column.get("question_uid") or column.get("column_id") or "").strip() not in consumed
        ]
        if leftovers:
            grouped_columns.append(
                {
                    "group_label": str(leftovers[0].get("group") or "未分组").strip() or "未分组",
                    "group_summary": str(leftovers[0].get("group_summary") or "").strip(),
                    "columns": leftovers,
                }
            )
        return grouped_columns

    current_label = None
    current_summary = ""
    current_columns: List[Dict[str, Any]] = []
    for column in columns:
        if not isinstance(column, dict):
            continue
        label = str(column.get("group") or "未分组").strip() or "未分组"
        summary = str(column.get("group_summary") or "").strip()
        if current_label is None or current_label != label:
            if current_columns:
                grouped_columns.append(
                    {
                        "group_label": current_label or "未分组",
                        "group_summary": current_summary,
                        "columns": current_columns,
                    }
                )
            current_label = label
            current_summary = summary
            current_columns = [column]
            continue
        current_columns.append(column)
    if current_columns:
        grouped_columns.append(
            {
                "group_label": current_label or "未分组",
                "group_summary": current_summary,
                "columns": current_columns,
            }
        )
    return grouped_columns


def _generate_ca_question_content(
    project_context: Any,
    questionnaire_name: str,
    question_uid: str,
    question_order: int,
    question_text: str,
    question_type: str,
    question_group: str,
    question_group_summary: str,
    interview_rows: List[Dict[str, Any]],
    minutes_texts: Dict[int, str],
    selected_interview_ids: List[int],
) -> Dict[str, Any]:
    """
    生成单个问题的 CA 单元格和行总结。
    """
    interview_blocks = _collect_interview_blocks_for_question(
        interview_rows=interview_rows,
        source_texts=minutes_texts,
        query_text=question_text,
    )

    cell_map: Dict[str, Any] = {}
    cell_error: Optional[str] = None
    try:
        cell_payload = ModelClient.generate_ca_cells_for_question(
            project_context=project_context,
            questionnaire_title=questionnaire_name,
            question_uid=question_uid,
            question_order=question_order,
            question_text=question_text,
            question_type=question_type,
            interview_blocks=interview_blocks,
        )
        cell_map = cell_payload.get("cells") or {}
    except Exception as exc:
        cell_error = str(exc)
        cell_map = {}
    if not isinstance(cell_map, dict):
        cell_map = {}

    interview_row_by_id = {
        int(row.get("id") or 0): row
        for row in interview_rows
        if int(row.get("id") or 0) > 0
    }
    interview_rows_for_summary: List[Dict[str, Any]] = []
    for interview_id in selected_interview_ids:
        interview_key = str(interview_id)
        raw_value = cell_map.get(interview_key)
        current_value = ""
        current_evidence: List[str] = []
        current_source = ""
        current_numeric_value = None
        if isinstance(raw_value, dict):
            current_value = str(raw_value.get("value") or raw_value.get("answer") or raw_value.get("text") or "").strip()
            current_evidence = [
                str(item or "").strip()
                for item in (raw_value.get("evidence") or raw_value.get("sources") or raw_value.get("quotes") or [])
                if str(item or "").strip()
            ]
            current_source = str(raw_value.get("source") or "").strip()
            current_numeric_value = raw_value.get("numeric_value")
        elif raw_value is not None:
            current_value = str(raw_value).strip()
        interview_row = interview_row_by_id.get(interview_id)
        interview_rows_for_summary.append(
            {
                "interview_id": interview_id,
                "name": str(interview_row.get("name") if isinstance(interview_row, dict) else f"访谈 {interview_id}").strip(),
                "answer": current_value or "/",
                "evidence": current_evidence,
                "numeric_value": current_numeric_value,
                "source": current_source or "llm",
            }
        )

    summary_text = "/"
    summary_error: Optional[str] = None
    try:
        row_summary_payload = ModelClient.generate_ca_row_summary_for_question(
            project_context=project_context,
            questionnaire_title=questionnaire_name,
            question_uid=question_uid,
            question_order=question_order,
            question_text=question_text,
            question_type=question_type,
            question_group=question_group,
            question_group_summary=question_group_summary,
            interview_rows=interview_rows_for_summary,
        )
        summary_text = str(row_summary_payload.get("summary") or "").strip() or "/"
    except Exception as exc:
        summary_error = str(exc)

    return {
        "question_uid": question_uid,
        "question_order": question_order,
        "question_text": question_text,
        "question_type": question_type,
        "question_group": question_group,
        "question_group_summary": question_group_summary,
        "cell_map": cell_map,
        "summary_text": summary_text,
        "cell_error": cell_error,
        "summary_error": summary_error,
    }


def _build_ca_framework_from_notes(
    project_id: int,
    project_name: str,
    questionnaire_row: Dict[str, Any],
    questionnaire_document: Dict[str, Any],
    interview_sources: List[Dict[str, Any]],
    selected_fields: List[str],
    project_context: Any = None,
) -> Dict[str, Any]:
    """
    基于多份全文 Notes 生成 CA 框架。
    """
    column_meta_field_labels = {
        str(item["key"]): str(item["label"])
        for item in INTERVIEW_DETAIL_FIELD_DEFINITIONS
        if str(item["key"]) in selected_fields
    }
    questionnaire_name = str(questionnaire_row.get("name") or f"questionnaire_{questionnaire_row.get('id')}").strip()

    framework_payload = ModelClient.generate_ca_notes_framework(
        project_context=project_context,
        interviews_notes=[
            {
                "interview_id": item["interview_id"],
                "name": item.get("name"),
                "notes_markdown": item.get("source_text") or "",
            }
            for item in interview_sources
        ],
    )
    groups = framework_payload.get("groups") or []
    if not isinstance(groups, list) or not groups:
        raise RuntimeError("notes framework generation returned empty groups")

    rows: List[Dict[str, Any]] = []
    columns: List[Dict[str, Any]] = []
    cells: Dict[str, Dict[str, Dict[str, Any]]] = {}
    structured_groups: List[Dict[str, Any]] = []
    selected_interview_ids: List[int] = []
    for source in interview_sources:
        interview_id = int(source.get("interview_id") or 0)
        if interview_id > 0:
            selected_interview_ids.append(interview_id)
    for source in interview_sources:
        interview_id = int(source.get("interview_id") or 0)
        if interview_id <= 0:
            continue
        rows.append(
            {
                "interview_id": interview_id,
                "name": str(source.get("name") or f"访谈 {interview_id}").strip(),
                "interview_date": source.get("interview_date"),
                "meta": _build_ca_meta(
                    {
                        "detail": source.get("meta") if isinstance(source.get("meta"), dict) else {},
                        "name": source.get("name"),
                        "interview_date": source.get("interview_date"),
                    },
                    selected_fields,
                ),
                "hidden": False,
            }
        )

    next_order = 1
    for group_index, group in enumerate(groups, start=1):
        if not isinstance(group, dict):
            continue
        group_title = str(group.get("title") or group.get("name") or f"主题分组 {group_index}").strip()
        group_summary = str(group.get("summary") or "").strip()
        raw_rows = group.get("rows") or group.get("questions") or group.get("sub_points") or []
        if not isinstance(raw_rows, list):
            raw_rows = []
        row_uids: List[str] = []
        for row_index, item in enumerate(raw_rows, start=1):
            if not isinstance(item, dict):
                continue
            row_title = str(item.get("title") or item.get("display_text") or item.get("question_text") or "").strip()
            row_summary = str(item.get("summary") or "").strip()
            if not row_title and not row_summary:
                continue
            question_type = str(item.get("question_type") or "qualitative").strip().lower()
            if question_type not in {"qualitative", "quantitative"}:
                question_type = "qualitative"
            question_uid = str(
                item.get("uid")
                or item.get("question_uid")
                or item.get("column_id")
                or f"g{group_index:02d}_r{row_index:03d}"
            ).strip()
            display_text = str(item.get("display_text") or row_title or row_summary).strip()
            columns.append(
                {
                    "column_id": question_uid,
                    "order": next_order,
                    "group": group_title,
                    "group_order": group_index,
                    "group_summary": group_summary,
                    "question_uid": question_uid,
                    "question_text": row_title or row_summary,
                    "display_text": display_text,
                    "summary_text": "/",
                    "question_type": question_type,
                    "hidden": False,
                }
            )
            row_uids.append(question_uid)
            for row in rows:
                interview_key = str(row["interview_id"])
                cells.setdefault(interview_key, {})
                cells[interview_key][question_uid] = {
                    "value": "",
                    "evidence": [],
                    "locked": False,
                    "source": "framework",
                    "numeric_value": None,
                }
            next_order += 1
        structured_groups.append(
            {
                "group_id": f"group_{group_index:02d}",
                "order": group_index,
                "title": group_title,
                "summary": group_summary,
                "row_uids": row_uids,
            }
        )

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "schema_version": CA_SCHEMA_VERSION,
        "framework_source": "notes",
        "project_id": project_id,
        "questionnaire_id": int(questionnaire_row["id"]),
        "project_name": project_name,
        "questionnaire_name": questionnaire_name,
        "column_meta_fields": selected_fields,
        "column_meta_field_labels": column_meta_field_labels,
        "selected_interview_ids": selected_interview_ids,
        "groups": structured_groups,
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
        "diff_row": {
            str(item["interview_id"]): {"value": "", "evidence": [], "locked": False, "source": "framework"}
            for item in interview_sources
            if int(item.get("interview_id") or 0) > 0
        },
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
    if not questionnaire_row:
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
    if not isinstance(questionnaire_document, dict):
        questionnaire_document = {}

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

    minutes_texts, missing_minutes_ids = _load_project_interview_minutes_texts(project_id, interview_rows)
    if missing_minutes_ids:
        log(
            f"CA generation failed: missing minutes.txt interview_ids={missing_minutes_ids}",
            project_id=project_id,
        )
        return {
            "success": False,
            "stage": "load_minutes_text",
            "detail": {
                "message": "minutes.txt missing for one or more interviews",
                "missing_interview_ids": missing_minutes_ids,
            },
            "project_id": project_id,
            "questionnaire_id": resolved_questionnaire_id,
        }

    interview_sources: List[Dict[str, Any]] = []
    for row in interview_rows:
        interview_id = int(row.get("id") or 0)
        source_text = str(minutes_texts.get(interview_id) or "").strip()
        interview_sources.append(
            {
                "interview_id": interview_id,
                "name": str(row.get("name") or f"访谈 {interview_id}").strip(),
                "interview_date": row.get("interview_date"),
                "meta": row.get("detail") if isinstance(row.get("detail"), dict) else {},
                "source_text": source_text,
                "segments": _split_markdown_segments(source_text),
            }
        )
    log(
        f"CA generation interview source texts prepared questionnaire_id={resolved_questionnaire_id} "
        f"interview_count={len(interview_sources)} source_text_count={len(minutes_texts)}",
        project_id=project_id,
    )

    if normalized_mode in {"framework", "draft"}:
        log(
            f"CA framework build start questionnaire_id={resolved_questionnaire_id} "
            f"interview_count={len(interview_rows)} selected_fields={selected_fields} mode=notes",
            project_id=project_id,
        )
        try:
            framework_payload = _build_ca_framework_from_notes(
                project_id=project_id,
                project_name=project_name,
                questionnaire_row=questionnaire_row,
                questionnaire_document=questionnaire_document,
                interview_sources=interview_sources,
                selected_fields=selected_fields,
                project_context=project_context,
            )
            framework_payload["schema_version"] = CA_SCHEMA_VERSION
        except Exception as exc:
            log(
                f"CA notes framework build failed questionnaire_id={resolved_questionnaire_id} error={exc}\n{traceback.format_exc()}",
                project_id=project_id,
            )
            framework_payload = _build_ca_framework(
                project_id=project_id,
                project_name=project_name,
                questionnaire_row=questionnaire_row,
                questionnaire_document=questionnaire_document,
                interview_rows=interview_rows,
                selected_fields=selected_fields,
                project_context=project_context,
            )
            framework_payload["schema_version"] = CA_LEGACY_SCHEMA_VERSION
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
        framework_payload["diff_row"] = {
            str(item["interview_id"]): {"value": "", "evidence": [], "locked": False, "source": "framework"}
            for item in interview_sources
            if int(item.get("interview_id") or 0) > 0
        }
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

    if normalized_mode in {"framework_legacy", "legacy_framework", "legacy"}:
        log(
            f"CA framework build start questionnaire_id={resolved_questionnaire_id} "
            f"interview_count={len(interview_rows)} selected_fields={selected_fields} mode=legacy",
            project_id=project_id,
        )
        framework_payload = _build_ca_framework(
            project_id=project_id,
            project_name=project_name,
            questionnaire_row=questionnaire_row,
            questionnaire_document=questionnaire_document,
            interview_rows=interview_rows,
            selected_fields=selected_fields,
            project_context=project_context,
        )
        framework_payload["schema_version"] = CA_LEGACY_SCHEMA_VERSION
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
        framework_payload["diff_row"] = {
            str(item["interview_id"]): {"value": "", "evidence": [], "locked": False, "source": "framework"}
            for item in interview_sources
            if int(item.get("interview_id") or 0) > 0
        }
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
            "mode": "framework_legacy",
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

    columns = [column for column in (final_payload.get("columns") or []) if isinstance(column, dict)]
    rows = [row for row in (final_payload.get("rows") or []) if isinstance(row, dict)]
    cells = final_payload.get("cells") if isinstance(final_payload.get("cells"), dict) else {}
    if not isinstance(cells, dict):
        cells = {}

    selected_interview_ids = [int(item.get("interview_id") or 0) for item in rows if int(item.get("interview_id") or 0) > 0]
    if not selected_interview_ids:
        selected_interview_ids = [int(row.get("id") or 0) for row in interview_rows if int(row.get("id") or 0) > 0]

    grouped_columns = _group_ca_columns_for_generation(columns, final_payload.get("groups"))
    final_generation_started_at = perf_counter()
    for group_index, group in enumerate(grouped_columns, start=1):
        group_label = str(group.get("group_label") or "未分组").strip() or "未分组"
        group_summary = str(group.get("group_summary") or "").strip()
        group_columns = [column for column in (group.get("columns") or []) if isinstance(column, dict)]
        if not group_columns:
            continue

        thread_count = min(max(len(group_columns), 1), 20)
        group_started_at = perf_counter()
        group_generated_count = 0
        group_cell_error_count = 0
        group_summary_error_count = 0
        log(
            f"CA final group generation start questionnaire_id={resolved_questionnaire_id} "
            f"group_index={group_index} group_label={group_label} question_count={len(group_columns)} "
            f"thread_count={thread_count} group_summary_len={len(group_summary)}",
            project_id=project_id,
        )
        with ThreadPoolExecutor(max_workers=thread_count) as executor:
            future_map = {
                executor.submit(
                    _generate_ca_question_content,
                    project_context,
                    questionnaire_name,
                    str(column.get("question_uid") or column.get("column_id") or "").strip(),
                    int(column.get("order") or 0),
                    str(column.get("question_text") or column.get("display_text") or "").strip(),
                    str(column.get("question_type") or "qualitative").strip().lower(),
                    str(column.get("group") or group_label).strip() or group_label,
                    str(column.get("group_summary") or group_summary).strip(),
                    interview_rows,
                    minutes_texts,
                    selected_interview_ids,
                ): column
                for column in group_columns
                if str(column.get("question_uid") or column.get("column_id") or "").strip()
            }

            for future in as_completed(future_map):
                column = future_map[future]
                column_id = str(column.get("column_id") or "").strip()
                question_uid = str(column.get("question_uid") or column_id).strip()
                question_text = str(column.get("question_text") or column.get("display_text") or "").strip()
                question_order = int(column.get("order") or 0)
                question_type = str(column.get("question_type") or "qualitative").strip().lower()
                try:
                    result = future.result()
                except Exception as exc:
                    log(
                        f"CA question worker failed questionnaire_id={resolved_questionnaire_id} "
                        f"group_label={group_label} question_uid={question_uid} error={exc}\n{traceback.format_exc()}",
                        project_id=project_id,
                    )
                    result = {
                        "question_uid": question_uid,
                        "question_order": question_order,
                        "question_text": question_text,
                        "question_type": question_type,
                        "question_group": str(column.get("group") or group_label).strip() or group_label,
                        "question_group_summary": str(column.get("group_summary") or group_summary).strip(),
                        "cell_map": {},
                        "summary_text": "/",
                        "cell_error": str(exc),
                        "summary_error": str(exc),
                    }

                cell_map = result.get("cell_map") or {}
                if not isinstance(cell_map, dict):
                    cell_map = {}
                if result.get("cell_error"):
                    group_cell_error_count += 1
                    log(
                        f"CA cell generation error questionnaire_id={resolved_questionnaire_id} "
                        f"group_label={group_label} question_uid={question_uid} error={result.get('cell_error')}",
                        project_id=project_id,
                    )
                if result.get("summary_error"):
                    group_summary_error_count += 1
                    log(
                        f"CA row summary error questionnaire_id={resolved_questionnaire_id} "
                        f"group_label={group_label} question_uid={question_uid} error={result.get('summary_error')}",
                        project_id=project_id,
                    )
                log(
                    f"CA final column generation done questionnaire_id={resolved_questionnaire_id} "
                    f"group_label={group_label} question_uid={question_uid} "
                    f"returned_cell_count={len(cell_map)}",
                    project_id=project_id,
                )

                for interview_id in selected_interview_ids:
                    interview_key = str(interview_id)
                    cells.setdefault(interview_key, {})
                    current_cell = cells[interview_key].get(column_id)
                    current_value = ""
                    current_evidence: List[str] = []
                    current_locked = False
                    current_source = "framework"
                    if isinstance(current_cell, dict):
                        current_value = str(current_cell.get("value") or "").strip()
                        current_evidence = [str(item or "").strip() for item in (current_cell.get("evidence") or []) if str(item or "").strip()]
                        current_locked = bool(current_cell.get("locked"))
                        current_source = str(current_cell.get("source") or "framework")
                    elif current_cell is not None:
                        current_value = str(current_cell).strip()

                    if current_locked or (current_source == "manual" and current_value and current_value != "/"):
                        continue

                    raw_value = cell_map.get(interview_key)
                    if isinstance(raw_value, dict):
                        next_value = str(raw_value.get("value") or raw_value.get("answer") or raw_value.get("text") or "").strip()
                        next_evidence = [
                            str(item or "").strip()
                            for item in (raw_value.get("evidence") or raw_value.get("sources") or raw_value.get("quotes") or [])
                            if str(item or "").strip()
                        ]
                    else:
                        next_value = str(raw_value or "").strip()
                        next_evidence = []
                    if not next_value:
                        next_value = "/"
                    cells[interview_key][column_id] = {
                        "value": next_value,
                        "evidence": next_evidence[:3] or current_evidence,
                        "locked": bool(current_locked),
                        "source": "llm",
                    }

                summary_text = str(result.get("summary_text") or "").strip() or "/"
                column["summary_text"] = summary_text
                log(
                    f"CA final column applied questionnaire_id={resolved_questionnaire_id} "
                    f"group_label={group_label} question_uid={question_uid} interview_count={len(selected_interview_ids)}",
                    project_id=project_id,
                )
                log(
                    f"CA row summary generation done questionnaire_id={resolved_questionnaire_id} "
                    f"group_label={group_label} question_uid={question_uid} summary_len={len(summary_text) if summary_text != '/' else 0}",
                    project_id=project_id,
                )
                group_generated_count += 1

        group_elapsed = perf_counter() - group_started_at
        log(
            f"CA final group generation done questionnaire_id={resolved_questionnaire_id} "
            f"group_index={group_index} group_label={group_label} question_count={len(group_columns)} "
            f"generated_count={group_generated_count} cell_error_count={group_cell_error_count} "
            f"summary_error_count={group_summary_error_count} thread_count={thread_count} "
            f"elapsed_sec={group_elapsed:.2f}",
            project_id=project_id,
        )

    try:
        diff_payload = ModelClient.generate_ca_diff_row_for_interviews(
            project_context=project_context,
            questionnaire_title=questionnaire_name,
            questions=[
                {
                    "uid": str(column.get("question_uid") or column.get("column_id") or ""),
                    "order": int(column.get("order") or 0),
                    "text": str(column.get("question_text") or "").strip(),
                    "display_text": str(column.get("display_text") or "").strip(),
                    "title": str(column.get("title") or "").strip(),
                }
                for column in columns
            ],
            interview_blocks=interview_sources,
        )
        diff_row = diff_payload.get("diff_row") or {}
        if not isinstance(diff_row, dict):
            diff_row = {}
    except Exception as exc:
        log(f"CA diff row failed error={exc}", project_id=project_id)
        diff_row = {}
    final_payload["diff_row"] = diff_row
    final_payload["schema_version"] = CA_SCHEMA_VERSION

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
    total_elapsed = perf_counter() - final_generation_started_at
    log(
        f"CA final generation summary questionnaire_id={resolved_questionnaire_id} "
        f"group_count={len(grouped_columns)} column_count={len(columns)} interview_count={len(selected_interview_ids)} "
        f"elapsed_sec={total_elapsed:.2f}",
        project_id=project_id,
    )

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
