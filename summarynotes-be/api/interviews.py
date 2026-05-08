from pathlib import Path
import mimetypes
import shutil
import json
import re
from difflib import SequenceMatcher
from datetime import datetime
from urllib.parse import quote
from typing import Any, Dict, List

import os
import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response

from api.auth import require_current_user_id
from db import (
    delete_interview_graph,
    delete_fewshot_sample,
    delete_question_and_notes,
    fetch_interview_by_id,
    fetch_interview_minutes_by_interview,
    fetch_interview_summary_by_id,
    fetch_fewshot_samples_by_interview,
    fetch_interview_summary,
    fetch_project_by_id,
    fetch_key_bq_rows_by_interview,
    fetch_question_by_id,
    fetch_question_intents,
    fetch_notes_rows_by_interview,
    fetch_questions_by_interview,
    insert_fewshot_sample,
    insert_questions_for_interview,
    update_interview_summary_text_with_corrections,
    upsert_interview_minutes,
)
from schemas.interviews import (
    DeleteInterviewResponse,
    FewshotSampleCreateRequest,
    FewshotSampleCreateResponse,
    FewshotSampleDeleteResponse,
    FewshotSampleItem,
    InterviewFewshotSamplesResponse,
    GenerateNotesResponse,
    InterviewNotesResponse,
    InterviewQuestionsResponse,
    InterviewSummaryResponse,
    InterviewStatusResponse,
    RunInterviewResponse,
    QuestionCreateRequest,
    QuestionCreateResponse,
    QuestionDeleteResponse,
    SummaryUpdateRequest,
    SummaryUpdateResponse,
)
from storage import delete_remote_object
from docx_export import build_transcript_docx_bytes, DOCX_MIME_TYPE


router = APIRouter(prefix="/api/interviews", tags=["interviews"])


def _get_data_root() -> Path:
    """
    获取项目根目录下的 data 目录。

    返回:
        `data/` 路径。
    """
    api_dir = Path(__file__).resolve().parent
    project_root = api_dir.parent.parent
    return project_root / "data"


def _get_interview_backup_dir(project_id: int, interview_id: int) -> Path:
    """
    获取访谈在 data 目录下的备份目录。

    参数:
        project_id: 项目 ID。
        interview_id: 访谈 ID。

    返回:
        `data/project_{project_id}/interview_{interview_id}` 路径。
    """
    return _get_data_root() / f"project_{project_id}" / f"interview_{interview_id}"


def _safe_load_json_file(path: Path) -> Dict[str, Any] | None:
    """
    安全读取 JSON 文件。

    参数:
        path: JSON 文件路径。

    返回:
        解析成功时返回字典，否则返回 `None`。
    """
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _is_minutes_payload_complete(payload: Dict[str, Any] | None) -> bool:
    """
    判断一个 minutes JSON 是否已经足够用于前端展示。

    参数:
        payload: 智能纪要 JSON。

    返回:
        若包含至少一个 section 则返回 True。
    """
    if not isinstance(payload, dict):
        return False
    raw_sections = payload.get("sections") or []
    return isinstance(raw_sections, list) and len(raw_sections) > 0


def _load_minutes_payload_from_files(project_id: int, interview_id: int) -> tuple[Dict[str, Any] | None, Path | None]:
    """
    从访谈目录中寻找可直接展示的 minutes JSON。

    参数:
        project_id: 项目 ID。
        interview_id: 访谈 ID。

    返回:
        (minutes_payload, source_path) 二元组；未找到时返回 (None, None)。
    """
    backup_dir = _get_interview_backup_dir(project_id, interview_id)
    if not backup_dir.exists():
        return None, None

    candidate_paths: List[Path] = []
    direct_path = backup_dir / "minutes.json"
    outline_path = backup_dir / "outline_minutes" / "minutes.json"
    candidate_paths.extend([direct_path, outline_path])
    for path in sorted(backup_dir.rglob("minutes.json")):
        if path not in candidate_paths:
            candidate_paths.append(path)

    for path in candidate_paths:
        payload = _safe_load_json_file(path)
        if _is_minutes_payload_complete(payload):
            return payload, path
    return None, None


def _payload_to_minutes_row(payload: Dict[str, Any], project_id: int, interview_id: int) -> Dict[str, Any]:
    """
    将文件里的 minutes JSON 转成 `_build_interview_minutes_response` 可消费的行结构。

    参数:
        payload: 读取到的 minutes JSON。
        project_id: 项目 ID。
        interview_id: 访谈 ID。

    返回:
        伪造的数据库行结构。
    """
    outline_json = payload.get("outline")
    if outline_json is None:
        outline_json = payload.get("outline_json")
    if outline_json is None:
        outline_json = payload
    return {
        "id": None,
        "project_id": project_id,
        "project_interview_id": interview_id,
        "outline_json": outline_json,
        "minutes_json": payload,
        "status": payload.get("status") or "done",
        "error_message": payload.get("error_message"),
        "generated_at": payload.get("generated_at"),
    }


def _render_minutes_payload_text(payload: Dict[str, Any]) -> str:
    """
    将智能纪要 JSON 渲染为前端可直接展示的 Markdown 文本。

    参数:
        payload: 智能纪要 JSON。

    返回:
        Markdown 风格的可读文本。
    """
    lines: List[str] = []

    def _normalize_fragment(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if text.startswith("{") and text.endswith("}"):
            try:
                parsed = json.loads(text)
            except Exception:
                return text
            if isinstance(parsed, dict):
                for key in ("core_summary", "核心总结", "summary"):
                    candidate = parsed.get(key)
                    if isinstance(candidate, str) and candidate.strip():
                        return candidate.strip()
                points = parsed.get("分点要点") or parsed.get("items") or parsed.get("points")
                if isinstance(points, list):
                    flattened = [str(item).strip() for item in points if str(item).strip()]
                    if flattened:
                        return "\n".join(f"· {item}" for item in flattened)
                conclusion = parsed.get("待办/结论") or parsed.get("结论")
                if isinstance(conclusion, str) and conclusion.strip():
                    return conclusion.strip()
            return text
        return text

    document_title = str(payload.get("document_title") or "").strip()
    if document_title:
        lines.append(f"# {document_title}")
        lines.append("")

    core_summary = _normalize_fragment(payload.get("core_summary"))
    if core_summary:
        lines.append("## 核心总结")
        lines.append(core_summary)
        lines.append("")

    sections = payload.get("sections") or []
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict):
                continue
            section_order = section.get("order")
            section_title = str(section.get("title") or "").strip()
            section_summary = _normalize_fragment(section.get("summary"))
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
                    item_summary = _normalize_fragment(item.get("summary"))
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


