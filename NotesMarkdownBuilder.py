#!/usr/bin/env python3
"""
@Date: 2026-05-08
@Author: lixinyang

全文 Notes Markdown 组装器。

该模块负责从数据库中读取单个访谈的 Summary Notes、KBQ Notes 和智能纪要，
并将它们组装成可直接供模型使用或导出缓存的 Markdown 文本。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from DbAccess import DbAccess
from MinutesWorkflow import _render_minutes_text


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_FULL_NOTES_MD_NAME = "full_notes.md"


def _safe_json_loads(value: Any) -> Any:
    """
    尝试将字符串解析为 JSON。

    参数:
        value: 原始值，可能是字符串、字典或列表。

    返回:
        解析成功返回对象本身；解析失败时返回原值。
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    try:
        return json.loads(text)
    except Exception:
        return value


def _normalize_text(value: Any) -> str:
    """
    将任意值归一化为可展示的文本。

    参数:
        value: 原始值。

    返回:
        归一化后的字符串。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _load_minutes_payload_from_files(backup_dir: Path) -> Dict[str, Any] | None:
    """
    从访谈备份目录中读取智能纪要 JSON 文件。

    参数:
        backup_dir: 访谈备份目录。

    返回:
        读取到的 minutes JSON；未找到时返回 None。
    """
    candidates = [
        backup_dir / "minutes.json",
        backup_dir / "outline_minutes" / "minutes.json",
    ]
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _load_minutes_markdown_from_files(backup_dir: Path) -> str | None:
    """
    从访谈备份目录中读取智能纪要 Markdown 文本。

    参数:
        backup_dir: 访谈备份目录。

    返回:
        读取到的 Markdown 文本；未找到时返回 None。
    """
    candidates = [
        backup_dir / "minutes.txt",
        backup_dir / "outline_minutes" / "minutes.txt",
    ]
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if text:
            return text
    return None


def _render_kbq_notes_markdown(kbq_rows: List[Dict[str, Any]]) -> str:
    """
    将 KBQ 明细渲染为 Markdown。

    参数:
        kbq_rows: 单访谈 key BQ 明细列表。

    返回:
        Markdown 文本。
    """
    if not kbq_rows:
        return ""

    lines: List[str] = ["## B. KBQ Notes", ""]
    has_content = False
    for row in kbq_rows:
        bq_order = row.get("bq_order")
        bq_text = _normalize_text(row.get("bq_text"))
        if not bq_text:
            continue
        lines.append(f"### {bq_order}. {bq_text}" if bq_order is not None else f"### {bq_text}")
        note_json = _safe_json_loads(row.get("note_json"))
        dimension_notes = []
        if isinstance(note_json, dict):
            dimension_notes = note_json.get("dimension_notes") or []
        if isinstance(dimension_notes, list) and dimension_notes:
            for item in dimension_notes:
                if not isinstance(item, dict):
                    continue
                dimension = _normalize_text(item.get("dimension"))
                summary = _normalize_text(item.get("summary"))
                analysis = _normalize_text(item.get("analysis"))
                text = summary or analysis
                if dimension and text:
                    lines.append(f"- **{dimension}**：{text}")
                elif dimension:
                    lines.append(f"- **{dimension}**")
                elif text:
                    lines.append(f"- {text}")
                has_content = has_content or bool(text or dimension)
        else:
            summary = _normalize_text(note_json.get("summary")) if isinstance(note_json, dict) else ""
            analysis = _normalize_text(note_json.get("analysis")) if isinstance(note_json, dict) else ""
            text = summary or analysis
            if text:
                lines.append(text)
                has_content = True
        lines.append("")
    if not has_content:
        return ""
    return "\n".join(lines).strip()


def build_interview_full_notes_markdown(
    interview_id: int,
    cache_path: Path | None = None,
) -> str:
    """
    读取单个访谈的全文 Notes，并组装为 Markdown。

    参数:
        interview_id: 访谈 ID。
        cache_path: 可选缓存路径；若传入则将最终 Markdown 写入该文件。

    返回:
        全文 Notes Markdown；若三部分均为空，则返回空字符串。
    """
    interview = DbAccess.get_interview_by_id(interview_id)
    if not interview:
        return ""

    project_id = int(interview.get("parse_project_id") or 0)
    interview_name = _normalize_text(interview.get("file_name") or interview.get("name")) or f"interview_{interview_id}"
    lines: List[str] = [f"# 全文 Notes - {interview_name}", ""]

    note_content = _normalize_text(interview.get("note_content"))
    kbq_rows = DbAccess.fetch_key_bq_rows_by_interview(interview_id)

    minutes_payload = DbAccess.fetch_interview_minutes_by_interview(interview_id)
    if not minutes_payload:
        backup_dir = ROOT_DIR / "data" / f"project_{project_id}" / f"interview_{interview_id}"
        file_payload = _load_minutes_payload_from_files(backup_dir)
        if file_payload:
            minutes_payload = file_payload

    minutes_text = ""
    if isinstance(minutes_payload, dict):
        raw_minutes_json = minutes_payload.get("minutes_json")
        if isinstance(raw_minutes_json, str):
            raw_minutes_json = _safe_json_loads(raw_minutes_json)
        if isinstance(raw_minutes_json, dict):
            minutes_text = _render_minutes_text(raw_minutes_json)
        elif isinstance(minutes_payload, dict):
            minutes_text = _render_minutes_text(minutes_payload)
    if not minutes_text:
        backup_dir = ROOT_DIR / "data" / f"project_{project_id}" / f"interview_{interview_id}"
        minutes_text = _load_minutes_markdown_from_files(backup_dir) or ""

    has_any_content = False

    lines.append("## A. 访谈总览 Summary Notes")
    lines.append("")
    if note_content:
        lines.append(note_content)
        has_any_content = True
    else:
        lines.append("（暂无）")
    lines.append("")

    kbq_markdown = _render_kbq_notes_markdown(kbq_rows)
    if kbq_markdown:
        lines.append(kbq_markdown)
        lines.append("")
        has_any_content = True

    lines.append("## C. 智能纪要")
    lines.append("")
    if minutes_text:
        lines.append(minutes_text)
        has_any_content = True
    else:
        lines.append("（暂无）")
    lines.append("")

    markdown = "\n".join(lines).strip()
    if not has_any_content:
        markdown = ""

    if cache_path is not None and markdown:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(markdown + "\n", encoding="utf-8")

    return markdown


def build_project_full_notes_markdowns(
    project_id: int,
    interview_ids: List[int],
) -> List[Dict[str, Any]]:
    """
    批量组装项目下多个访谈的全文 Notes Markdown。

    参数:
        project_id: 项目 ID。
        interview_ids: 访谈 ID 列表。

    返回:
        包含 interview_id / name / meta / notes_markdown / cache_path 的字典列表。
    """
    results: List[Dict[str, Any]] = []
    for interview_id in interview_ids:
        interview = DbAccess.get_interview_by_id(interview_id)
        if not interview:
            continue
        cache_path = ROOT_DIR / "data" / f"project_{project_id}" / f"interview_{interview_id}" / DEFAULT_FULL_NOTES_MD_NAME
        markdown = build_interview_full_notes_markdown(interview_id, cache_path=cache_path)
        meta = {
            "hospital_city": interview.get("hospital_city"),
            "hospital_decile": interview.get("hospital_decile"),
            "doctor_level": interview.get("doctor_level"),
        }
        results.append(
            {
                "interview_id": int(interview_id),
                "name": _normalize_text(interview.get("name") or interview.get("file_name")) or f"interview_{interview_id}",
                "interview_date": interview.get("interview_date"),
                "meta": meta,
                "notes_markdown": markdown,
                "notes_md_path": str(cache_path),
            }
        )
    return results
