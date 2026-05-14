from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import require_current_user_id
from db import (
    count_key_bq_usage,
    delete_key_bq,
    fetch_key_bq_by_id,
    fetch_key_bq_by_project,
    fetch_project_by_id,
    insert_key_bq,
    upsert_project_key_bq,
    update_key_bq,
)


router = APIRouter(prefix="/api/projects", tags=["project_key_bq"])

_CURRENT_KEY_BQ_NAME = "__current__"


class ProjectKeyBqCreateRequest(BaseModel):
    name: str
    key_bq_json: Any = Field(default_factory=dict)


class ProjectKeyBqUpdateRequest(BaseModel):
    name: Optional[str] = None
    key_bq_json: Any = None


class ProjectKeyBqSingletonRequest(BaseModel):
    key_bq_json: Any = Field(default_factory=dict)


def _get_owned_project_or_404(project_id: int, current_user_id: int) -> Dict[str, Any]:
    project = fetch_project_by_id(project_id, current_user_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _normalize_dimensions(raw_dimensions: Any) -> List[dict[str, Any]]:
    result: List[dict[str, Any]] = []
    if not isinstance(raw_dimensions, list):
        return result
    for item in raw_dimensions:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            normalized = {"name": name}
            description = str(item.get("description") or "").strip()
            if description:
                normalized["description"] = description
            result.append(normalized)
        else:
            text = str(item or "").strip()
            if text:
                result.append({"name": text})
    return result


def _normalize_key_bq_items(raw_items: Any) -> List[dict[str, Any]]:
    result: List[dict[str, Any]] = []
    if not isinstance(raw_items, list):
        return result
    for item in raw_items:
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            user_demension = _normalize_dimensions(
                item.get("user_demension")
                if item.get("user_demension") is not None
                else item.get("user_dimensions")
            )
            llm_demension = _normalize_dimensions(
                item.get("llm_demension")
                if item.get("llm_demension") is not None
                else item.get("llm_dimensions")
                if item.get("llm_dimensions") is not None
                else item.get("supplemental_dimensions")
            )
            demension = _normalize_dimensions(
                item.get("demension")
                if item.get("demension") is not None
                else item.get("dimensions")
            )
            if not demension:
                demension = list(user_demension) + [entry for entry in llm_demension if entry not in user_demension]
        else:
            text = str(item or "").strip()
            if not text:
                continue
            user_demension = []
            llm_demension = []
            demension = []
        result.append(
            {
                "order": len(result) + 1,
                "text": text,
                "user_demension": user_demension,
                "llm_demension": llm_demension,
                "demension": demension,
            }
        )
    return result


def _normalize_key_bq_json(raw_value: Any) -> str:
    if raw_value is None:
        raise HTTPException(status_code=400, detail="key_bq_json is required")

    payload: dict[str, Any] | None = None
    if isinstance(raw_value, dict):
        items = raw_value.get("key_bq_list")
        if isinstance(items, list):
            payload = {"key_bq_list": _normalize_key_bq_items(items)}
    elif isinstance(raw_value, list):
        payload = {"key_bq_list": _normalize_key_bq_items(raw_value)}
    else:
        text = str(raw_value).strip()
        if not text:
            raise HTTPException(status_code=400, detail="key_bq_json is required")
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("key_bq_list"), list):
            payload = {"key_bq_list": _normalize_key_bq_items(parsed.get("key_bq_list"))}
        elif isinstance(parsed, list):
            payload = {"key_bq_list": _normalize_key_bq_items(parsed)}
        else:
            items = []
            for line in text.splitlines():
                line_text = line.strip()
                if not line_text:
                    continue
                items.append(
                    {
                        "order": len(items) + 1,
                        "text": line_text,
                        "user_demension": [],
                        "llm_demension": [],
                        "demension": [],
                    }
                )
            payload = {"key_bq_list": items}

    items = payload.get("key_bq_list") if payload else []
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="key_bq_json is empty")
    return json.dumps(payload, ensure_ascii=False)


def _parse_key_bq_json(raw_value: Any) -> dict[str, Any]:
    if raw_value is None:
        return {"key_bq_list": []}
    if isinstance(raw_value, dict):
        return raw_value if isinstance(raw_value.get("key_bq_list"), list) else {"key_bq_list": []}
    text = str(raw_value).strip()
    if not text:
        return {"key_bq_list": []}
    try:
        parsed = json.loads(text)
    except Exception:
        return {"key_bq_list": []}
    if isinstance(parsed, dict) and isinstance(parsed.get("key_bq_list"), list):
        return parsed
    return {"key_bq_list": []}


