"""
CA 摘要导出辅助工具。

该模块负责从 CA JSON 中抽取适合生成 Summary Word 的轻量 JSON，
避免在 workflow、API 和导出层重复实现同一套口径。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_CA_SUMMARY_JSON_NAME = "ca_summary.json"


def _clean_text(value: Any) -> str:
    """
    将任意值归一化为可展示文本。
    """
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def _get_data_root() -> Path:
    """
    获取项目根目录下的 data 目录。
    """
    return ROOT_DIR / "data"


def get_ca_summary_cache_path(project_id: int, questionnaire_id: int | None = None) -> Path:
    """
    获取 CA Summary JSON 的本地缓存路径。
    """
    project_dir = _get_data_root() / f"project_{project_id}"
    project_dir.mkdir(parents=True, exist_ok=True)
    if questionnaire_id is not None:
        ca_dir = project_dir / "ca"
        ca_dir.mkdir(parents=True, exist_ok=True)
        return ca_dir / f"questionnaire_{questionnaire_id}_summary.json"
    return project_dir / DEFAULT_CA_SUMMARY_JSON_NAME


def _normalize_cell_value(value: Any) -> str:
    """
    将 CA 单元格值归一化为字符串。
    """
    if isinstance(value, dict):
        for key in ("value", "answer", "text"):
            candidate = _clean_text(value.get(key))
            if candidate:
                return candidate
        return ""
    return _clean_text(value)


def _count_valid_answers(ca_payload: Dict[str, Any], column_id: str) -> int:
    """
    统计某个问题在当前 CA 中的有效回答数。
    """
    cells = ca_payload.get("cells") if isinstance(ca_payload.get("cells"), dict) else {}
    selected_interview_ids = ca_payload.get("selected_interview_ids") if isinstance(ca_payload.get("selected_interview_ids"), list) else []
    if not selected_interview_ids:
        selected_interview_ids = sorted(
            int(key)
            for key in cells.keys()
            if str(key).strip().isdigit()
        )
    valid_count = 0
    for interview_id in selected_interview_ids:
        interview_key = str(interview_id)
        row = cells.get(interview_key)
        if not isinstance(row, dict):
            continue
        cell_value = _normalize_cell_value(row.get(column_id))
        if cell_value and cell_value != "/":
            valid_count += 1
    return valid_count


def build_ca_summary_payload(ca_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    从 CA JSON 中抽取 Summary Word 需要的轻量 JSON。

    返回结构:
    - schema_version
    - project_id / project_name / questionnaire_id / questionnaire_name
    - generated_at / final_generated_at / reviewed_at
    - items: [{ order, question_uid, question, valid_answer_count, summary_text }]
    """
    source_payload = ca_json.get("final_json") if isinstance(ca_json, dict) and isinstance(ca_json.get("final_json"), dict) else ca_json
    if not isinstance(source_payload, dict):
        source_payload = {}

    columns = source_payload.get("columns") if isinstance(source_payload.get("columns"), list) else []
    items: List[Dict[str, Any]] = []
    for index, column in enumerate(columns, start=1):
        if not isinstance(column, dict):
            continue
        if column.get("hidden"):
            continue
        summary_text = _clean_text(column.get("summary_text") or "/") or "/"
        question_text = _clean_text(column.get("question_text"))
        if not question_text:
            question_text = _clean_text(column.get("display_text"))
        if not question_text:
            question_text = _clean_text(column.get("title"))
        question_uid = _clean_text(column.get("question_uid") or column.get("column_id"))
        column_id = _clean_text(column.get("column_id") or question_uid)
        valid_answer_count = _count_valid_answers(source_payload, column_id)
        if summary_text == "/" or valid_answer_count <= 0:
            continue
        items.append(
            {
                "order": int(column.get("order") or index),
                "question_uid": question_uid or column_id,
                "question": question_text or column_id,
                "valid_answer_count": valid_answer_count,
                "summary_text": summary_text,
            }
        )

    summary_payload: Dict[str, Any] = {
        "schema_version": int(source_payload.get("schema_version") or 0),
        "project_id": source_payload.get("project_id"),
        "project_name": source_payload.get("project_name"),
        "questionnaire_id": source_payload.get("questionnaire_id"),
        "questionnaire_name": source_payload.get("questionnaire_name"),
        "generated_at": source_payload.get("generated_at"),
        "framework_generated_at": source_payload.get("framework_generated_at"),
        "final_generated_at": source_payload.get("final_generated_at"),
        "reviewed_at": source_payload.get("reviewed_at"),
        "items": items,
    }
    return summary_payload
