import os
import json
from typing import Any, Dict, Optional
from pathlib import Path

import requests

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from db import (
    fetch_interviews_by_project,
    fetch_question_intents,
    insert_interview,
    insert_questions_for_interview,
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
    base = os.getenv("INTERNAL_SERVICE_BASE", "http://127.0.0.1:8000")
    return base.rstrip("/")


def _trigger_workflow_background(interview_id: int) -> None:
    """
    在后台触发内部引擎工作流。

    这里不把长耗时工作放进创建访谈请求里，避免前端上传接口阻塞。
    """
    try:
        update_interview_status(interview_id, 1)
    except Exception:
        # 状态更新失败不阻止后续触发，避免因为状态字段写入失败导致 workflow 无法执行。
        pass

    url = f"{_get_internal_base()}/internal/interviews/{interview_id}/run-workflow"
    try:
        resp = requests.post(url, timeout=600)
        if resp.status_code >= 400:
            update_interview_status(interview_id, 3)
            return

        data = resp.json()
        if not data.get("success", False):
            update_interview_status(interview_id, 3)
            return

        update_interview_status(interview_id, 2)
    except Exception:
        try:
            update_interview_status(interview_id, 3)
        except Exception:
            pass


def _parse_questions_payload(questions_json: Optional[str]) -> list[dict]:
    if not questions_json:
        return []
    try:
        data = json.loads(questions_json)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"questions_json 格式错误: {e}")

    if not isinstance(data, list):
        raise HTTPException(status_code=400, detail="questions_json 必须是数组")

    valid_intent_ids = {
        row.get("id")
        for row in fetch_question_intents()
        if row.get("id") is not None
    }

    cleaned: list[dict] = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"第 {index} 条问题格式错误")
        question_text = (item.get("question_text") or "").strip()
        question_type = (item.get("question_type") or "OPEN").strip().upper()
        intent_id_raw = item.get("intent_id")
        try:
            intent_id = int(intent_id_raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"第 {index} 条问题的 intent_id 非法")
        if not question_text:
            raise HTTPException(status_code=400, detail=f"第 {index} 条问题不能为空")
        if intent_id not in valid_intent_ids:
            raise HTTPException(status_code=400, detail=f"第 {index} 条问题的 intent_id 不存在")
        cleaned.append(
            {
                "question_order": index,
                "question_text": question_text,
                "question_type": question_type,
                "intent_id": intent_id,
            }
        )

    if not cleaned:
        raise HTTPException(status_code=400, detail="请至少填写一个需总结的问题")

    return cleaned


@router.post("/{project_id}/interviews", response_model=Dict[str, Any])
async def create_interview(
    project_id: int,
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    interview_date: Optional[str] = Form(None),
    questions_json: Optional[str] = Form(None),
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    """
    为指定项目创建访谈，并保存本地音频文件。

    参数:
        project_id:     项目 ID，对应 bh_project.id，写入 bh_project_interview.parse_project_id。
        name:           访谈名称，对应 bh_project_interview.name。
        interview_date: 访谈时间字符串（如 '2026-04-15'），写入 bh_project_interview.interview_date。
        file:           单个音频文件，文件名写入 bh_project_interview.file_name。
        questions_json: 需总结的问题列表 JSON 字符串。

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

    questions = _parse_questions_payload(questions_json)

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

    try:
        insert_questions_for_interview(
            project_interview_id=interview_id,
            questions=questions,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"insert questions failed: {e}")

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
        访谈记录字典列表。
    """
    rows = fetch_interviews_by_project(parse_project_id=project_id)
    return rows
