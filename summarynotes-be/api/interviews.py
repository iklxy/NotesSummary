from pathlib import Path
import shutil
from typing import Any, Dict, List

import os
import requests
from fastapi import APIRouter, HTTPException

from db import delete_interview_graph, fetch_interview_by_id, fetch_interview_summary
from schemas.interviews import (
    DeleteInterviewResponse,
    InterviewNotesResponse,
    InterviewQuestionsResponse,
    InterviewStatusResponse,
    RunInterviewResponse,
)


router = APIRouter(prefix="/api/interviews", tags=["interviews"])


def _get_internal_base() -> str:
    """
    获取内部 SummaryNotes 引擎服务的基地址。

    优先从环境变量 INTERNAL_SERVICE_BASE 中读取；
    如果未配置，则默认使用本地地址 http://127.0.0.1:8000。
    最终返回值会移除末尾多余的斜杠。

    返回:
        用于拼接 /internal/... 路由的服务基地址字符串。
    """
    base = os.getenv("INTERNAL_SERVICE_BASE", "http://127.0.0.1:8000")
    return base.rstrip("/")


def _get_audio_root() -> Path:
    api_dir = Path(__file__).resolve().parent
    project_root = api_dir.parent.parent
    return project_root / "audio"


@router.post("/{interview_id}/run", response_model=RunInterviewResponse)
def run_interview_workflow(interview_id: int) -> RunInterviewResponse:
    """
    对外接口：触发指定访谈的完整工作流执行。

    调用内部 SummaryNotes 服务的:
        POST /internal/interviews/{interview_id}/run-workflow
    并从返回结果中抽取核心信息，封装为精简的 RunInterviewResponse。

    参数:
        interview_id: 访谈主键 ID，对应 bh_project_interview.id。

    返回:
        RunInterviewResponse 实例，包含:
            - success: 是否执行成功。
            - summary_inserted: 写入 summary 表的记录数（若有）。
            - notes_inserted: 写入 notes 表的记录数（若有）。
            - message: 在失败或部分失败时的人类可读错误信息。

    异常:
        HTTPException(404): 内部服务返回 404，表示访谈不存在。
        HTTPException(502): 内部服务不可用或返回 5xx 错误。
    """
    base = _get_internal_base()
    url = f"{base}/internal/interviews/{interview_id}/run-workflow"
    try:
        resp = requests.post(url, timeout=600)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"internal service error: {e}")

    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="interview not found")
    if resp.status_code >= 500:
        raise HTTPException(status_code=502, detail="internal service failed")

    data: Dict[str, Any] = resp.json()

    success = bool(data.get("success", False))
    summary_inserted = data.get("summary_inserted")
    notes_db = data.get("notes_db") or {}
    notes_inserted = notes_db.get("inserted")
    message = None

    if not success:
        stage = data.get("stage")
        detail = data.get("detail")
        if isinstance(detail, dict):
            detail_msg = detail.get("message") or ""
        else:
            detail_msg = str(detail)
        parts = [p for p in [stage, detail_msg] if p]
        message = " | ".join(parts) if parts else "run workflow failed"

    return RunInterviewResponse(
        success=success,
        summary_inserted=summary_inserted,
        notes_inserted=notes_inserted,
        message=message,
    )


@router.get("/{interview_id}/status", response_model=InterviewStatusResponse)
def get_interview_status(interview_id: int) -> InterviewStatusResponse:
    """
    查询访谈当前处理状态。

    返回:
        - interview_id
        - status: bh_project_interview.status
    """
    row = fetch_interview_by_id(interview_id)
    if not row:
        raise HTTPException(status_code=404, detail="interview not found")
    return InterviewStatusResponse(
        interview_id=interview_id,
        status=row.get("status"),
    )


