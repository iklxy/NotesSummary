from pathlib import Path
import mimetypes
import shutil
import json
from typing import Any, Dict, List

import os
import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from api.auth import require_current_user_id
from db import (
    delete_interview_graph,
    delete_fewshot_sample,
    delete_question_and_notes,
    fetch_interview_by_id,
    fetch_fewshot_samples_by_interview,
    fetch_interview_summary,
    fetch_question_by_id,
    fetch_question_intents,
    fetch_notes_rows_by_interview,
    fetch_questions_by_interview,
    insert_fewshot_sample,
    insert_questions_for_interview,
    update_interview_summary_text,
)
from schemas.interviews import (
    DeleteInterviewResponse,
    FewshotSampleCreateRequest,
    FewshotSampleCreateResponse,
    FewshotSampleDeleteResponse,
    FewshotSampleItem,
    InterviewFewshotSamplesResponse,
    GenerateNotesResponse,
    InterviewNotesResponse,
    InterviewQuestionsResponse,
    InterviewSummaryResponse,
    InterviewStatusResponse,
    RunInterviewResponse,
    QuestionCreateRequest,
    QuestionCreateResponse,
    QuestionDeleteResponse,
    SummaryUpdateRequest,
    SummaryUpdateResponse,
)
from storage import delete_remote_object


router = APIRouter(prefix="/api/interviews", tags=["interviews"])


def _get_owned_interview_or_404(interview_id: int, current_user_id: int) -> Dict[str, Any]:
    """
    查询当前用户可访问的访谈；若不属于当前用户则统一返回 404。

    参数:
        interview_id: 访谈主键 ID。
        current_user_id: 当前登录用户 ID。

    返回:
        访谈记录字典。
    """
    interview = fetch_interview_by_id(interview_id, current_user_id)
    if not interview:
        raise HTTPException(status_code=404, detail="interview not found")
    return interview


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


def _resolve_audio_file(interview_id: int, current_user_id: int) -> tuple[Path, str]:
    """
    根据访谈 ID 定位本地音频文件。

    该函数会先查访谈记录，读取项目 ID 和原始文件名，再拼出本地 audio 目录下的真实路径。
    """
    row = fetch_interview_by_id(interview_id, current_user_id)
    if not row:
        raise HTTPException(status_code=404, detail="interview not found")

    project_id = row.get("parse_project_id")
    file_name = row.get("file_name")
    if project_id is None or not file_name:
        raise HTTPException(status_code=404, detail="audio file not found")

    audio_path = (
        _get_audio_root()
        / f"project_{project_id}"
        / f"interview_{interview_id}"
        / str(file_name)
    )
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="audio file not found")

    return audio_path, str(file_name)


def _get_qdrant_base_url() -> str:
    host_env = os.getenv("QDRANT_HOST", "localhost")
    port_env = int(os.getenv("QDRANT_PORT", "6333"))
    if host_env.startswith("http://") or host_env.startswith("https://"):
        return host_env.rstrip("/")
    return f"http://{host_env}:{port_env}"


def _get_qdrant_collection_name() -> str:
    return os.getenv("QDRANT_COLLECTION_SUMMARY", "interview_summary")


def _delete_qdrant_points_for_interview(interview_id: int) -> tuple[bool, str | None]:
    """
    按访谈 ID 删除 Qdrant 中对应的 summary chunk 向量。
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
    删除 data 目录下的访谈备份目录。
    """
    api_dir = Path(__file__).resolve().parent
    project_root = api_dir.parent.parent
    target_dir = project_root / "data" / f"project_{project_id}" / f"interview_{interview_id}"
    if not target_dir.exists():
        return True, None
    try:
        shutil.rmtree(target_dir)
    except Exception as e:
        return False, f"local backup delete failed: {e}"
    return True, None


def _delete_cloud_audio_object(object_key: str | None) -> tuple[bool, str | None]:
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


def _parse_sample_json(raw: Any) -> tuple[Any, str | None, str | None, int]:
    if isinstance(raw, str):
        try:
            parsed: Any = json.loads(raw)
        except Exception:
            return raw, None, None, 0
    else:
        parsed = raw

    if not isinstance(parsed, dict):
        return parsed, None, None, 0

    summary = parsed.get("summary")
    analysis = parsed.get("analysis")
    evidence = parsed.get("evidence")
    evidence_count = len(evidence) if isinstance(evidence, list) else 0
    return parsed, summary if isinstance(summary, str) else None, analysis if isinstance(analysis, str) else None, evidence_count