def _get_owned_interview_or_404(interview_id: int, current_user_id: int) -> Dict[str, Any]:
    """
    查询当前用户可访问的访谈；若不属于当前用户则统一返回 404。

    参数:
        interview_id: 访谈主键 ID。
        current_user_id: 当前登录用户 ID。

    返回:
        访谈记录字典。
    """
    interview = fetch_interview_by_id(interview_id, current_user_id)
    if not interview:
        raise HTTPException(status_code=404, detail="interview not found")
    return interview


def _get_internal_base() -> str:
    """
    获取内部 SummaryNotes 引擎服务的基地址。

    优先从环境变量 INTERNAL_SERVICE_BASE 中读取；
    如果未配置，则默认使用本地地址 http://127.0.0.1:8000。
    最终返回值会移除末尾多余的斜杠。

    返回:
        用于拼接 /internal/... 路由的服务基地址字符串。
    """
    base = os.getenv("INTERNAL_SERVICE_BASE", "http://127.0.0.1:8000")
    return base.rstrip("/")


def _get_audio_root() -> Path:
    """
    获取本地音频备份根目录。

    返回:
        项目根目录下的 `audio/` 路径。
    """
    api_dir = Path(__file__).resolve().parent
    project_root = api_dir.parent.parent
    return project_root / "audio"


def _resolve_audio_file(interview_id: int, current_user_id: int) -> tuple[Path, str]:
    """
    根据访谈 ID 定位本地音频文件。

    该函数会先查访谈记录，读取项目 ID 和原始文件名，再拼出本地 audio 目录下的真实路径。
    """
    row = fetch_interview_by_id(interview_id, current_user_id)
    if not row:
        raise HTTPException(status_code=404, detail="interview not found")

    project_id = row.get("parse_project_id")
    file_name = row.get("file_name")
    if project_id is None or not file_name:
        raise HTTPException(status_code=404, detail="audio file not found")

    audio_path = (
        _get_audio_root()
        / f"project_{project_id}"
        / f"interview_{interview_id}"
        / str(file_name)
    )
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="audio file not found")

    return audio_path, str(file_name)


def _get_qdrant_base_url() -> str:
    """
    获取 Qdrant 服务基地址。

    返回:
        形如 `http://127.0.0.1:6333` 的字符串。
    """
    host_env = os.getenv("QDRANT_HOST", "localhost")
    port_env = int(os.getenv("QDRANT_PORT", "6333"))
    if host_env.startswith("http://") or host_env.startswith("https://"):
        return host_env.rstrip("/")
    return f"http://{host_env}:{port_env}"


def _get_qdrant_collection_name() -> str:
    """
    获取用于访谈 summary 向量的 Qdrant 集合名。

    返回:
        集合名称字符串。
    """
    return os.getenv("QDRANT_COLLECTION_SUMMARY", "interview_summary")


