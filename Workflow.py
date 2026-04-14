"@Date:2026-04-10"
"@Author:lixinyang"

import os
import json
from typing import Any, Dict, List, Optional
import dotenv

from VolcUpload import upload_local_file, build_object_key, build_local_file_path, get_tos_client, bucket_name, TOS_URL_EXPIRE_SECONDS, tos
from VolcengineConversion import run_asr
from CleanConversion import clean_file_content_json
from Model import ModelClient
from RagIndex import index_interview_summary, retrieve_segments_for_question
from Fewshot import select_fewshot_samples
from DbAccess import DbAccess

dotenv.load_dotenv()


def step_upload_interview_audio(interview_id: int) -> Dict[str, Any]:
    """
    步骤 1：本地上云，返回 {object_key, audio_url}。
    如果 bh_project_interview 已存在 file_path，则直接用它作为 object_key 并生成预签名 URL。
    """
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
    row = DbAccess.get_interview_by_id(interview_id)
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
        DbAccess.update_interview_file_content(interview_id, json.dumps(payload, ensure_ascii=False))
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
        inserted = DbAccess.insert_summary_from_cleaned_speakers(interview_id, speakers)
    except Exception as e:
        return {"success": False, "message": f"write summary failed: {e}"}

    return {"success": True, "inserted": inserted}


def step_fetch_questions(interview_id: int) -> Dict[str, Any]:
    """
    步骤 6：根据访谈 ID 从 bh_project_question 中读取题目列表。

    返回结构:
        {
            "success": True/False,
            "questions": [ {id, project_interview_id, question_order, question_text, question_type, intent_id}, ... ],
            "message":  可选的错误说明
        }
    """
    sql = """
        SELECT
            id,
            project_interview_id,
            question_order,
            question_text,
            question_type,
            research_phase,
            intent_id
        FROM bh_project_question
        WHERE project_interview_id = %s
        ORDER BY question_order ASC, id ASC
    """
    conn = DbAccess.get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (interview_id,))
            rows: List[Dict[str, Any]] = cursor.fetchall()
    except Exception as e:
        return {"success": False, "questions": [], "message": f"fetch questions failed: {e}"}
    finally:
        conn.close()

    if not rows:
        return {
            "success": False,
            "questions": [],
            "message": f"no questions found for interview {interview_id}",
        }

    return {"success": True, "questions": rows}


def step_generate_notes(
    project_id: int,
    interview_id: int,
    questions: List[Dict[str, Any]],
    top_k: int = 10,
) -> Dict[str, Any]:
    """
    步骤 7：针对题目列表执行 RAG 检索并调用 LLM 生成 Notes（仅返回内存结果，不落库）。

    参数:
        project_id:   项目 ID。
        interview_id: 访谈 ID。
        questions:    步骤 6 返回的题目列表，需包含 research_phase 字段。
        top_k:        每道题目 RAG 检索返回的片段数量上限。

    返回结构:
        {
            "success": True/False,
            "project_id": ...,
            "interview_id": ...,
            "total_questions": N,
            "results": [
                {
                    "project_id": ...,
                    "project_interview_id": ...,
                    "question_id": ...,
                    "intent_id": ...,
                    "question_text": "...",
                    "question_type": "...",
                    "segments": [...],   # RAG 检索片段
                    "notes": {...},      # LLM 生成的 Notes JSON
                },
                ...
            ]
        }
    """
    if not questions:
        return {
            "success": False,
            "project_id": project_id,
            "interview_id": interview_id,
            "total_questions": 0,
            "results": [],
            "message": "no questions to generate notes for",
        }

    print(f"[NOTES] 为访谈 {interview_id} 构建/更新向量索引")
    index_interview_summary(interview_id)

    intent_ids = [row.get("intent_id") for row in questions if row.get("intent_id") is not None]
    intent_desc_map: Dict[int, str] = {}
    if intent_ids:
        placeholders = ",".join(["%s"] * len(intent_ids))
        sql = f"""
            SELECT id, description
            FROM bh_question_intent
            WHERE id IN ({placeholders})
        """
        conn = DbAccess.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, intent_ids)
                rows = cursor.fetchall()
                for r in rows:
                    iid = r.get("id")
                    desc = r.get("description") or ""
                    if iid is not None:
                        intent_desc_map[int(iid)] = desc
        finally:
            conn.close()

    model_client = ModelClient()
    results: List[Dict[str, Any]] = []

    print(f"[NOTES] 共 {len(questions)} 条题目，开始生成 Notes")

    for row in questions:
        question_id = row.get("id")
        question_text = row.get("question_text", "")
        question_type = row.get("question_type")
        intent_id = row.get("intent_id")
        intent_desc = intent_desc_map.get(intent_id) if intent_id is not None else None

        print(f"[NOTES] 开始为问题 {question_id} 生成 Notes")

        segments = retrieve_segments_for_question(
            interview_id=interview_id,
            question_text=question_text,
            top_k=top_k,
        )
        print(f"[NOTES] 问题 {question_id} 检索到 {len(segments)} 条相关片段")

        fewshot_samples = select_fewshot_samples(
            project_id=project_id,
            question_id=question_id,
            question_type=question_type or "",
            research_phase=row.get("research_phase"),
            intent_id=intent_id if intent_id is not None else 0,
            limit=2,
        )

        print(f"[NOTES] 问题 {question_id} 选出 few-shot 样本数量: {len(fewshot_samples)}")

        notes = model_client.generate_notes_for_question_with_fewshot(
            question_text=question_text,
            segments=segments,
            intent_name=intent_desc,
            question_type=question_type,
            fewshot_samples=fewshot_samples,
        )

        results.append(
            {
                "project_id": project_id,
                "project_interview_id": interview_id,
                "question_id": question_id,
                "intent_id": intent_id,
                "question_text": question_text,
                "question_type": question_type,
                "segments": segments,
                 "fewshot_count": len(fewshot_samples),
                 "fewshot_sample_ids": [s.get("id") for s in fewshot_samples],
                "notes": notes,
            }
        )

    return {
        "success": True,
        "project_id": project_id,
        "interview_id": interview_id,
        "total_questions": len(questions),
        "results": results,
    }


