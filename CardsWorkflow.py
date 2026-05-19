#!/usr/bin/env python3
"""
@Date: 2026-05-19
@Author: lixinyang

全文模块总结卡片生成工作流。

该模块负责把“智能纪要 minutes -> LLM -> 全文模块总结卡片”
这条链路串起来，并将最终结果写入 `bh_project_interview_cards`
与 `bh_project_interview_cards_items`。
"""

from __future__ import annotations

import json
import re
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from DbAccess import DbAccess
from InterviewLogger import log_interview
from Model import ModelClient
from ModelNotes import generate_cards_from_minutes
from ProjectContext import load_project_context_by_id


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_MINUTES_JSON_NAME = "minutes.json"
DEFAULT_MINUTES_TXT_NAME = "minutes.txt"


def _get_data_root() -> Path:
    return ROOT_DIR / "data"


def _get_interview_backup_dir(project_id: int, interview_id: int) -> Path:
    return _get_data_root() / f"project_{project_id}" / f"interview_{interview_id}"


def _build_project_context_block(project_context: Optional[str]) -> str:
    if not project_context:
        return ""
    cleaned = str(project_context).strip()
    if not cleaned:
        return ""
    return f"【项目背景】\n{cleaned}\n\n"


def _build_interview_context_block(interview: Dict[str, Any] | None) -> str:
    if not isinstance(interview, dict):
        return ""
    lines: List[str] = ["【访谈背景】"]
    name = str(interview.get("name") or "").strip()
    if name:
        lines.append(f"访谈名称：{name}")
    interview_date = str(interview.get("interview_date") or "").strip()
    if interview_date:
        lines.append(f"访谈日期：{interview_date}")
    doctor_level = str(interview.get("doctor_level") or "").strip()
    if doctor_level:
        lines.append(f"医生级别：{doctor_level}")
    hospital = str(interview.get("hospital") or "").strip()
    if hospital:
        lines.append(f"医院：{hospital}")
    department = str(interview.get("department") or "").strip()
    if department:
        lines.append(f"科室：{department}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines) + "\n\n"


def _normalize_json_payload(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _load_minutes_payload_from_files(project_id: int, interview_id: int) -> Dict[str, Any] | None:
    backup_dir = _get_interview_backup_dir(project_id, interview_id)
    if not backup_dir.exists():
        return None

    candidate_paths: List[Path] = [
        backup_dir / DEFAULT_MINUTES_JSON_NAME,
        backup_dir / "outline_minutes" / DEFAULT_MINUTES_JSON_NAME,
    ]
    for path in sorted(backup_dir.rglob(DEFAULT_MINUTES_JSON_NAME)):
        if path not in candidate_paths:
            candidate_paths.append(path)

    for path in candidate_paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _render_minutes_text(minutes_payload: Dict[str, Any]) -> str:
    raw_minutes_text = str(minutes_payload.get("minutes_text") or minutes_payload.get("raw_minutes_text") or "").strip()
    if raw_minutes_text:
        return raw_minutes_text

    lines: List[str] = []
    document_title = str(minutes_payload.get("document_title") or "").strip()
    if document_title:
        lines.append(f"# {document_title}")
        lines.append("")

    core_summary = str(minutes_payload.get("core_summary") or "").strip()
    if core_summary:
        lines.append("## 核心总结")
        lines.append(core_summary)
        lines.append("")

    sections = minutes_payload.get("sections") or []
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict):
                continue
            section_order = section.get("order")
            section_title = str(section.get("title") or "").strip()
            section_summary = str(section.get("summary") or section.get("content") or "").strip()
            if section_title:
                lines.append(
                    f"## 第{section_order}部分：{section_title}" if section_order is not None else f"## {section_title}"
                )
            if section_summary:
                lines.append(section_summary)
            items = section.get("items") or []
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    item_order = item.get("order")
                    item_title = str(item.get("title") or "").strip()
                    item_summary = str(item.get("summary") or item.get("content") or "").strip()
                    prefix = f"{item_order}. " if item_order is not None else "- "
                    if item_title and item_summary:
                        lines.append(f"{prefix}{item_title}：{item_summary}")
                    elif item_title:
                        lines.append(f"{prefix}{item_title}")
                    elif item_summary:
                        lines.append(f"{prefix}{item_summary}")
            lines.append("")
    return "\n".join(lines).strip()


def _fetch_minutes_payload(interview_id: int, project_id: int) -> Dict[str, Any] | None:
    row = DbAccess.fetch_interview_minutes_by_interview(interview_id)
    if row:
        minutes_json = _normalize_json_payload(row.get("minutes_json"))
        if isinstance(minutes_json, dict):
            minutes_json.setdefault("status", row.get("status"))
            minutes_json.setdefault("error_message", row.get("error_message"))
            minutes_json.setdefault("generated_at", row.get("generated_at"))
            return minutes_json

    fallback_payload = _load_minutes_payload_from_files(project_id, interview_id)
    if fallback_payload is not None:
        return fallback_payload
    return None


def _upsert_cards_parent(
    project_id: int,
    interview_id: int,
    status: str,
    error_message: Optional[str] = None,
) -> Dict[str, Any]:
    sql = """
        INSERT INTO bh_project_interview_cards
            (project_id, project_interview_id, status, error_message)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            project_id = VALUES(project_id),
            status = VALUES(status),
            error_message = VALUES(error_message)
    """
    conn = DbAccess.get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (project_id, interview_id, status, error_message))
            cursor.execute(
                """
                SELECT
                    id,
                    project_id,
                    project_interview_id,
                    status,
                    error_message,
                    created_at,
                    updated_at
                FROM bh_project_interview_cards
                WHERE project_interview_id = %s
                LIMIT 1
                """,
                (interview_id,),
            )
            row = cursor.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return row or {}


