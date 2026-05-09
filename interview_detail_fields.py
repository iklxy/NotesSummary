from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


INTERVIEW_DETAIL_FIELD_DEFINITIONS: List[Dict[str, Any]] = [
    {"key": "doctor_level", "label": "医生级别", "kind": "text"},
    {"key": "doctor_title", "label": "职称", "kind": "text"},
    {"key": "city", "label": "城市", "kind": "text"},
    {"key": "hospital", "label": "所在医院", "kind": "text"},
    {"key": "department", "label": "科室", "kind": "text"},
    {"key": "hospital_decile", "label": "医院Decile", "kind": "number"},
]

INTERVIEW_DETAIL_FIELD_KEYS: List[str] = [str(item["key"]) for item in INTERVIEW_DETAIL_FIELD_DEFINITIONS]
INTERVIEW_DETAIL_FIELD_LABELS: Dict[str, str] = {
    str(item["key"]): str(item["label"]) for item in INTERVIEW_DETAIL_FIELD_DEFINITIONS
}
INTERVIEW_DETAIL_FIELD_KINDS: Dict[str, str] = {
    str(item["key"]): str(item.get("kind") or "text") for item in INTERVIEW_DETAIL_FIELD_DEFINITIONS
}

LEGACY_INTERVIEW_DETAIL_FIELD_ALIASES: Dict[str, str] = {
    "city": "hospital_city",
    "doctor_level": "doctor_level",
    "hospital_decile": "hospital_decile",
}


def _normalize_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_hospital_decile(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        if value <= 0:
            return None
        return value if value <= 10 else None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = int(float(text))
    except Exception:
        return None
    if number <= 0:
        return None
    if number > 10:
        return None
    return number


def normalize_interview_detail_payload(
    raw_value: Any = None,
    legacy_values: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    将访谈细节输入统一归一化为系统内部结构。
    """
    payload: Dict[str, Any] = {}
    if isinstance(raw_value, dict):
        payload.update(raw_value)
    elif isinstance(raw_value, str):
        text = raw_value.strip()
        if text:
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = {}
            if isinstance(parsed, dict):
                payload.update(parsed)

    legacy_values = legacy_values or {}
    normalized: Dict[str, Any] = {}
    for key in INTERVIEW_DETAIL_FIELD_KEYS:
        source_value = payload.get(key)
        if source_value is None and key in LEGACY_INTERVIEW_DETAIL_FIELD_ALIASES:
            source_value = legacy_values.get(LEGACY_INTERVIEW_DETAIL_FIELD_ALIASES[key])
        if key == "hospital_decile":
            normalized[key] = _normalize_hospital_decile(source_value)
        else:
            normalized[key] = _normalize_text(source_value)
    return normalized


def build_interview_display_name(
    project_name: str,
    detail: Dict[str, Any],
    interview_id: Optional[int] = None,
) -> str:
    """
    根据项目名称和访谈细节生成展示名称。
    """
    clean_project_name = _normalize_text(project_name) or "项目"
    segments: List[str] = []
    for key in INTERVIEW_DETAIL_FIELD_KEYS:
        value = detail.get(key)
        if key == "hospital_decile":
            if value is None:
                continue
            try:
                number = int(value)
            except Exception:
                continue
            if number <= 0:
                continue
            segments.append(str(number))
            continue
        text = _normalize_text(value)
        if text:
            segments.append(text)

    if segments:
        return "-".join([clean_project_name, *segments])
    if interview_id is not None:
        return f"{clean_project_name}-访谈-{interview_id}"
    return f"{clean_project_name}-访谈"


def build_interview_detail_meta(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    从访谈行中提取可用于 CA / 展示的细节字段。
    """
    meta: Dict[str, Any] = {}
    for key in INTERVIEW_DETAIL_FIELD_KEYS:
        value = row.get(key)
        if value is None:
            alias = LEGACY_INTERVIEW_DETAIL_FIELD_ALIASES.get(key)
            if alias is not None:
                value = row.get(alias)
        if key == "hospital_decile":
            meta[key] = _normalize_hospital_decile(value)
        else:
            meta[key] = _normalize_text(value)
    return meta