def step_write_notes_results(notes_block: Dict[str, Any]) -> Dict[str, Any]:
    """
    步骤 8：将步骤 7 生成的 Notes 结果写入 bh_project_nterview_notes 表。

    参数:
        notes_block: step_generate_notes 的返回结果。

    返回:
        {
            "success": True/False,
            "inserted": 实际插入的记录数,
            "errors":   [可选的错误信息列表]
        }
    """
    results = notes_block.get("results") or []
    if not results:
        return {"success": False, "inserted": 0, "errors": ["no notes results to write"]}

    inserted = 0
    errors: List[str] = []

    for item in results:
        project_id = item.get("project_id")
        interview_id = item.get("project_interview_id")
        question_id = item.get("question_id")
        intent_id = item.get("intent_id")
        notes = item.get("notes") or {}

        if not isinstance(notes, dict):
            errors.append(f"question_id={question_id}: notes is not dict")
            continue
        if project_id is None or interview_id is None or question_id is None or intent_id is None:
            errors.append(f"question_id={question_id}: missing ids for insert")
            continue

        note_json_str = json.dumps(notes, ensure_ascii=False)
        confidence_raw = notes.get("confidence", 0.0)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0

        if "llm_raw_output" in notes:
            status = 4
            error_message = "llm_raw_output present; please inspect note_json"
        else:
            status = 0
            error_message = None

        try:
            new_id = DbAccess.insert_notes_result(
                project_id=project_id,
                interview_id=interview_id,
                question_id=question_id,
                intent_id=intent_id,
                note_json_str=note_json_str,
                confidence=confidence,
                status=status,
                error_message=error_message,
            )
            inserted += 1
        except Exception as e:
            errors.append(f"question_id={question_id}: insert failed: {e}")

    return {"success": True, "inserted": inserted, "errors": errors}


def run_workflow(interview_id: int) -> Dict[str, Any]:
    """
    总工作流：
        1) 本地上云（或直接生成预签名 URL）
        2) 云上音频转文字（ASR）
        3) 组装并写入 file_content
        4) LLM 清洗
        5) 将清洗后的结果落库到 bh_project_interview_summary
        6) 从 bh_project_question 读取题目列表
        7) 使用 RAG + LLM 为每个题目生成 Notes（仅返回，不落库）
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

    row = DbAccess.get_interview_by_id(interview_id)
    project_id = row.get("parse_project_id") if row else None

    fq = step_fetch_questions(interview_id)
    if not fq.get("success"):
        notes_block = {
            "success": False,
            "stage": "fetch_questions",
            "message": fq.get("message", ""),
            "total_questions": 0,
            "results": [],
        }
        notes_write = {"success": False, "inserted": 0, "errors": ["fetch_questions failed"]}
    else:
        gn = step_generate_notes(
            project_id=project_id or 0,
            interview_id=interview_id,
            questions=fq["questions"],
            top_k=10,
        )
        notes_block = gn
        if gn.get("success"):
            notes_write = step_write_notes_results(gn)
        else:
            notes_write = {"success": False, "inserted": 0, "errors": ["generate_notes failed"]}

    return {
        "success": True,
        "object_key": object_key,
        "audio_url": audio_url,
        "asr_result_preview": {
            "full_text_len": len(asr_result.get("full_text", "")),
            "speakers_count": len(asr_result.get("speakers", [])),
        },
        "summary_inserted": ws.get("inserted", 0),
        "notes": notes_block,
        "notes_db": notes_write,
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
