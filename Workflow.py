"@Date: 2026-04-10"
"@Author: lixinyang"


import json
import os
import socket
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List

from VolcUpload import upload_local_file, build_object_key, build_local_file_path, get_tos_client, tos
from VolcengineConversion import run_asr
from CleanConversion import clean_file_content_json
from Model import ModelClient
from Hotword import load_correction_rules_from_state, load_term_hints_from_state, merge_term_hints
from QuestionnaireHotword import load_reviewed_questionnaire_hotwords
from DbAccess import DbAccess
from InterviewLogger import log_interview
from KBQNotesWorkflow import run_kbq_notes_generation_for_interview
from MinutesWorkflow import generate_minutes_for_interview
from ProjectContext import load_project_context_by_id
from config import config


WORKFLOW_JOB_TYPE = "transcription"
WORKFLOW_LEASE_SECONDS = 45 * 60
WORKFLOW_ASR_TASK_EXPIRES_HOURS = 24


def _workflow_owner() -> str:
    """
    生成当前 worker 的标识，用于工作流租约与恢复扫描。
    """
    return f"{socket.gethostname()}:{os.getpid()}"


def _now() -> datetime:
    """
    返回当前本地时间。
    """
    return datetime.now()


def _parse_json_maybe(value: Any) -> Any:
    """
    尽量将数据库中的 JSON 字符串还原成 Python 对象。
    """
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value
        try:
            return json.loads(text)
        except Exception:
            return value
    return value


def _build_asr_checkpoint(
    *,
    interview_id: int,
    project_id: int | None,
    object_key: str | None,
    audio_url: str | None,
    task_id: str | None = None,
    note: str | None = None,
    retry_count: int | None = None,
    poll_count: int | None = None,
) -> Dict[str, Any]:
    """
    构造 ASR 阶段的恢复上下文。
    """
    checkpoint: Dict[str, Any] = {
        "interview_id": interview_id,
        "project_id": project_id,
        "object_key": object_key,
        "audio_url": audio_url,
    }
    if task_id is not None:
        checkpoint["task_id"] = task_id
    if note is not None:
        checkpoint["note"] = note
    if retry_count is not None:
        checkpoint["retry_count"] = retry_count
    if poll_count is not None:
        checkpoint["poll_count"] = poll_count
    return checkpoint


def _task_expires_at(submitted_at: datetime) -> datetime:
    """
    按当前约定生成 ASR 任务的可恢复截止时间。
    """
    return submitted_at + timedelta(hours=WORKFLOW_ASR_TASK_EXPIRES_HOURS)


def _workflow_log(interview_id: int | None, stage: str, message: str) -> None:
    """
    打印工作流阶段日志，便于定位 ASR、纠错、写库等步骤的执行位置。

    参数:
        interview_id: 访谈 ID；未知时可传 None。
        stage: 阶段名，例如 transcribe、clean_with_llm、write_summary。
        message: 阶段要输出的日志内容。
    """
    log_interview("WORKFLOW", interview_id, f"stage={stage} {message}")


def step_upload_interview_audio(interview_id: int) -> Dict[str, Any]:
    """
    步骤 1：本地上云，返回 {object_key, audio_url}。
    如果 bh_project_interview 已存在 file_path，则直接用它作为 object_key 并生成预签名 URL。
    """
    try:
        _workflow_log(interview_id, "upload", "start")
        row = DbAccess.get_interview_by_id(interview_id)
        if not row:
            _workflow_log(interview_id, "upload", f"failed interview={interview_id} not found")
            return {"success": False, "message": f"interview {interview_id} not found"}

        project_id = row.get("parse_project_id")
        file_name = row.get("file_name") or f"{interview_id}.wav"
        object_key = row.get("file_path")

        if not object_key:
            local_path = build_local_file_path(project_id, interview_id, file_name)
            object_key = build_object_key(project_id, interview_id, file_name)
            upload_result = upload_local_file(local_path, object_key)
            if not upload_result.get("success"):
                _workflow_log(interview_id, "upload", f"failed upload_result={upload_result}")
                return {"success": False, "message": "upload failed", "detail": upload_result}
            audio_url = upload_result["data"]["audio_url"]
            try:
                DbAccess.update_interview_after_upload(
                    interview_id=interview_id,
                    object_key=object_key,
                    status=1,
                    file_id=object_key,
                    audio_url=audio_url,
                )
                DbAccess.upsert_workflow_job(
                    project_id=int(project_id),
                    interview_id=interview_id,
                    workflow_type=WORKFLOW_JOB_TYPE,
                    status="running",
                    stage="audio_ready",
                    object_key=object_key,
                    audio_url=audio_url,
                    checkpoint_json=_build_asr_checkpoint(
                        interview_id=interview_id,
                        project_id=int(project_id),
                        object_key=object_key,
                        audio_url=audio_url,
                        note="audio uploaded",
                    ),
                    lease_owner=_workflow_owner(),
                    lease_expires_at=_now() + timedelta(seconds=WORKFLOW_LEASE_SECONDS),
                )
            except Exception as e:
                _workflow_log(interview_id, "upload", f"failed update after upload error={e}")
                return {"success": False, "message": f"update after upload failed: {e}"}
            _workflow_log(interview_id, "upload", f"done object_key={object_key}")
            return {"success": True, "object_key": object_key, "audio_url": audio_url}
        else:
            client = get_tos_client()
            pre = client.pre_signed_url(
                tos.HttpMethodType.Http_Method_Get,
                bucket=config.TOS_BUCKET_NAME,
                key=object_key,
                expires=config.TOS_URL_EXPIRE_SECONDS,
            )
            audio_url = pre.signed_url
            try:
                DbAccess.upsert_workflow_job(
                    project_id=int(project_id),
                    interview_id=interview_id,
                    workflow_type=WORKFLOW_JOB_TYPE,
                    status="running",
                    stage="audio_ready",
                    object_key=object_key,
                    audio_url=audio_url,
                    checkpoint_json=_build_asr_checkpoint(
                        interview_id=interview_id,
                        project_id=int(project_id),
                        object_key=object_key,
                        audio_url=audio_url,
                        note="audio reused",
                    ),
                    lease_owner=_workflow_owner(),
                    lease_expires_at=_now() + timedelta(seconds=WORKFLOW_LEASE_SECONDS),
                )
            except Exception as e:
                _workflow_log(interview_id, "upload", f"failed update existing audio job error={e}")
            _workflow_log(interview_id, "upload", f"done existing_object_key={object_key}")
            return {"success": True, "object_key": object_key, "audio_url": audio_url}
    except Exception as e:
        _workflow_log(interview_id, "upload", f"failed error={e} traceback={traceback.format_exc()}")
        return {"success": False, "message": f"upload step unexpected error: {e}"}


