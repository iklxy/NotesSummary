import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from db import fetch_interviews_by_project, insert_interview


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


@router.post("/{project_id}/interviews", response_model=Dict[str, Any])
async def create_interview(
    project_id: int,
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
        访谈记录字典列表。
    """
    rows = fetch_interviews_by_project(parse_project_id=project_id)
    return rows