@router.post("/{interview_id}/run", response_model=RunInterviewResponse)
def run_interview_workflow(
    interview_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> RunInterviewResponse:
    """
    对外接口：触发指定访谈的转录工作流执行。

    调用内部 SummaryNotes 服务的:
        POST /internal/interviews/{interview_id}/transcribe
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
    _get_owned_interview_or_404(interview_id, current_user_id)
    base = _get_internal_base()
    url = f"{base}/internal/interviews/{interview_id}/transcribe"
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
    queued = bool(data.get("queued", False))
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
        queued=queued,
        summary_inserted=summary_inserted,
        notes_inserted=notes_inserted,
        message=message,
    )


@router.post(
    "/{interview_id}/questions/{question_id}/generate-notes",
    response_model=GenerateNotesResponse,
)
def generate_question_notes(
    interview_id: int,
    question_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> GenerateNotesResponse:
    """
    针对指定题目生成 Notes。
    """
    interview = _get_owned_interview_or_404(interview_id, current_user_id)

    base = _get_internal_base()
    url = f"{base}/internal/interviews/{interview_id}/generate-notes"
    try:
        resp = requests.post(url, params={"question_id": question_id}, timeout=600)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"internal service error: {e}")

    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="interview or question not found")
    if resp.status_code >= 500:
        raise HTTPException(status_code=502, detail="internal service failed")

    data: Dict[str, Any] = resp.json()
    success = bool(data.get("success", False))
    total_questions = int(data.get("total_questions") or 0)
    generated = int(data.get("generated") or 0)
    inserted = int(data.get("inserted") or 0)
    warnings = data.get("warnings") or []
    message = None
    if not success:
        stage = data.get("stage")
        detail = data.get("detail")
        if isinstance(detail, dict):
            detail_msg = detail.get("message") or ""
        else:
            detail_msg = str(detail)
        parts = [p for p in [stage, detail_msg] if p]
        message = " | ".join(parts) if parts else "generate notes failed"

    return GenerateNotesResponse(
        success=success,
        interview_id=interview_id,
        question_id=question_id,
        project_id=interview.get("parse_project_id"),
        total_questions=total_questions,
        generated=generated,
        inserted=inserted,
        warnings=warnings,
        message=message,
    )


@router.get("/{interview_id}/status", response_model=InterviewStatusResponse)
def get_interview_status(
    interview_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> InterviewStatusResponse:
    """
    查询访谈当前处理状态。

    返回:
        - interview_id
        - status: bh_project_interview.status
    """
    row = _get_owned_interview_or_404(interview_id, current_user_id)
    return InterviewStatusResponse(
        interview_id=interview_id,
        status=row.get("status"),
    )


@router.get("/{interview_id}/audio")
def get_interview_audio(
    interview_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> FileResponse:
    """
    返回该访谈对应的本地音频文件，供前端播放器直接播放。

    该接口返回的是文件流响应，而不是预先读取到内存的完整二进制内容，
    方便浏览器按需缓存和 seek。
    """
    audio_path, file_name = _resolve_audio_file(interview_id, current_user_id)
    media_type, _ = mimetypes.guess_type(str(audio_path))
    return FileResponse(
        path=str(audio_path),
        filename=file_name,
        media_type=media_type or "application/octet-stream",
    )


@router.delete("/{interview_id}", response_model=DeleteInterviewResponse)
def delete_interview(
    interview_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> DeleteInterviewResponse:
    """
    删除访谈及其关联数据。
    """
    row = _get_owned_interview_or_404(interview_id, current_user_id)

    project_id = row.get("parse_project_id")
    object_key = row.get("file_path")
    failures: list[str] = []

    qdrant_deleted, qdrant_error = _delete_qdrant_points_for_interview(interview_id)
    if not qdrant_deleted:
        failures.append(qdrant_error or "qdrant delete failed")

    local_audio_deleted = False
    local_audio_error: str | None = None
    if project_id is not None:
        local_audio_deleted, local_audio_error = _delete_local_audio_dir(project_id, interview_id)
        if not local_audio_deleted:
            failures.append(local_audio_error or "local audio delete failed")
        backup_deleted, backup_error = _delete_local_backup_dir(project_id, interview_id)
        if not backup_deleted:
            failures.append(backup_error or "local backup delete failed")

    cloud_audio_deleted, cloud_audio_error = _delete_cloud_audio_object(object_key)
    if not cloud_audio_deleted:
        failures.append(cloud_audio_error or "cloud audio delete failed")

    if failures:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "failed to delete external interview resources",
                "failures": failures,
                "qdrant_deleted": qdrant_deleted,
                "local_audio_deleted": local_audio_deleted,
                "cloud_audio_deleted": cloud_audio_deleted,
            },
        )

    try:
        db_row = delete_interview_graph(interview_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"database delete failed: {e}")

    if not db_row:
        raise HTTPException(status_code=404, detail="interview not found")

    return DeleteInterviewResponse(
        success=True,
        interview_id=interview_id,
        db_deleted=True,
        audio_deleted=local_audio_deleted or cloud_audio_deleted,
        local_audio_deleted=local_audio_deleted,
        cloud_audio_deleted=cloud_audio_deleted,
        qdrant_deleted=qdrant_deleted,
        message=None,
    )


@router.get(
    "/{interview_id}/notes",
    response_model=InterviewNotesResponse,
)
def get_interview_notes(
    interview_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> InterviewNotesResponse:
    """
    对外接口：直接从数据库获取指定访谈的 Notes 列表（按题目聚合）。
    """
    interview = _get_owned_interview_or_404(interview_id, current_user_id)

    rows = fetch_notes_rows_by_interview(interview_id)
    questions_map: Dict[int, Dict[str, Any]] = {}

    for row in rows:
        question_id = row["question_id"]
        if question_id not in questions_map:
            questions_map[question_id] = {
                "question_id": question_id,
                "question_order": row["question_order"],
                "question_text": row["question_text"],
                "question_type": row["question_type"],
                "intent_id": row["question_intent_id"],
                "research_phase": row.get("research_phase"),
                "notes": [],
            }

        notes_id = row.get("notes_id")
        if notes_id is not None:
            note_json_raw = row.get("note_json")
            if isinstance(note_json_raw, str):
                try:
                    note_parsed: Any = json.loads(note_json_raw)
                except Exception:
                    note_parsed = note_json_raw
            else:
                note_parsed = note_json_raw

            questions_map[question_id]["notes"].append(
                {
                    "notes_id": notes_id,
                    "intent_id": row.get("notes_intent_id"),
                    "note_json": note_parsed,
                    "confidence": row.get("confidence"),
                    "status": row.get("status"),
                }
            )

    questions_list = sorted(
        questions_map.values(),
        key=lambda x: (x["question_order"], x["question_id"]),
    )

    return InterviewNotesResponse(
        interview_id=interview_id,
        project_id=interview.get("parse_project_id"),
        questions=questions_list,
    )


@router.get(
    "/{interview_id}/questions",
    response_model=InterviewQuestionsResponse,
)
def get_interview_questions(
    interview_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> InterviewQuestionsResponse:
    """
    对外接口：直接从数据库获取指定访谈下配置的题目列表。
    """
    interview = _get_owned_interview_or_404(interview_id, current_user_id)

    rows = fetch_questions_by_interview(interview_id)
    questions = [
        {
            "id": row["id"],
            "project_interview_id": row["project_interview_id"],
            "question_order": row["question_order"],
            "question_text": row["question_text"],
            "question_type": row.get("question_type"),
            "research_phase": row.get("research_phase"),
            "intent_id": row.get("intent_id"),
        }
        for row in rows
    ]
    return InterviewQuestionsResponse(interview_id=interview_id, questions=questions)


@router.post(
    "/{interview_id}/questions",
    response_model=QuestionCreateResponse,
)
def create_interview_questions(
    interview_id: int,
    payload: QuestionCreateRequest,
    current_user_id: int = Depends(require_current_user_id),
) -> QuestionCreateResponse:
    """
    为指定访谈批量新增需总结的问题。
    """
    interview = _get_owned_interview_or_404(interview_id, current_user_id)

    questions = payload.questions or []
    if not questions:
        raise HTTPException(status_code=400, detail="questions is required")

    existing_questions = fetch_questions_by_interview(interview_id)
    next_order = 1
    if existing_questions:
        next_order = max(int(row.get("question_order") or 0) for row in existing_questions) + 1

    cleaned: List[Dict[str, Any]] = []
    for index, item in enumerate(questions, start=1):
        question_text = (item.question_text or "").strip()
        if not question_text:
            raise HTTPException(status_code=400, detail=f"第 {index} 条问题不能为空")

        cleaned.append(
            {
                "question_order": next_order,
                "question_text": question_text,
                "question_type": "OPEN",
                "intent_id": 1,
                "research_phase": None,
            }
        )
        next_order += 1

    try:
        inserted = insert_questions_for_interview(interview_id, cleaned)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"insert questions failed: {e}")

    return QuestionCreateResponse(
        success=True,
        interview_id=interview_id,
        inserted=inserted,
    )


@router.delete(
    "/{interview_id}/questions/{question_id}",
    response_model=QuestionDeleteResponse,
)
def delete_interview_question(
    interview_id: int,
    question_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> QuestionDeleteResponse:
    """
    删除指定访谈下的一条题目，并级联删除其对应的 Notes。
    """
    _get_owned_interview_or_404(interview_id, current_user_id)

    try:
        result = delete_question_and_notes(interview_id, question_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"delete question failed: {e}")

    if not result:
        raise HTTPException(status_code=404, detail="question not found")

    return QuestionDeleteResponse(
        success=True,
        interview_id=interview_id,
        question_id=question_id,
        question_deleted=bool(result.get("question_deleted")),
        fewshot_deleted=int(result.get("fewshot_deleted") or 0),
        notes_deleted=int(result.get("notes_deleted") or 0),
        message=None,
    )


@router.get(
    "/{interview_id}/fewshot-samples",
    response_model=InterviewFewshotSamplesResponse,
)
def get_interview_fewshot_samples(
    interview_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> InterviewFewshotSamplesResponse:
    """
    查询某个访谈下全部 few-shot 种子。
    """
    interview = _get_owned_interview_or_404(interview_id, current_user_id)

    rows = fetch_fewshot_samples_by_interview(interview_id)
    samples: List[Dict[str, Any]] = []
    for row in rows:
        sample_json, sample_summary, sample_analysis, evidence_count = _parse_sample_json(
            row.get("sample_json")
        )
        samples.append(
            {
                "id": row["id"],
                "project_id": row["project_id"],
                "project_interview_id": row["project_interview_id"],
                "question_id": row["question_id"],
                "question_order": row.get("question_order"),
                "question_text": row.get("question_text"),
                "question_type": row.get("question_type"),
                "research_phase": row.get("research_phase"),
                "intent_id": row["intent_id"],
                "notes_result_id": row.get("notes_result_id"),
                "sample_json": sample_json,
                "sample_summary": sample_summary,
                "sample_analysis": sample_analysis,
                "evidence_count": evidence_count,
                "quality_score": row.get("quality_score"),
                "source_kind": row.get("source_kind"),
                "created_time": row.get("created_time"),
            }
        )

    return InterviewFewshotSamplesResponse(interview_id=interview_id, samples=samples)


@router.post(
    "/{interview_id}/questions/{question_id}/fewshot-samples",
    response_model=FewshotSampleCreateResponse,
)
def create_question_fewshot_sample(
    interview_id: int,
    question_id: int,
    payload: FewshotSampleCreateRequest,
    current_user_id: int = Depends(require_current_user_id),
) -> FewshotSampleCreateResponse:
    """
    为指定问题新增 few-shot 冷启动种子。
    """
    interview = _get_owned_interview_or_404(interview_id, current_user_id)

    question = fetch_question_by_id(interview_id, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="question not found")

    valid_intent_ids = {
        row.get("id")
        for row in fetch_question_intents()
        if row.get("id") is not None
    }
    if payload.intent_id not in valid_intent_ids:
        raise HTTPException(status_code=400, detail="intent_id not found")

    summary = (payload.summary or "").strip()
    analysis = (payload.analysis or "").strip()
    evidence = payload.evidence or []
    if not summary:
        raise HTTPException(status_code=400, detail="summary is required")
    if not analysis:
        raise HTTPException(status_code=400, detail="analysis is required")
    if not evidence:
        raise HTTPException(status_code=400, detail="evidence is required")

    cleaned_evidence: List[Dict[str, Any]] = []
    for index, item in enumerate(evidence, start=1):
        text = (item.text or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail=f"第 {index} 条 evidence 不能为空")
        cleaned_evidence.append(
            {
                "summary_id": int(item.summary_id),
                "speaker": item.speaker,
                "text": text,
            }
        )

    sample_json = {
        "summary": summary,
        "analysis": analysis,
        "evidence": cleaned_evidence,
        "confidence": payload.confidence if payload.confidence is not None else 0.95,
    }

    try:
        sample_id = insert_fewshot_sample(
            project_id=int(interview.get("parse_project_id")),
            project_interview_id=interview_id,
            question_id=question_id,
            intent_id=payload.intent_id,
            sample_json=sample_json,
            quality_score=int(payload.quality_score or 95),
            source_kind=payload.source_kind or "seed",
            notes_result_id=payload.notes_result_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"insert fewshot sample failed: {e}")

    return FewshotSampleCreateResponse(
        success=True,
        interview_id=interview_id,
        question_id=question_id,
        sample_id=sample_id,
    )


@router.delete(
    "/{interview_id}/fewshot-samples/{sample_id}",
    response_model=FewshotSampleDeleteResponse,
)
def delete_question_fewshot_sample(
    interview_id: int,
    sample_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> FewshotSampleDeleteResponse:
    """
    删除指定访谈下的一条 few-shot 冷启动种子。
    """
    _get_owned_interview_or_404(interview_id, current_user_id)

    try:
        row = delete_fewshot_sample(interview_id, sample_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"delete fewshot sample failed: {e}")

    if not row:
        raise HTTPException(status_code=404, detail="fewshot sample not found")

    return FewshotSampleDeleteResponse(
        success=True,
        interview_id=interview_id,
        sample_id=sample_id,
        question_id=row.get("question_id"),
        deleted=True,
        message=None,
    )


@router.get("/{interview_id}/summary")
def get_interview_summary(
    interview_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> Dict[str, Any]:
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
    _get_owned_interview_or_404(interview_id, current_user_id)
    rows: List[Dict[str, Any]] = fetch_interview_summary(project_interview_id=interview_id)
    return {"interview_id": interview_id, "items": rows}


def _reindex_summary_chunks(interview_id: int) -> tuple[bool, int | None, str | None]:
    """
    触发内部引擎重建当前访谈的 RAG 索引。
    """
    base = _get_internal_base()
    url = f"{base}/internal/interviews/{interview_id}/reindex-rag"
    try:
        resp = requests.post(url, timeout=300)
    except Exception as e:
        return False, None, f"internal service error: {e}"

    if resp.status_code == 404:
        return False, None, "interview not found"
    if resp.status_code >= 500:
        return False, None, f"internal service failed: {resp.status_code}"

    data = resp.json()
    return bool(data.get("success", False)), data.get("indexed"), None


@router.patch(
    "/{interview_id}/summary/{summary_id}",
    response_model=SummaryUpdateResponse,
)
def update_interview_summary(
    interview_id: int,
    summary_id: int,
    payload: SummaryUpdateRequest,
    current_user_id: int = Depends(require_current_user_id),
) -> SummaryUpdateResponse:
    """
    更新指定 summary 的文本，并触发索引重建。
    """
    _get_owned_interview_or_404(interview_id, current_user_id)
    new_text = payload.text.strip()
    if not new_text:
        raise HTTPException(status_code=400, detail="summary text is required")

    try:
        updated = update_interview_summary_text(
            summary_id=summary_id,
            project_interview_id=interview_id,
            text=new_text,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"update summary failed: {e}")

    if not updated:
        raise HTTPException(status_code=404, detail="summary not found")

    reindex_succeeded, reindex_indexed, reindex_warning = _reindex_summary_chunks(interview_id)
    if not reindex_succeeded and not reindex_warning:
        reindex_warning = "reindex failed"

    return SummaryUpdateResponse(
        success=True,
        summary=updated,
        reindex_succeeded=reindex_succeeded,
        reindex_indexed=reindex_indexed,
        reindex_warning=reindex_warning,
    )