def step_transcribe(
    audio_url: str,
    interview_id: int | None = None,
    project_id: int | None = None,
    object_key: str | None = None,
) -> Dict[str, Any]:
    """
    步骤 2：调用 ASR，将云上音频转写为 {full_text, speakers[]} 结构。
    """
    try:
        _workflow_log(interview_id, "transcribe", f"start audio_url={audio_url}")
        job_row = None
        if interview_id is not None:
            job_row = DbAccess.get_workflow_job_by_interview(interview_id, WORKFLOW_JOB_TYPE)
        current_project_id = project_id
        current_object_key = object_key
        if job_row:
            if current_project_id is None and job_row.get("project_id") is not None:
                current_project_id = int(job_row.get("project_id"))
            if current_object_key is None and job_row.get("object_key"):
                current_object_key = str(job_row.get("object_key"))

        if job_row and job_row.get("asr_result_json"):
            cached_asr_result = _parse_json_maybe(job_row.get("asr_result_json"))
            if isinstance(cached_asr_result, dict):
                if interview_id is not None and current_project_id is not None:
                    try:
                        DbAccess.upsert_workflow_job(
                            project_id=int(current_project_id),
                            interview_id=interview_id,
                            workflow_type=WORKFLOW_JOB_TYPE,
                            status="running",
                            stage="asr_done",
                            object_key=current_object_key,
                            audio_url=audio_url,
                            volc_task_id=job_row.get("volc_task_id"),
                            task_submitted_at=job_row.get("task_submitted_at"),
                            last_polled_at=_now(),
                            task_expires_at=job_row.get("task_expires_at"),
                            retry_count=int(job_row.get("retry_count") or 0),
                            poll_count=int(job_row.get("poll_count") or 0),
                            lease_owner=_workflow_owner(),
                            lease_expires_at=_now() + timedelta(seconds=WORKFLOW_LEASE_SECONDS),
                            asr_result_json=cached_asr_result,
                            checkpoint_json=_build_asr_checkpoint(
                                interview_id=interview_id,
                                project_id=current_project_id,
                                object_key=current_object_key,
                                audio_url=audio_url,
                                task_id=str(job_row.get("volc_task_id") or ""),
                                note="cached asr result reused",
                                retry_count=int(job_row.get("retry_count") or 0),
                                poll_count=int(job_row.get("poll_count") or 0),
                            ),
                        )
                    except Exception:
                        pass
                _workflow_log(
                    interview_id,
                    "transcribe",
                    f"reuse cached asr_result task_id={job_row.get('volc_task_id')} stage={job_row.get('stage')}",
                )
                return {
                    "success": True,
                    "asr_result": cached_asr_result,
                    "task_id": job_row.get("volc_task_id"),
                    "cached": True,
                }

        existing_task_id = None
        existing_task_expires_at = None
        existing_task_submitted_at = None
        if job_row and job_row.get("volc_task_id"):
            task_expires_at = job_row.get("task_expires_at")
            if task_expires_at is None or task_expires_at > _now():
                existing_task_id = str(job_row.get("volc_task_id"))
                existing_task_expires_at = task_expires_at
                existing_task_submitted_at = job_row.get("task_submitted_at")

        retry_count = int(job_row.get("retry_count") or 0) if job_row else 0
        poll_count = int(job_row.get("poll_count") or 0) if job_row else 0
        poll_state = {"count": poll_count}
        lease_owner = _workflow_owner()
        submitted_at = _now()
        current_task_submitted_at = existing_task_submitted_at or submitted_at
        current_task_expires_at = existing_task_expires_at or _task_expires_at(submitted_at)
        current_task_id = existing_task_id or str(job_row.get("volc_task_id") or "")

        if job_row and job_row.get("volc_task_id") and not existing_task_id:
            retry_count += 1

        def _persist_task_submitted(task_id: str) -> None:
            nonlocal current_task_id
            if interview_id is None or current_project_id is None:
                return
            current_task_id = task_id
            current_task_submitted_at_local = submitted_at
            current_task_expires_at_local = _task_expires_at(current_task_submitted_at_local)
            DbAccess.upsert_workflow_job(
                project_id=int(current_project_id),
                interview_id=interview_id,
                workflow_type=WORKFLOW_JOB_TYPE,
                status="waiting_asr",
                stage="asr_submitting",
                object_key=current_object_key,
                audio_url=audio_url,
                volc_task_id=task_id,
                task_submitted_at=current_task_submitted_at_local,
                next_poll_at=current_task_submitted_at_local,
                last_polled_at=current_task_submitted_at_local,
                task_expires_at=current_task_expires_at_local,
                retry_count=retry_count,
                poll_count=poll_state["count"],
                lease_owner=lease_owner,
                lease_expires_at=current_task_submitted_at_local + timedelta(seconds=WORKFLOW_LEASE_SECONDS),
                checkpoint_json=_build_asr_checkpoint(
                    interview_id=interview_id,
                    project_id=current_project_id,
                    object_key=current_object_key,
                    audio_url=audio_url,
                    task_id=task_id,
                    note="asr submitted",
                    retry_count=retry_count,
                    poll_count=poll_state["count"],
                ),
            )

        def _persist_poll_state(response: Dict[str, Any]) -> None:
            if interview_id is None or current_project_id is None:
                return
            response_payload = response.get("resp", {}) if isinstance(response, dict) else {}
            poll_at = _now()
            poll_state["count"] += 1
            DbAccess.upsert_workflow_job(
                project_id=int(current_project_id),
                interview_id=interview_id,
                workflow_type=WORKFLOW_JOB_TYPE,
                status="waiting_asr",
                stage="asr_polling",
                object_key=current_object_key,
                audio_url=audio_url,
                volc_task_id=current_task_id,
                last_polled_at=poll_at,
                next_poll_at=poll_at,
                retry_count=retry_count,
                poll_count=poll_state["count"],
                lease_owner=lease_owner,
                lease_expires_at=poll_at + timedelta(seconds=WORKFLOW_LEASE_SECONDS),
                checkpoint_json=_build_asr_checkpoint(
                    interview_id=interview_id,
                    project_id=current_project_id,
                    object_key=current_object_key,
                    audio_url=audio_url,
                    task_id=current_task_id,
                    note=f"poll code={response_payload.get('code')} message={response_payload.get('message')}",
                    retry_count=retry_count,
                    poll_count=poll_state["count"],
                ),
            )

        run_result = run_asr(
            audio_url,
            task_id=existing_task_id,
            on_task_submitted=_persist_task_submitted if existing_task_id is None else None,
            on_poll=_persist_poll_state,
        )

        if run_result.get("success"):
            asr_result = run_result.get("asr_result") or {}
            if not isinstance(asr_result, dict):
                asr_result = {}
            if interview_id is not None and current_project_id is not None:
                DbAccess.upsert_workflow_job(
                    project_id=int(current_project_id),
                    interview_id=interview_id,
                    workflow_type=WORKFLOW_JOB_TYPE,
                    status="running",
                    stage="asr_done",
                    object_key=current_object_key,
                    audio_url=audio_url,
                    volc_task_id=str(run_result.get("task_id") or existing_task_id or ""),
                    task_submitted_at=current_task_submitted_at,
                    last_polled_at=_now(),
                    task_expires_at=current_task_expires_at,
                    retry_count=retry_count,
                    poll_count=max(poll_state["count"], 1),
                    lease_owner=lease_owner,
                    lease_expires_at=_now() + timedelta(seconds=WORKFLOW_LEASE_SECONDS),
                    asr_result_json=asr_result,
                    error_stage=None,
                    error_message=None,
                    error_traceback=None,
                    checkpoint_json=_build_asr_checkpoint(
                        interview_id=interview_id,
                        project_id=current_project_id,
                        object_key=current_object_key,
                        audio_url=audio_url,
                        task_id=str(run_result.get("task_id") or existing_task_id or ""),
                        note="asr done",
                        retry_count=retry_count,
                        poll_count=max(poll_state["count"], 1),
                    ),
                )
            _workflow_log(
                interview_id,
                "transcribe",
                f"done keys={sorted(asr_result.keys())} task_id={run_result.get('task_id')} source={'cache' if run_result.get('cached') else 'live'}",
            )
            return {
                "success": True,
                "asr_result": asr_result,
                "task_id": run_result.get("task_id") or existing_task_id,
                "cached": bool(run_result.get("cached")),
            }

        if run_result.get("recoverable"):
            if interview_id is not None and current_project_id is not None:
                now = _now()
                DbAccess.upsert_workflow_job(
                    project_id=int(current_project_id),
                    interview_id=interview_id,
                    workflow_type=WORKFLOW_JOB_TYPE,
                    status="waiting_asr",
                    stage="asr_polling",
                    object_key=current_object_key,
                    audio_url=audio_url,
                    volc_task_id=str(run_result.get("task_id") or existing_task_id or ""),
                    last_polled_at=now,
                    next_poll_at=now,
                    task_expires_at=current_task_expires_at,
                    retry_count=retry_count,
                    poll_count=max(poll_state["count"], 1),
                    lease_owner=lease_owner,
                    lease_expires_at=now + timedelta(seconds=WORKFLOW_LEASE_SECONDS),
                    error_stage="transcribe",
                    error_message=run_result.get("message"),
                    checkpoint_json=_build_asr_checkpoint(
                        interview_id=interview_id,
                        project_id=current_project_id,
                        object_key=current_object_key,
                        audio_url=audio_url,
                        task_id=str(run_result.get("task_id") or existing_task_id or ""),
                        note="asr pending",
                        retry_count=retry_count,
                        poll_count=max(poll_state["count"], 1),
                    ),
                )
            _workflow_log(
                interview_id,
                "transcribe",
                f"pending task_id={run_result.get('task_id') or existing_task_id} message={run_result.get('message')}",
            )
            return {
                "success": False,
                "recoverable": True,
                "message": run_result.get("message") or "ASR pending",
                "task_id": run_result.get("task_id") or existing_task_id,
            }

        if interview_id is not None and current_project_id is not None:
            now = _now()
            DbAccess.upsert_workflow_job(
                project_id=int(current_project_id),
                interview_id=interview_id,
                workflow_type=WORKFLOW_JOB_TYPE,
                status="failed",
                stage="failed",
                object_key=current_object_key,
                audio_url=audio_url,
                volc_task_id=str(run_result.get("task_id") or existing_task_id or ""),
                last_polled_at=now,
                next_poll_at=now,
                retry_count=retry_count,
                poll_count=max(poll_state["count"], 1),
                lease_owner=lease_owner,
                lease_expires_at=now + timedelta(seconds=WORKFLOW_LEASE_SECONDS),
                error_stage="transcribe",
                error_message=run_result.get("message"),
                checkpoint_json=_build_asr_checkpoint(
                    interview_id=interview_id,
                    project_id=current_project_id,
                    object_key=current_object_key,
                    audio_url=audio_url,
                    task_id=str(run_result.get("task_id") or existing_task_id or ""),
                    note="asr failed",
                    retry_count=retry_count,
                    poll_count=max(poll_state["count"], 1),
                ),
            )
        _workflow_log(
            interview_id,
            "transcribe",
            f"failed recoverable=False message={run_result.get('message')}",
        )
        return {
            "success": False,
            "recoverable": False,
            "message": run_result.get("message") or "transcribe failed",
            "task_id": run_result.get("task_id") or existing_task_id,
        }
    except Exception as e:
        _workflow_log(
            interview_id,
            "transcribe",
            f"failed error={e} traceback={traceback.format_exc()}",
        )
        if interview_id is not None and project_id is not None:
            try:
                DbAccess.upsert_workflow_job(
                    project_id=int(project_id),
                    interview_id=interview_id,
                    workflow_type=WORKFLOW_JOB_TYPE,
                    status="failed",
                    stage="failed",
                    object_key=object_key,
                    audio_url=audio_url,
                    error_stage="transcribe",
                    error_message=str(e),
                    error_traceback=traceback.format_exc(),
                    lease_owner=_workflow_owner(),
                    lease_expires_at=_now() + timedelta(seconds=WORKFLOW_LEASE_SECONDS),
                )
            except Exception:
                pass
        return {"success": False, "recoverable": False, "message": f"transcribe failed: {e}"}


