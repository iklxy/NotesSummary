"""
@Date: 2026-05-08
@Author: lixinyang

KBQ Notes 生成工作流。

职责：
1. 从 bh_project_interview_key_bq 读取 key BQ。
2. 基于智能纪要 txt 做本地检索。
3. 抽取维度并生成 KBQ Notes。
4. 将结果回写数据库并落盘到访谈目录。
"""

from __future__ import annotations

import json
import re
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from DbAccess import DbAccess
from InterviewLogger import log_interview
from Model import ModelClient
from ProjectContext import load_project_context_by_id


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


def _normalize_kbq_dimensions(raw_dimensions: Any) -> List[Dict[str, Any]]:
    """
    将维度列表归一化为 `name` / `description` 结构。
    """
    if not isinstance(raw_dimensions, list):
        return []

    result: List[Dict[str, Any]] = []
    for item in raw_dimensions:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            normalized: Dict[str, Any] = {"name": name}
            description = str(item.get("description") or "").strip()
            if description:
                normalized["description"] = description
            result.append(normalized)
        else:
            text = str(item or "").strip()
            if text:
                result.append({"name": text})
    return result


def _parse_kbq_dimension_payload(
    raw_value: Any,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    从数据库字段中解析出用户维度、模型补充维度和合并后的维度。

    返回:
        (user_demension, llm_demension, demension)
    """
    if raw_value is None:
        return [], [], []

    parsed: Any = raw_value
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return [], [], []
        try:
            parsed = json.loads(text)
        except Exception:
            return [], [], []

    if isinstance(parsed, list):
        legacy_demension = _normalize_kbq_dimensions(parsed)
        return [], [], legacy_demension

    if isinstance(parsed, dict):
        user_raw = parsed.get("user_demension")
        if user_raw is None:
            user_raw = parsed.get("user_dimensions")
        llm_raw = parsed.get("llm_demension")
        if llm_raw is None:
            llm_raw = parsed.get("llm_dimensions")
        if llm_raw is None:
            llm_raw = parsed.get("supplemental_dimensions")
        demension_raw = parsed.get("demension")
        if demension_raw is None:
            demension_raw = parsed.get("dimensions")

        user_demension = _normalize_kbq_dimensions(user_raw or [])
        llm_demension = _normalize_kbq_dimensions(llm_raw or [])
        demension = _normalize_kbq_dimensions(demension_raw or [])

        if not demension and (user_demension or llm_demension):
            demension = _merge_kbq_dimensions(user_demension, llm_demension)

        return user_demension, llm_demension, demension

    return [], [], []


def _merge_kbq_dimensions(
    base_dimensions: List[Dict[str, Any]],
    supplemental_dimensions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    合并两组维度并去重。
    """
    merged: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in base_dimensions + supplemental_dimensions:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        description = str(item.get("description") or "").strip()
        key = (name.lower(), description.lower())
        if key in seen:
            continue
        seen.add(key)
        normalized: Dict[str, Any] = {"name": name}
        if description:
            normalized["description"] = description
        merged.append(normalized)
    return merged


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


def _load_minutes_text_from_backup_dir(project_id: int, interview_id: int) -> tuple[str | None, Path | None]:
    """
    从访谈备份目录读取最终智能纪要 txt。

    参数:
        project_id: 项目 ID。
        interview_id: 访谈 ID。

    返回:
        (minutes_text, minutes_path) 二元组；未找到时返回 (None, None)。
    """
    backup_dir = Path(__file__).resolve().parent / "data" / f"project_{project_id}" / f"interview_{interview_id}"
    if not backup_dir.exists():
        return None, None
    candidate_paths = [
        backup_dir / "minutes.txt",
        backup_dir / "outline_minutes" / "minutes.txt",
    ]
    for path in candidate_paths:
        if path.exists() and path.is_file():
            try:
                text = path.read_text(encoding="utf-8").strip()
            except Exception:
                continue
            if text:
                return text, path
    return None, None


def _build_minutes_segments_from_text(minutes_text: str) -> List[Dict[str, Any]]:
    """
    将智能纪要 txt 切分为适合本地检索的片段。

    参数:
        minutes_text: minutes.txt 的全文内容。

    返回:
        可用于本地检索的片段列表。
    """
    lines = [line.rstrip() for line in minutes_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    segments: List[Dict[str, Any]] = []
    heading_stack: List[str] = []
    buffer: List[str] = []

    def flush_buffer() -> None:
        if not buffer:
            return
        content = "\n".join(buffer).strip()
        buffer.clear()
        if not content:
            return
        prefix = " ".join(heading_stack).strip()
        text = f"{prefix}\n{content}".strip() if prefix else content
        segments.append({"summary_id": len(segments) + 1, "speaker": "minutes", "timestamp": None, "text": text})

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush_buffer()
            continue
        if line.startswith("#"):
            flush_buffer()
            level = len(line) - len(line.lstrip("#"))
            title = line[level:].strip()
            if not title:
                continue
            heading_stack = heading_stack[: max(0, level - 1)]
            heading_stack.append(title)
            segments.append(
                {
                    "summary_id": len(segments) + 1,
                    "speaker": "minutes",
                    "timestamp": None,
                    "text": " ".join(heading_stack).strip(),
                }
            )
            continue
        if re.match(r"^(?:-|\*|\+)\s+", line) or re.match(r"^\d+[.)]\s+", line):
            flush_buffer()
            item_text = re.sub(r"^(?:-|\*|\+)\s+|^\d+[.)]\s+", "", line).strip()
            if item_text:
                prefix = " ".join(heading_stack).strip()
                text = f"{prefix}\n{item_text}".strip() if prefix else item_text
                segments.append(
                    {
                        "summary_id": len(segments) + 1,
                        "speaker": "minutes",
                        "timestamp": None,
                        "text": text,
                    }
                )
            continue
        buffer.append(line)

    flush_buffer()
    return segments


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
        适合直接传给 KBQ 生成步骤的片段字典列表。
    """
    ranked: List[tuple[float, Dict[str, Any]]] = []
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

    minutes_text, minutes_path = _load_minutes_text_from_backup_dir(project_id, interview_id)
    if not minutes_text:
        return {
            "success": False,
            "stage": "fetch_minutes_text",
            "detail": {"message": "no smart minutes txt found"},
            "project_id": project_id,
            "interview_id": interview_id,
            "total_kbq": 0,
            "results": [],
        }
    minutes_segments = _build_minutes_segments_from_text(minutes_text)
    if not minutes_segments:
        return {
            "success": False,
            "stage": "build_minutes_text",
            "detail": {"message": f"smart minutes txt is empty: {minutes_path}"},
            "project_id": project_id,
            "interview_id": interview_id,
            "total_kbq": 0,
            "results": [],
        }

    model_client: Optional[ModelClient] = None
    model_client_error: Optional[str] = None
    try:
        model_client = ModelClient()
    except Exception as exc:
        model_client_error = f"init model client failed: {exc}"
        log_interview("KBQ", interview_id, f"{model_client_error}; fall back to degraded KBQ Notes")

    results: List[Dict[str, Any]] = []
    log_interview("KBQ", interview_id, f"start generating KBQ Notes for {len(kbq_items)} key BQ items")

    for row in kbq_items:
        kbq_id = row.get("id")
        kbq_order = row.get("bq_order")
        key_bq_text = str(row.get("bq_text") or "").strip()
        if not key_bq_text:
            continue

        user_demension, llm_demension, demension = _parse_kbq_dimension_payload(row.get("dimension_json"))
        generated_llm_demension: List[Dict[str, Any]] = []
        demension_result: Dict[str, Any] = {"user_demension": [], "llm_demension": [], "demension": []}
        merged_demension: List[Dict[str, Any]] = []

        log_interview("KBQ", interview_id, f"start generating KBQ Notes for key BQ {kbq_id}")
        try:
            if user_demension:
                if model_client is not None:
                    generated_dimensions_result = model_client.generate_kbq_dimensions(
                        key_bq_text=key_bq_text,
                        project_context=project_context,
                        interview_context=interview_context,
                        user_dimensions=user_demension,
                    )
                    generated_llm_demension = generated_dimensions_result.get("dimensions") or []
                    llm_demension = _merge_kbq_dimensions(llm_demension, generated_llm_demension)
                    merged_demension = _merge_kbq_dimensions(user_demension, llm_demension)
                    demension_result = {
                        "user_demension": user_demension,
                        "llm_demension": llm_demension,
                        "demension": merged_demension,
                    }
                    if "llm_raw_output" in generated_dimensions_result:
                        demension_result["llm_raw_output"] = generated_dimensions_result["llm_raw_output"]
                else:
                    merged_demension = list(user_demension)
                    demension_result = {
                        "user_demension": user_demension,
                        "llm_demension": llm_demension,
                        "demension": merged_demension,
                        "llm_raw_output": model_client_error or "model client not available",
                    }
            elif llm_demension:
                merged_demension = list(llm_demension)
                demension_result = {
                    "user_demension": [],
                    "llm_demension": llm_demension,
                    "demension": merged_demension,
                }
            elif demension:
                merged_demension = list(demension)
                demension_result = {
                    "user_demension": [],
                    "llm_demension": [],
                    "demension": merged_demension,
                }
            elif model_client is not None:
                generated_dimensions_result = model_client.generate_kbq_dimensions(
                    key_bq_text=key_bq_text,
                    project_context=project_context,
                    interview_context=interview_context,
                )
                generated_llm_demension = generated_dimensions_result.get("dimensions") or []
                llm_demension = _merge_kbq_dimensions(llm_demension, generated_llm_demension)
                merged_demension = _merge_kbq_dimensions(user_demension, llm_demension)
                demension_result = {
                    "user_demension": user_demension,
                    "llm_demension": llm_demension,
                    "demension": merged_demension,
                }
                if "llm_raw_output" in generated_dimensions_result:
                    demension_result["llm_raw_output"] = generated_dimensions_result["llm_raw_output"]
            else:
                merged_demension = []
                demension_result = {
                    "user_demension": [],
                    "llm_demension": [],
                    "demension": [],
                    "llm_raw_output": model_client_error or "model client not available",
                }

            query_text = _build_kbq_query_text(key_bq_text, merged_demension)
            segments = _retrieve_segments_from_summary(minutes_segments, query_text, top_k=top_k)
            log_interview("KBQ", interview_id, f"key BQ {kbq_id} retrieved {len(segments)} local segments")

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
                    demension=merged_demension,
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
                    "demension": demension_result if "demension_result" in locals() else {},
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
                "demension": demension_result,
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
        "warnings": [warning for warning in [model_client_error] if warning],
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
        demension_bundle = item.get("demension") or {}
        notes = item.get("notes") or {}

        if not isinstance(notes, dict):
            errors.append(f"kbq_order={kbq_order}: notes is not dict")
            continue
        if project_id is None or interview_id is None or kbq_order is None or not kbq_text:
            errors.append(f"kbq_order={kbq_order}: missing ids/text for insert")
            continue

        compact_demension = demension_bundle if isinstance(demension_bundle, dict) else {"demension": demension_bundle}
        if isinstance(compact_demension, dict):
            compact_demension = dict(compact_demension)
            compact_demension.pop("llm_raw_output", None)
        compact_notes = dict(notes)
        compact_notes.pop("llm_raw_output", None)

        dimension_json = json.dumps(compact_demension, ensure_ascii=False)
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
    log_interview(
        "KBQ",
        interview_id,
        f"run_kbq_notes start top_k={top_k} project_context_present={bool(project_context)} interview_context_present={bool(interview_context)}",
    )
    interview = DbAccess.get_interview_by_id(interview_id)
    if not interview:
        log_interview("KBQ", interview_id, "run_kbq_notes failed: interview not found")
        return {
            "success": False,
            "stage": "fetch_interview",
            "detail": {"message": f"interview {interview_id} not found"},
        }

    project_id = int(interview.get("parse_project_id") or 0)
    kbq_result = fetch_kbq_items_step(interview_id)
    if not kbq_result.get("success"):
        log_interview("KBQ", interview_id, f"run_kbq_notes failed stage=fetch_kbq detail={kbq_result}")
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
        log_interview("KBQ", interview_id, f"run_kbq_notes failed stage=generate_kbq detail={notes_result}")
        return notes_result

    write_result = write_kbq_notes_results_step(notes_result)
    log_interview(
        "KBQ",
        interview_id,
        f"run_kbq_notes done generated={len(notes_result.get('results') or [])} inserted={write_result.get('inserted', 0)}",
    )
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
