import json
import os
import shutil
from typing import Any, Dict, List, Optional
from pathlib import Path

import requests

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile

from api.auth import require_current_user_id
from DocxToMd import convert_docx_questionnaire
from Hotword import save_hotword_state
from QuestionnaireHotword import (
    extract_questionnaire_hotword_candidates,
    has_reviewed_questionnaire_hotwords,
    load_questionnaire_hotword_candidates,
    load_reviewed_questionnaire_hotwords,
    save_questionnaire_hotword_candidates,
    save_reviewed_questionnaire_hotwords,
)
from QuestionTree import build_question_insert_rows
from db import (
    delete_interview_graph,
    fetch_project_by_id,
    fetch_interviews_by_project,
    insert_interview,
    insert_key_bq_rows_for_interview,
    insert_questions_for_interview,
    update_interview_status,
)
from schemas.interviews import (
    QuestionnaireHotwordLoadResponse,
    QuestionnaireHotwordReviewRequest,
    QuestionnaireHotwordReviewResponse,
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


def _get_data_root() -> Path:
    """
    获取本地问卷/备份数据根目录。

    固定使用 SummaryNotes 工程根目录下的 data 目录：
        <project_root>/data
    """
    api_dir = Path(__file__).resolve().parent
    project_root = api_dir.parent.parent
    return project_root / "data"


def _get_owned_project_or_404(project_id: int, current_user_id: int) -> Dict[str, Any]:
    """
    查询当前用户可访问的项目；若项目不属于当前用户则统一返回 404。

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


def _get_interview_backup_dir(project_id: int, interview_id: int) -> Path:
    """
    获取指定访谈在 data 目录下的备份目录。

    目录结构：
        data/project_{project_id}/interview_{interview_id}
    """
    return _get_data_root() / f"project_{project_id}" / f"interview_{interview_id}"


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


def _save_backup_audio_file(
    project_id: int,
    interview_id: int,
    source_audio_path: Path,
    file_name: str,
) -> str:
    """
    将音频文件复制到 data 目录下的访谈备份目录。

    参数:
        project_id:       项目 ID。
        interview_id:     访谈 ID。
        source_audio_path: 当前 audio 目录下的源音频文件绝对路径。
        file_name:        原始音频文件名。

    返回:
        备份后的相对路径，便于调试和日志输出。
    """
    backup_dir = _get_interview_backup_dir(project_id, interview_id)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / file_name
    try:
        shutil.copy2(source_audio_path, backup_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"backup audio file failed: {e}")
    return f"project_{project_id}/interview_{interview_id}/{file_name}"


def _save_uploaded_questionnaire_file(
    project_id: int,
    interview_id: int,
    upload_file: UploadFile,
) -> Path:
    """
    将上传的问卷文件保存到 data 目录下的访谈备份目录。

    参数:
        project_id:    项目 ID。
        interview_id:  访谈 ID。
        upload_file:   访谈问卷文件，要求为 docx。

    返回:
        保存后的绝对路径。
    """
    original_name = upload_file.filename or ""
    if not original_name:
        raise HTTPException(status_code=400, detail="上传问卷缺少文件名")
    if not original_name.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="仅支持 docx 格式的问卷")

    backup_dir = _get_interview_backup_dir(project_id, interview_id)
    backup_dir.mkdir(parents=True, exist_ok=True)
    target_path = backup_dir / original_name

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


def _read_text_file(path: Path) -> str:
    """
    读取文本文件内容；不存在时返回空字符串。

    参数:
        path: 待读取的文本文件路径。

    返回:
        文件内容字符串。
    """
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _normalize_core_problem_json(raw_value: str) -> str:
    """
    将前端提交的 key BQ 内容统一归一化为 JSON 字符串。

    规则:
        - 优先接受已经是 JSON 的内容
        - 如果是多行纯文本，则按行拆分为 key_bq_list
        - 每条问题保留 order 和 text

    参数:
        raw_value: 前端提交的原始 key BQ 文本。

    返回:
        规范化后的 JSON 字符串。
    """
    text = (raw_value or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="key BQ 不能为空")

    payload: Dict[str, Any] | None = None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and isinstance(parsed.get("key_bq_list"), list):
            items = []
            for idx, item in enumerate(parsed.get("key_bq_list") or [], start=1):
                if isinstance(item, dict):
                    item_text = str(item.get("text") or "").strip()
                else:
                    item_text = str(item).strip()
                if not item_text:
                    continue
                items.append({"order": idx, "text": item_text})
            if not items:
                raise ValueError("key BQ 列表不能为空")
            payload = {"key_bq_list": items}
    except Exception:
        payload = None

    if payload is None:
        items = []
        for idx, line in enumerate(text.splitlines(), start=1):
            line_text = line.strip()
            if not line_text:
                continue
            items.append({"order": idx, "text": line_text})
        if not items:
            raise HTTPException(status_code=400, detail="key BQ 不能为空")
        payload = {"key_bq_list": items}

    return json.dumps(payload, ensure_ascii=False)


def _extract_key_bq_items(core_problem_json: str) -> list[Dict[str, Any]]:
    """
    从归一化后的 core_problem JSON 中提取 key BQ 列表。

    参数:
        core_problem_json: `_normalize_core_problem_json` 的输出结果。

    返回:
        可直接写入 `bh_project_interview_key_bq` 的明细列表。
    """
    try:
        obj = json.loads(core_problem_json)
    except Exception:
        return []
    items = obj.get("key_bq_list") or []
    result: list[Dict[str, Any]] = []
    for idx, item in enumerate(items, start=1):
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            order = item.get("order") or idx
        else:
            text = str(item or "").strip()
            order = idx
        if not text:
            continue
        result.append({"order": int(order), "text": text, "status": "pending"})
    return result


def _delete_interview_backup_dir(project_id: int, interview_id: int) -> None:
    """
    删除 data 目录下该访谈对应的备份目录。

    删除失败时只记录为异常，由调用方决定是否中断。
    """
    backup_dir = _get_interview_backup_dir(project_id, interview_id)
    if backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)


def _delete_local_audio_dir(project_id: int, interview_id: int) -> None:
    """
    删除本地 audio 目录下该访谈对应的文件夹。
    """
    audio_root = _get_audio_root()
    target_dir = audio_root / f"project_{project_id}" / f"interview_{interview_id}"
    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)


def _cleanup_failed_interview(project_id: int, interview_id: int) -> None:
    """
    清理创建访谈过程中失败的半成品数据。

    会删除：
        - bh_project_interview 及其关联数据
        - 本地 audio 目录下的音频备份
        - data 目录下的访谈备份目录
    """
    try:
        delete_interview_graph(interview_id)
    except Exception:
        pass
    try:
        _delete_local_audio_dir(project_id, interview_id)
    except Exception:
        pass
    try:
        _delete_interview_backup_dir(project_id, interview_id)
    except Exception:
        pass


@router.post("/{project_id}/interviews", response_model=Dict[str, Any])
async def create_interview(
    project_id: int,
    background_tasks: BackgroundTasks,
    current_user_id: int = Depends(require_current_user_id),
    name: str = Form(...),
    core_problem: str = Form(...),
    interview_date: Optional[str] = Form(None),
    hospital_city: str = Form(...),
    hospital_decile: int = Form(...),
    doctor_level: str = Form(...),
    hotword_keys: Optional[str] = Form(None),
    file: UploadFile = File(...),
    questionnaire_file: Optional[UploadFile] = File(None),
) -> Dict[str, Any]:
    """
    为指定项目创建访谈，并保存本地音频文件。

    参数:
        project_id:     项目 ID，对应 bh_project.id，写入 bh_project_interview.parse_project_id。
        name:           访谈名称，对应 bh_project_interview.name。
        core_problem:    访谈 key BQ，写入 bh_project_interview.core_problem（JSON 字符串）。
        interview_date: 访谈时间字符串（如 '2026-04-15'），写入 bh_project_interview.interview_date。
        hospital_city:   医院所在城市，写入 bh_project_interview.hospital_city。
        hospital_decile: 医院 Decile，写入 bh_project_interview.hospital_decile。
        doctor_level:    医生级别，写入 bh_project_interview.doctor_level。
        file:           单个音频文件，文件名写入 bh_project_interview.file_name。
        questionnaire_file:  可选 Word 问卷文件，仅支持 .docx。

    返回:
        {
            "id": interview_id,
            "project_id": project_id,
            "name": name,
            "interview_date": interview_date,
            "file_name": 原始文件名,
            "local_path": "project_{project_id}/interview_{interview_id}/{文件名}",
            "questionnaire_file_name": 问卷原始文件名（如果上传了）,
            "questionnaire_backup_path": data 下备份相对路径（如果上传了）,
            "questionnaire_md_path": md 相对路径（如果上传了）,
            "questionnaire_json_path": json 相对路径（如果上传了）
        }

    说明:
        上传完成后会异步触发转录工作流；该接口只负责创建记录和保存音频。
    """
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="访谈名称不能为空")
    normalized_core_problem = _normalize_core_problem_json(core_problem)
    key_bq_items = _extract_key_bq_items(normalized_core_problem)
    if not key_bq_items:
        raise HTTPException(status_code=400, detail="key BQ 不能为空")

    project_row = _get_owned_project_or_404(project_id, current_user_id)

    original_name = file.filename or ""
    if not original_name:
        raise HTTPException(status_code=400, detail="上传文件缺少文件名")

    interview_id: int | None = None
    try:
        interview_id = insert_interview(
            parse_project_id=project_id,
            name=clean_name,
            interview_date=interview_date,
            file_name=original_name,
            hospital_city=hospital_city.strip(),
            hospital_decile=hospital_decile,
            doctor_level=doctor_level.strip(),
            core_problem=normalized_core_problem,
        )
        inserted_key_bq = insert_key_bq_rows_for_interview(project_id, interview_id, key_bq_items)
        if inserted_key_bq <= 0:
            raise RuntimeError("no key BQ rows inserted")
        keys = [item.strip() for item in (hotword_keys or "").split(",") if item.strip()]
        if keys:
            save_hotword_state("interview", interview_id, keys)
    except Exception as e:
        if interview_id is not None:
            try:
                delete_interview_graph(interview_id)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"insert interview failed: {e}")

    local_path = _save_uploaded_audio_file(project_id, interview_id, file)
    backup_audio_path = _save_backup_audio_file(project_id, interview_id, _get_audio_root() / f"project_{project_id}" / f"interview_{interview_id}" / original_name, original_name)

    questionnaire_name: str | None = None
    questionnaire_backup_path: str | None = None
    questionnaire_md_path: str | None = None
    questionnaire_json_path: str | None = None
    if questionnaire_file is not None and questionnaire_file.filename:
        questionnaire_name = questionnaire_file.filename
        try:
            saved_questionnaire_path = _save_uploaded_questionnaire_file(project_id, interview_id, questionnaire_file)
            convert_result = convert_docx_questionnaire(
                saved_questionnaire_path,
                _get_interview_backup_dir(project_id, interview_id),
            )
            questionnaire_backup_path = str(saved_questionnaire_path.relative_to(_get_data_root()))
            questionnaire_md_path = str(convert_result["markdown_path"].relative_to(_get_data_root()))
            questionnaire_json_path = str(convert_result["json_path"].relative_to(_get_data_root()))
            questionnaire_document = convert_result.get("document") or {}
            question_rows = build_question_insert_rows(questionnaire_document)
            if not question_rows:
                raise ValueError("no questions extracted from questionnaire")
            try:
                insert_questions_for_interview(interview_id, question_rows)
            except Exception as exc:
                raise RuntimeError(f"insert questions failed: {exc}") from exc
        except Exception as e:
            if interview_id is not None:
                _cleanup_failed_interview(project_id, interview_id)
            raise HTTPException(status_code=500, detail=f"questionnaire processing failed: {e}")

    workflow_started = False
    questionnaire_hotword_candidates: list[Dict[str, Any]] = []
    questionnaire_hotword_candidates_path: str | None = None
    questionnaire_hotword_review_required = False

    if questionnaire_file is not None and questionnaire_file.filename:
        questionnaire_hotword_review_required = True
        try:
            questionnaire_md_text = ""
            if questionnaire_md_path:
                questionnaire_md_text = _read_text_file(_get_data_root() / questionnaire_md_path)
            questionnaire_hotword_result = extract_questionnaire_hotword_candidates(
                markdown_text=questionnaire_md_text,
                project_context=str(project_row.get("core_problem") or ""),
            )
            questionnaire_hotword_candidates = questionnaire_hotword_result.get("hotword_candidates") or []
            questionnaire_hotword_candidates_path = str(
                save_questionnaire_hotword_candidates(
                    project_id=project_id,
                    interview_id=interview_id,
                    payload=questionnaire_hotword_result,
                ).relative_to(_get_data_root())
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"questionnaire hotword extraction failed: {e}")
    else:
        background_tasks.add_task(_trigger_workflow_background, interview_id)
        workflow_started = True

    return {
        "id": interview_id,
        "project_id": project_id,
        "name": clean_name,
        "core_problem": normalized_core_problem,
        "interview_date": interview_date,
        "hospital_city": hospital_city.strip(),
        "hospital_decile": hospital_decile,
        "doctor_level": doctor_level.strip(),
        "file_name": original_name,
        "local_path": local_path,
        "audio_backup_path": backup_audio_path,
        "questionnaire_file_name": questionnaire_name,
        "questionnaire_backup_path": questionnaire_backup_path,
        "questionnaire_md_path": questionnaire_md_path,
        "questionnaire_json_path": questionnaire_json_path,
        "questionnaire_hotword_review_required": questionnaire_hotword_review_required,
        "questionnaire_hotword_candidates": questionnaire_hotword_candidates,
        "questionnaire_hotword_candidates_path": questionnaire_hotword_candidates_path,
        "workflow_started": workflow_started,
    }


@router.get(
    "/{project_id}/interviews/{interview_id}/questionnaire-hotwords",
    response_model=QuestionnaireHotwordLoadResponse,
)
def get_questionnaire_hotwords(
    project_id: int,
    interview_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> QuestionnaireHotwordLoadResponse:
    """
    读取指定访谈的问卷热词候选或已审核热词。

    参数:
        project_id: 项目 ID。
        interview_id: 访谈 ID。
        current_user_id: 当前登录用户 ID。

    返回:
        问卷热词候选列表以及是否仍然需要 review。
    """
    _get_owned_project_or_404(project_id, current_user_id)
    interview = fetch_interviews_by_project(project_id, current_user_id)
    if not any(int(row["id"]) == interview_id for row in interview):
        raise HTTPException(status_code=404, detail="interview not found")

    reviewed_exists = has_reviewed_questionnaire_hotwords(project_id, interview_id)
    reviewed_hotwords = load_reviewed_questionnaire_hotwords(project_id, interview_id)
    candidates_payload = load_questionnaire_hotword_candidates(project_id, interview_id)
    candidates_raw = candidates_payload.get("hotword_candidates") or []
    candidates: List[Dict[str, Any]] = []
    for item in candidates_raw:
        if not isinstance(item, dict):
            continue
        candidates.append(
            {
                "term": str(item.get("term") or "").strip(),
                "normalized_term": str(item.get("normalized_term") or "").strip(),
                "reason": str(item.get("reason") or "").strip() or None,
                "confidence": item.get("confidence"),
            }
        )
    return QuestionnaireHotwordLoadResponse(
        interview_id=interview_id,
        project_id=project_id,
        review_required=not reviewed_exists,
        candidates=candidates,
        reviewed_hotwords=reviewed_hotwords,
    )


@router.post(
    "/{project_id}/interviews/{interview_id}/questionnaire-hotwords",
    response_model=QuestionnaireHotwordReviewResponse,
)
def save_questionnaire_hotwords_review(
    project_id: int,
    interview_id: int,
    payload: QuestionnaireHotwordReviewRequest,
    background_tasks: BackgroundTasks,
    current_user_id: int = Depends(require_current_user_id),
) -> QuestionnaireHotwordReviewResponse:
    """
    保存人工 review 后的问卷热词，并触发访谈工作流。

    参数:
        project_id: 项目 ID。
        interview_id: 访谈 ID。
        payload: review 后的热词列表。
        background_tasks: FastAPI 后台任务队列。
        current_user_id: 当前登录用户 ID。

    返回:
        保存结果与工作流触发状态。
    """
    _get_owned_project_or_404(project_id, current_user_id)
    interview_rows = fetch_interviews_by_project(project_id, current_user_id)
    if not any(int(row["id"]) == interview_id for row in interview_rows):
        raise HTTPException(status_code=404, detail="interview not found")

    hotwords = [str(item).strip() for item in (payload.hotwords or []) if str(item).strip()]
    reviewed_path = save_reviewed_questionnaire_hotwords(project_id, interview_id, hotwords)
    reviewed_json_path = reviewed_path.with_suffix(".json")

    background_tasks.add_task(_trigger_workflow_background, interview_id)

    return QuestionnaireHotwordReviewResponse(
        success=True,
        interview_id=interview_id,
        project_id=project_id,
        reviewed_count=len(hotwords),
        reviewed_path=str(reviewed_path.relative_to(_get_data_root())),
        reviewed_json_path=str(reviewed_json_path.relative_to(_get_data_root())),
        workflow_started=True,
        message=None,
    )


@router.get("/{project_id}/interviews", response_model=list[Dict[str, Any]])
def list_project_interviews(
    project_id: int,
    current_user_id: int = Depends(require_current_user_id),
) -> list[Dict[str, Any]]:
    """
    查询指定项目下的所有访谈记录。

    参数:
        project_id: 项目 ID，对应 bh_project.id，映射为 bh_project_interview.parse_project_id。

    返回:
        访谈记录字典列表，每项至少包含 id、name、interview_date、file_name。
    """
    _get_owned_project_or_404(project_id, current_user_id)
    rows = fetch_interviews_by_project(
        parse_project_id=project_id,
        created_by_user_id=current_user_id,
    )
    return rows