def step_store_file_content(interview_id: int, object_key: str, audio_url: str, asr_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 ASR 结果组装为 file_content JSON 并写入 bh_project_interview.file_content。
    """
    try:
        _workflow_log(interview_id, "store_file_content", "start")
        row = DbAccess.get_interview_by_id(interview_id)
        if not row:
            _workflow_log(interview_id, "store_file_content", f"failed interview={interview_id} not found")
            return {"success": False, "message": f"interview {interview_id} not found"}
        project_id = row.get("parse_project_id")
        file_name = row.get("file_name") or f"{interview_id}.wav"

        speakers = asr_result.get("speakers", [])
        transcript = []
        for idx, seg in enumerate(speakers, start=1):
            if not isinstance(seg, dict):
                continue
            transcript.append(
                {
                    "uid": f"u{idx:04d}",
                    "speaker_id": str(seg.get("speaker_id", "")),
                    "start_time": seg.get("start_time"),
                    "end_time": seg.get("end_time"),
                    "text": seg.get("speaker_content", ""),
                }
            )

        payload = {
            "audio": {
                "project_id": project_id,
                "interview_id": interview_id,
                "object_key": object_key,
                "bucket_name": config.TOS_BUCKET_NAME,
                "url": audio_url,
                "format": file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "wav",
            },
            "result": {
                "full_text": asr_result.get("full_text", ""),
                "speakers": speakers,
                "transcript": transcript,
            },
        }
        DbAccess.update_interview_file_content(interview_id, json.dumps(payload, ensure_ascii=False))
    except Exception as e:
        _workflow_log(interview_id, "store_file_content", f"failed error={e} traceback={traceback.format_exc()}")
        return {"success": False, "message": f"write file_content failed: {e}"}
    _workflow_log(interview_id, "store_file_content", "done")
    return {"success": True, "file_content": payload}


def step_extract_interview_context(
    interview_id: int,
    project_context: str | None = None,
    term_hints: List[str] | None = None,
) -> Dict[str, Any]:
    """
    步骤 4：从已落库的 file_content 中读取整篇 ASR 全文，提炼访谈背景说明。
    """
    try:
        _workflow_log(interview_id, "extract_interview_context", "start")
        row = DbAccess.get_interview_by_id(interview_id)
        if not row:
            return {"success": False, "message": f"interview {interview_id} not found"}
        file_content_json = row.get("file_content") or ""
        if not file_content_json.strip():
            return {"success": False, "message": "file_content is empty"}
        obj = json.loads(file_content_json)
        full_text = (obj.get("result") or {}).get("full_text") or ""
        if not str(full_text).strip():
            return {"success": False, "message": "full_text is empty"}
        client = ModelClient()
        interview_context = client.extract_interview_context(
            full_text=str(full_text),
            project_context=project_context,
            term_hints=term_hints,
        )
        _workflow_log(
            interview_id,
            "extract_interview_context",
            f"done keys={sorted(interview_context.keys()) if isinstance(interview_context, dict) else type(interview_context).__name__}",
        )
    except Exception as e:
        _workflow_log(
            interview_id,
            "extract_interview_context",
            f"failed error={e} traceback={traceback.format_exc()}",
        )
        return {"success": False, "message": f"extract interview context failed: {e}"}
    return {"success": True, "interview_context": interview_context}


def step_clean_with_llm(
    file_content_json: str,
    project_context: str | None = None,
    interview_context: Dict[str, Any] | str | None = None,
    term_hints: List[str] | None = None,
    correction_rules: List[str] | None = None,
    interview_id: int | None = None,
) -> Dict[str, Any]:
    """
    步骤 5：先逐段纠错，再做热词兜底纠错，返回更新后的 JSON 字符串。

    参数:
        file_content_json: 上一步写入的 file_content JSON。
        project_context:   可选的项目背景块，会注入到清洗 prompt，帮助模型理解行业语境。
    """
    speaker_roles = {"1": "interviewer", "2": "interviewee"}
    effective_term_hints = merge_term_hints(term_hints or [])
    try:
        _workflow_log(interview_id, "clean_with_llm", "start")
        updated_json = clean_file_content_json(
            file_content_json=file_content_json,
            speaker_roles=speaker_roles,
            term_hints=effective_term_hints,
            correction_rules=correction_rules,
            project_context=project_context,
            interview_context=interview_context,
            interview_id=interview_id,
        )
        _workflow_log(
            interview_id,
            "clean_with_llm",
            f"done json_len={len(updated_json) if isinstance(updated_json, str) else 'n/a'}",
        )
    except Exception as e:
        _workflow_log(
            interview_id,
            "clean_with_llm",
            f"failed error={e} traceback={traceback.format_exc()}",
        )
        return {"success": False, "message": f"clean with llm failed: {e}"}
    return {"success": True, "cleaned_json": updated_json}


def step_write_summary(interview_id: int, cleaned_json: str) -> Dict[str, Any]:
    """
    步骤 4：将最终修正后的 speakers 写入 bh_project_interview_summary（逐句/逐段明细表）。
    目标字段:
        - project_interview_id: interview_id
        - timestamp: 由 ASR 原始分段计算得到的毫秒级时间区间
        - speaker: speaker_id（或映射后的角色）
        - text: speaker_content_clean；若清洗未启用，则回退到 speaker_content_corrected
        - modify: 0
    """
    try:
        _workflow_log(interview_id, "write_summary", "start")
        obj = json.loads(cleaned_json)
        speakers = obj.get("result", {}).get("speakers") or []
        if not speakers:
            return {"success": False, "message": "no speakers in cleaned json"}
        for seg in speakers:
            if not isinstance(seg, dict):
                continue
            final_text = str(seg.get("speaker_content_clean") or "").strip()
            if not final_text:
                final_text = str(seg.get("speaker_content_corrected") or "").strip()
            if not final_text:
                final_text = str(seg.get("text") or "").strip()
            if not final_text:
                final_text = str(seg.get("speaker_content") or "").strip()
            seg["speaker_content_clean"] = final_text
        inserted = DbAccess.insert_summary_from_cleaned_speakers(interview_id, speakers)
        _workflow_log(interview_id, "write_summary", f"done inserted={inserted}")
    except Exception as e:
        _workflow_log(
            interview_id,
            "write_summary",
            f"failed error={e} traceback={traceback.format_exc()}",
        )
        return {"success": False, "message": f"write summary failed: {e}"}

    return {"success": True, "inserted": inserted}


def _extract_key_bq_text(core_problem: Any) -> str:
    """
    将访谈 core_problem 字段中的 key BQ JSON 归一化为可直接注入 prompt 的文本。

    参数:
        core_problem: bh_project_interview.core_problem 的原始值，通常是 JSON 字符串。

    返回:
        按顺序拼接后的 key BQ 文本。
    """
    if core_problem is None:
        return ""
    obj: Any = core_problem
    if isinstance(core_problem, str):
        try:
            obj = json.loads(core_problem)
        except Exception:
            return core_problem.strip()
    if not isinstance(obj, dict):
        return str(core_problem).strip()
    items = obj.get("key_bq_list") or []
    if not isinstance(items, list):
        return ""
    lines: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def _extract_transcript_text(cleaned_json: str) -> str:
    """
    将清洗后的 transcript 组织成可用于整体 summary 的纯文本。

    参数:
        cleaned_json: step_clean_with_llm 返回的 JSON 字符串。

    返回:
        按说话人顺序拼接的访谈文本。
    """
    try:
        obj = json.loads(cleaned_json)
    except Exception:
        return ""
    speakers = obj.get("result", {}).get("speakers") or []
    lines: List[str] = []
    for seg in speakers:
        if not isinstance(seg, dict):
            continue
        speaker_id = str(seg.get("speaker_id") or "").strip() or "unknown"
        text = (
            str(seg.get("speaker_content_clean") or "").strip()
            or str(seg.get("speaker_content_corrected") or "").strip()
            or str(seg.get("text") or "").strip()
            or str(seg.get("speaker_content") or "").strip()
        )
        if not text:
            continue
        lines.append(f"{speaker_id}: {text}")
    return "\n".join(lines)


def step_generate_overall_note(
    interview_id: int,
    cleaned_json: str,
    project_context: str | None = None,
    interview_context: Dict[str, Any] | str | None = None,
    core_problem: Any = None,
) -> Dict[str, Any]:
    """
    生成访谈级整体 summary notes，并写入 `bh_project_interview.note_content`。

    参数:
        interview_id: 访谈 ID。
        cleaned_json: 已完成纠错/清洗的 transcript JSON。
        project_context: 可选项目背景。
        interview_context: 可选访谈背景。
        core_problem: 访谈 key BQ 原始值或 JSON 字符串。

    返回:
        包含 success、note_content、warning 的 step 结果。
    """
    transcript_text = _extract_transcript_text(cleaned_json)
    if not transcript_text.strip():
        return {"success": False, "message": "transcript text is empty"}

    key_bq_text = _extract_key_bq_text(core_problem)
    client = ModelClient()
    try:
        _workflow_log(interview_id, "generate_overall_note", "start")
        note_content = client.generate_overall_interview_note(
            key_bq_text=key_bq_text,
            transcript_text=transcript_text,
            project_context=project_context,
            interview_context=interview_context,
        )
        _workflow_log(
            interview_id,
            "generate_overall_note",
            f"done note_len={len(note_content) if isinstance(note_content, str) else 'n/a'}",
        )
    except Exception as e:
        _workflow_log(
            interview_id,
            "generate_overall_note",
            f"failed error={e} traceback={traceback.format_exc()}",
        )
        return {"success": False, "message": f"generate overall note failed: {e}"}

    note_content = (note_content or "").strip()
    if not note_content:
        return {"success": False, "message": "overall note is empty"}

    try:
        DbAccess.update_interview_note_content(interview_id, note_content)
    except Exception as e:
        return {"success": False, "message": f"write overall note failed: {e}"}

    return {"success": True, "note_content": note_content}
def run_workflow(interview_id: int) -> Dict[str, Any]:
    """
    只负责“转录 -> 背景提炼 -> 纠错兜底 -> 写 summary -> 生成整体 Notes -> 自动生成问题 Notes”的工作流。

    旧版工作流中的 Notes 生成已拆分出去，后续由独立接口按题目触发。
    当前工作流会先读取访谈所属项目的背景描述，并将其注入到纠错阶段，
    以便后续 summary 的文本更贴合项目语境。
    """
    project_id: int | None = None

    def fail(stage: str, detail: Dict[str, Any] | str) -> Dict[str, Any]:
        """
        统一封装工作流失败返回，并尝试把访谈状态写回失败态。

        参数:
            stage: 当前失败发生的阶段标识，用于前端和日志定位，例如 load_interview、transcribe。
            detail: 失败细节，可以是错误说明字符串，也可以是包含更多上下文的字典。

        返回:
            标准化的失败响应字典，包含 success=False、stage 和 detail。
        """
        recoverable = isinstance(detail, dict) and bool(detail.get("recoverable"))
        try:
            if not recoverable:
                DbAccess.update_interview_status(interview_id, 3)
        except Exception:
            pass
        try:
            if project_id is not None:
                now = _now()
                DbAccess.upsert_workflow_job(
                    project_id=int(project_id),
                    interview_id=interview_id,
                    workflow_type=WORKFLOW_JOB_TYPE,
                    status="waiting_asr" if recoverable else "failed",
                    stage="asr_polling" if recoverable and stage == "transcribe" else "failed",
                    error_stage=stage,
                    error_message=(detail.get("message") if isinstance(detail, dict) else str(detail)),
                    error_traceback=(detail.get("traceback") if isinstance(detail, dict) else None),
                    lease_owner=_workflow_owner(),
                    lease_expires_at=now + timedelta(seconds=WORKFLOW_LEASE_SECONDS),
                )
        except Exception:
            pass
        _workflow_log(interview_id, stage, f"failed detail={detail}")
        return {"success": False, "stage": stage, "detail": detail, "recoverable": recoverable}

    try:
        _workflow_log(interview_id, "run_workflow", "start")
        try:
            DbAccess.update_interview_status(interview_id, 1)
        except Exception:
            # 状态更新失败不影响主流程。
            pass

        interview_row = DbAccess.get_interview_by_id(interview_id)
        if not interview_row:
            return fail("load_interview", {"message": f"interview {interview_id} not found"})
        _workflow_log(interview_id, "load_interview", "done")
        project_id = interview_row.get("parse_project_id")
        if project_id is None:
            return fail("load_project", {"message": "project id missing from interview"})
        _workflow_log(interview_id, "load_project", f"done project_id={project_id}")
        project_context = load_project_context_by_id(int(project_id))
        _workflow_log(
            interview_id,
            "load_project_context",
            f"done length={len(project_context) if isinstance(project_context, str) else 'n/a'}",
        )
        try:
            DbAccess.upsert_workflow_job(
                project_id=int(project_id),
                interview_id=interview_id,
                workflow_type=WORKFLOW_JOB_TYPE,
                status="running",
                stage="created",
                started_at=_now(),
                lease_owner=_workflow_owner(),
                lease_expires_at=_now() + timedelta(seconds=WORKFLOW_LEASE_SECONDS),
                checkpoint_json={
                    "interview_id": interview_id,
                    "project_id": int(project_id),
                    "project_context_loaded": True,
                },
            )
        except Exception as e:
            _workflow_log(interview_id, "job_init", f"warning failed to init job record error={e}")
        interview_term_hints = load_term_hints_from_state(interview_id=interview_id)
        correction_rules = load_correction_rules_from_state(interview_id=interview_id)
        core_problem = interview_row.get("core_problem")

        questionnaire_term_hints: List[str] = []
        questionnaire_id = interview_row.get("questionnaire_id")
        if questionnaire_id is not None:
            questionnaire_row = DbAccess.get_questionnaire_by_id(int(questionnaire_id))
            if questionnaire_row:
                raw_hotwords = questionnaire_row.get("hotwords")
                parsed_hotwords: List[str] = []
                if isinstance(raw_hotwords, list):
                    parsed_hotwords = [str(item).strip() for item in raw_hotwords if str(item).strip()]
                elif isinstance(raw_hotwords, str):
                    try:
                        loaded_hotwords = json.loads(raw_hotwords)
                    except Exception:
                        loaded_hotwords = None
                    if isinstance(loaded_hotwords, list):
                        parsed_hotwords = [str(item).strip() for item in loaded_hotwords if str(item).strip()]
                    elif isinstance(loaded_hotwords, dict) and isinstance(loaded_hotwords.get("hotwords"), list):
                        parsed_hotwords = [
                            str(item).strip()
                            for item in loaded_hotwords.get("hotwords") or []
                            if str(item).strip()
                        ]
                questionnaire_term_hints = parsed_hotwords

        if not questionnaire_term_hints:
            questionnaire_term_hints = load_reviewed_questionnaire_hotwords(
                int(project_id),
                interview_id,
            )
        term_hints = merge_term_hints(interview_term_hints, questionnaire_term_hints)
        _workflow_log(
            interview_id,
            "load_hotwords",
            f"done term_hints={len(term_hints)} correction_rules={len(correction_rules)}",
        )

        # 1. 本地上云 / 预签名 URL
        up = step_upload_interview_audio(interview_id)
        if not up.get("success"):
            return fail("upload", up)
        object_key = up["object_key"]
        audio_url = up["audio_url"]
        _workflow_log(interview_id, "upload", f"done object_key={object_key}")

        # 2. ASR
        tr = step_transcribe(audio_url, interview_id=interview_id, project_id=int(project_id), object_key=object_key)
        if not tr.get("success"):
            return fail("transcribe", tr)
        asr_result = tr["asr_result"]
        _workflow_log(
            interview_id,
            "transcribe",
            f"done full_text_len={len(asr_result.get('full_text', '')) if isinstance(asr_result, dict) else 'n/a'} speakers_count={len(asr_result.get('speakers', [])) if isinstance(asr_result, dict) else 'n/a'}",
        )

        # 3. 写 file_content
        st = step_store_file_content(interview_id, object_key, audio_url, asr_result)
        if not st.get("success"):
            return fail("store_file_content", st)
        file_content_obj = st["file_content"]
        file_content_json = json.dumps(file_content_obj, ensure_ascii=False)
        _workflow_log(interview_id, "store_file_content", "done")

        # 4. 提炼访谈背景
        ec = step_extract_interview_context(
            interview_id,
            project_context=project_context,
            term_hints=term_hints,
        )
        if not ec.get("success"):
            return fail("extract_interview_context", ec)
        interview_context = ec["interview_context"]
        _workflow_log(interview_id, "extract_interview_context", "done")

        try:
            current_job = DbAccess.get_workflow_job_by_interview(interview_id, WORKFLOW_JOB_TYPE)
            retry_count = int(current_job.get("retry_count") or 0) if current_job else 0
            poll_count = int(current_job.get("poll_count") or 0) if current_job else 0
            current_task_id = str(current_job.get("volc_task_id") or "") if current_job else ""
            DbAccess.upsert_workflow_job(
                project_id=int(project_id),
                interview_id=interview_id,
                workflow_type=WORKFLOW_JOB_TYPE,
                status="running",
                stage="cleaning",
                object_key=object_key,
                audio_url=audio_url,
                volc_task_id=current_task_id,
                retry_count=retry_count,
                poll_count=poll_count,
                lease_owner=_workflow_owner(),
                lease_expires_at=_now() + timedelta(seconds=WORKFLOW_LEASE_SECONDS),
                checkpoint_json={
                    "interview_id": interview_id,
                    "project_id": int(project_id),
                    "stage": "cleaning",
                    "object_key": object_key,
                    "audio_url": audio_url,
                    "note": "cleaning started",
                },
            )
        except Exception as e:
            _workflow_log(interview_id, "clean_with_llm", f"warning failed to persist cleaning stage error={e}")

        # 5. LLM 纠错 + 再纠错 + 清洗
        cl = step_clean_with_llm(
            file_content_json,
            project_context=project_context,
            interview_context=interview_context,
            term_hints=term_hints,
            correction_rules=correction_rules,
            interview_id=interview_id,
        )
        if not cl.get("success"):
            return fail("correct_fallback", cl)
        cleaned_json = cl["cleaned_json"]
        try:
            current_job = DbAccess.get_workflow_job_by_interview(interview_id, WORKFLOW_JOB_TYPE)
            retry_count = int(current_job.get("retry_count") or 0) if current_job else 0
            poll_count = int(current_job.get("poll_count") or 0) if current_job else 0
            current_task_id = str(current_job.get("volc_task_id") or "") if current_job else ""
            DbAccess.upsert_workflow_job(
                project_id=int(project_id),
                interview_id=interview_id,
                workflow_type=WORKFLOW_JOB_TYPE,
                status="running",
                stage="cleaning",
                object_key=object_key,
                audio_url=audio_url,
                volc_task_id=current_task_id,
                retry_count=retry_count,
                poll_count=poll_count,
                cleaned_json=cleaned_json,
                lease_owner=_workflow_owner(),
                lease_expires_at=_now() + timedelta(seconds=WORKFLOW_LEASE_SECONDS),
                checkpoint_json={
                    "interview_id": interview_id,
                    "project_id": int(project_id),
                    "stage": "cleaning",
                    "object_key": object_key,
                    "audio_url": audio_url,
                    "note": "cleaning done",
                    "cleaned_json_len": len(cleaned_json) if isinstance(cleaned_json, str) else None,
                },
            )
        except Exception as e:
            _workflow_log(interview_id, "clean_with_llm", f"warning failed to persist cleaned json error={e}")
        _workflow_log(interview_id, "correct_fallback", "done")

        # 6. 写 summary
        ws = step_write_summary(interview_id, cleaned_json)
        if not ws.get("success"):
            return fail("write_summary", ws)
        _workflow_log(interview_id, "write_summary", f"done inserted={ws.get('inserted', 0)}")

        overall_note_result = step_generate_overall_note(
            interview_id=interview_id,
            cleaned_json=cleaned_json,
            project_context=project_context,
            interview_context=interview_context,
            core_problem=core_problem,
        )
        overall_note_warning = None
        if not overall_note_result.get("success"):
            overall_note_warning = overall_note_result.get("message") or "generate overall note failed"
            _workflow_log(interview_id, "generate_overall_note", f"warning detail={overall_note_result}")
        else:
            _workflow_log(interview_id, "generate_overall_note", "done")

        minutes_result = generate_minutes_for_interview(
            interview_id,
            project_context=project_context,
            top_k=8,
        )
        minutes_warning = None
        if not minutes_result.get("success"):
            minutes_warning = minutes_result.get("message") or "generate minutes failed"
            _workflow_log(interview_id, "generate_minutes", f"warning detail={minutes_result}")
        else:
            _workflow_log(
                interview_id,
                "generate_minutes",
                f"done minutes_chars={minutes_result.get('minutes_chars', 0)} inserted={minutes_result.get('inserted', 0)}",
            )
        cards_warning = None
        if minutes_result.get("cards_success") is False:
            cards_warning = minutes_result.get("cards_message") or "generate cards failed"
            _workflow_log(interview_id, "generate_cards", f"warning detail={minutes_result}")

        kbq_result = {"success": False, "message": "kbq skipped because smart minutes generation failed", "inserted": 0}
        if minutes_result.get("success"):
            kbq_result = run_kbq_notes_generation_for_interview(
                interview_id,
                project_context=project_context,
                interview_context=interview_context,
            )
        kbq_warning = None
        if not kbq_result.get("success"):
            kbq_warning = kbq_result.get("message") or "generate kbq notes failed"

        try:
            DbAccess.upsert_workflow_job(
                project_id=int(project_id),
                interview_id=interview_id,
                workflow_type=WORKFLOW_JOB_TYPE,
                status="done",
                stage="done",
                finished_at=_now(),
                lease_owner=_workflow_owner(),
                lease_expires_at=_now() + timedelta(seconds=WORKFLOW_LEASE_SECONDS),
            )
            DbAccess.update_interview_status(interview_id, 2)
        except Exception:
            pass
        _workflow_log(interview_id, "run_workflow", "done")

        return {
            "success": True,
            "object_key": object_key,
            "audio_url": audio_url,
            "asr_result_preview": {
                "full_text_len": len(asr_result.get("full_text", "")),
                "speakers_count": len(asr_result.get("speakers", [])),
            },
            "summary_inserted": ws.get("inserted", 0),
            "overall_note_written": bool(overall_note_result.get("success")),
            "kbq_notes_inserted": kbq_result.get("inserted", 0),
            "minutes_inserted": minutes_result.get("inserted", 0),
            "notes_inserted": minutes_result.get("inserted", 0),
            "warnings": [
                warning
                for warning in [overall_note_warning, kbq_warning, minutes_warning, cards_warning]
                if warning
            ],
        }
    except Exception as e:
        _workflow_log(
            interview_id,
            "run_workflow",
            f"unexpected error={e} traceback={traceback.format_exc()}",
        )
        return fail("unexpected", {
            "message": str(e),
            "traceback": traceback.format_exc(),
        })
if __name__ == "__main__":
    """
    命令行用法（示例）：
        1. 在 .env 中设置 TEST_INTERVIEW_ID
        2. 运行本文件
    """
    iid = config.TEST_INTERVIEW_ID
    if not iid:
        print("请在 .env 中配置 TEST_INTERVIEW_ID")
        raise SystemExit(1)
    try:
        iid_int = int(iid)
    except ValueError:
        print(f"TEST_INTERVIEW_ID 非法: {iid}")
        raise SystemExit(1)

    result = run_workflow(iid_int)
    print(json.dumps(result, ensure_ascii=False, indent=2))
