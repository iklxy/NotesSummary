from pathlib import Path
import json
import os
import re
import shutil
import traceback
from typing import Any, Dict, Optional
from urllib.parse import quote

import requests

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from pydantic import BaseModel

from api.auth import require_current_user_id
from InterviewLogger import log_project
from db import (
    delete_project_graph,
    fetch_interview_by_id,
    fetch_interviews_by_project,
    fetch_ca_table_by_project,
    fetch_project_by_id,
    fetch_projects,
    insert_project,
    upsert_ca_table,
)
from storage import delete_remote_object
from xlsx_export import XLSX_MIME_TYPE, build_ca_table_xlsx_bytes


class ProjectCreate(BaseModel):
    """
    创建项目的请求体结构。

    字段:
        name:             项目名称，必填。
        keywords:         项目关键词，可空。
        core_problem:   访谈核心描述，可空。
    """

    name: str
    keywords: Optional[str] = None
    core_problem: Optional[str] = None


router = APIRouter(prefix="/api/projects", tags=["projects"])


def _get_owned_project_or_404(project_id: int, current_user_id: int) -> Dict[str, Any]:
    """
    查询当前用户可访问的项目；若不属于当前用户则统一返回 404。

    参数:
        project_id: 项目主键 ID。
        current_user_id: 当前登录用户 ID。

    返回:
        项目记录字典。
    """
    project = fetch_project_by_id(project_id, current_user_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _get_audio_root() -> Path:
    """
    获取本地音频备份的根目录 audio/。

    返回:
        项目根目录下的 audio 路径。
    """
    api_dir = Path(__file__).resolve().parent
    project_root = api_dir.parent.parent
    return project_root / "audio"


def _get_data_root() -> Path:
    """
    获取本地问卷与访谈备份的根目录 data/。

    返回:
        项目根目录下的 data 路径。
    """
    api_dir = Path(__file__).resolve().parent
    project_root = api_dir.parent.parent
    return project_root / "data"


def _get_internal_base() -> str:
    """
    获取内部 Engine 服务的基地址。

    返回:
        可直接拼接 /internal/... 的服务基地址。
    """
    base = os.getenv("INTERNAL_SERVICE_BASE", "http://127.0.0.1:8000")
    return base.rstrip("/")


def _get_qdrant_base_url() -> str:
    """
    获取 Qdrant 服务基地址。

    返回:
        例如 http://127.0.0.1:6333 的字符串。
    """
    host_env = os.getenv("QDRANT_HOST", "localhost")
    port_env = int(os.getenv("QDRANT_PORT", "6333"))
    if host_env.startswith("http://") or host_env.startswith("https://"):
        return host_env.rstrip("/")
    return f"http://{host_env}:{port_env}"


def _get_qdrant_collection_name() -> str:
    """
    获取用于 summary 向量的 Qdrant 集合名。

    返回:
        集合名称字符串。
    """
    return os.getenv("QDRANT_COLLECTION_SUMMARY", "interview_summary")


def _delete_qdrant_points_for_interview(interview_id: int) -> tuple[bool, str | None]:
    """
    按访谈 ID 删除 Qdrant 中对应的 summary chunk 向量。

    参数:
        interview_id: 访谈 ID。

    返回:
        (是否删除成功, 失败原因)。当 Qdrant 集合不存在时视为成功。
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
    删除单个访谈对应的本地音频目录。

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
    删除单个访谈对应的本地备份目录。

    参数:
        project_id: 项目 ID。
        interview_id: 访谈 ID。

    返回:
        (是否删除成功, 失败原因)。
    """
    target_dir = _get_data_root() / f"project_{project_id}" / f"interview_{interview_id}"
    if not target_dir.exists():
        return True, None
    try:
        shutil.rmtree(target_dir)
    except Exception as e:
        return False, f"local backup delete failed: {e}"
    return True, None


def _delete_project_local_dirs(project_id: int) -> tuple[bool, str | None]:
    """
    删除项目级本地目录，作为访谈级目录清理后的补充。

    参数:
        project_id: 项目 ID。

    返回:
        (是否删除成功, 失败原因)。
    """
    targets = [
        _get_audio_root() / f"project_{project_id}",
        _get_data_root() / f"project_{project_id}",
    ]
    for target_dir in targets:
        if not target_dir.exists():
            continue
        try:
            shutil.rmtree(target_dir)
        except Exception as e:
            return False, f"project local dir delete failed: {e}"
    return True, None


def _delete_cloud_audio_object(object_key: str | None) -> tuple[bool, str | None]:
    """
    删除云端音频对象。

    参数:
        object_key: TOS 对象 key；如果为空则跳过。

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


def _safe_load_json_text(value: Any) -> Dict[str, Any] | None:
    """
    安全解析 JSON 文本。

    参数:
        value: 可能已经是字典、也可能是 JSON 字符串的对象。

    返回:
        解析成功时返回字典；否则返回 None。
    """
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _get_ca_data_root() -> Path:
    """
    获取本地 CA 缓存目录根路径。

    返回:
        项目根目录下的 `data` 路径。
    """
    api_dir = Path(__file__).resolve().parent
    project_root = api_dir.parent.parent
    return project_root / "data"


def _get_ca_cache_path(project_id: int) -> Path:
    """
    获取项目级 CA 缓存文件路径。

    参数:
        project_id: 项目 ID。

    返回:
        `data/project_{project_id}/ca_table.json`
    """
    return _get_ca_data_root() / f"project_{project_id}" / "ca_table.json"


def _load_ca_payload_from_files(project_id: int) -> tuple[Dict[str, Any] | None, Path | None]:
    """
    从本地缓存中读取 CA JSON。

    参数:
        project_id: 项目 ID。

    返回:
        (payload, source_path)；没有有效文件则返回 (None, None)。
    """
    candidate_paths = [
        _get_ca_cache_path(project_id),
    ]
    for path in candidate_paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload, path
    return None, None


def _build_download_content_disposition(filename: str) -> str:
    """
    生成兼容中文文件名的 Content-Disposition。

    参数:
        filename: 目标文件名。

    返回:
        可直接放入响应头的 Content-Disposition。
    """
    ascii_filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("_") or "download.xlsx"
    return f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{quote(filename)}'


def _build_ca_export_filename(project_name: str | None, project_id: int) -> str:
    """
    构造 CA 导出文件名。

    参数:
        project_name: 项目名称。
        project_id: 项目 ID。

    返回:
        导出文件名字符串。
    """
    base_name = (project_name or f"project_{project_id}").strip() or f"project_{project_id}"
    safe_chars: List[str] = []
    for ch in base_name:
        if ch.isalnum() or ch in {"-", "_", " ", "(", ")", "[", "]", "【", "】", "、", ".", ","}:
            safe_chars.append(ch)
        else:
            safe_chars.append("_")
    cleaned = "".join(safe_chars).strip().replace(" ", "_")
    if not cleaned:
        cleaned = f"project_{project_id}"
    return f"{cleaned}_CA.xlsx"


@router.post("", response_model=Dict[str, Any])
def create_project(
    payload: ProjectCreate,
    current_user_id: int = Depends(require_current_user_id),
) -> Dict[str, Any]:
    """
    创建新项目，对应在 bh_project 表中插入一条记录。

    参数:
        payload: 前端传入的项目信息，包括 name、keywords、core_problem。

    返回:
        新创建项目的基础信息字典，至少包含:
            - id
            - name
            - keywords
            - core_problem

    异常:
        HTTPException(400): name 为空或非法。
        HTTPException(500): 数据库插入失败。
    """
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="项目名称不能为空")

    try:
        new_id = insert_project(
            name=name,
            keywords=(payload.keywords.strip() if payload.keywords else None),
            core_problem=(payload.core_problem.strip() if payload.core_problem else None),
            created_by_user_id=current_user_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"insert project failed: {e}")

    return {
        "id": new_id,
        "name": name,
        "keywords": payload.keywords,
        "core_problem": payload.core_problem,
    }


@router.get("", response_model=list[Dict[str, Any]])
def list_projects(
    current_user_id: int = Depends(require_current_user_id),
) -> list[Dict[str, Any]]:
    """
    查询所有项目列表。

    返回:
        项目字典列表，每个元素至少包含:
            - id
            - name
            - keywords
            - core_problem
    """
    rows = fetch_projects(created_by_user_id=current_user_id)
    return rows


@router.get("/{project_id}/ca-table", response_model=Dict[str, Any])
def get_project_ca_table(
    project_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> Dict[str, Any]:
    """
    查询指定项目的 CA 表结果。

    返回:
        包含 ca_json 的响应字典；若数据库未命中则尝试从本地缓存恢复。
    """
    project = _get_owned_project_or_404(project_id, current_user_id)
    row = fetch_ca_table_by_project(project_id)
    ca_json = None
    if row:
        ca_json = _safe_load_json_text(row.get("ca_json"))

    if ca_json is None:
        fallback_payload, fallback_path = _load_ca_payload_from_files(project_id)
        if fallback_payload is not None:
            ca_json = fallback_payload
            try:
                upsert_ca_table(
                    project_id=project_id,
                    ca_json=fallback_payload,
                    status=str(fallback_payload.get("status") or "done"),
                    error_message=fallback_payload.get("error_message"),
                    generated_at=fallback_payload.get("generated_at"),
                )
            except Exception:
                pass

    return {
        "success": True,
        "project_id": project_id,
        "project_name": project.get("name"),
        "ca_json": ca_json,
    }


@router.post("/{project_id}/ca-table/generate", response_model=Dict[str, Any])
def generate_project_ca_table(
    project_id: int,
    payload: Dict[str, Any] | None = Body(default=None),
    current_user_id: int = Depends(require_current_user_id),
) -> Dict[str, Any]:
    """
    触发项目级 CA 表生成。

    参数:
        project_id: 项目 ID。
        payload: 可选请求体，支持:
            - interview_ids: 当前选择的访谈 ID 列表
            - column_meta_fields: 列元数据字段列表
    """
    _get_owned_project_or_404(project_id, current_user_id)
    body = payload or {}
    url = f"{_get_internal_base()}/internal/projects/{project_id}/generate-ca-table"
    request_payload = {
        "interview_ids": body.get("interview_ids") or [],
        "column_meta_fields": body.get("column_meta_fields") or [],
    }
    log_project("CA", project_id, f"BFF 开始请求 CA 生成 request_payload={request_payload}")
    try:
        resp = requests.post(url, json=request_payload, timeout=3600)
    except Exception as e:
        log_project("CA", project_id, f"BFF 请求 CA 生成异常 error={e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"generate ca table request failed: {e}")

    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        log_project(
            "CA",
            project_id,
            f"BFF 收到 CA 生成失败响应 status_code={resp.status_code} detail={detail}",
        )
        raise HTTPException(status_code=resp.status_code, detail=detail)

    try:
        log_project("CA", project_id, "BFF 收到 CA 生成成功响应")
        return resp.json()
    except Exception as e:
        log_project("CA", project_id, f"BFF 解析 CA 生成响应失败 error={e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"parse generate ca table response failed: {e}")


@router.post("/{project_id}/ca-table/export-xlsx")
def export_project_ca_table_xlsx(
    project_id: int,
    payload: Dict[str, Any] | None = Body(default=None),
    current_user_id: int = Depends(require_current_user_id),
) -> Response:
    """
    导出项目级 CA 表为 Excel。

    支持在请求体中携带 `ca_json`，用于在前端编辑后直接导出并回填数据库。
    """
    project = _get_owned_project_or_404(project_id, current_user_id)
    log_project("CA", project_id, "开始导出 CA Excel")
    body = payload or {}
    ca_json = body.get("ca_json") if isinstance(body, dict) else None
    if not isinstance(ca_json, dict):
        row = fetch_ca_table_by_project(project_id)
        if row:
            ca_json = _safe_load_json_text(row.get("ca_json"))
    if not isinstance(ca_json, dict):
        fallback_payload, _ = _load_ca_payload_from_files(project_id)
        if fallback_payload is not None:
            ca_json = fallback_payload
    if not isinstance(ca_json, dict):
        log_project("CA", project_id, "导出 CA Excel 失败：未找到可用 CA 数据")
        raise HTTPException(status_code=404, detail="ca table not found")

    try:
        upsert_ca_table(
            project_id=project_id,
            ca_json=ca_json,
            status=str(ca_json.get("status") or "done"),
            error_message=ca_json.get("error_message"),
            generated_at=ca_json.get("generated_at"),
        )
    except Exception as e:
        log_project("CA", project_id, f"CA Excel 回填数据库失败 error={e}")
        raise HTTPException(status_code=500, detail=f"save ca table failed: {e}")

    try:
        xlsx_bytes = build_ca_table_xlsx_bytes(ca_json)
    except Exception as e:
        log_project("CA", project_id, f"CA Excel 导出失败：build xlsx failed error={e}")
        raise HTTPException(status_code=500, detail=f"build ca xlsx failed: {e}")

    project_name = project.get("name")
    filename = _build_ca_export_filename(project_name, project_id)
    headers = {
        "Content-Disposition": _build_download_content_disposition(filename),
    }
    log_project("CA", project_id, f"CA Excel 导出完成 filename={filename}")
    return Response(content=xlsx_bytes, media_type=XLSX_MIME_TYPE, headers=headers)


@router.delete("/{project_id}", response_model=Dict[str, Any])
def delete_project(
    project_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> Dict[str, Any]:
    """
    删除项目及其关联访谈、题目、summary、notes、few-shot 样本。

    参数:
        project_id: 项目主键 ID。
        current_user_id: 当前登录用户 ID，用于校验项目归属。

    返回:
        删除结果字典，包含成功标记、删除访谈数量和可能的外部资源清理警告。
    """
    project = _get_owned_project_or_404(project_id, current_user_id)

    interview_rows = fetch_interviews_by_project(project_id, current_user_id)
    interview_ids = [int(row["id"]) for row in interview_rows]
    warnings: list[str] = []

    for interview_id in interview_ids:
        interview = fetch_interview_by_id(interview_id, current_user_id)
        if not interview:
            continue

        project_for_interview = interview.get("parse_project_id")
        file_path = interview.get("file_path")
        local_audio_deleted = False
        local_backup_deleted = False
        cloud_audio_deleted = False
        qdrant_deleted = False

        qdrant_deleted, qdrant_error = _delete_qdrant_points_for_interview(interview_id)
        if not qdrant_deleted and qdrant_error:
            warnings.append(qdrant_error)

        if project_for_interview is not None:
            local_audio_deleted, local_audio_error = _delete_local_audio_dir(
                int(project_for_interview),
                interview_id,
            )
            if not local_audio_deleted and local_audio_error:
                warnings.append(local_audio_error)

            local_backup_deleted, local_backup_error = _delete_local_backup_dir(
                int(project_for_interview),
                interview_id,
            )
            if not local_backup_deleted and local_backup_error:
                warnings.append(local_backup_error)

        cloud_audio_deleted, cloud_audio_error = _delete_cloud_audio_object(file_path)
        if not cloud_audio_deleted and cloud_audio_error:
            warnings.append(cloud_audio_error)

    project_dir_deleted, project_dir_error = _delete_project_local_dirs(project_id)
    if not project_dir_deleted and project_dir_error:
        warnings.append(project_dir_error)

    try:
        db_row = delete_project_graph(project_id, current_user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"database delete failed: {e}")

    if not db_row:
        raise HTTPException(status_code=404, detail="project not found")

    return {
        "success": True,
        "project_id": project_id,
        "project_name": project.get("name"),
        "deleted_interviews": len(interview_ids),
        "warnings": warnings or None,
    }
