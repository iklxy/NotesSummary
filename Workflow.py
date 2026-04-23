"@Date:2026-04-10"
"@Author:lixinyang"

import json
import traceback
from typing import Any, Dict, List, Optional

from VolcUpload import upload_local_file, build_object_key, build_local_file_path, get_tos_client, tos
from VolcengineConversion import run_asr
from CleanConversion import clean_file_content_json
from Model import ModelClient
from RagIndex import index_interview_summary, retrieve_segments_for_question
from Fewshot import select_fewshot_samples
from Hotword import load_term_hints_from_state, merge_term_hints
from DbAccess import DbAccess
from config import config


def _build_project_context(project_row: Dict[str, Any] | None) -> str:
    """
    将项目表中的名称、关键词和核心描述，整理为可直接注入 prompt 的背景块。

    参数:
        project_row: bh_project 表中的项目记录，通常包含 name、keywords、core_problem。

    返回:
        以【项目背景】开头的多行文本；如果没有有效内容则返回空字符串。
    """
    if not project_row:
        return ""

    name = str(project_row.get("name") or "").strip()
    keywords = str(project_row.get("keywords") or "").strip()
    core_problem = str(project_row.get("core_problem") or "").strip()

    lines: List[str] = ["【项目背景】"]
    if name:
        lines.append(f"项目名称：{name}")
    if keywords:
        lines.append(f"项目关键词：{keywords}")
    if core_problem:
        lines.append(f"访谈核心描述：{core_problem}")

    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def _load_project_context_by_id(project_id: int) -> str:
    """
    按项目 ID 读取项目记录并格式化为背景块。

    该函数仅承担“查询 + 格式化”职责，方便清洗和 notes 阶段复用同一份上下文。
    """
    try:
        project_row = DbAccess.get_project_by_id(project_id)
    except Exception as e:
        print(f"[PROJECT] 读取项目背景失败 project_id={project_id}: {e}")
        return ""
    return _build_project_context(project_row)


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
) -> Dict[str, Any]:
    """
    步骤 5：先逐段纠错，再逐段清洗，返回更新后的 JSON 字符串。

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
            project_context=project_context,
            interview_context=interview_context,
        )
    except Exception as e:
        return {"success": False, "message": f"clean with llm failed: {e}"}
    return {"success": True, "cleaned_json": updated_json}


def step_write_summary(interview_id: int, cleaned_json: str) -> Dict[str, Any]:
    """
    步骤 4：将清洗后的 speakers 写入 bh_project_interview_summary（逐句/逐段明细表）。
    目标字段:
        - project_interview_id: interview_id
        - timestamp: 由 ASR 原始分段计算得到的毫秒级时间区间
        - speaker: speaker_id（或映射后的角色）
        - text: speaker_content_clean
        - modify: 0
    """
    try:
        obj = json.loads(cleaned_json)
        speakers = obj.get("result", {}).get("speakers") or []
        if not speakers:
            return {"success": False, "message": "no speakers in cleaned json"}
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


def step_fetch_intent_names(intent_ids: List[int]) -> Dict[str, Any]:
    """
    根据 intent_id 列表读取意图名称，用于构造更强约束的 RAG query。
    """
    if not intent_ids:
        return {"success": True, "intent_name_map": {}}

    placeholders = ",".join(["%s"] * len(intent_ids))
    sql = f"""
        SELECT id, name, code
        FROM bh_question_intent
        WHERE id IN ({placeholders})
    """
    conn = DbAccess.get_connection()
    intent_name_map: Dict[int, str] = {}
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, intent_ids)
            rows = cursor.fetchall()
            for r in rows:
                iid = r.get("id")
                name = (r.get("name") or r.get("code") or "").strip()
                if iid is not None:
                    intent_name_map[int(iid)] = name
    except Exception as e:
        return {"success": False, "intent_name_map": {}, "message": f"fetch intents failed: {e}"}
    finally:
        conn.close()

    return {"success": True, "intent_name_map": intent_name_map}


def step_generate_notes(
    project_id: int,
    interview_id: int,
    questions: List[Dict[str, Any]],
    top_k: int = 10,
    project_context: str | None = None,
) -> Dict[str, Any]:
    """
    步骤 7：针对题目列表执行 RAG 检索并调用 LLM 生成 Notes（仅返回内存结果，不落库）。

    参数:
        project_id:   项目 ID。
        interview_id: 访谈 ID。
        questions:    步骤 6 返回的题目列表，需包含 research_phase 字段。
        top_k:        每道题目 RAG 检索返回的片段数量上限。
        project_context: 可选的项目背景块；为空时会根据 project_id 自动回查项目表。

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

    if not project_context:
        project_context = _load_project_context_by_id(project_id)

    index_warning = None
    try:
        print(f"[NOTES] 为访谈 {interview_id} 构建/更新向量索引")
        index_interview_summary(interview_id)
    except Exception as e:
        index_warning = f"index summary failed: {e}"
        print(f"[NOTES] {index_warning}，将降级为不依赖向量索引继续生成 Notes")

    intent_ids = [row.get("intent_id") for row in questions if row.get("intent_id") is not None]
    intent_name_map: Dict[int, str] = {}
    if intent_ids:
        fi = step_fetch_intent_names([int(i) for i in intent_ids if i is not None])
        if fi.get("success"):
            intent_name_map = fi.get("intent_name_map") or {}
        else:
            print(f"[NOTES] 读取 intent 名称失败：{fi.get('message')}")

    model_client: ModelClient | None = None
    model_client_error: str | None = None
    try:
        model_client = ModelClient()
    except Exception as e:
        model_client_error = f"init model client failed: {e}"
        print(f"[NOTES] {model_client_error}，将写入降级 Notes")
    results: List[Dict[str, Any]] = []

    print(f"[NOTES] 共 {len(questions)} 条题目，开始生成 Notes")

    for row in questions:
        question_id = row.get("id")
        question_text = row.get("question_text", "")
        question_type = row.get("question_type")
        intent_id = row.get("intent_id")
        intent_name = intent_name_map.get(intent_id) if intent_id is not None else None

        print(f"[NOTES] 开始为问题 {question_id} 生成 Notes")
        try:
            segments = retrieve_segments_for_question(
                interview_id=interview_id,
                question_text=question_text,
                top_k=top_k,
                question_type=question_type or None,
                intent_name=intent_name,
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

            if model_client is None:
                notes = {
                    "summary": "Notes 生成失败",
                    "analysis": model_client_error or "model client not available",
                    "confidence": 0.0,
                    "error": model_client_error or "model client not available",
                }
            else:
                notes = model_client.generate_notes_for_question_with_fewshot(
                    question_text=question_text,
                    segments=segments,
                intent_name=intent_name,
                question_type=question_type,
                fewshot_samples=fewshot_samples,
                project_context=project_context,
            )
        except Exception as e:
            results.append(
                {
                    "project_id": project_id,
                    "project_interview_id": interview_id,
                    "question_id": question_id,
                    "intent_id": intent_id,
                    "question_text": question_text,
                    "question_type": question_type,
                    "segments": [],
                    "fewshot_count": 0,
                    "fewshot_sample_ids": [],
                    "notes": {
                        "error": f"generate notes failed: {e}",
                        "llm_raw_output": traceback.format_exc(),
                    },
                }
            )
            continue

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
        "warnings": [w for w in [index_warning, model_client_error] if w],
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
    只负责“转录 -> 背景提炼 -> 纠错 -> 清洗 -> 写 summary”的工作流。

    旧版工作流中的 Notes 生成已拆分出去，后续由独立接口按题目触发。
    当前工作流会先读取访谈所属项目的背景描述，并将其注入到清洗阶段，
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
        project_context = _load_project_context_by_id(int(project_id))
        term_hints = load_term_hints_from_state(interview_id=interview_id)

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

        # 5. LLM 清洗
        cl = step_clean_with_llm(
            file_content_json,
            project_context=project_context,
            interview_context=interview_context,
            term_hints=term_hints,
        )
        if not cl.get("success"):
            return fail("clean_llm", cl)
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


def run_notes_generation_for_interview(
    interview_id: int,
    question_id: Optional[int] = None,
    top_k: int = 10,
) -> Dict[str, Any]:
    """
    针对指定访谈的题目，执行 RAG + LLM 生成 Notes 并落库。

    参数:
        interview_id: 访谈主键 ID。
        question_id:   可选，只为单个题目生成 Notes；不传则为该访谈下全部题目生成。
        top_k:         每道题目检索返回的片段数量上限。
    """
    row = DbAccess.get_interview_by_id(interview_id)
    if not row:
        return {
            "success": False,
            "stage": "fetch_interview",
            "detail": {"message": f"interview {interview_id} not found"},
        }

    project_id = row.get("parse_project_id") or 0
    fq = step_fetch_questions(interview_id)
    if not fq.get("success"):
        return {
            "success": False,
            "stage": "fetch_questions",
            "detail": fq,
            "project_id": project_id,
            "interview_id": interview_id,
            "total_questions": 0,
            "results": [],
        }

    questions: List[Dict[str, Any]] = fq.get("questions") or []
    if question_id is not None:
        try:
            target_question_id = int(question_id)
        except (TypeError, ValueError):
            return {
                "success": False,
                "stage": "validate_question_id",
                "detail": {"message": f"invalid question_id: {question_id}"},
                "project_id": project_id,
                "interview_id": interview_id,
                "total_questions": 0,
                "results": [],
            }
        questions = [row for row in questions if int(row.get("id") or 0) == target_question_id]
        if not questions:
            return {
                "success": False,
                "stage": "filter_question",
                "detail": {"message": f"question {target_question_id} not found"},
                "project_id": project_id,
                "interview_id": interview_id,
                "total_questions": 0,
                "results": [],
            }

    gn = step_generate_notes(
        project_id=project_id,
        interview_id=interview_id,
        questions=questions,
        top_k=top_k,
    )
    if not gn.get("success"):
        return gn

    notes_write = step_write_notes_results(gn)
    return {
        "success": True,
        "project_id": project_id,
        "interview_id": interview_id,
        "question_id": question_id,
        "total_questions": gn.get("total_questions", 0),
        "generated": len(gn.get("results") or []),
        "inserted": notes_write.get("inserted", 0),
        "results": gn.get("results") or [],
        "warnings": [w for w in gn.get("warnings", []) if w] + [e for e in notes_write.get("errors", []) if e],
    }


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
