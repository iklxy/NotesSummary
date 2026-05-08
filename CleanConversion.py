"@Date: 2026-04-10"
"@Author: lixinyang"

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import dotenv

from Model import ModelClient
from InterviewLogger import log_interview

dotenv.load_dotenv()


def _extract_transcript_records(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    从 file_content JSON 中提取可供批处理模型使用的逐条转录记录。

    优先读取 result.transcript；如果不存在，则回退到 result.speakers。
    """
    result = data.get("result") or {}
    transcript = result.get("transcript")
    speakers = result.get("speakers") or []

    source = transcript if isinstance(transcript, list) and transcript else speakers
    records: List[Dict[str, Any]] = []
    for idx, seg in enumerate(source, start=1):
        if not isinstance(seg, dict):
            continue
        uid = str(seg.get("uid") or seg.get("id") or f"u{idx:04d}")
        speaker_id = str(seg.get("speaker_id") or "")
        start_time = seg.get("start_time")
        if start_time is None:
            start_time = seg.get("start_ms")
        end_time = seg.get("end_time")
        if end_time is None:
            end_time = seg.get("end_ms")
        text = seg.get("speaker_content")
        if text is None:
            text = seg.get("text", "")
        records.append(
            {
                "uid": uid,
                "speaker_id": speaker_id,
                "start_time": start_time,
                "end_time": end_time,
                "text": str(text or ""),
            }
        )
    return records


def _build_segment_prompt_record(
    seg: Dict[str, Any],
    idx: int,
    speaker_roles: Optional[Dict[str, str]] = None,
    text_field: str = "speaker_content",
) -> Dict[str, Any]:
    """
    将单条 speaker 记录整理成模型调用所需的最小输入结构。

    参数:
        seg: 单条 speaker 记录，通常包含 speaker_id、时间戳和文本字段。
        idx: 当前记录在列表中的顺序编号，用于兜底生成 uid。
        speaker_roles: 可选的 speaker_id -> 角色映射字典。
        text_field: 本轮调用需要读取的文本字段名，例如 `text` 或 `corrected_text`。

    返回:
        适合直接送入 transcript prompt 的字典。
    """
    speaker_id = str(seg.get("speaker_id", ""))
    text_value = seg.get(text_field)
    if text_value is None and text_field == "text":
        text_value = seg.get("speaker_content", "")
    if text_value is None and text_field == "corrected_text":
        text_value = seg.get("speaker_content_corrected", seg.get("speaker_content", ""))
    return {
        "uid": str(seg.get("uid") or f"u{idx:04d}"),
        "id": seg.get("id"),
        "speaker_id": speaker_id,
        "speaker_role": speaker_roles.get(speaker_id) if speaker_roles else None,
        "start_time": seg.get("start_time"),
        "end_time": seg.get("end_time"),
        text_field: str(text_value or ""),
    }


def _run_segment_stage(
    speakers: List[Dict[str, Any]],
    stage_name: str,
    model_method_name: str,
    input_text_field: str,
    output_text_field: str,
    speaker_roles: Optional[Dict[str, str]] = None,
    term_hints: Optional[List[str]] = None,
    correction_rules: Optional[List[str]] = None,
    project_context: Optional[str] = None,
    interview_context: Optional[Dict[str, Any] | str] = None,
    interview_id: Optional[int] = None,
    max_workers: int = 5,
) -> List[Dict[str, Any]]:
    """
    用统一模板执行逐段处理，避免主纠错 / 兜底纠错 / 清洗三段逻辑重复。

    参数:
        speakers: 待处理的逐段记录列表。
        stage_name: 当前阶段名称，用于日志输出。
        model_method_name: ModelClient 上实际要调用的方法名。
        input_text_field: 本阶段从输入记录里读取的文本字段名。
        output_text_field: 本阶段期望写回的文本字段名。
        speaker_roles: 可选的 speaker_id -> 角色映射字典。
        term_hints: 可选热词提示列表。
        correction_rules: 可选兜底纠错规则列表，仅兜底纠错阶段使用。
        project_context: 可选项目背景文本。
        interview_context: 可选访谈背景对象或文本。

    返回:
        合并了原始字段和当前阶段输出字段的记录列表。
    """
    client = ModelClient()
    runner = getattr(client, model_method_name)
    total = len(speakers)
    results: List[Dict[str, Any]] = []

    def _resolve_output_text(stage_row: Dict[str, Any], request_item: Dict[str, Any]) -> str:
        """
        从模型返回值中解析当前阶段的最终文本。

        参数:
            stage_row: 单段模型返回的字典。
            request_item: 本次送给模型的请求记录。

        返回:
            当前阶段应写回的文本；如果模型没有返回有效结果，则回退到请求文本。
        """
        if output_text_field == "speaker_content_corrected":
            candidates = (
                stage_row.get("corrected_text"),
                stage_row.get("speaker_content_corrected"),
                stage_row.get("text"),
                request_item.get(input_text_field),
            )
        elif output_text_field == "speaker_content_clean":
            candidates = (
                stage_row.get("clean_text"),
                stage_row.get("speaker_content_clean"),
                stage_row.get("text"),
                request_item.get(input_text_field),
            )
        else:
            candidates = (
                stage_row.get(output_text_field),
                stage_row.get("text"),
                request_item.get(input_text_field),
            )

        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate
        return str(request_item.get(input_text_field) or "")

    def _process_one(idx: int, seg: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        seg_id = seg.get("id")
        speaker_id = str(seg.get("speaker_id", ""))
        log_interview("CLEAN", interview_id, f"[{stage_name}] 开始处理第 {idx}/{total} 段, id={seg_id}, speaker_id={speaker_id}")

        request_item = _build_segment_prompt_record(
            seg=seg,
            idx=idx,
            speaker_roles=speaker_roles,
            text_field=input_text_field,
        )
        runner_kwargs = {
            "transcript": [request_item],
            "term_hints": term_hints,
            "project_context": project_context,
            "interview_context": interview_context,
        }
        if correction_rules is not None and model_method_name == "apply_correction_fallback_batch":
            runner_kwargs["correction_rules"] = correction_rules
        try:
            stage_rows = runner(**runner_kwargs)
            stage_row = stage_rows[0] if stage_rows else {}
        except Exception as exc:
            log_interview("CLEAN", interview_id, f"[{stage_name}] 第 {idx}/{total} 段失败 id={seg_id} error={exc}")
            stage_row = {"error": str(exc)}

        raw_text = str(seg.get("speaker_content", "") or "")
        corrected_text = str(seg.get("speaker_content_corrected", raw_text) or raw_text)
        final_text = _resolve_output_text(stage_row, request_item)

        merged = {
            "id": seg_id,
            "uid": stage_row.get("uid", request_item["uid"]),
            "speaker_id": speaker_id,
            "speaker_role": request_item.get("speaker_role"),
            "speaker_content": raw_text,
            "speaker_content_corrected": corrected_text,
            "speaker_content_clean": str(seg.get("speaker_content_clean", corrected_text) or corrected_text),
            "start_time": seg.get("start_time"),
            "end_time": seg.get("end_time"),
            "term_corrections": stage_row.get("corrections", seg.get("term_corrections", [])),
            "uncertain_terms": stage_row.get("uncertain_terms", seg.get("uncertain_terms", [])),
        }
        merged[output_text_field] = final_text
        if output_text_field == "speaker_content_corrected":
            merged["speaker_content_clean"] = final_text
        if output_text_field == "speaker_content_clean":
            merged["speaker_content_clean"] = final_text
        log_interview("CLEAN", interview_id, f"[{stage_name}] 完成处理第 {idx}/{total} 段, id={seg_id}")
        return idx, merged

    batch_size = max(1, max_workers)
    for start in range(0, total, batch_size):
        batch = list(enumerate(speakers[start:start + batch_size], start=start + 1))
        if len(batch) == 1:
            idx, seg = batch[0]
            _, merged = _process_one(idx, seg)
            results.append(merged)
            continue

        batch_results: Dict[int, Dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=min(batch_size, len(batch)), thread_name_prefix=f"clean-{stage_name.lower()}") as executor:
            future_map = {executor.submit(_process_one, idx, seg): idx for idx, seg in batch}
            for future in as_completed(future_map):
                idx = future_map[future]
                try:
                    _, merged = future.result()
                    batch_results[idx] = merged
                except Exception as exc:
                    seg = speakers[idx - 1]
                    seg_id = seg.get("id")
                    speaker_id = str(seg.get("speaker_id", ""))
                    log_interview("CLEAN", interview_id, f"[{stage_name}] 第 {idx}/{total} 段线程异常 id={seg_id} speaker_id={speaker_id} error={exc}")
                    raw_text = str(seg.get("speaker_content", "") or "")
                    batch_results[idx] = {
                        "id": seg_id,
                        "uid": str(seg.get("uid") or seg.get("id") or f"u{idx:04d}"),
                        "speaker_id": speaker_id,
                        "speaker_role": str(seg.get("speaker_role") or ""),
                        "speaker_content": raw_text,
                        "speaker_content_corrected": raw_text,
                        "speaker_content_clean": raw_text,
                        "start_time": seg.get("start_time"),
                        "end_time": seg.get("end_time"),
                        "term_corrections": [],
                        "uncertain_terms": [],
                        output_text_field: raw_text,
                    }
        for idx in sorted(batch_results):
            results.append(batch_results[idx])

    return results


def correct_speakers(
    speakers: List[Dict[str, Any]],
    speaker_roles: Optional[Dict[str, str]] = None,
    term_hints: Optional[List[str]] = None,
    project_context: Optional[str] = None,
    interview_context: Optional[Dict[str, Any] | str] = None,
    interview_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    对按说话轮次切分后的 speakers 列表进行逐段纠错。

    参数:
        speakers:      说话轮次列表，每个元素通常包含:
                       {
                           "id": int,
                           "speaker_id": str,
                           "speaker_content": str
                       }
        speaker_roles: 可选，将 speaker_id 映射为角色标签的字典，
                       例如 {"1": "interviewer", "2": "interviewee"}。
        term_hints:    可选，专业热词提示列表，用于增强术语纠错能力。
        project_context: 可选，项目背景说明块，会被注入到清洗模型的提示词中，
                         用于帮助模型理解本次访谈的业务场景和术语偏好。

    返回:
        纠错后的轮次列表，每个元素扩展为:
        {
            "id": int,
            "speaker_id": str,
            "speaker_content": str,
            "speaker_content_corrected": str,
            "term_corrections": [
                {"from": str, "to": str}
            ],
            "uncertain_terms": [str]
        }
    """
    return _run_segment_stage(
        speakers=speakers,
        stage_name="CorrectSpeakers",
        model_method_name="correct_transcript_batch",
        input_text_field="text",
        output_text_field="speaker_content_corrected",
        speaker_roles=speaker_roles,
        term_hints=term_hints,
        project_context=project_context,
        interview_context=interview_context,
        interview_id=interview_id,
    )


def fallback_correct_speakers(
    speakers: List[Dict[str, Any]],
    correction_rules: Optional[List[str]] = None,
    speaker_roles: Optional[Dict[str, str]] = None,
    term_hints: Optional[List[str]] = None,
    project_context: Optional[str] = None,
    interview_context: Optional[Dict[str, Any] | str] = None,
    interview_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    在主纠错后，根据热词对应的兜底纠错文本再做一次收敛修正。
    """
    return _run_segment_stage(
        speakers=speakers,
        stage_name="FallbackCorrectSpeakers",
        model_method_name="apply_correction_fallback_batch",
        input_text_field="corrected_text",
        output_text_field="speaker_content_corrected",
        speaker_roles=speaker_roles,
        term_hints=term_hints,
        correction_rules=correction_rules,
        project_context=project_context,
        interview_context=interview_context,
        interview_id=interview_id,
    )


def clean_speakers(
    speakers: List[Dict[str, Any]],
    speaker_roles: Optional[Dict[str, str]] = None,
    term_hints: Optional[List[str]] = None,
    project_context: Optional[str] = None,
    interview_context: Optional[Dict[str, Any] | str] = None,
    interview_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    对纠错后的 speakers 列表进行逐段清洗。
    """
    return _run_segment_stage(
        speakers=speakers,
        stage_name="CleanSpeakers",
        model_method_name="clean_transcript_batch",
        input_text_field="corrected_text",
        output_text_field="speaker_content_clean",
        speaker_roles=speaker_roles,
        term_hints=term_hints,
        project_context=project_context,
        interview_context=interview_context,
        interview_id=interview_id,
    )


def clean_file_content_json(
    file_content_json: str,
    speaker_roles: Optional[Dict[str, str]] = None,
    term_hints: Optional[List[str]] = None,
    correction_rules: Optional[List[str]] = None,
    project_context: Optional[str] = None,
    interview_context: Optional[Dict[str, Any] | str] = None,
    interview_id: Optional[int] = None,
) -> str:
    """
    针对 bh_project_interview.file_content 中的 JSON 结果进行逐段纠错与兜底纠错，
    在现有结构的基础上为每个说话轮次增加最终纠错结果。

    参数:
        file_content_json: 现有的 file_content JSON 字符串，
                           应包含 result.speakers 结构。
        speaker_roles:     可选，speaker_id 到角色的映射。
        term_hints:        可选，专业术语提示列表。
        correction_rules:   可选，兜底纠错文本列表（错误词 -> 正确词）。
        project_context:   可选，项目背景说明块，会在逐段清洗时注入到模型提示词中。

    返回:
        更新后的 JSON 字符串，结构大致为:
        {
            "audio": { ... },
            "result": {
                "full_text": str,
                "transcript": [
                    {
                        "uid": str,
                        "speaker_id": str,
                        "start_time": int,
                        "end_time": int,
                        "speaker_content": str,
                        "speaker_content_corrected": str,
                        "speaker_content_clean": str
                    }
                ],
                "speakers": [
                    {
                        "id": int,
                        "speaker_id": str,
                        "speaker_content": str,
                        "speaker_content_corrected": str,
                        "speaker_content_clean": str,
                        "term_corrections": [...]
                    }
                ]
            }
        }
    说明:
        当前版本会先执行主纠错、再纠错和清洗三个步骤；
        因此 speaker_content_clean 会承接清洗后的最终文本。
    """
    data = json.loads(file_content_json)
    result = data.get("result") or {}
    speakers = result.get("speakers") or []
    transcript_records = _extract_transcript_records(data)
    if not transcript_records:
        transcript_records = [
            {
                "uid": str(seg.get("uid") or seg.get("id") or f"u{idx:04d}"),
                "speaker_id": str(seg.get("speaker_id", "")),
                "speaker_role": speaker_roles.get(str(seg.get("speaker_id", "")), "") if speaker_roles else "",
                "start_time": seg.get("start_time"),
                "end_time": seg.get("end_time"),
                "text": str(seg.get("speaker_content", "") or seg.get("text", "") or ""),
            }
            for idx, seg in enumerate(speakers, start=1)
            if isinstance(seg, dict)
        ]
    source_speakers = speakers
    if not source_speakers and transcript_records:
        source_speakers = [
            {
                "id": idx,
                "uid": item.get("uid"),
                "speaker_id": item.get("speaker_id", ""),
                "speaker_role": item.get("speaker_role", ""),
                "speaker_content": item.get("text", ""),
                "start_time": item.get("start_time"),
                "end_time": item.get("end_time"),
            }
            for idx, item in enumerate(transcript_records, start=1)
        ]

    corrected_speakers = correct_speakers(
        speakers=source_speakers,
        speaker_roles=speaker_roles,
        term_hints=term_hints,
        project_context=project_context,
        interview_context=interview_context,
        interview_id=interview_id,
    )
    fallback_corrected_speakers = fallback_correct_speakers(
        speakers=corrected_speakers,
        correction_rules=correction_rules,
        speaker_roles=speaker_roles,
        term_hints=term_hints,
        project_context=project_context,
        interview_context=interview_context,
        interview_id=interview_id,
    )
    cleaned_speakers = clean_speakers(
        speakers=fallback_corrected_speakers,
        speaker_roles=speaker_roles,
        term_hints=term_hints,
        project_context=project_context,
        interview_context=interview_context,
        interview_id=interview_id,
    )

    enriched: List[Dict[str, Any]] = []
    transcript_enriched: List[Dict[str, Any]] = []
    for original, corrected, cleaned in zip(source_speakers, fallback_corrected_speakers, cleaned_speakers):
        merged = dict(original)
        uid = str(corrected.get("uid") or original.get("uid") or original.get("id") or "")
        raw_text = str(original.get("speaker_content", "") or original.get("text", "") or "")
        corrected_text = str(corrected.get("speaker_content_corrected", raw_text) or raw_text)
        clean_text = str(cleaned.get("speaker_content_clean", corrected_text) or corrected_text)

        merged["uid"] = uid
        merged["speaker_content"] = raw_text
        merged["speaker_content_corrected"] = corrected_text
        merged["speaker_content_clean"] = clean_text
        merged["term_corrections"] = corrected.get("term_corrections", [])
        merged["uncertain_terms"] = corrected.get("uncertain_terms", [])
        enriched.append(merged)

        transcript_enriched.append(
            {
                "uid": uid,
                "speaker_id": merged.get("speaker_id", ""),
                "speaker_role": merged.get("speaker_role", ""),
                "start_time": merged.get("start_time"),
                "end_time": merged.get("end_time"),
                "speaker_content": raw_text,
                "speaker_content_corrected": corrected_text,
                "speaker_content_clean": clean_text,
                "term_corrections": merged.get("term_corrections", []),
                "uncertain_terms": merged.get("uncertain_terms", []),
            }
        )

    result["speakers"] = enriched
    result["transcript"] = transcript_enriched
    if transcript_enriched:
        result["full_text_corrected"] = "\n".join(
            item.get("speaker_content_corrected", "") for item in transcript_enriched if item.get("speaker_content_corrected")
        )
        result["full_text_clean"] = "\n".join(
            item.get("speaker_content_clean", "") for item in transcript_enriched if item.get("speaker_content_clean")
        )
    data["result"] = result
    return json.dumps(data, ensure_ascii=False)


if __name__ == "__main__":
    """
    简单命令行用法示例:
        1. 从 stdin 读取一段 file_content JSON。
        2. 调用大模型进行清洗。
        3. 将更新后的 JSON 输出到 stdout。

    实际项目中推荐在业务代码中直接调用 clean_speakers 或 clean_file_content_json。
    """
    import sys

    raw = sys.stdin.read()
    if not raw.strip():
        print("stdin 未读取到任何内容")
        sys.exit(1)

    updated = clean_file_content_json(raw)
    print(updated)
