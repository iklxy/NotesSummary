import os
from typing import Any, Dict, Optional
from pathlib import Path

import requests

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from db import (
    fetch_interviews_by_project,
    insert_interview,
    update_interview_status,
)


router = APIRouter(prefix="/api/projects", tags=["project_interviews"])


def _get_audio_root() -> Path:
    """
    获取本地音频根目录。

    固定使用 SummaryNotes 工程根目录下的 audio 目录：
        <project_root>/audio
    """
    api_dir = Path(__file__).resolve().parent
    project_root = api_dir.parent.parent
    return project_root / "audio"


def _save_uploaded_audio_file(
    project_id: int,
    interview_id: int,
    upload_file: UploadFile,
) -> str:
    """
    将上传的音频文件保存到本地 audio 目录，并返回相对路径。

    保存规则:
        audio/project_{project_id}/interview_{interview_id}/{文件名}

    返回:
        保存后的相对路径，供数据库记录和后续工作流使用。
    """
    original_name = upload_file.filename or ""
    if not original_name:
        raise HTTPException(status_code=400, detail="上传文件缺少文件名")

    audio_root = _get_audio_root()
    target_dir = audio_root / f"project_{project_id}" / f"interview_{interview_id}"
    target_dir.mkdir(parents=True, exist_ok=True)

    target_path = target_dir / original_name

    try:
        with target_path.open("wb") as f:
            while True:
                chunk = upload_file.file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"save audio file failed: {e}")

    relative_path = f"project_{project_id}/interview_{interview_id}/{original_name}"
    return relative_path


def _get_internal_base() -> str:
    """
    获取内部引擎服务的基地址。

    优先读取 INTERNAL_SERVICE_BASE 环境变量，未设置时回退到本机默认地址。
    """
    base = os.getenv("INTERNAL_SERVICE_BASE", "http://127.0.0.1:8000")
    return base.rstrip("/")


def _trigger_workflow_background(interview_id: int) -> None:
    """
    在后台触发内部引擎工作流。

    这里不把长耗时工作放进创建访谈请求里，避免前端上传接口阻塞。
    如果工作流失败，这里只负责更新状态，不向上抛出异常影响上传接口。
    """
    try:
        update_interview_status(interview_id, 1)
    except Exception:
        # 状态更新失败不阻止后续触发，避免因为状态字段写入失败导致 workflow 无法执行。
        pass

    url = f"{_get_internal_base()}/internal/interviews/{interview_id}/transcribe"
    try:
        resp = requests.post(url, timeout=600)
        if resp.status_code >= 400:
            update_interview_status(interview_id, 3)
            return
    except Exception:
        try:
            update_interview_status(interview_id, 3)
        except Exception:
            pass


@router.post("/{project_id}/interviews", response_model=Dict[str, Any])
async def create_interview(
    project_id: int,
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    interview_date: Optional[str] = Form(None),
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    """
    为指定项目创建访谈，并保存本地音频文件。

    参数:
        project_id:     项目 ID，对应 bh_project.id，写入 bh_project_interview.parse_project_id。
        name:           访谈名称，对应 bh_project_interview.name。
        interview_date: 访谈时间字符串（如 '2026-04-15'），写入 bh_project_interview.interview_date。
        file:           单个音频文件，文件名写入 bh_project_interview.file_name。

    返回:
        {
            "id": interview_id,
            "project_id": project_id,
            "name": name,
            "interview_date": interview_date,
            "file_name": 原始文件名,
            "local_path": "project_{project_id}/interview_{interview_id}/{文件名}"
        }

    说明:
        上传完成后会异步触发转录工作流；该接口只负责创建记录和保存音频。
    """
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="访谈名称不能为空")

    original_name = file.filename or ""
    if not original_name:
        raise HTTPException(status_code=400, detail="上传文件缺少文件名")

    try:
        interview_id = insert_interview(
            parse_project_id=project_id,
            name=clean_name,
            interview_date=interview_date,
            file_name=original_name,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"insert interview failed: {e}")

    local_path = _save_uploaded_audio_file(project_id, interview_id, file)

    background_tasks.add_task(_trigger_workflow_background, interview_id)

    return {
        "id": interview_id,
        "project_id": project_id,
        "name": clean_name,
        "interview_date": interview_date,
        "file_name": original_name,
        "local_path": local_path,
    }


@router.get("/{project_id}/interviews", response_model=list[Dict[str, Any]])
def list_project_interviews(project_id: int) -> list[Dict[str, Any]]:
    """
    查询指定项目下的所有访谈记录。

    参数:
        project_id: 项目 ID，对应 bh_project.id，映射为 bh_project_interview.parse_project_id。

    返回:
        访谈记录字典列表，每项至少包含 id、name、interview_date、file_name。
    """
    rows = fetch_interviews_by_project(parse_project_id=project_id)
    return rows
