"@Date:2026-04-10"
"@Author:lixinyang"

import os
import json
from typing import Any, Dict, List, Optional
import dotenv

from VolcUpload import upload_local_file, build_object_key, build_local_file_path, get_tos_client, bucket_name, TOS_URL_EXPIRE_SECONDS, tos
from VolcengineConversion import run_asr
from CleanConversion import clean_file_content_json
from DbAccess import (
    get_interview_by_id,
    update_interview_after_upload,
    update_interview_file_content,
    insert_summary_from_cleaned_speakers,
)

dotenv.load_dotenv()


def step_upload_interview_audio(interview_id: int) -> Dict[str, Any]:
    """
    步骤 1：本地上云，返回 {object_key, audio_url}。
    如果 bh_project_interview 已存在 file_path，则直接用它作为 object_key 并生成预签名 URL。
    """
    row = get_interview_by_id(interview_id)
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
            update_interview_after_upload(
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
            bucket=bucket_name,
            key=object_key,
            expires=TOS_URL_EXPIRE_SECONDS,
        )
        audio_url = pre.signed_url
        return {"success": True, "object_key": object_key, "audio_url": audio_url}


def step_transcribe(audio_url: str) -> Dict[str, Any]:
    """
    步骤 2：调用 ASR，将云上音频转写为 {full_text, speakers[]} 结构。
    """
    asr_result = run_asr(audio_url) or {}
    return {"success": True, "asr_result": asr_result}


def step_store_file_content(interview_id: int, object_key: str, audio_url: str, asr_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 ASR 结果组装为 file_content JSON 并写入 bh_project_interview.file_content。
    """
    row = get_interview_by_id(interview_id)
    project_id = row.get("parse_project_id")
    file_name = row.get("file_name") or f"{interview_id}.wav"

    payload = {
        "audio": {
            "project_id": project_id,
            "interview_id": interview_id,
            "object_key": object_key,
            "bucket_name": bucket_name,
            "url": audio_url,
            "format": file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "wav",
        },
        "result": {
            "full_text": asr_result.get("full_text", ""),
            "speakers": asr_result.get("speakers", []),
        },
    }
    try:
        update_interview_file_content(interview_id, json.dumps(payload, ensure_ascii=False))
    except Exception as e:
        return {"success": False, "message": f"write file_content failed: {e}"}
    return {"success": True, "file_content": payload}


def step_clean_with_llm(file_content_json: str) -> Dict[str, Any]:
    """
    步骤 3：调用模型进行清洗（去口头禅、统一术语），返回更新后的 JSON 字符串。
    """
    # 可选：根据项目实际构建 speaker_roles / term_hints
    speaker_roles = {"1": "interviewer", "2": "interviewee"}
    term_hints: List[str] = []
    try:
        updated_json = clean_file_content_json(
            file_content_json=file_content_json,
            speaker_roles=speaker_roles,
            term_hints=term_hints,
        )
    except Exception as e:
        return {"success": False, "message": f"clean with llm failed: {e}"}
    return {"success": True, "cleaned_json": updated_json}


def step_write_summary(interview_id: int, cleaned_json: str) -> Dict[str, Any]:
    """
    步骤 4：将清洗后的 speakers 写入 bh_project_interview_summary（逐句/逐段明细表）。
    目标字段:
        - project_interview_id: interview_id
        - timestamp: 可空，这里写空字符串
        - speaker: speaker_id（或映射后的角色）
        - text: speaker_content_clean
        - modify: 0
    """
    obj = json.loads(cleaned_json)
    speakers = obj.get("result", {}).get("speakers") or []
    if not speakers:
        return {"success": False, "message": "no speakers in cleaned json"}

    try:
        inserted = insert_summary_from_cleaned_speakers(interview_id, speakers)
    except Exception as e:
        return {"success": False, "message": f"write summary failed: {e}"}

    return {"success": True, "inserted": inserted}


def run_workflow(interview_id: int) -> Dict[str, Any]:
    """
    总工作流：
        1) 本地上云（或直接生成预签名 URL）
        2) 云上音频转文字（ASR）
        3) 组装并写入 file_content
        4) LLM 清洗
        5) 将清洗后的结果落库到 bh_project_interview_summary
    """
    # 1. 本地上云 / 预签名 URL
    up = step_upload_interview_audio(interview_id)
    if not up.get("success"):
        return {"success": False, "stage": "upload", "detail": up}
    object_key = up["object_key"]
    audio_url = up["audio_url"]

    # 2. ASR
    tr = step_transcribe(audio_url)
    if not tr.get("success"):
        return {"success": False, "stage": "transcribe", "detail": tr}
    asr_result = tr["asr_result"]

    # 3. 写 file_content
    st = step_store_file_content(interview_id, object_key, audio_url, asr_result)
    if not st.get("success"):
        return {"success": False, "stage": "store_file_content", "detail": st}
    file_content_obj = st["file_content"]
    file_content_json = json.dumps(file_content_obj, ensure_ascii=False)

    # 4. LLM 清洗
    cl = step_clean_with_llm(file_content_json)
    if not cl.get("success"):
        return {"success": False, "stage": "clean_llm", "detail": cl}
    cleaned_json = cl["cleaned_json"]

    # 5. 写 summary
    ws = step_write_summary(interview_id, cleaned_json)
    if not ws.get("success"):
        return {"success": False, "stage": "write_summary", "detail": ws}

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


if __name__ == "__main__":
    """
    命令行用法（示例）：
        1. 在 .env 中设置 TEST_INTERVIEW_ID
        2. 运行本文件
    """
    iid = os.getenv("TEST_INTERVIEW_ID")
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
