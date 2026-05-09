#!/usr/bin/env python3
"""
@Date: 2026-05-06
@Author: lixinyang

智能纪要生成工作流。

该模块负责把“清洗后的 summary 全文 -> 智能纪要大纲 -> 逐小点检索 -> 逐小点总结”
这条链路串起来，并将最终结果落到 `bh_project_interview_minutes`。

它的定位是用来替代原先按题生成 Delivery Notes 的流程，但保留相同的触发时机：
ASR 与 summary 完成之后，后台自动生成可直接展示的智能纪要。
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
from ProjectContext import load_project_context_by_id


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_MINUTES_JSON_NAME = "minutes.json"
DEFAULT_MINUTES_TXT_NAME = "minutes.txt"
DEFAULT_SUMMARY_TEXT_NAME = "summary_full_text.txt"


def log(message: str, interview_id: int | None = None) -> None:
    """
    输出统一前缀的进度日志。

    参数:
        message: 需要打印的日志内容。
    """

    log_interview("MINUTES", interview_id, message)


def _get_data_root() -> Path:
    """
    获取本地 data 目录。

    返回:
        SummaryNotes 根目录下的 `data` 路径。
    """
    return ROOT_DIR / "data"


def _get_interview_backup_dir(project_id: int, interview_id: int) -> Path:
    """
    获取访谈对应的 data 备份目录。

    参数:
        project_id: 项目 ID。
        interview_id: 访谈 ID。

    返回:
        目录路径 `data/project_{project_id}/interview_{interview_id}`。
    """
    return _get_data_root() / f"project_{project_id}" / f"interview_{interview_id}"


def _build_project_context_block(project_context: Optional[str]) -> str:
    """
    将项目背景包装成统一的 prompt 区块。

    参数:
        project_context: 项目背景文本。

    返回:
        可直接注入 prompt 的背景块。
    """
    if not project_context:
        return ""
    cleaned = project_context.strip()
    if not cleaned:
        return ""
    return f"【项目背景】\n{cleaned}\n\n"


def _build_interview_context_block(interview_context: Optional[Any]) -> str:
    """
    将访谈背景对象包装成统一的 prompt 区块。

    参数:
        interview_context: 访谈背景对象或字符串。

    返回:
        可直接注入 prompt 的背景块。
    """
    if not interview_context:
        return ""
    if isinstance(interview_context, str):
        cleaned = interview_context.strip()
        if not cleaned:
            return ""
        return f"【访谈背景】\n{cleaned}\n\n"
    try:
        return f"【访谈背景】\n{json.dumps(interview_context, ensure_ascii=False, indent=2)}\n\n"
    except Exception:
        return f"【访谈背景】\n{str(interview_context)}\n\n"


def _build_minutes_output_paths(backup_dir: Path) -> Tuple[Path, Path]:
    """
    根据访谈备份目录构造智能纪要输出路径。

    参数:
        backup_dir: 访谈备份目录。

    返回:
        (json_path, txt_path) 二元组。
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir / DEFAULT_MINUTES_JSON_NAME, backup_dir / DEFAULT_MINUTES_TXT_NAME


def _build_summary_source_path(backup_dir: Path) -> Path:
    """
    获取用于保存拼接后 summary 全文的路径。

    参数:
        backup_dir: 访谈备份目录。

    返回:
        summary 全文落盘路径。
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir / DEFAULT_SUMMARY_TEXT_NAME


def _build_summary_segments(summary_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    将数据库里的 summary 明细行归一化为检索片段。

    参数:
        summary_rows: bh_project_interview_summary 查询结果。

    返回:
        可用于本地检索的片段列表。
    """
    segments: List[Dict[str, Any]] = []
    for idx, row in enumerate(summary_rows, start=1):
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        speaker = str(row.get("speaker") or "summary").strip() or "summary"
        timestamp = str(row.get("timestamp") or "").strip()
        summary_id = row.get("id") or idx
        segments.append(
            {
                "summary_id": int(summary_id),
                "speaker": speaker,
                "timestamp": timestamp or None,
                "text": text,
            }
        )
    return segments