def _build_interview_notes_response(
    interview_id: int,
    project_id: int | None,
    rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    将数据库原始 Notes 行聚合为前端可直接消费的题目-Notes 结构。

    参数:
        interview_id: 访谈 ID。
        project_id: 所属项目 ID。
        rows: fetch_notes_rows_by_interview 返回的原始记录列表。

    返回:
        包含 interview_id、project_id、questions 的聚合字典。
    """
    questions_map: Dict[int, Dict[str, Any]] = {}

    for row in rows:
        question_id = int(row["question_id"])
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


def _build_interview_kbq_notes_response(
    interview_id: int,
    project_id: int | None,
    rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    将 key BQ 明细聚合为前端可直接消费的 KBQ Notes 结构。

    参数:
        interview_id: 访谈 ID。
        project_id: 所属项目 ID。
        rows: fetch_key_bq_rows_by_interview 返回的原始记录列表。

    返回:
        包含 interview_id、project_id、items 的聚合字典。
    """
    items: List[Dict[str, Any]] = []
    for row in rows:
        dimension_json_raw = row.get("dimension_json")
        note_json_raw = row.get("note_json")
        if isinstance(dimension_json_raw, str):
            try:
                dimension_json = json.loads(dimension_json_raw)
            except Exception:
                dimension_json = dimension_json_raw
        else:
            dimension_json = dimension_json_raw
        if isinstance(note_json_raw, str):
            try:
                note_json = json.loads(note_json_raw)
            except Exception:
                note_json = note_json_raw
        else:
            note_json = note_json_raw

        items.append(
            {
                "id": row.get("id"),
                "project_id": row.get("project_id"),
                "project_interview_id": row.get("project_interview_id"),
                "bq_order": row.get("bq_order"),
                "bq_text": row.get("bq_text"),
                "dimension_json": dimension_json,
                "note_json": note_json,
                "status": row.get("status"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            }
        )

    items.sort(key=lambda item: (item.get("bq_order") or 0, item.get("id") or 0))
    return {
        "interview_id": interview_id,
        "project_id": project_id,
        "items": items,
    }


def _build_interview_minutes_response(
    interview_id: int,
    project_id: int | None,
    row: Dict[str, Any] | None,
) -> Dict[str, Any]:
    """
    将数据库中的智能纪要记录整理为前端可直接消费的结构。

    参数:
        interview_id: 访谈 ID。
        project_id: 所属项目 ID。
        row: fetch_interview_minutes_by_interview 返回的单条记录。

    返回:
        包含 interview_id、project_id、outline、sections、status 等字段的聚合字典。
    """
    if not row:
        return {
            "interview_id": interview_id,
            "project_id": project_id,
            "outline": None,
            "sections": [],
            "status": None,
            "generated_at": None,
        }

    outline_json_raw = row.get("outline_json")
    minutes_json_raw = row.get("minutes_json")
    if isinstance(outline_json_raw, str):
        try:
            outline_json = json.loads(outline_json_raw)
        except Exception:
            outline_json = outline_json_raw
    else:
        outline_json = outline_json_raw
    if isinstance(minutes_json_raw, str):
        try:
            minutes_json = json.loads(minutes_json_raw)
        except Exception:
            minutes_json = minutes_json_raw
    else:
        minutes_json = minutes_json_raw

    sections = []
    if isinstance(minutes_json, dict):
        raw_sections = minutes_json.get("sections") or []
        if isinstance(raw_sections, list):
            sections = raw_sections

    return {
        "interview_id": interview_id,
        "project_id": project_id,
        "document_title": minutes_json.get("document_title") if isinstance(minutes_json, dict) else None,
        "core_summary": minutes_json.get("core_summary") if isinstance(minutes_json, dict) else None,
        "minutes_text": _render_minutes_payload_text(minutes_json)
        if isinstance(minutes_json, dict)
        else None,
        "outline": outline_json,
        "sections": sections,
        "action_items": minutes_json.get("action_items") if isinstance(minutes_json, dict) else [],
        "highlights": minutes_json.get("highlights") if isinstance(minutes_json, dict) else [],
        "status": row.get("status"),
        "error_message": row.get("error_message"),
        "generated_at": row.get("generated_at"),
        "minutes_json": minutes_json,
    }


def _build_transcript_export_filename(interview_name: str | None, interview_id: int) -> str:
    """
    生成全文 trans 的导出文件名。

    参数:
        interview_name: 访谈名称。
        interview_id: 访谈 ID。

    返回:
        适合作为下载文件名的字符串。
    """
    base_name = (interview_name or f"interview_{interview_id}").strip() or f"interview_{interview_id}"
    safe_chars: List[str] = []
    for ch in base_name:
        if ch.isalnum() or ch in {"-", "_", " ", "(", ")", "[", "]", "【", "】", "、", ".", ","}:
            safe_chars.append(ch)
        else:
            safe_chars.append("_")
    cleaned = "".join(safe_chars).strip().replace(" ", "_")
    if not cleaned:
        cleaned = f"interview_{interview_id}"
    return f"{cleaned}_全文trans.docx"


def _delete_qdrant_points_for_interview(interview_id: int) -> tuple[bool, str | None]:
    """
    按访谈 ID 删除 Qdrant 中对应的 summary chunk 向量。
    """
    base_url = _get_qdrant_base_url()
    collection_name = _get_qdrant_collection_name()

    collection_url = f"{base_url}/collections/{collection_name}"
    try:
        collection_resp = requests.get(collection_url, timeout=30)
    except Exception as e:
        return False, f"qdrant collection check failed: {e}"

    if collection_resp.status_code == 404:
        return True, None
    if collection_resp.status_code >= 500:
        return False, f"qdrant collection check failed: {collection_resp.status_code}"

    delete_url = f"{base_url}/collections/{collection_name}/points/delete"
    body = {
        "filter": {
            "must": [
                {
                    "key": "project_interview_id",
                    "match": {"value": interview_id},
                }
            ]
        },
        "wait": True,
    }
    try:
        resp = requests.post(delete_url, json=body, timeout=30)
    except Exception as e:
        return False, f"qdrant delete request failed: {e}"

    if resp.status_code >= 500:
        return False, f"qdrant delete failed: {resp.status_code}"
    if resp.status_code == 404:
        return True, None
    if not resp.ok:
        return False, f"qdrant delete failed: {resp.status_code}"
    return True, None


def _delete_local_audio_dir(project_id: int, interview_id: int) -> tuple[bool, str | None]:
    """
    删除本地 audio 目录下该访谈对应的文件夹。

    参数:
        project_id: 项目 ID。
        interview_id: 访谈 ID。

    返回:
        (是否删除成功, 失败原因)。
    """
    target_dir = _get_audio_root() / f"project_{project_id}" / f"interview_{interview_id}"
    if not target_dir.exists():
        return True, None
    try:
        shutil.rmtree(target_dir)
    except Exception as e:
        return False, f"local audio delete failed: {e}"
    return True, None


def _delete_local_backup_dir(project_id: int, interview_id: int) -> tuple[bool, str | None]:
    """
    删除 data 目录下的访谈备份目录。
    """
    api_dir = Path(__file__).resolve().parent
    project_root = api_dir.parent.parent
    target_dir = project_root / "data" / f"project_{project_id}" / f"interview_{interview_id}"
    if not target_dir.exists():
        return True, None
    try:
        shutil.rmtree(target_dir)
    except Exception as e:
        return False, f"local backup delete failed: {e}"
    return True, None


def _delete_cloud_audio_object(object_key: str | None) -> tuple[bool, str | None]:
    """
    删除云端音频对象。

    参数:
        object_key: TOS 对象 key；为空时表示无需删除。

    返回:
        (是否删除成功, 失败原因)。
    """
    if not object_key:
        return True, None
    result = delete_remote_object(object_key)
    if result.get("success"):
        return True, None
    message = result.get("message") or "cloud audio delete failed"
    detail = result.get("data") or {}
    if detail:
        return False, f"{message}: {detail}"
    return False, message


def _parse_sample_json(raw: Any) -> tuple[Any, str | None, str | None, int]:
    """
    解析 Notes 的 JSON 样本内容。

    参数:
        raw: 数据库原始返回值，可能是 JSON 字符串、字典或其他类型。

    返回:
        一个四元组:
            - 解析后的对象
            - summary 文本或 None
            - analysis 文本或 None
            - evidence 条数
    """
    if isinstance(raw, str):
        try:
            parsed: Any = json.loads(raw)
        except Exception:
            return raw, None, None, 0
    else:
        parsed = raw

    if not isinstance(parsed, dict):
        return parsed, None, None, 0

    summary = parsed.get("summary")
    analysis = parsed.get("analysis")
    evidence = parsed.get("evidence")
    evidence_count = len(evidence) if isinstance(evidence, list) else 0
    return parsed, summary if isinstance(summary, str) else None, analysis if isinstance(analysis, str) else None, evidence_count


_SUMMARY_DIFF_TOKEN_RE = re.compile(
    r"\s+|[A-Za-z0-9]+(?:[._/-][A-Za-z0-9]+)*|[\u4e00-\u9fff]|[^\w\s]",
    re.UNICODE,
)


def _normalize_correction_compare_text(text: str) -> str:
    """
    规范化用于 diff 比较的文本，移除空白与标点噪声。

    参数:
        text: 原始文本。

    返回:
        仅保留字母、数字、中文等可比较内容的字符串。
    """
    return re.sub(r"[\s\W_]+", "", text or "", flags=re.UNICODE)


def _tokenize_correction_text(text: str) -> List[Dict[str, Any]]:
    """
    将文本切成适合做差异对齐的 token 序列，并保留原始位置。

    参数:
        text: 原始文本。

    返回:
        token 字典列表，每个元素包含 text/start/end。
    """
    tokens: List[Dict[str, Any]] = []
    raw_text = text or ""
    for match in _SUMMARY_DIFF_TOKEN_RE.finditer(raw_text):
        token = match.group(0)
        if token.isspace():
            continue
        tokens.append(
            {
                "text": token,
                "start": match.start(),
                "end": match.end(),
            }
        )
    if not tokens and raw_text.strip():
        stripped = raw_text.strip()
        start = raw_text.find(stripped)
        if start < 0:
            start = 0
        tokens.append(
            {
                "text": stripped,
                "start": start,
                "end": start + len(stripped),
            }
        )
    return tokens


def _context_window(text: str, start: int, end: int, window: int = 24) -> tuple[str | None, str | None]:
    """
    从原文中截取修改点前后的一小段上下文。

    参数:
        text: 原始文本。
        start: 修改片段起始位置。
        end: 修改片段结束位置。
        window: 上下文窗口长度，默认 24 个字符。

    返回:
        (前文, 后文) 二元组，空时返回 None。
    """
    safe_start = max(0, start)
    safe_end = max(safe_start, end)
    before = (text[max(0, safe_start - window):safe_start] or "").strip()
    after = (text[safe_end:min(len(text), safe_end + window)] or "").strip()
    return before or None, after or None


def _classify_correction_edit_type(wrong_text: str, correct_text: str) -> str:
    """
    根据修改片段长度与形态，粗分类修改类型。

    参数:
        wrong_text: 原始错误片段。
        correct_text: 用户修正后的正确片段。

    返回:
        edit_type 字符串。
    """
    wrong_norm = _normalize_correction_compare_text(wrong_text)
    correct_norm = _normalize_correction_compare_text(correct_text)
    if not wrong_norm:
        return "insertion"
    if not correct_norm:
        return "deletion"

    combined = f"{wrong_text}{correct_text}"
    if any(mark in combined for mark in ("。", "！", "？", "\n", "；", ";")):
        return "sentence_rewrite"
    if max(len(wrong_norm), len(correct_norm)) >= 24:
        return "sentence_rewrite"
    if max(len(wrong_norm), len(correct_norm)) <= 8:
        return "term_replace"
    return "phrase_replace"


def _limit_correction_text(text: str, limit: int = 1024) -> str:
    """
    限制纠错文本长度，避免写入数据库时超出字段上限。

    参数:
        text: 原始文本。
        limit: 最大字符数，默认 1024。

    返回:
        截断后的文本。
    """
    safe_text = text or ""
    if len(safe_text) <= limit:
        return safe_text
    return safe_text[:limit]


def _extract_transcription_corrections(
    old_text: str,
    new_text: str,
    *,
    project_id: int,
    interview_id: int,
    summary_id: int,
    created_by: int,
) -> List[Dict[str, Any]]:
    """
    从旧文本和新文本中抽取最小级别的纠错记录。

    参数:
        old_text: 修改前文本。
        new_text: 修改后文本。
        project_id: 项目 ID。
        interview_id: 访谈 ID。
        summary_id: summary ID。
        created_by: 操作人用户 ID。

    返回:
        纠错记录列表，每条记录可直接写入 bh_transcription_corrections。
    """
    normalized_old = _normalize_correction_compare_text(old_text)
    normalized_new = _normalize_correction_compare_text(new_text)
    if normalized_old == normalized_new:
        return []

    old_tokens = _tokenize_correction_text(old_text)
    new_tokens = _tokenize_correction_text(new_text)
    old_seq = [token["text"] for token in old_tokens]
    new_seq = [token["text"] for token in new_tokens]

    if not old_seq and not new_seq:
        return []

    matcher = SequenceMatcher(None, old_seq, new_seq, autojunk=False)
    corrections: List[Dict[str, Any]] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        old_start = old_tokens[i1]["start"] if i1 < len(old_tokens) else len(old_text or "")
        old_end = old_tokens[i2 - 1]["end"] if i2 > i1 else old_start
        new_start = new_tokens[j1]["start"] if j1 < len(new_tokens) else len(new_text or "")
        new_end = new_tokens[j2 - 1]["end"] if j2 > j1 else new_start

        wrong_text = (old_text or "")[old_start:old_end].strip()
        correct_text = (new_text or "")[new_start:new_end].strip()

        wrong_norm = _normalize_correction_compare_text(wrong_text)
        correct_norm = _normalize_correction_compare_text(correct_text)
        if not wrong_norm and not correct_norm:
            continue
        if wrong_norm == correct_norm:
            continue

        edit_type = _classify_correction_edit_type(wrong_text, correct_text)
        context_before, context_after = _context_window(old_text or "", old_start, old_end)
        corrections.append(
            {
                "project_id": project_id,
                "project_interview_id": interview_id,
                "summary_id": summary_id,
                "wrong_text": _limit_correction_text(wrong_text),
                "correct_text": _limit_correction_text(correct_text),
                "context_before": context_before,
                "context_after": context_after,
                "edit_type": edit_type,
                "confidence": 1.0,
                "usage_count": 0,
                "status": "approved",
                "created_by": created_by,
            }
        )

    return corrections


@router.post("/{interview_id}/run", response_model=RunInterviewResponse)
def run_interview_workflow(
    interview_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> RunInterviewResponse:
    """
    对外接口：触发指定访谈的转录工作流执行。

    调用内部 SummaryNotes 服务的:
        POST /internal/interviews/{interview_id}/transcribe
    并从返回结果中抽取核心信息，封装为精简的 RunInterviewResponse。

    参数:
        interview_id: 访谈主键 ID，对应 bh_project_interview.id。

    返回:
        RunInterviewResponse 实例，包含:
            - success: 是否执行成功。
            - summary_inserted: 写入 summary 表的记录数（若有）。
            - notes_inserted: 写入 notes 表的记录数（若有）。
            - message: 在失败或部分失败时的人类可读错误信息。

    异常:
        HTTPException(404): 内部服务返回 404，表示访谈不存在。
        HTTPException(502): 内部服务不可用或返回 5xx 错误。
    """
    _get_owned_interview_or_404(interview_id, current_user_id)
    base = _get_internal_base()
    url = f"{base}/internal/interviews/{interview_id}/transcribe"
    try:
        resp = requests.post(url, timeout=600)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"internal service error: {e}")

    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="interview not found")
    if resp.status_code >= 500:
        raise HTTPException(status_code=502, detail="internal service failed")

    data: Dict[str, Any] = resp.json()

    success = bool(data.get("success", False))
    queued = bool(data.get("queued", False))
    summary_inserted = data.get("summary_inserted")
    minutes_inserted = data.get("minutes_inserted")
    notes_inserted = data.get("notes_inserted")
    if minutes_inserted is not None and notes_inserted is None:
        notes_inserted = minutes_inserted
    message = None

    if not success:
        stage = data.get("stage")
        detail = data.get("detail")
        if isinstance(detail, dict):
            detail_msg = detail.get("message") or ""
        else:
            detail_msg = str(detail)
        parts = [p for p in [stage, detail_msg] if p]
        message = " | ".join(parts) if parts else "run workflow failed"

    return RunInterviewResponse(
        success=success,
        queued=queued,
        summary_inserted=summary_inserted,
        notes_inserted=notes_inserted,
        minutes_inserted=minutes_inserted,
        message=message,
    )


@router.post(
    "/{interview_id}/questions/{question_id}/generate-notes",
    response_model=GenerateNotesResponse,
)
def generate_question_notes(
    interview_id: int,
    question_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> GenerateNotesResponse:
    """
    针对指定题目生成 Notes。
    """
    interview = _get_owned_interview_or_404(interview_id, current_user_id)

    base = _get_internal_base()
    url = f"{base}/internal/interviews/{interview_id}/generate-notes"
    try:
        resp = requests.post(url, params={"question_id": question_id}, timeout=600)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"internal service error: {e}")

    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="interview or question not found")
    if resp.status_code >= 500:
        raise HTTPException(status_code=502, detail="internal service failed")

    data: Dict[str, Any] = resp.json()
    success = bool(data.get("success", False))
    total_questions = int(data.get("total_questions") or 0)
    generated = int(data.get("generated") or 0)
    inserted = int(data.get("inserted") or 0)
    warnings = data.get("warnings") or []
    message = None
    if not success:
        stage = data.get("stage")
        detail = data.get("detail")
        if isinstance(detail, dict):
            detail_msg = detail.get("message") or ""
        else:
            detail_msg = str(detail)
        parts = [p for p in [stage, detail_msg] if p]
        message = " | ".join(parts) if parts else "generate notes failed"

    return GenerateNotesResponse(
        success=success,
        interview_id=interview_id,
        question_id=question_id,
        project_id=interview.get("parse_project_id"),
        total_questions=total_questions,
        generated=generated,
        inserted=inserted,
        warnings=warnings,
        message=message,
    )