@router.delete("/{interview_id}", response_model=DeleteInterviewResponse)
def delete_interview(interview_id: int) -> DeleteInterviewResponse:
    """
    删除访谈及其关联数据。
    """
    row = delete_interview_graph(interview_id)
    if not row:
        raise HTTPException(status_code=404, detail="interview not found")

    project_id = row.get("parse_project_id")
    audio_deleted = False
    if project_id is not None:
        target_dir = _get_audio_root() / f"project_{project_id}" / f"interview_{interview_id}"
        if target_dir.exists():
            shutil.rmtree(target_dir)
            audio_deleted = True

    return DeleteInterviewResponse(
        success=True,
        interview_id=interview_id,
        audio_deleted=audio_deleted,
    )


@router.get(
    "/{interview_id}/notes",
    response_model=InterviewNotesResponse,
)
def get_interview_notes(interview_id: int) -> InterviewNotesResponse:
    """
    对外接口：获取指定访谈的 Notes 列表（按题目聚合）。

    调用内部 SummaryNotes 服务的:
        GET /internal/interviews/{interview_id}/notes
    并将其返回的 JSON 映射为 InterviewNotesResponse。

    参数:
        interview_id: 访谈主键 ID，对应 bh_project_interview.id。

    返回:
        InterviewNotesResponse 实例，包含:
            - interview_id: 访谈 ID。
            - project_id: 所属项目 ID。
            - questions: 每个题目及其对应的 Notes 列表。

    异常:
        HTTPException(404): 内部服务返回 404，表示访谈不存在。
        HTTPException(502): 内部服务不可用或返回 5xx 错误。
    """
    base = _get_internal_base()
    url = f"{base}/internal/interviews/{interview_id}/notes"
    try:
        resp = requests.get(url, timeout=60)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"internal service error: {e}")

    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="interview not found")
    if resp.status_code >= 500:
        raise HTTPException(status_code=502, detail="internal service failed")

    data = resp.json()
    return InterviewNotesResponse(**data)


@router.get(
    "/{interview_id}/questions",
    response_model=InterviewQuestionsResponse,
)
def get_interview_questions(interview_id: int) -> InterviewQuestionsResponse:
    """
    对外接口：获取指定访谈下配置的题目列表。

    调用内部 SummaryNotes 服务的:
        GET /internal/interviews/{interview_id}/questions
    并将其返回的 JSON 映射为 InterviewQuestionsResponse。

    参数:
        interview_id: 访谈主键 ID，对应 bh_project_interview.id。

    返回:
        InterviewQuestionsResponse 实例，包含:
            - interview_id: 访谈 ID。
            - questions: 该访谈下的题目明细列表。

    异常:
        HTTPException(404): 内部服务返回 404，通常表示未配置题目。
        HTTPException(502): 内部服务不可用或返回 5xx 错误。
    """
    base = _get_internal_base()
    url = f"{base}/internal/interviews/{interview_id}/questions"
    try:
        resp = requests.get(url, timeout=30)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"internal service error: {e}")

    if resp.status_code == 404:
        detail = resp.json().get("detail", "questions not found")
        raise HTTPException(status_code=404, detail=detail)
    if resp.status_code >= 500:
        raise HTTPException(status_code=502, detail="internal service failed")

    data = resp.json()
    return InterviewQuestionsResponse(**data)


@router.get("/{interview_id}/summary")
def get_interview_summary(interview_id: int) -> Dict[str, Any]:
    """
    对外接口：获取指定访谈的原文明细列表。

    数据直接从 bh_project_interview_summary 表中读取。

    参数:
        interview_id: 访谈主键 ID，对应 bh_project_interview_summary.project_interview_id。

    返回:
        {
            "interview_id": interview_id,
            "items": [
                {
                    "id": ...,
                    "project_interview_id": ...,
                    "timestamp": "...",
                    "speaker": "...",
                    "text": "..."
                },
                ...
            ]
        }
    """
    rows: List[Dict[str, Any]] = fetch_interview_summary(project_interview_id=interview_id)
    return {"interview_id": interview_id, "items": rows}
