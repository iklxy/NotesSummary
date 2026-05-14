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
    "hospital_city": "city",
    "doctor_level": "doctor_level",
    "doctor_title": "doctor_title",
    "hospital": "hospital",
    "department": "department",
    "hospital_decile": "hospital_decile",
}


def _normalize_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_number(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except Exception:
        return None


def _normalize_hospital_decile(value: Any) -> Optional[int]:
    number = _normalize_number(value)
    if number is None:
        return None
    if number <= 0:
        return None
    if number > 10:
        return None
    return number


def _normalize_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return value
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return value
    text = str(value).strip()
    return text or None


def normalize_interview_detail_payload(
    raw_value: Any = None,
    legacy_values: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    将访谈细节输入统一归一化为通用 JSON 结构。
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
    for key, value in legacy_values.items():
        payload.setdefault(key, value)

    normalized: Dict[str, Any] = {}
    for key, value in payload.items():
        normalized_value = _normalize_scalar(value)
        if key == "hospital_decile":
            normalized_value = _normalize_hospital_decile(value)
        elif key in {"doctor_level", "doctor_title", "city", "hospital_city", "hospital", "department"}:
            normalized_value = _normalize_text(value)
        if normalized_value is not None:
            normalized[key] = normalized_value

    if "city" in normalized and "hospital_city" not in normalized:
        normalized["hospital_city"] = normalized["city"]
    if "hospital_city" in normalized and "city" not in normalized:
        normalized["city"] = normalized["hospital_city"]
    return normalized


def build_interview_display_name(
    project_name: str,
    detail: Dict[str, Any],
    interview_id: Optional[int] = None,
    field_definitions: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    根据项目名称和访谈细节生成展示名称。
    """
    clean_project_name = _normalize_text(project_name) or "项目"
    segments: List[str] = []
    detail_keys: List[str] = []
    if field_definitions:
        detail_keys = [
            str(item.get("key") or "").strip()
            for item in field_definitions
            if str(item.get("key") or "").strip()
        ]
    if not detail_keys:
        detail_keys = [key for key in detail.keys() if key not in {"detail_json", "role_id", "role_name", "role_type"}]

    for key in detail_keys:
        value = detail.get(key)
        if key == "hospital_decile":
            number = _normalize_hospital_decile(value)
            if number is not None:
                segments.append(str(number))
            continue
        text = _normalize_text(value)
        if text:
            segments.append(text)

    if segments:
        deduped_segments: List[str] = []
        seen_segments: set[str] = set()
        for segment in segments:
            if segment in seen_segments:
                continue
            seen_segments.add(segment)
            deduped_segments.append(segment)
        return "-".join([clean_project_name, *deduped_segments[:4]])
    if interview_id is not None:
        return f"{clean_project_name}-访谈-{interview_id}"
    return f"{clean_project_name}-访谈"


def build_interview_detail_meta(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    从访谈行中提取可用于 CA / 展示的细节字段。
    """
    meta: Dict[str, Any] = {}
    detail_json = row.get("detail_json")
    if isinstance(detail_json, str) and detail_json.strip():
        try:
            parsed = json.loads(detail_json)
        except Exception:
            parsed = {}
        if isinstance(parsed, dict):
            meta.update({k: _normalize_scalar(v) for k, v in parsed.items() if _normalize_scalar(v) is not None})

    for key in INTERVIEW_DETAIL_FIELD_KEYS:
        if key in meta and meta[key] is not None:
            continue
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