def _replace_cards_items(
    cards_id: int,
    project_id: int,
    project_interview_id: int,
    cards: List[Dict[str, Any]],
) -> int:
    delete_sql = """
        DELETE FROM bh_project_interview_cards_items
        WHERE cards_id = %s
    """
    insert_sql = """
        INSERT INTO bh_project_interview_cards_items
            (cards_id, project_id, project_interview_id, card_order, card_title, card_summary,
             generated_json, final_json, review_status, review_comment, reviewed_by, reviewed_at, updated_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    conn = DbAccess.get_connection()
    inserted = 0
    try:
        with conn.cursor() as cursor:
            cursor.execute(delete_sql, (cards_id,))
            for index, card in enumerate(cards, start=1):
                order_raw = card.get("order") if card.get("order") is not None else card.get("card_order")
                try:
                    order_value = int(order_raw) if order_raw is not None else index
                except Exception:
                    order_value = index
                card_type = str(card.get("card_type") or ("overview" if order_value == 0 else "topic")).strip().lower()
                title = str(card.get("title") or "").strip()
                if not title:
                    title = "全文总览" if card_type == "overview" else f"卡片 {index}"
                summary = str(card.get("summary") or "").strip()
                points_raw = card.get("points") or []
                points: List[str] = []
                if isinstance(points_raw, list):
                    for point in points_raw:
                        point_text = str(point).strip()
                        if point_text:
                            points.append(point_text)
                elif isinstance(points_raw, str):
                    points = [point.strip() for point in points_raw.splitlines() if point.strip()]
                if not summary and points:
                    summary = "\n".join(points)
                layout_span_raw = card.get("layout_span") if card.get("layout_span") is not None else card.get("span")
                try:
                    layout_span = int(layout_span_raw) if layout_span_raw is not None else (3 if card_type == "overview" else 1)
                except Exception:
                    layout_span = 3 if card_type == "overview" else 1
                generated_json = {
                    "order": order_value,
                    "card_type": card_type,
                    "layout_span": layout_span,
                    "title": title,
                    "summary": summary,
                    "tags": card.get("tags") or [],
                    "points": points,
                    "source_sections": card.get("source_sections") or [],
                }
                cursor.execute(
                    insert_sql,
                    (
                        cards_id,
                        project_id,
                        project_interview_id,
                        order_value,
                        title,
                        summary,
                        json.dumps(generated_json, ensure_ascii=False),
                        json.dumps(generated_json, ensure_ascii=False),
                        "pending",
                        None,
                        None,
                        None,
                        None,
                    ),
                )
                inserted += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return inserted


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _trim_text(text: str, limit: int) -> str:
    cleaned = _normalize_text(text)
    if not cleaned:
        return ""
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip("，,。；;：:、 ") + "…"


def _collect_points_from_section(section: Dict[str, Any]) -> List[str]:
    points: List[str] = []
    section_summary = _normalize_text(section.get("summary") or section.get("content"))
    if section_summary:
        for part in re.split(r"[。！？!?；;\n]+", section_summary):
            part_text = _normalize_text(part)
            if part_text:
                points.append(_trim_text(part_text, 12))
            if len(points) >= 5:
                break

    if len(points) < 5:
        items = section.get("items") or []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_title = _normalize_text(item.get("title"))
                item_summary = _normalize_text(item.get("summary") or item.get("content"))
                candidate = item_title or item_summary
                if not candidate and item_title and item_summary:
                    candidate = f"{item_title}：{item_summary}"
                if candidate:
                    points.append(_trim_text(candidate, 12))
                if len(points) >= 5:
                    break

    unique_points: List[str] = []
    seen: set[str] = set()
    for point in points:
        normalized = re.sub(r"\s+", "", point)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_points.append(point)
        if len(unique_points) >= 5:
            break
    return unique_points


def _build_fallback_cards_from_minutes(minutes_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    当 LLM 生成失败时，基于 minutes 结构构造一组可展示的兜底卡片。
    """
    fallback_cards: List[Dict[str, Any]] = []
    minutes_text = _render_minutes_text(minutes_payload)
    core_summary = _normalize_text(minutes_payload.get("core_summary"))
    if not core_summary:
        core_summary = _trim_text(
            re.sub(r"\s+", "", minutes_text.replace("\n", " ")),
            100,
        )
    fallback_cards.append(
        {
            "order": 0,
            "card_type": "overview",
            "layout_span": 3,
            "title": "全文总览",
            "summary": core_summary,
            "tags": ["总览"],
            "points": [],
            "source_sections": [],
        }
    )

    sections = minutes_payload.get("sections") or []
    topic_cards: List[Dict[str, Any]] = []
    if isinstance(sections, list):
        for index, section in enumerate(sections, start=1):
            if not isinstance(section, dict):
                continue
            section_title = _normalize_text(section.get("title"))
            if not section_title:
                section_title = f"第{section.get('order') or index}部分"
            section_summary = _normalize_text(section.get("summary") or section.get("content"))
            points = _collect_points_from_section(section)
            topic_cards.append(
                {
                    "order": index,
                    "card_type": "topic",
                    "layout_span": 1,
                    "title": section_title,
                    "summary": section_summary or ("\n".join(points) if points else ""),
                    "tags": [section_title] if section_title else [],
                    "points": points,
                    "source_sections": [section_title] if section_title else [],
                }
            )

    if not topic_cards:
        highlights = minutes_payload.get("highlights") or []
        if isinstance(highlights, list):
            for index, item in enumerate(highlights[:6], start=1):
                highlight_text = _normalize_text(item)
                if not highlight_text:
                    continue
                topic_cards.append(
                    {
                        "order": index,
                        "card_type": "topic",
                        "layout_span": 1,
                        "title": _trim_text(highlight_text, 18) or f"要点 {index}",
                        "summary": highlight_text,
                        "tags": ["高亮"],
                        "points": [_trim_text(highlight_text, 12)],
                        "source_sections": [],
                    }
                )

    if not topic_cards:
        action_items = minutes_payload.get("action_items") or []
        if isinstance(action_items, list):
            for index, item in enumerate(action_items[:6], start=1):
                if isinstance(item, dict):
                    candidate = _normalize_text(item.get("title") or item.get("summary") or item.get("content"))
                else:
                    candidate = _normalize_text(item)
                if not candidate:
                    continue
                topic_cards.append(
                    {
                        "order": index,
                        "card_type": "topic",
                        "layout_span": 1,
                        "title": _trim_text(candidate, 18) or f"事项 {index}",
                        "summary": candidate,
                        "tags": ["待办"],
                        "points": [_trim_text(candidate, 12)],
                        "source_sections": [],
                    }
                )

    fallback_cards.extend(topic_cards[:8])
    return fallback_cards