@router.get("/{interview_id}/status", response_model=InterviewStatusResponse)
def get_interview_status(
    interview_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> InterviewStatusResponse:
    """
    查询访谈当前处理状态。

    返回:
        - interview_id
        - status: bh_project_interview.status
    """
    row = _get_owned_interview_or_404(interview_id, current_user_id)
    return InterviewStatusResponse(
        interview_id=interview_id,
        status=row.get("status"),
    )


@router.get("/{interview_id}/audio")
def get_interview_audio(
    interview_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> FileResponse:
    """
    返回该访谈对应的本地音频文件，供前端播放器直接播放。

    该接口返回的是文件流响应，而不是预先读取到内存的完整二进制内容，
    方便浏览器按需缓存和 seek。
    """
    audio_path, file_name = _resolve_audio_file(interview_id, current_user_id)
    media_type, _ = mimetypes.guess_type(str(audio_path))
    return FileResponse(
        path=str(audio_path),
        filename=file_name,
        media_type=media_type or "application/octet-stream",
    )


@router.delete("/{interview_id}", response_model=DeleteInterviewResponse)
def delete_interview(
    interview_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> DeleteInterviewResponse:
    """
    删除访谈及其关联数据。
    """
    row = _get_owned_interview_or_404(interview_id, current_user_id)

    project_id = row.get("parse_project_id")
    object_key = row.get("file_path")
    failures: list[str] = []

    qdrant_deleted, qdrant_error = _delete_qdrant_points_for_interview(interview_id)
    if not qdrant_deleted:
        failures.append(qdrant_error or "qdrant delete failed")

    local_audio_deleted = False
    local_audio_error: str | None = None
    if project_id is not None:
        local_audio_deleted, local_audio_error = _delete_local_audio_dir(project_id, interview_id)
        if not local_audio_deleted:
            failures.append(local_audio_error or "local audio delete failed")
        backup_deleted, backup_error = _delete_local_backup_dir(project_id, interview_id)
        if not backup_deleted:
            failures.append(backup_error or "local backup delete failed")

    cloud_audio_deleted, cloud_audio_error = _delete_cloud_audio_object(object_key)
    if not cloud_audio_deleted:
        failures.append(cloud_audio_error or "cloud audio delete failed")

    if failures:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "failed to delete external interview resources",
                "failures": failures,
                "qdrant_deleted": qdrant_deleted,
                "local_audio_deleted": local_audio_deleted,
                "cloud_audio_deleted": cloud_audio_deleted,
            },
        )

    try:
        db_row = delete_interview_graph(interview_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"database delete failed: {e}")

    if not db_row:
        raise HTTPException(status_code=404, detail="interview not found")

    return DeleteInterviewResponse(
        success=True,
        interview_id=interview_id,
        db_deleted=True,
        audio_deleted=local_audio_deleted or cloud_audio_deleted,
        local_audio_deleted=local_audio_deleted,
        cloud_audio_deleted=cloud_audio_deleted,
        qdrant_deleted=qdrant_deleted,
        message=None,
    )


@router.get(
    "/{interview_id}/notes",
    response_model=InterviewNotesResponse,
)
def get_interview_notes(
    interview_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> InterviewNotesResponse:
    """
    对外接口：直接从数据库获取指定访谈的 Notes 列表（按题目聚合）。
    """
    interview = _get_owned_interview_or_404(interview_id, current_user_id)

    rows = fetch_notes_rows_by_interview(interview_id)
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

    return InterviewNotesResponse(
        interview_id=interview_id,
        project_id=interview.get("parse_project_id"),
        questions=questions_list,
    )


@router.get(
    "/{interview_id}/questions",
    response_model=InterviewQuestionsResponse,
)
def get_interview_questions(
    interview_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> InterviewQuestionsResponse:
    """
    对外接口：直接从数据库获取指定访谈下配置的题目列表。
    """
    interview = _get_owned_interview_or_404(interview_id, current_user_id)

    rows = fetch_questions_by_interview(interview_id)
    questions = [
        {
            "id": row["id"],
            "project_interview_id": row["project_interview_id"],
            "question_order": row["question_order"],
            "question_text": row["question_text"],
            "question_type": row.get("question_type"),
            "research_phase": row.get("research_phase"),
            "meta": row.get("meta"),
            "intent_id": row.get("intent_id"),
        }
        for row in rows
    ]
    return InterviewQuestionsResponse(interview_id=interview_id, questions=questions)


@router.post(
    "/{interview_id}/questions",
    response_model=QuestionCreateResponse,
)
def create_interview_questions(
    interview_id: int,
    payload: QuestionCreateRequest,
    current_user_id: int = Depends(require_current_user_id),
) -> QuestionCreateResponse:
    """
    为指定访谈批量新增需总结的问题。
    """
    interview = _get_owned_interview_or_404(interview_id, current_user_id)

    questions = payload.questions or []
    if not questions:
        raise HTTPException(status_code=400, detail="questions is required")

    existing_questions = fetch_questions_by_interview(interview_id)
    next_order = 1
    if existing_questions:
        next_order = max(int(row.get("question_order") or 0) for row in existing_questions) + 1

    cleaned: List[Dict[str, Any]] = []
    for index, item in enumerate(questions, start=1):
        question_text = (item.question_text or "").strip()
        if not question_text:
            raise HTTPException(status_code=400, detail=f"第 {index} 条问题不能为空")

        cleaned.append(
            {
                "question_order": next_order,
                "question_text": question_text,
                "question_type": "OPEN",
                "intent_id": 1,
                "research_phase": None,
                "meta": {"source_kind": "manual"},
            }
        )
        next_order += 1

    try:
        inserted = insert_questions_for_interview(interview_id, cleaned)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"insert questions failed: {e}")

    return QuestionCreateResponse(
        success=True,
        interview_id=interview_id,
        inserted=inserted,
    )


@router.get(
    "/{interview_id}/overall-notes",
    response_model=Dict[str, Any],
)
def get_interview_overall_notes(
    interview_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> Dict[str, Any]:
    """
    返回整体 Notes 页面所需的聚合数据。

    返回字段包含:
        - interview_id
        - project_id
        - note_content: 访谈级 summary notes
        - minutes: 智能纪要
        - summary: 原始 summary 明细列表
    """
    interview = _get_owned_interview_or_404(interview_id, current_user_id)
    kbq_rows = fetch_key_bq_rows_by_interview(interview_id)
    kbq_payload = _build_interview_kbq_notes_response(
        interview_id=interview_id,
        project_id=interview.get("parse_project_id"),
        rows=kbq_rows,
    )
    minutes_row = fetch_interview_minutes_by_interview(interview_id)
    minutes_payload = _build_interview_minutes_response(
        interview_id=interview_id,
        project_id=interview.get("parse_project_id"),
        row=minutes_row,
    )
    if not minutes_payload.get("sections"):
        fallback_payload, fallback_path = _load_minutes_payload_from_files(
            project_id=int(interview.get("parse_project_id") or 0),
            interview_id=interview_id,
        )
        if fallback_payload is not None:
            try:
                upsert_interview_minutes(
                    project_id=int(interview.get("parse_project_id") or 0),
                    interview_id=interview_id,
                    outline_json=fallback_payload.get("outline") or fallback_payload.get("outline_json") or fallback_payload,
                    minutes_json=fallback_payload,
                    status=str(fallback_payload.get("status") or "done"),
                    error_message=fallback_payload.get("error_message"),
                    generated_at=fallback_payload.get("generated_at"),
                )
                minutes_row = fetch_interview_minutes_by_interview(interview_id)
                minutes_payload = _build_interview_minutes_response(
                    interview_id=interview_id,
                    project_id=interview.get("parse_project_id"),
                    row=minutes_row,
                )
            except Exception as exc:
                minutes_row = _payload_to_minutes_row(
                    fallback_payload,
                    project_id=int(interview.get("parse_project_id") or 0),
                    interview_id=interview_id,
                )
                minutes_payload = _build_interview_minutes_response(
                    interview_id=interview_id,
                    project_id=interview.get("parse_project_id"),
                    row=minutes_row,
                )
    summary_rows = fetch_interview_summary(project_interview_id=interview_id)
    return {
        "interview_id": interview_id,
        "project_id": interview.get("parse_project_id"),
        "note_content": interview.get("note_content"),
        "kbq_notes": kbq_payload,
        "minutes": minutes_payload,
        "summary": {
            "interview_id": interview_id,
            "items": summary_rows,
        },
    }


@router.post(
    "/{interview_id}/kbq-notes/refresh",
    response_model=Dict[str, Any],
)
def refresh_interview_kbq_notes(
    interview_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> Dict[str, Any]:
    """
    重新从访谈 core_problem 回填 key BQ，并触发 KBQ Notes 重建。

    返回:
        内部引擎服务返回的刷新结果。
    """
    _get_owned_interview_or_404(interview_id, current_user_id)

    url = f"{_get_internal_base()}/internal/interviews/{interview_id}/refresh-kbq-notes"
    try:
        resp = requests.post(url, timeout=600)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"refresh kbq notes request failed: {e}")

    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise HTTPException(status_code=resp.status_code, detail=detail)

    try:
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"parse refresh kbq notes response failed: {e}")


@router.post(
    "/{interview_id}/minutes/refresh",
    response_model=Dict[str, Any],
)
def refresh_interview_minutes(
    interview_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> Dict[str, Any]:
    """
    重新生成该访谈下的智能纪要。

    返回:
        内部引擎服务返回的智能纪要生成结果。
    """
    _get_owned_interview_or_404(interview_id, current_user_id)

    url = f"{_get_internal_base()}/internal/interviews/{interview_id}/generate-minutes"
    try:
        resp = requests.post(url, timeout=3600)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"refresh minutes request failed: {e}")

    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise HTTPException(status_code=resp.status_code, detail=detail)

    try:
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"parse refresh minutes response failed: {e}")


@router.delete(
    "/{interview_id}/questions/{question_id}",
    response_model=QuestionDeleteResponse,
)
def delete_interview_question(
    interview_id: int,
    question_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> QuestionDeleteResponse:
    """
    删除指定访谈下的一条题目，并级联删除其对应的 Notes。
    """
    _get_owned_interview_or_404(interview_id, current_user_id)

    try:
        result = delete_question_and_notes(interview_id, question_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"delete question failed: {e}")

    if not result:
        raise HTTPException(status_code=404, detail="question not found")

    return QuestionDeleteResponse(
        success=True,
        interview_id=interview_id,
        question_id=question_id,
        question_deleted=bool(result.get("question_deleted")),
        fewshot_deleted=int(result.get("fewshot_deleted") or 0),
        notes_deleted=int(result.get("notes_deleted") or 0),
        message=None,
    )


@router.get(
    "/{interview_id}/fewshot-samples",
    response_model=InterviewFewshotSamplesResponse,
)
def get_interview_fewshot_samples(
    interview_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> InterviewFewshotSamplesResponse:
    """
    查询某个访谈下全部 few-shot 种子。
    """
    interview = _get_owned_interview_or_404(interview_id, current_user_id)

    rows = fetch_fewshot_samples_by_interview(interview_id)
    samples: List[Dict[str, Any]] = []
    for row in rows:
        sample_json, sample_summary, sample_analysis, evidence_count = _parse_sample_json(
            row.get("sample_json")
        )
        samples.append(
            {
                "id": row["id"],
                "project_id": row["project_id"],
                "project_interview_id": row["project_interview_id"],
                "question_id": row["question_id"],
                "question_order": row.get("question_order"),
                "question_text": row.get("question_text"),
                "question_type": row.get("question_type"),
                "research_phase": row.get("research_phase"),
                "intent_id": row["intent_id"],
                "notes_result_id": row.get("notes_result_id"),
                "sample_json": sample_json,
                "sample_summary": sample_summary,
                "sample_analysis": sample_analysis,
                "evidence_count": evidence_count,
                "quality_score": row.get("quality_score"),
                "source_kind": row.get("source_kind"),
                "created_time": row.get("created_time"),
            }
        )

    return InterviewFewshotSamplesResponse(interview_id=interview_id, samples=samples)


@router.post(
    "/{interview_id}/questions/{question_id}/fewshot-samples",
    response_model=FewshotSampleCreateResponse,
)
def create_question_fewshot_sample(
    interview_id: int,
    question_id: int,
    payload: FewshotSampleCreateRequest,
    current_user_id: int = Depends(require_current_user_id),
) -> FewshotSampleCreateResponse:
    """
    为指定问题新增 few-shot 冷启动种子。
    """
    interview = _get_owned_interview_or_404(interview_id, current_user_id)

    question = fetch_question_by_id(interview_id, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="question not found")

    valid_intent_ids = {
        row.get("id")
        for row in fetch_question_intents()
        if row.get("id") is not None
    }
    if payload.intent_id not in valid_intent_ids:
        raise HTTPException(status_code=400, detail="intent_id not found")

    summary = (payload.summary or "").strip()
    analysis = (payload.analysis or "").strip()
    evidence = payload.evidence or []
    if not summary:
        raise HTTPException(status_code=400, detail="summary is required")
    if not analysis:
        raise HTTPException(status_code=400, detail="analysis is required")
    if not evidence:
        raise HTTPException(status_code=400, detail="evidence is required")

    cleaned_evidence: List[Dict[str, Any]] = []
    for index, item in enumerate(evidence, start=1):
        text = (item.text or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail=f"第 {index} 条 evidence 不能为空")
        cleaned_evidence.append(
            {
                "summary_id": int(item.summary_id),
                "speaker": item.speaker,
                "text": text,
            }
        )

    sample_json = {
        "summary": summary,
        "analysis": analysis,
        "evidence": cleaned_evidence,
        "confidence": payload.confidence if payload.confidence is not None else 0.95,
    }

    try:
        sample_id = insert_fewshot_sample(
            project_id=int(interview.get("parse_project_id")),
            project_interview_id=interview_id,
            question_id=question_id,
            intent_id=payload.intent_id,
            sample_json=sample_json,
            quality_score=int(payload.quality_score or 95),
            source_kind=payload.source_kind or "seed",
            notes_result_id=payload.notes_result_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"insert fewshot sample failed: {e}")

    return FewshotSampleCreateResponse(
        success=True,
        interview_id=interview_id,
        question_id=question_id,
        sample_id=sample_id,
    )


@router.delete(
    "/{interview_id}/fewshot-samples/{sample_id}",
    response_model=FewshotSampleDeleteResponse,
)
def delete_question_fewshot_sample(
    interview_id: int,
    sample_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> FewshotSampleDeleteResponse:
    """
    删除指定访谈下的一条 few-shot 冷启动种子。
    """
    _get_owned_interview_or_404(interview_id, current_user_id)

    try:
        row = delete_fewshot_sample(interview_id, sample_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"delete fewshot sample failed: {e}")

    if not row:
        raise HTTPException(status_code=404, detail="fewshot sample not found")

    return FewshotSampleDeleteResponse(
        success=True,
        interview_id=interview_id,
        sample_id=sample_id,
        question_id=row.get("question_id"),
        deleted=True,
        message=None,
    )


@router.get("/{interview_id}/summary")
def get_interview_summary(
    interview_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> Dict[str, Any]:
    """
    对外接口：获取指定访谈的原文明细列表。

    数据直接从 bh_project_interview_summary 表中读取。

    参数:
        interview_id: 访谈主键 ID，对应 bh_project_interview_summary.project_interview_id。

    返回:
        {
            "interview_id": interview_id,
            "items": [
                {
                    "id": ...,
                    "project_interview_id": ...,
                    "timestamp": "...",
                    "speaker": "...",
                    "text": "..."
                },
                ...
            ]
        }
    """
    _get_owned_interview_or_404(interview_id, current_user_id)
    rows: List[Dict[str, Any]] = fetch_interview_summary(project_interview_id=interview_id)
    return {"interview_id": interview_id, "items": rows}


@router.get("/{interview_id}/trans/export-word")
def export_interview_trans_word(
    interview_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> Response:
    """
    导出当前访谈的全文 trans 为 Word 文档。

    导出的内容和全文 trans 页面保持一致，直接基于 summary 明细组装。
    """
    interview = _get_owned_interview_or_404(interview_id, current_user_id)
    project_row = fetch_project_by_id(int(interview.get("parse_project_id") or 0), current_user_id)
    summary_rows = fetch_interview_summary(project_interview_id=interview_id)

    transcript_items: List[Dict[str, Any]] = []
    for row in summary_rows:
        transcript_items.append(
            {
                "speaker": row.get("speaker"),
                "timestamp": row.get("timestamp"),
                "text": row.get("text"),
            }
        )

    project_name = None
    if project_row:
        project_name = project_row.get("name")
    interview_name = interview.get("name")
    interview_date = interview.get("interview_date")
    subtitle_lines = [
        f"项目：{project_name or interview.get('parse_project_id')}",
        f"访谈：{interview_name or interview_id}",
        f"访谈日期：{interview_date or '未填写'}",
        f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    docx_bytes = build_transcript_docx_bytes(
        title=f"全文 trans - {interview_name or interview_id}",
        subtitle_lines=subtitle_lines,
        transcript_items=transcript_items,
    )
    filename = _build_transcript_export_filename(interview_name, interview_id)
    headers = {
        "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}",
    }
    return Response(content=docx_bytes, media_type=DOCX_MIME_TYPE, headers=headers)


def _reindex_summary_chunks(interview_id: int) -> tuple[bool, int | None, str | None]:
    """
    触发内部引擎重建当前访谈的 RAG 索引。
    """
    base = _get_internal_base()
    url = f"{base}/internal/interviews/{interview_id}/reindex-rag"
    try:
        resp = requests.post(url, timeout=300)
    except Exception as e:
        return False, None, f"internal service error: {e}"

    if resp.status_code == 404:
        return False, None, "interview not found"
    if resp.status_code >= 500:
        return False, None, f"internal service failed: {resp.status_code}"

    data = resp.json()
    return bool(data.get("success", False)), data.get("indexed"), None


@router.patch(
    "/{interview_id}/summary/{summary_id}",
    response_model=SummaryUpdateResponse,
)
def update_interview_summary(
    interview_id: int,
    summary_id: int,
    payload: SummaryUpdateRequest,
    current_user_id: int = Depends(require_current_user_id),
) -> SummaryUpdateResponse:
    """
    更新指定 summary 的文本，并记录用户修正得到的纠错学习样本。
    """
    interview = _get_owned_interview_or_404(interview_id, current_user_id)
    new_text = payload.text.strip()
    if not new_text:
        raise HTTPException(status_code=400, detail="summary text is required")

    original = fetch_interview_summary_by_id(summary_id, interview_id)
    if not original:
        raise HTTPException(status_code=404, detail="summary not found")

    old_text = str(original.get("text") or "")
    corrections = _extract_transcription_corrections(
        old_text,
        new_text,
        project_id=int(interview.get("parse_project_id") or 0),
        interview_id=interview_id,
        summary_id=summary_id,
        created_by=current_user_id,
    )

    try:
        updated, corrections_inserted = update_interview_summary_text_with_corrections(
            summary_id=summary_id,
            project_interview_id=interview_id,
            text=new_text,
            corrections=corrections,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"update summary failed: {e}")

    if not updated:
        raise HTTPException(status_code=404, detail="summary not found")

    return SummaryUpdateResponse(
        success=True,
        summary=updated,
        reindex_succeeded=False,
        reindex_indexed=None,
        reindex_warning=None,
        corrections_inserted=corrections_inserted,
    )
