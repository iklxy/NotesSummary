from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from api.auth import require_current_user_id
from db import (
    count_questionnaire_usage,
    delete_questionnaire,
    fetch_project_by_id,
    fetch_questionnaire_by_id,
    fetch_questionnaires_by_project,
    insert_questionnaire,
    update_questionnaire,
)
from DocxToMd import convert_docx_questionnaire
from QuestionnaireHotword import extract_questionnaire_hotword_candidates


router = APIRouter(prefix="/api/projects", tags=["project_questionnaires"])


class QuestionnaireHotwordReviewRequest(BaseModel):
    hotwords: List[str] = Field(default_factory=list)


def _normalize_object_type(raw_value: Any) -> Optional[str]:
    if raw_value is None:
        return None
    text = str(raw_value).strip().lower()
    if text in {"patient", "患者"}:
        return "patient"
    if text in {"doctor", "医生"}:
        return "doctor"
    return None


def _get_data_root() -> Path:
    api_dir = Path(__file__).resolve().parent
    project_root = api_dir.parent.parent
    return project_root / "data"


def _get_owned_project_or_404(project_id: int, current_user_id: int) -> Dict[str, Any]:
    project = fetch_project_by_id(project_id, current_user_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _get_questionnaire_dir(project_id: int, questionnaire_id: int) -> Path:
    return _get_data_root() / f"project_{project_id}" / "question" / f"questionnaire_{questionnaire_id}"


def _normalize_text_list(items: List[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _parse_hotwords(raw_value: Any) -> List[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        return _normalize_text_list([str(item) for item in raw_value])
    if isinstance(raw_value, dict):
        value = raw_value.get("hotwords")
        if isinstance(value, list):
            return _normalize_text_list([str(item) for item in value])
        return []
    text = str(raw_value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        return _normalize_text_list(text.splitlines())
    if isinstance(parsed, list):
        return _normalize_text_list([str(item) for item in parsed])
    if isinstance(parsed, dict):
        value = parsed.get("hotwords")
        if isinstance(value, list):
            return _normalize_text_list([str(item) for item in value])
    return []


def _read_text_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write_json_file(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_uploaded_docx_file(target_dir: Path, upload_file: UploadFile) -> Path:
    filename = upload_file.filename or ""
    if not filename:
        raise HTTPException(status_code=400, detail="上传文件缺少文件名")
    if not filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="仅支持 docx 格式的问卷")

    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / "source.docx"
    try:
        with target_path.open("wb") as f:
            while True:
                chunk = upload_file.file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"save questionnaire file failed: {e}")
    return target_path


def _rename_questionnaire_outputs(target_dir: Path, source_docx: Path) -> tuple[Path, Path]:
    source_md = target_dir / f"{source_docx.stem}.md"
    source_json = target_dir / f"{source_docx.stem}.json"
    target_md = target_dir / "questionnaire.md"
    target_json = target_dir / "questionnaire.json"

    if source_md.exists():
        if target_md.exists():
            target_md.unlink()
        source_md.replace(target_md)
    if source_json.exists():
        if target_json.exists():
            target_json.unlink()
        source_json.replace(target_json)

    if not target_md.exists() or not target_json.exists():
        raise HTTPException(status_code=500, detail="questionnaire conversion output missing")
    return target_md, target_json


def _build_candidates_payload(
    project_id: int,
    questionnaire_id: int,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "questionnaire_id": questionnaire_id,
        "hotword_candidates": candidates,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }


def _to_response_row(row: dict | None) -> dict | None:
    if not row:
        return None
    hotwords = _parse_hotwords(row.get("hotwords"))
    return {
        "id": int(row["id"]),
        "project_id": int(row["project_id"]),
        "name": row.get("name"),
        "object_type": row.get("object_type"),
        "file_name": row.get("file_name"),
        "docx_path": row.get("docx_path"),
        "md_path": row.get("md_path"),
        "json_path": row.get("json_path"),
        "hotwords": hotwords,
        "status": row.get("status"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "referenced_interview_count": int(row.get("referenced_interview_count") or 0),
    }


@router.post("/{project_id}/questionnaires", response_model=Dict[str, Any])
async def create_questionnaire(
    project_id: int,
    current_user_id: int = Depends(require_current_user_id),
    name: str = Form(...),
    object_type: str = Form(...),
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    project_row = _get_owned_project_or_404(project_id, current_user_id)
    clean_name = name.strip() or Path(file.filename or "questionnaire").stem
    clean_object_type = _normalize_object_type(object_type)
    if clean_object_type is None:
        raise HTTPException(status_code=400, detail="object type is required")
    existing_rows = fetch_questionnaires_by_project(project_id, current_user_id)
    if any(_normalize_object_type(row.get("object_type")) == clean_object_type for row in existing_rows):
        raise HTTPException(status_code=409, detail="object type already exists")

    questionnaire_id = insert_questionnaire(
        project_id=project_id,
        name=clean_name,
        object_type=clean_object_type,
        file_name=file.filename or None,
        status="hotword_review_pending",
    )

    questionnaire_dir = _get_questionnaire_dir(project_id, questionnaire_id)
    questionnaire_dir.mkdir(parents=True, exist_ok=True)
    try:
        source_docx = _save_uploaded_docx_file(questionnaire_dir, file)
        convert_result = convert_docx_questionnaire(source_docx, questionnaire_dir)
        md_path, json_path = _rename_questionnaire_outputs(questionnaire_dir, source_docx)
        md_text = _read_text_file(md_path)

        hotword_result = extract_questionnaire_hotword_candidates(
            markdown_text=md_text,
            project_context=str(project_row.get("core_problem") or ""),
        )
        candidates_raw = hotword_result.get("hotword_candidates") or []
        hotword_candidates: list[dict[str, Any]] = []
        hotword_terms: list[str] = []
        for item in candidates_raw:
            if not isinstance(item, dict):
                continue
            term = str(item.get("term") or "").strip()
            normalized_term = str(item.get("normalized_term") or "").strip()
            if not term and not normalized_term:
                continue
            hotword_candidates.append(
                {
                    "term": term,
                    "normalized_term": normalized_term,
                    "reason": item.get("reason"),
                    "confidence": item.get("confidence"),
                }
            )
            hotword_terms.append(normalized_term or term)

        hotword_terms = _normalize_text_list(hotword_terms)
        _write_json_file(
            questionnaire_dir / "hotword_candidates.json",
            _build_candidates_payload(project_id, questionnaire_id, hotword_candidates),
        )
        _write_json_file(
            questionnaire_dir / "hotwords.json",
            {
                "project_id": project_id,
                "questionnaire_id": questionnaire_id,
                "hotwords": hotword_terms,
                "updated_at": datetime.utcnow().isoformat() + "Z",
            },
        )

        updated_row = update_questionnaire(
            questionnaire_id=questionnaire_id,
            project_id=project_id,
            docx_path=str(source_docx.relative_to(_get_data_root())),
            md_path=str(md_path.relative_to(_get_data_root())),
            json_path=str(json_path.relative_to(_get_data_root())),
            hotwords=hotword_terms,
            status="hotword_review_pending",
            object_type=clean_object_type,
        )
        response_row = _to_response_row(updated_row)
        if response_row is None:
            raise RuntimeError("update questionnaire failed")
        response_row["success"] = True
        response_row["hotword_candidates"] = hotword_candidates
        response_row["review_required"] = True
        return response_row
    except Exception as e:
        try:
            shutil.rmtree(questionnaire_dir, ignore_errors=True)
        except Exception:
            pass
        try:
            delete_questionnaire(questionnaire_id, project_id, current_user_id)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"questionnaire processing failed: {e}")


@router.get("/{project_id}/questionnaires", response_model=list[Dict[str, Any]])
def list_questionnaires(
    project_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> list[Dict[str, Any]]:
    _get_owned_project_or_404(project_id, current_user_id)
    rows = fetch_questionnaires_by_project(project_id, current_user_id)
    return [_to_response_row(row) or {} for row in rows]


@router.get("/{project_id}/questionnaires/{questionnaire_id}", response_model=Dict[str, Any])
def get_questionnaire(
    project_id: int,
    questionnaire_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> Dict[str, Any]:
    row = fetch_questionnaire_by_id(questionnaire_id, project_id, current_user_id)
    if not row:
        raise HTTPException(status_code=404, detail="questionnaire not found")
    response_row = _to_response_row(row)
    if response_row is None:
        raise HTTPException(status_code=404, detail="questionnaire not found")
    questionnaire_dir = _get_questionnaire_dir(project_id, questionnaire_id)
    hotword_candidates_path = questionnaire_dir / "hotword_candidates.json"
    if hotword_candidates_path.exists():
        try:
            candidates_payload = json.loads(hotword_candidates_path.read_text(encoding="utf-8"))
            response_row["hotword_candidates"] = candidates_payload.get("hotword_candidates") or []
        except Exception:
            response_row["hotword_candidates"] = []
    else:
        response_row["hotword_candidates"] = []
    return response_row


@router.put("/{project_id}/questionnaires/{questionnaire_id}/hotwords", response_model=Dict[str, Any])
def update_questionnaire_hotwords(
    project_id: int,
    questionnaire_id: int,
    payload: QuestionnaireHotwordReviewRequest,
    current_user_id: int = Depends(require_current_user_id),
) -> Dict[str, Any]:
    row = fetch_questionnaire_by_id(questionnaire_id, project_id, current_user_id)
    if not row:
        raise HTTPException(status_code=404, detail="questionnaire not found")

    hotwords = _normalize_text_list(payload.hotwords or [])
    questionnaire_dir = _get_questionnaire_dir(project_id, questionnaire_id)
    questionnaire_dir.mkdir(parents=True, exist_ok=True)
    _write_json_file(
        questionnaire_dir / "hotwords.json",
        {
            "project_id": project_id,
            "questionnaire_id": questionnaire_id,
            "hotwords": hotwords,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        },
    )

    updated_row = update_questionnaire(
        questionnaire_id=questionnaire_id,
        project_id=project_id,
        hotwords=hotwords,
        status="ready",
    )
    response_row = _to_response_row(updated_row)
    if response_row is None:
        raise HTTPException(status_code=500, detail="update questionnaire hotwords failed")
    response_row["success"] = True
    response_row["reviewed_count"] = len(hotwords)
    return response_row


@router.delete("/{project_id}/questionnaires/{questionnaire_id}", response_model=Dict[str, Any])
def remove_questionnaire(
    project_id: int,
    questionnaire_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> Dict[str, Any]:
    row = fetch_questionnaire_by_id(questionnaire_id, project_id, current_user_id)
    if not row:
        raise HTTPException(status_code=404, detail="questionnaire not found")

    usage_count = count_questionnaire_usage(questionnaire_id, project_id)
    if usage_count > 0:
        raise HTTPException(status_code=409, detail="questionnaire is referenced by interviews")

    deleted_row = delete_questionnaire(questionnaire_id, project_id, current_user_id)
    if not deleted_row:
        raise HTTPException(status_code=500, detail="delete questionnaire failed")

    questionnaire_dir = _get_questionnaire_dir(project_id, questionnaire_id)
    shutil.rmtree(questionnaire_dir, ignore_errors=True)
    return {
        "success": True,
        "questionnaire_id": questionnaire_id,
        "project_id": project_id,
        "questionnaire_name": deleted_row.get("name"),
        "deleted": True,
    }