def _build_summary_full_text(summary_segments: List[Dict[str, Any]]) -> str:
    """
    将 summary 片段拼接成全文。

    参数:
        summary_segments: 归一化后的 summary 片段列表。

    返回:
        按顺序拼接后的全文文本。
    """
    lines: List[str] = []
    for segment in summary_segments:
        speaker = str(segment.get("speaker") or "summary").strip() or "summary"
        timestamp = str(segment.get("timestamp") or "").strip()
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        prefix_parts: List[str] = []
        if timestamp:
            prefix_parts.append(f"[{timestamp}]")
        if speaker:
            prefix_parts.append(f"{speaker}:")
        prefix = " ".join(prefix_parts).strip()
        lines.append(f"{prefix} {text}".strip() if prefix else text)
        lines.append("")
    return "\n".join(lines).strip()


def _normalize_minutes_text_fragment(value: Any) -> str:
    """
    将智能纪要中的单段文本归一化为普通可读文本。

    主要用于清理模型偶尔返回的 JSON-like 片段，避免把大括号、字段名
    直接写入 minutes.json / minutes.txt。

    参数:
        value: 原始文本或其他类型值。

    返回:
        归一化后的纯文本字符串。
    """
    if value is None:
        return ""

    text = str(value).strip()
    if not text:
        return ""

    if text.startswith("{") and text.endswith("}"):
        try:
            payload = json.loads(text)
        except Exception:
            return text

        if isinstance(payload, dict):
            for key in ("core_summary", "核心总结", "summary"):
                candidate = payload.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()

            points = payload.get("分点要点") or payload.get("items") or payload.get("points")
            if isinstance(points, list):
                flattened_points: List[str] = []
                for item in points:
                    if isinstance(item, str) and item.strip():
                        flattened_points.append(item.strip())
                if flattened_points:
                    return "\n".join(f"· {item}" for item in flattened_points)

            conclusion = payload.get("待办/结论") or payload.get("结论")
            if isinstance(conclusion, str) and conclusion.strip():
                return conclusion.strip()

        return text

    return text


def _tokenize_for_search(text: str) -> List[str]:
    """
    将文本拆成适合做本地检索的 token。

    参数:
        text: 待拆分文本。

    返回:
        token 列表。
    """
    normalized = text.lower()
    tokens = re.findall(r"[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)*|[\u4e00-\u9fff]{2,}", normalized)
    extra_tokens: List[str] = []
    for token in tokens:
        if len(token) <= 6:
            extra_tokens.append(token)
    return tokens + extra_tokens


def _score_segment(segment_text: str, query_text: str) -> float:
    """
    根据 token 重叠度给单条片段打分。

    参数:
        segment_text: 片段文本。
        query_text: 检索 query。

    返回:
        相关性分数。
    """
    segment_tokens = _tokenize_for_search(segment_text)
    query_tokens = _tokenize_for_search(query_text)
    if not segment_tokens or not query_tokens:
        return 0.0

    segment_token_set = set(segment_tokens)
    query_token_set = set(query_tokens)
    overlap = segment_token_set & query_token_set

    score = float(len(overlap))
    for token in overlap:
        if len(token) >= 4:
            score += 0.5
    if query_text and query_text in segment_text:
        score += 5.0
    if segment_text and any(token in segment_text for token in query_token_set):
        score += 1.0
    return score


def _retrieve_segments_from_summary(
    summary_segments: List[Dict[str, Any]],
    query_text: str,
    top_k: int,
) -> List[Dict[str, Any]]:
    """
    从 summary 片段中检索最相关的若干段。

    参数:
        summary_segments: summary 片段列表。
        query_text: 检索 query。
        top_k: 返回片段数上限。

    返回:
        适合直接传给纪要生成步骤的片段字典列表。
    """
    ranked: List[Tuple[float, Dict[str, Any]]] = []
    for seg in summary_segments:
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


