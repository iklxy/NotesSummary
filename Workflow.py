"@Date:2026-04-10"
"@Author:lixinyang"

import json
import traceback
from typing import Any, Dict, List

from VolcUpload import upload_local_file, build_object_key, build_local_file_path, get_tos_client, tos
from VolcengineConversion import run_asr
from CleanConversion import clean_file_content_json
from Model import ModelClient
from Hotword import load_correction_rules_from_state, load_term_hints_from_state, merge_term_hints
from DbAccess import DbAccess
from ProjectContext import load_project_context_by_id
from config import config


def step_upload_interview_audio(interview_id: int) -> Dict[str, Any]:
    """
    步骤 1：本地上云，返回 {object_key, audio_url}。
    如果 bh_project_interview 已存在 file_path，则直接用它作为 object_key 并生成预签名 URL。
    """
    try:
        row = DbAccess.get_interview_by_id(interview_id)
        if not row:
            return {"success": False, "message": f"interview {interview_id} not found"}

        project_id = row.get("parse_project_id")
        file_name = row.get("file_name") or f"{interview_id}.wav"
        object_key = row.get("file_path")

        if not object_key:
            local_path = build_local_file_path(project_id, interview_id, file_name)
            object_key = build_object_key(project_id, interview_id, file_name)
            upload_result = upload_local_file(local_path, object_key)
            if not upload_result.get("success"):
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
            except Exception as e:
                return {"success": False, "message": f"update after upload failed: {e}"}
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
            return {"success": True, "object_key": object_key, "audio_url": audio_url}
    except Exception as e:
        return {"success": False, "message": f"upload step unexpected error: {e}"}


def step_transcribe(audio_url: str) -> Dict[str, Any]:
    """
    步骤 2：调用 ASR，将云上音频转写为 {full_text, speakers[]} 结构。
    """
    try:
        asr_result = run_asr(audio_url) or {}
    except Exception as e:
        return {"success": False, "message": f"transcribe failed: {e}"}
    return {"success": True, "asr_result": asr_result}


def step_store_file_content(interview_id: int, object_key: str, audio_url: str, asr_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 ASR 结果组装为 file_content JSON 并写入 bh_project_interview.file_content。
    """
    try:
        row = DbAccess.get_interview_by_id(interview_id)
        if not row:
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
        return {"success": False, "message": f"write file_content failed: {e}"}
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
    except Exception as e:
        return {"success": False, "message": f"extract interview context failed: {e}"}
    return {"success": True, "interview_context": interview_context}


def step_clean_with_llm(
    file_content_json: str,
    project_context: str | None = None,
    interview_context: Dict[str, Any] | str | None = None,
    term_hints: List[str] | None = None,
    correction_rules: List[str] | None = None,
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
        updated_json = clean_file_content_json(
            file_content_json=file_content_json,
            speaker_roles=speaker_roles,
            term_hints=effective_term_hints,
            correction_rules=correction_rules,
            project_context=project_context,
            interview_context=interview_context,
        )
    except Exception as e:
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
    except Exception as e:
        return {"success": False, "message": f"write summary failed: {e}"}

    return {"success": True, "inserted": inserted}
def run_workflow(interview_id: int) -> Dict[str, Any]:
    """
    只负责“转录 -> 背景提炼 -> 纠错兜底 -> 写 summary”的工作流。

    旧版工作流中的 Notes 生成已拆分出去，后续由独立接口按题目触发。
    当前工作流会先读取访谈所属项目的背景描述，并将其注入到纠错阶段，
    以便后续 summary 的文本更贴合项目语境。
    """
    def fail(stage: str, detail: Dict[str, Any] | str) -> Dict[str, Any]:
        try:
            DbAccess.update_interview_status(interview_id, 3)
        except Exception:
            pass
        return {"success": False, "stage": stage, "detail": detail}

    try:
        try:
            DbAccess.update_interview_status(interview_id, 1)
        except Exception:
            # 状态更新失败不影响主流程。
            pass

        interview_row = DbAccess.get_interview_by_id(interview_id)
        if not interview_row:
            return fail("load_interview", {"message": f"interview {interview_id} not found"})
        project_id = interview_row.get("parse_project_id")
        if project_id is None:
            return fail("load_project", {"message": "project id missing from interview"})
        project_context = load_project_context_by_id(int(project_id))
        term_hints = load_term_hints_from_state(interview_id=interview_id)
        correction_rules = load_correction_rules_from_state(interview_id=interview_id)

        # 1. 本地上云 / 预签名 URL
        up = step_upload_interview_audio(interview_id)
        if not up.get("success"):
            return fail("upload", up)
        object_key = up["object_key"]
        audio_url = up["audio_url"]

        # 2. ASR
        tr = step_transcribe(audio_url)
        if not tr.get("success"):
            return fail("transcribe", tr)
        asr_result = tr["asr_result"]

        # 3. 写 file_content
        st = step_store_file_content(interview_id, object_key, audio_url, asr_result)
        if not st.get("success"):
            return fail("store_file_content", st)
        file_content_obj = st["file_content"]
        file_content_json = json.dumps(file_content_obj, ensure_ascii=False)

        # 4. 提炼访谈背景
        ec = step_extract_interview_context(
            interview_id,
            project_context=project_context,
            term_hints=term_hints,
        )
        if not ec.get("success"):
            return fail("extract_interview_context", ec)
        interview_context = ec["interview_context"]

        # 5. LLM 兜底纠错（清洗流程当前保留注释，暂不启用）
        cl = step_clean_with_llm(
            file_content_json,
            project_context=project_context,
            interview_context=interview_context,
            term_hints=term_hints,
            correction_rules=correction_rules,
        )
        if not cl.get("success"):
            return fail("correct_fallback", cl)
        cleaned_json = cl["cleaned_json"]

        # 6. 写 summary
        ws = step_write_summary(interview_id, cleaned_json)
        if not ws.get("success"):
            return fail("write_summary", ws)

        row = DbAccess.get_interview_by_id(interview_id)

        try:
            DbAccess.update_interview_status(interview_id, 2)
        except Exception:
            pass

        return {
            "success": True,
            "object_key": object_key,
            "audio_url": audio_url,
            "asr_result_preview": {
                "full_text_len": len(asr_result.get("full_text", "")),
                "speakers_count": len(asr_result.get("speakers", [])),
            },
            "summary_inserted": ws.get("inserted", 0),
        }
    except Exception as e:
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
