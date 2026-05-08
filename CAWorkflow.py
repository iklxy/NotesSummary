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
from InterviewLogger import log_interview
from Model import ModelClient
from ModelCA import generate_ca_cells_for_sub_point, generate_ca_dimensions
from NotesMarkdownBuilder import build_interview_full_notes_markdown, build_project_full_notes_markdowns
from MinutesWorkflow import _score_segment, _tokenize_for_search
from ProjectContext import load_project_context_by_id


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_CA_JSON_NAME = "ca_table.json"
DEFAULT_CA_FULL_NOTES_NAME = "full_notes.md"
DEFAULT_COLUMN_META_FIELDS = ["hospital_city", "hospital_decile", "doctor_level"]


def log(message: str, project_id: int | None = None) -> None:
    """
    输出 CA 进度日志。

    参数:
        message: 日志内容。
        project_id: 可选项目 ID。
    """
    log_interview("CA", project_id, message, subject_label="project_id")


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


def _build_ca_cache_path(project_id: int) -> Path:
    """
    获取 CA 表的本地缓存路径。
    """
    project_dir = _get_project_data_dir(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir / DEFAULT_CA_JSON_NAME


def generate_ca_table_for_project(
    project_id: int,
    interview_ids: Optional[List[int]] = None,
    column_meta_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    为指定项目生成 CA 表。
    """
    log(
        "开始生成 CA 表 "
        f"project_id={project_id} "
        f"interview_ids={interview_ids} "
        f"column_meta_fields={column_meta_fields}",
        project_id=project_id,
    )
    project = DbAccess.get_project_by_id(project_id)
    if not project:
        log("CA 表生成失败：项目不存在", project_id=project_id)
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
        f"项目背景加载完成，project_name={project_name}, selected_fields={selected_fields}",
        project_id=project_id,
    )

    requested_interview_ids = [int(item) for item in (interview_ids or []) if item is not None]
    interview_rows = DbAccess.fetch_completed_interviews_for_project(
        project_id=project_id,
        interview_ids=requested_interview_ids or None,
    )
    skipped_interview_ids: List[int] = []
    if requested_interview_ids:
        completed_id_set = {int(row.get("id")) for row in interview_rows}
        skipped_interview_ids = [item for item in requested_interview_ids if item not in completed_id_set]
    log(
        f"已完成访谈查询完成，返回 {len(interview_rows)} 条，skipped_interview_ids={skipped_interview_ids}",
        project_id=project_id,
    )
    if len(interview_rows) < 2:
        return {
            "success": False,
            "stage": "fetch_interviews",
            "detail": {
                "message": "访谈数量小于2，无法生成对应的CA表格",
                "skipped_interview_ids": skipped_interview_ids,
            },
            "project_id": project_id,
        }

    interviews_notes = _build_project_full_notes_markdown(
        project_id=project_id,
        interview_ids=[int(row["id"]) for row in interview_rows],
    )
    log(
        f"全文 Notes Markdown 组装完成，共 {len(interviews_notes)} 条",
        project_id=project_id,
    )
    interviews_notes_by_id = {item["interview_id"]: item for item in interviews_notes if item.get("interview_id") is not None}

    usable_interviews: List[Dict[str, Any]] = []
    for row in interview_rows:
        interview_id = int(row.get("id"))
        item = interviews_notes_by_id.get(interview_id, {})
        notes_markdown = str(item.get("notes_markdown") or "").strip()
        segments = _split_markdown_segments(notes_markdown)
        meta = {field: _normalize_meta_value(row.get(field)) for field in selected_fields}
        usable_interviews.append(
            {
                "interview_id": interview_id,
                "name": str(row.get("name") or item.get("name") or f"访谈 {interview_id}").strip(),
                "interview_date": row.get("interview_date"),
                "meta": meta,
                "notes_markdown": notes_markdown,
                "segments": segments,
            }
        )
        log(
            f"访谈 {interview_id} 可用全文 Notes 长度={len(notes_markdown)} 片段数={len(segments)}",
            project_id=project_id,
        )

    if len(usable_interviews) < 2:
        return {
            "success": False,
            "stage": "build_notes_markdown",
            "detail": {"message": "有效访谈数量小于2，无法生成 CA"},
            "project_id": project_id,
        }

    if not any(str(item.get("notes_markdown") or "").strip() for item in usable_interviews):
        return {
            "success": False,
            "stage": "build_notes_markdown",
            "detail": {
                "message": "当前选择集没有可用的全文 Notes Markdown",
                "skipped_interview_ids": skipped_interview_ids,
            },
            "project_id": project_id,
        }

    try:
        log(
            f"开始生成 CA 维度骨架，访谈数={len(usable_interviews)}",
            project_id=project_id,
        )
        outline_payload = ModelClient.generate_ca_dimensions(
            project_context=project_context,
            interviews_notes=usable_interviews,
        )
    except Exception as exc:
        error_message = f"generate ca dimensions failed: {exc}"
        log(error_message, project_id=project_id)
        return {
            "success": False,
            "stage": "generate_dimensions",
            "detail": {
                "message": error_message,
                "traceback": traceback.format_exc(),
            },
            "project_id": project_id,
        }

    dimensions = _normalize_dimension_items(outline_payload.get("dimensions"))
    if not dimensions:
        log("CA 维度骨架生成后为空", project_id=project_id)
        return {
            "success": False,
            "stage": "generate_dimensions",
            "detail": {
                "message": "no ca dimensions generated",
                "skipped_interview_ids": skipped_interview_ids,
            },
            "project_id": project_id,
        }

    interview_id_list = [int(item["interview_id"]) for item in usable_interviews]
    log(
        f"CA 维度骨架生成完成，维度数={len(dimensions)}，开始逐小点生成单元格",
        project_id=project_id,
    )
    for dimension in dimensions:
        dimension_title = str(dimension.get("title") or "").strip()
        dimension_summary = str(dimension.get("summary") or "").strip()
        for sub_point in dimension.get("sub_points") or []:
            sub_title = str(sub_point.get("title") or "").strip()
            sub_summary = str(sub_point.get("summary") or "").strip()
            query_text = "\n".join(part for part in [dimension_title, dimension_summary, sub_title, sub_summary] if part)
            log(
                f"开始生成 CA 单元格 dimension={dimension_title} sub_point={sub_title}",
                project_id=project_id,
            )

            interview_blocks: List[Dict[str, Any]] = []
            for item in usable_interviews:
                notes_markdown = str(item.get("notes_markdown") or "").strip()
                segments = _retrieve_segments_from_markdown(
                    segments=item.get("segments") or [],
                    query_text=query_text,
                    top_k=6,
                )
                interview_blocks.append(
                    {
                        "interview_id": int(item["interview_id"]),
                        "name": item.get("name"),
                        "meta": item.get("meta"),
                        "segments": segments,
                        "notes_markdown": notes_markdown,
                    }
                )

            try:
                cell_payload = ModelClient.generate_ca_cells_for_sub_point(
                    project_context=project_context,
                    dimension_title=dimension_title,
                    dimension_summary=dimension_summary,
                    sub_point_title=sub_title,
                    sub_point_summary=sub_summary,
                    interview_blocks=interview_blocks,
                )
                cell_map = cell_payload.get("cells") or {}
            except Exception as exc:
                log(
                    f"CA 小点 {dimension_title} / {sub_title} 生成失败：{exc}",
                    project_id=project_id,
                )
                cell_map = {str(interview_id): "生成失败" for interview_id in interview_id_list}

            if not isinstance(cell_map, dict):
                cell_map = {}

            normalized_cells: Dict[str, str] = {}
            for interview_id in interview_id_list:
                key = str(interview_id)
                value = str(cell_map.get(key) or "").strip()
                if not value:
                    value = "/"
                normalized_cells[key] = value

            sub_point["cells"] = normalized_cells
            log(
                f"完成 CA 单元格 dimension={dimension_title} sub_point={sub_title}",
                project_id=project_id,
            )

    ca_payload: Dict[str, Any] = {
        "project_id": project_id,
        "project_name": project_name,
        "column_meta_fields": selected_fields,
        "selected_interview_ids": interview_id_list,
        "requested_interview_ids": requested_interview_ids,
        "skipped_interview_ids": skipped_interview_ids,
        "interviews": [
            {
                "interview_id": item["interview_id"],
                "name": item["name"],
                "interview_date": item.get("interview_date"),
                "meta": item.get("meta") or {},
            }
            for item in usable_interviews
        ],
        "dimensions": dimensions,
        "status": "done",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "project_context": project_context if isinstance(project_context, dict) else None,
    }

    cache_path = _build_ca_cache_path(project_id)
    log(f"开始写入 CA 缓存文件：{cache_path}", project_id=project_id)
    safe_ca_payload = _json_safe_value(ca_payload)
    cache_path.write_text(json.dumps(safe_ca_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        log("开始写入 CA 数据库表", project_id=project_id)
        DbAccess.upsert_ca_table(
            project_id=project_id,
            ca_json=safe_ca_payload,
            status="done",
            error_message=None,
            generated_at=safe_ca_payload["generated_at"],
        )
    except Exception as exc:
        log(
            f"CA 表写库失败：{exc}\n{traceback.format_exc()}",
            project_id=project_id,
        )
        return {
            "success": False,
            "stage": "upsert_ca_table",
            "detail": {
                "message": f"upsert ca table failed: {exc}",
                "traceback": traceback.format_exc(),
                "skipped_interview_ids": skipped_interview_ids,
            },
            "project_id": project_id,
        }

    return {
        "success": True,
        "project_id": project_id,
        "generated_at": ca_payload["generated_at"],
        "column_meta_fields": selected_fields,
        "interview_count": len(usable_interviews),
        "dimension_count": len(dimensions),
        "requested_interview_ids": requested_interview_ids,
        "skipped_interview_ids": skipped_interview_ids,
        "ca_json": safe_ca_payload,
        "ca_json_path": str(cache_path),
    }