def _normalize_outline_sections(raw_outline: Any) -> List[Dict[str, Any]]:
    """
    将模型生成的大纲归一化为统一结构。

    参数:
        raw_outline: 模型返回的 outline 列表。

    返回:
        标准化后的章节列表。
    """
    if not isinstance(raw_outline, list):
        return []

    sections: List[Dict[str, Any]] = []
    for section_index, section in enumerate(raw_outline, start=1):
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or section.get("name") or "").strip()
        summary = _normalize_minutes_text_fragment(section.get("summary") or section.get("content"))

        items: List[Dict[str, Any]] = []
        raw_items = section.get("items") or section.get("points") or section.get("children") or []
        if isinstance(raw_items, list):
            for item_index, item in enumerate(raw_items, start=1):
                if not isinstance(item, dict):
                    continue
                item_title = str(item.get("title") or item.get("name") or "").strip()
                item_summary = _normalize_minutes_text_fragment(item.get("summary") or item.get("content"))
                if not item_title and not item_summary:
                    continue
                items.append(
                    {
                        "order": int(item.get("order") or item_index),
                        "title": item_title,
                        "summary": item_summary,
                    }
                )

        if not title and not summary and not items:
            continue
        sections.append(
            {
                "order": int(section.get("order") or section_index),
                "title": title,
                "summary": summary,
                "items": items,
            }
        )
    return sections


def _render_minutes_text(payload: Dict[str, Any]) -> str:
    """
    将智能纪要结果渲染为可读文本。

    参数:
        payload: 智能纪要 JSON 对象。

    返回:
        适合人工查看的 Markdown 风格文本。
    """
    lines: List[str] = []
    document_title = str(payload.get("document_title") or "").strip()
    if document_title:
        lines.append(f"# {document_title}")
        lines.append("")

    core_summary = str(payload.get("core_summary") or "").strip()
    if core_summary:
        lines.append("## 核心总结")
        lines.append(core_summary)
        lines.append("")

    highlights = payload.get("highlights") or []
    if isinstance(highlights, list) and highlights:
        lines.append("## 关键高亮")
        for idx, highlight in enumerate(highlights, start=1):
            highlight_text = str(highlight or "").strip()
            if highlight_text:
                lines.append(f"- {idx}. {highlight_text}")
        lines.append("")

    sections = payload.get("sections") or []
    if not isinstance(sections, list):
        return "\n".join(lines).strip()

    for section in sections:
        if not isinstance(section, dict):
            continue
        section_order = section.get("order")
        section_title = str(section.get("title") or "").strip()
        section_summary = str(section.get("summary") or "").strip()
        if section_title:
            if section_order is not None:
                lines.append(f"## 第{section_order}部分：{section_title}")
            else:
                lines.append(f"## {section_title}")

        items = section.get("items") or []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_order = item.get("order")
                item_title = str(item.get("title") or "").strip()
                item_summary = str(item.get("summary") or "").strip()
                prefix = f"{item_order}. " if item_order is not None else "- "
                if item_title and item_summary:
                    lines.append(f"{prefix}{item_title}：{item_summary}")
                elif item_title:
                    lines.append(f"{prefix}{item_title}")
                elif item_summary:
                    lines.append(f"{prefix}{item_summary}")
        if section_summary:
            lines.append(section_summary)
        lines.append("")

    return "\n".join(lines).strip()


