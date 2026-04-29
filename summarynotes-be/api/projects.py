from pathlib import Path
import os
import shutil
from typing import Any, Dict, Optional

import requests

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import require_current_user_id
from db import (
    delete_project_graph,
    fetch_interview_by_id,
    fetch_interviews_by_project,
    fetch_project_by_id,
    fetch_projects,
    insert_project,
)
from storage import delete_remote_object


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