def _to_response_row(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "id": int(row["id"]),
        "project_id": int(row["project_id"]),
        "name": row.get("name"),
        "key_bq_json": _parse_key_bq_json(row.get("key_bq_json")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "referenced_interview_count": int(row.get("referenced_interview_count") or 0),
    }


def _to_singleton_response(project_row: dict | None) -> dict:
    if not project_row:
        raise HTTPException(status_code=404, detail="project not found")
    return {
        "success": True,
        "project_id": int(project_row["id"]),
        "key_bq_json": _parse_key_bq_json(project_row.get("key_bq_json")),
        "updated_at": project_row.get("updated_at"),
    }


@router.post("/{project_id}/key-bq", response_model=Dict[str, Any])
def create_key_bq(
    project_id: int,
    payload: ProjectKeyBqCreateRequest,
    current_user_id: int = Depends(require_current_user_id),
) -> Dict[str, Any]:
    _get_owned_project_or_404(project_id, current_user_id)
    clean_name = payload.name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="key bq name is required")
    if clean_name == _CURRENT_KEY_BQ_NAME:
        raise HTTPException(status_code=400, detail="reserved key bq name")

    existing = fetch_key_bq_by_project(project_id, current_user_id)
    if any(str(row.get("name") or "").strip() == clean_name for row in existing):
        raise HTTPException(status_code=409, detail="key bq name already exists")

    normalized_json = _normalize_key_bq_json(payload.key_bq_json)
    new_id = insert_key_bq(project_id, clean_name, normalized_json)
    row = fetch_key_bq_by_id(new_id, project_id, current_user_id)
    response_row = _to_response_row(row)
    if response_row is None:
        raise HTTPException(status_code=500, detail="create key bq failed")
    response_row["success"] = True
    return response_row


@router.get("/{project_id}/key-bq/current", response_model=Dict[str, Any])
def get_current_key_bq(
    project_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> Dict[str, Any]:
    project = _get_owned_project_or_404(project_id, current_user_id)
    return _to_singleton_response(project)


@router.put("/{project_id}/key-bq/current", response_model=Dict[str, Any])
def update_current_key_bq(
    project_id: int,
    payload: ProjectKeyBqSingletonRequest,
    current_user_id: int = Depends(require_current_user_id),
) -> Dict[str, Any]:
    _get_owned_project_or_404(project_id, current_user_id)
    normalized_json = _normalize_key_bq_json(payload.key_bq_json)
    upsert_project_key_bq(project_id, normalized_json)
    refreshed_project = fetch_project_by_id(project_id, current_user_id)
    if not refreshed_project:
        raise HTTPException(status_code=500, detail="update project key bq failed")
    return _to_singleton_response(refreshed_project)


@router.get("/{project_id}/key-bq", response_model=list[Dict[str, Any]])
def list_key_bq(
    project_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> list[Dict[str, Any]]:
    _get_owned_project_or_404(project_id, current_user_id)
    rows = fetch_key_bq_by_project(project_id, current_user_id)
    return [_to_response_row(row) or {} for row in rows]


@router.get("/{project_id}/key-bq/{key_bq_id}", response_model=Dict[str, Any])
def get_key_bq(
    project_id: int,
    key_bq_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> Dict[str, Any]:
    row = fetch_key_bq_by_id(key_bq_id, project_id, current_user_id)
    if not row:
        raise HTTPException(status_code=404, detail="key bq not found")
    response_row = _to_response_row(row)
    if response_row is None:
        raise HTTPException(status_code=404, detail="key bq not found")
    return response_row


@router.put("/{project_id}/key-bq/{key_bq_id}", response_model=Dict[str, Any])
def update_key_bq_item(
    project_id: int,
    key_bq_id: int,
    payload: ProjectKeyBqUpdateRequest,
    current_user_id: int = Depends(require_current_user_id),
) -> Dict[str, Any]:
    row = fetch_key_bq_by_id(key_bq_id, project_id, current_user_id)
    if not row:
        raise HTTPException(status_code=404, detail="key bq not found")

    clean_name = payload.name.strip() if payload.name is not None else None
    if clean_name is not None:
        if not clean_name:
            raise HTTPException(status_code=400, detail="key bq name is required")
        existing = fetch_key_bq_by_project(project_id, current_user_id)
        if any(int(item["id"]) != key_bq_id and str(item.get("name") or "").strip() == clean_name for item in existing):
            raise HTTPException(status_code=409, detail="key bq name already exists")

    normalized_json = None
    if payload.key_bq_json is not None:
        normalized_json = _normalize_key_bq_json(payload.key_bq_json)

    updated = update_key_bq(
        key_bq_id=key_bq_id,
        project_id=project_id,
        name=clean_name,
        key_bq_json=normalized_json,
    )
    response_row = _to_response_row(updated)
    if response_row is None:
        raise HTTPException(status_code=500, detail="update key bq failed")
    response_row["success"] = True
    return response_row


@router.delete("/{project_id}/key-bq/{key_bq_id}", response_model=Dict[str, Any])
def remove_key_bq_item(
    project_id: int,
    key_bq_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> Dict[str, Any]:
    row = fetch_key_bq_by_id(key_bq_id, project_id, current_user_id)
    if not row:
        raise HTTPException(status_code=404, detail="key bq not found")

    usage_count = count_key_bq_usage(key_bq_id, project_id)
    if usage_count > 0:
        raise HTTPException(status_code=409, detail="key bq is referenced by interviews")

    deleted_row = delete_key_bq(key_bq_id, project_id, current_user_id)
    if not deleted_row:
        raise HTTPException(status_code=500, detail="delete key bq failed")

    return {
        "success": True,
        "key_bq_id": key_bq_id,
        "project_id": project_id,
        "key_bq_name": deleted_row.get("name"),
        "deleted": True,
    }