def _extract_minutes_outline_from_summary_text(
    backup_dir: Path,
    summary_rows: List[Dict[str, Any]],
    project_context: Optional[str] = None,
) -> Dict[str, Any]:
    """
    从清洗后的 summary 明细生成智能纪要大纲。

    参数:
        backup_dir: 访谈备份目录。
        summary_rows: bh_project_interview_summary 的原始记录。
        project_context: 可选项目背景文本。

    返回:
        标准化后的 outline payload。
    """
    summary_segments = _build_summary_segments(summary_rows)
    full_text = _build_summary_full_text(summary_segments)
    if not full_text:
        raise ValueError("summary transcript text is empty")

    source_text_path = _build_summary_source_path(backup_dir)
    source_text_path.write_text(full_text + "\n", encoding="utf-8")

    outline_payload = ModelClient.generate_minutes_outline_from_transcript(
        transcript_text=full_text,
        project_context=project_context,
    )
    outline_payload["source_file"] = str(source_text_path)
    outline_payload["input_path"] = str(backup_dir)
    outline_payload["source_text_path"] = str(source_text_path)
    outline_payload["source_text_len"] = len(full_text)

    outline_json_path, outline_txt_path = _build_minutes_output_paths(backup_dir / "outline_minutes")
    outline_json_path.write_text(json.dumps(outline_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    outline_txt_path.write_text(_render_minutes_text(outline_payload) + "\n", encoding="utf-8")
    outline_payload["outline_json_path"] = str(outline_json_path)
    outline_payload["outline_txt_path"] = str(outline_txt_path)
    return outline_payload


def _build_minutes_sections(
    summary_segments: List[Dict[str, Any]],
    outline_sections: List[Dict[str, Any]],
    model_client: Optional[ModelClient],
    project_context: Optional[str],
    interview_context: Optional[Any],
    top_k: int,
    interview_id: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    根据 outline 逐小点生成智能纪要正文。

    参数:
        summary_segments: 清洗后的 summary 片段列表。
        outline_sections: outline 章节列表。
        model_client: 已初始化的大模型客户端；若为 None 则降级为直出占位文本。
        project_context: 可选项目背景文本。
        interview_context: 可选访谈背景摘要。
        top_k: 每个小点检索 summary 片段数量上限。

    返回:
        (minutes_sections, generated_count) 二元组。
    """
    minutes_sections: List[Dict[str, Any]] = []
    generated_count = 0

    for section in outline_sections:
        if not isinstance(section, dict):
            continue

        section_order = int(section.get("order") or len(minutes_sections) + 1)
        section_title = str(section.get("title") or "").strip()
        section_summary = str(section.get("summary") or "").strip()
        section_items: List[Dict[str, Any]] = []

        raw_items = section.get("items") or []
        if isinstance(raw_items, list):
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                item_order = int(item.get("order") or len(section_items) + 1)
                item_title = str(item.get("title") or "").strip()
                item_summary = _normalize_minutes_text_fragment(item.get("summary"))
                if not item_title and not item_summary:
                    continue

                query_parts = [section_title, section_summary, item_title, item_summary]
                query_text = "\n".join(part for part in query_parts if part)
                segments = _retrieve_segments_from_summary(
                    summary_segments=summary_segments,
                    query_text=query_text,
                    top_k=top_k,
                )
                log(
                    f"章节 {section_order} 小点 {item_order} 检索到 {len(segments)} 条相关片段",
                    interview_id=interview_id,
                )

                if model_client is None:
                    point_summary = item_summary or section_summary or "当前访谈中信息不足"
                else:
                    point_summary = model_client.generate_minutes_item_summary(
                        section_title=section_title,
                        section_summary=section_summary,
                        item_title=item_title,
                        item_summary=item_summary,
                        segments=segments,
                        project_context=project_context,
                        interview_context=interview_context,
                    )
                point_summary = _normalize_minutes_text_fragment(point_summary) or "当前访谈中信息不足"

                section_items.append(
                    {
                        "order": item_order,
                        "title": item_title,
                        "summary": point_summary,
                    }
                )
                generated_count += 1

        minutes_sections.append(
            {
                "order": section_order,
                "title": section_title,
                "summary": section_summary,
                "items": section_items,
            }
        )

    return minutes_sections, generated_count


def generate_minutes_for_interview(
    interview_id: int,
    project_context: Optional[str] = None,
    interview_context: Optional[Any] = None,
    top_k: int = 8,
) -> Dict[str, Any]:
    """
    为指定访谈生成智能纪要，并将结果写入数据库和本地文件。

    参数:
        interview_id: 访谈 ID。
        project_context: 可选项目背景文本。
        interview_context: 可选访谈背景摘要，若为空则由清洗 summary 全文自动提炼。
        top_k: 每个小点检索 summary 片段数量上限。

    返回:
        智能纪要生成与写库的聚合结果。
    """
    log(interview_id=interview_id, message=f"run_minutes start top_k={top_k} project_context_present={bool(project_context)} interview_context_present={bool(interview_context)}")
    interview = DbAccess.get_interview_by_id(interview_id)
    if not interview:
        log(interview_id=interview_id, message="run_minutes failed: interview not found")
        return {
            "success": False,
            "stage": "fetch_interview",
            "detail": {"message": f"interview {interview_id} not found"},
        }

    project_id = int(interview.get("parse_project_id") or 0)
    if project_id <= 0:
        log(interview_id=interview_id, message="run_minutes failed: project id missing from interview")
        return {
            "success": False,
            "stage": "fetch_project",
            "detail": {"message": "project id missing from interview"},
            "project_id": project_id,
            "interview_id": interview_id,
        }

    if not project_context:
        project_context = load_project_context_by_id(project_id)

    backup_dir = _get_interview_backup_dir(project_id, interview_id)
    if not backup_dir.exists():
        log(interview_id=interview_id, message=f"run_minutes failed: backup directory not found: {backup_dir}")
        return {
            "success": False,
            "stage": "resolve_questionnaire",
            "detail": {"message": f"backup directory not found: {backup_dir}"},
            "project_id": project_id,
            "interview_id": interview_id,
        }

    try:
        summary_rows = DbAccess.fetch_interview_summary(interview_id)
        if not summary_rows:
            log(interview_id=interview_id, message="run_minutes failed: no cleaned summary rows found")
            return {
                "success": False,
                "stage": "fetch_summary",
                "detail": {"message": "no cleaned summary rows found"},
                "project_id": project_id,
                "interview_id": interview_id,
            }

        summary_segments = _build_summary_segments(summary_rows)
        full_text = _build_summary_full_text(summary_segments)
        if not full_text.strip():
            log(interview_id=interview_id, message="run_minutes failed: cleaned summary text is empty")
            return {
                "success": False,
                "stage": "build_summary_text",
                "detail": {"message": "cleaned summary text is empty"},
                "project_id": project_id,
                "interview_id": interview_id,
            }

        derived_interview_context: Optional[Any] = None
        try:
            derived_interview_context = ModelClient().extract_interview_context(
                full_text=full_text,
                project_context=project_context,
            )
        except Exception as exc:
            log(f"访谈 {interview_id} 提炼访谈背景失败，继续使用外部背景或空背景：{exc}", interview_id=interview_id)
        interview_context = derived_interview_context or interview_context

        log(f"开始为访谈 {interview_id} 生成智能纪要大纲", interview_id=interview_id)
        outline_payload = _extract_minutes_outline_from_summary_text(
            backup_dir,
            summary_rows,
            project_context=project_context,
        )
        outline_payload["document_title"] = (
            outline_payload.get("document_title")
            or str(interview.get("name") or "").strip()
            or f"interview_{interview_id}"
        )
        outline_sections = _normalize_outline_sections(outline_payload.get("sections") or outline_payload.get("outline"))
        if not outline_sections:
            log(interview_id=interview_id, message="run_minutes failed: no outline sections generated")
            return {
                "success": False,
                "stage": "generate_outline",
                "detail": {"message": "no outline sections generated"},
                "project_id": project_id,
                "interview_id": interview_id,
            }

        model_client: Optional[ModelClient] = None
        model_client_error: Optional[str] = None
        try:
            model_client = ModelClient()
        except Exception as exc:
            model_client_error = f"init model client failed: {exc}"
            log(model_client_error, interview_id=interview_id)

        minutes_sections, generated_count = _build_minutes_sections(
            summary_segments=summary_segments,
            outline_sections=outline_sections,
            model_client=model_client,
            project_context=project_context,
            interview_context=interview_context,
            top_k=top_k,
            interview_id=interview_id,
        )

        minutes_payload: Dict[str, Any] = {
            "document_title": outline_payload.get("document_title") or "",
            "core_summary": outline_payload.get("core_summary") or "",
            "source_file": outline_payload.get("source_file"),
            "source_text_path": outline_payload.get("source_text_path"),
            "source_text_len": outline_payload.get("source_text_len"),
            "outline_json_path": outline_payload.get("outline_json_path"),
            "outline_txt_path": outline_payload.get("outline_txt_path"),
            "sections": minutes_sections,
            "action_items": outline_payload.get("action_items") or [],
            "highlights": outline_payload.get("highlights") or [],
        }
        if model_client_error:
            minutes_payload["warnings"] = [model_client_error]

        minutes_json_path, minutes_txt_path = _build_minutes_output_paths(backup_dir)
        minutes_json_path.write_text(json.dumps(minutes_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        minutes_txt_path.write_text(_render_minutes_text(minutes_payload) + "\n", encoding="utf-8")

        written = DbAccess.upsert_interview_minutes(
            project_id=project_id,
            interview_id=interview_id,
            outline_json=outline_payload,
            minutes_json=minutes_payload,
            status="done",
            error_message=None,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        log(
            interview_id=interview_id,
            message=(
                "run_minutes done "
                f"outline_generated={len(outline_sections)} "
                f"generated={generated_count} "
                f"inserted={written} "
                f"minutes_json_path={minutes_json_path} "
                f"minutes_txt_path={minutes_txt_path}"
            ),
        )

        return {
            "success": True,
            "project_id": project_id,
            "interview_id": interview_id,
            "outline_generated": len(outline_sections),
            "generated": generated_count,
            "inserted": written,
            "outline_json_path": outline_payload.get("outline_json_path"),
            "outline_txt_path": outline_payload.get("outline_txt_path"),
            "minutes_json_path": str(minutes_json_path),
            "minutes_txt_path": str(minutes_txt_path),
            "warnings": [warning for warning in [model_client_error] if warning],
        }
    except Exception as exc:
        error_message = f"generate minutes failed: {exc}"
        log(interview_id=interview_id, message=f"run_minutes failed error={exc}\n{traceback.format_exc()}")
        try:
            DbAccess.upsert_interview_minutes(
                project_id=project_id,
                interview_id=interview_id,
                outline_json=outline_payload if "outline_payload" in locals() else None,
                minutes_json=None,
                status="failed",
                error_message=error_message,
                generated_at=None,
            )
        except Exception:
            pass
        return {
            "success": False,
            "stage": "generate_minutes",
            "detail": {
                "message": error_message,
                "traceback": traceback.format_exc(),
            },
            "project_id": project_id,
            "interview_id": interview_id,
        }


if __name__ == "__main__":
    """
    命令行用法（示例）：
        1. 在 .env 中设置 TEST_INTERVIEW_ID
        2. 运行本文件
    """
    from config import config

    iid = config.TEST_INTERVIEW_ID
    if not iid:
        print("请在 .env 中配置 TEST_INTERVIEW_ID")
        raise SystemExit(1)
    try:
        iid_int = int(iid)
    except ValueError:
        print(f"TEST_INTERVIEW_ID 非法: {iid}")
        raise SystemExit(1)

    result = generate_minutes_for_interview(iid_int)
    print(json.dumps(result, ensure_ascii=False, indent=2))