def generate_cards_for_interview(
    interview_id: int,
    project_context: Optional[str] = None,
) -> Dict[str, Any]:
    """
    基于智能纪要生成全文模块总结卡片。
    """
    log_interview("CARDS", interview_id, "generate cards start")
    try:
        interview = DbAccess.get_interview_by_id(interview_id)
        if not interview:
            raise RuntimeError("interview not found")

        project_id = int(interview.get("parse_project_id") or 0)
        if project_id <= 0:
            raise RuntimeError("project id missing from interview")

        minutes_payload = _fetch_minutes_payload(interview_id, project_id)
        if not isinstance(minutes_payload, dict):
            raise RuntimeError("no minutes payload found")

        minutes_text = _render_minutes_text(minutes_payload)
        if not minutes_text.strip():
            raise RuntimeError("minutes text is empty")

        if project_context is None:
            try:
                project_context = load_project_context_by_id(project_id)
            except Exception:
                project_context = None

        cards_row = _upsert_cards_parent(project_id, interview_id, status="generating", error_message=None)
        cards_id = int(cards_row.get("id") or 0)
        if cards_id <= 0:
            raise RuntimeError("create cards parent failed")

        project_context_block = _build_project_context_block(project_context)
        interview_context_block = _build_interview_context_block(interview)
        cards_payload: Dict[str, Any] = {}
        cards: List[Dict[str, Any]] = []
        generation_warning: Optional[str] = None
        try:
            cards_payload = generate_cards_from_minutes(
                ModelClient.generate,
                project_context_block=project_context_block,
                minutes_payload=minutes_payload,
                interview_context_block=interview_context_block,
            )
            cards = cards_payload.get("cards") or []
            if not isinstance(cards, list) or not cards:
                raise RuntimeError("no cards generated")
            cards = [card for card in cards if isinstance(card, dict)]
        except Exception as exc:
            generation_warning = f"LLM 生成失败，已使用 minutes 兜底生成卡片：{exc}"
            log_interview("CARDS", interview_id, generation_warning)
            cards = _build_fallback_cards_from_minutes(minutes_payload)
            cards_payload = {
                "cards": cards,
                "llm_raw_output": None,
                "fallback": True,
                "warning": generation_warning,
            }
        if not cards:
            raise RuntimeError("no cards generated")

        inserted = _replace_cards_items(
            cards_id=cards_id,
            project_id=project_id,
            project_interview_id=interview_id,
            cards=cards,
        )
        if inserted <= 0:
            raise RuntimeError("insert cards failed")

        _upsert_cards_parent(project_id, interview_id, status="done", error_message=None)
        log_interview("CARDS", interview_id, f"generate cards done cards={inserted}")
        return {
            "success": True,
            "interview_id": interview_id,
            "project_id": project_id,
            "cards_id": cards_id,
            "generated": len(cards),
            "inserted": inserted,
            "cards": cards,
            "minutes_text_len": len(minutes_text),
            "llm_raw_output": cards_payload.get("llm_raw_output"),
            "fallback": bool(cards_payload.get("fallback")),
            "warning": cards_payload.get("warning") or generation_warning,
        }
    except Exception as exc:
        error_message = f"generate cards failed: {exc}"
        try:
            interview = DbAccess.get_interview_by_id(interview_id)
            if interview:
                project_id = int(interview.get("parse_project_id") or 0)
                if project_id > 0:
                    _upsert_cards_parent(project_id, interview_id, status="failed", error_message=error_message)
        except Exception:
            pass
        log_interview("CARDS", interview_id, f"generate cards failed error={exc}\n{traceback.format_exc()}")
        return {
            "success": False,
            "interview_id": interview_id,
            "generated": 0,
            "inserted": 0,
            "message": error_message,
        }
