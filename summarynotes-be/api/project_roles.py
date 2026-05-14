from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


DEFAULT_PROJECT_ROLE_LABELS: Dict[str, str] = {
    "doctor": "医生",
    "patient": "患者",
    "custom": "自定义角色",
}

DEFAULT_PROJECT_ROLE_FIELDS: Dict[str, List[Dict[str, Any]]] = {
    "doctor": [
        {"key": "doctor_level", "label": "医生级别", "kind": "text"},
        {"key": "doctor_title", "label": "职称", "kind": "text"},
        {"key": "city", "label": "城市", "kind": "text"},
        {"key": "hospital", "label": "所在医院", "kind": "text"},
        {"key": "department", "label": "科室", "kind": "text"},
        {"key": "hospital_decile", "label": "医院Decile", "kind": "number"},
    ],
    "patient": [
        {"key": "patient_disease_type", "label": "患者疾病类型", "kind": "text"},
        {"key": "region", "label": "地区", "kind": "text"},
        {"key": "hospital", "label": "就诊医院", "kind": "text"},
        {"key": "department", "label": "就诊科室", "kind": "text"},
    ],
    "custom": [],
}


def normalize_role_type(raw_value: Any) -> Optional[str]:
    if raw_value is None:
        return None
    text = str(raw_value).strip().lower()
    if text in {"doctor", "医生"}:
        return "doctor"
    if text in {"patient", "患者"}:
        return "patient"
    if text in {"custom", "自定义", "其他", "other"}:
        return "custom"
    return None


def build_default_role_name(role_type: str | None) -> str:
    normalized = normalize_role_type(role_type)
    if normalized is None:
        return "角色"
    return DEFAULT_PROJECT_ROLE_LABELS.get(normalized, normalized)


def normalize_detail_schema_fields(
    raw_value: Any = None,
    role_type: str | None = None,
) -> List[Dict[str, Any]]:
    normalized_role_type = normalize_role_type(role_type)
    default_fields = DEFAULT_PROJECT_ROLE_FIELDS.get(normalized_role_type or "", [])

    payload: Any = raw_value
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            payload = None
        else:
            try:
                payload = json.loads(text)
            except Exception:
                payload = None

    if payload is None:
        return [dict(item) for item in default_fields]

    if isinstance(payload, dict):
        candidate = payload.get("fields")
        if isinstance(candidate, list):
            payload = candidate
        else:
            payload = []

    if not isinstance(payload, list):
        return [dict(item) for item in default_fields]

    fields: List[Dict[str, Any]] = []
    seen_keys: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        label = str(item.get("label") or "").strip()
        kind = str(item.get("kind") or "text").strip() or "text"
        if not key:
            continue
        if key in seen_keys:
            continue
        seen_keys.add(key)
        fields.append(
            {
                "key": key,
                "label": label or key,
                "kind": kind,
            }
        )

    if not fields:
        return [dict(item) for item in default_fields]
    return fields


def build_default_role_detail_schema(role_type: str | None) -> List[Dict[str, Any]]:
    normalized_role_type = normalize_role_type(role_type)
    return [dict(item) for item in DEFAULT_PROJECT_ROLE_FIELDS.get(normalized_role_type or "", [])]
