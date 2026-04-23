"@Date: 2026-04-10"
"@Author: lixinyang"
import json
from typing import Any, Dict, List, Optional

import dotenv

from Model import ModelClient

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


def correct_speakers(
    speakers: List[Dict[str, Any]],
    speaker_roles: Optional[Dict[str, str]] = None,
    term_hints: Optional[List[str]] = None,
    project_context: Optional[str] = None,
    interview_context: Optional[Dict[str, Any] | str] = None,
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
    client = ModelClient()
    total = len(speakers)
    corrected: List[Dict[str, Any]] = []
    for idx, seg in enumerate(speakers, start=1):
        seg_id = seg.get("id")
        speaker_id = str(seg.get("speaker_id", ""))
        raw_text = str(seg.get("speaker_content", "") or "")
        role = speaker_roles.get(speaker_id) if speaker_roles else None
        print(f"[CorrectSpeakers] 开始纠错第 {idx}/{total} 段, id={seg_id}, speaker_id={speaker_id}")
        corrected_item = client.correct_transcript_batch(
            transcript=[
                {
                    "uid": str(seg.get("uid") or f"u{idx:04d}"),
                    "id": seg_id,
                    "speaker_id": speaker_id,
                    "speaker_role": role,
                    "start_time": seg.get("start_time"),
                    "end_time": seg.get("end_time"),
                    "text": raw_text,
                }
            ],
            term_hints=term_hints,
            project_context=project_context,
            interview_context=interview_context,
        )
        corrected_row = corrected_item[0] if corrected_item else {}
        corrected_text = corrected_row.get("corrected_text", raw_text)
        corrected.append(
            {
                "id": seg_id,
                "uid": corrected_row.get("uid", f"u{idx:04d}"),
                "speaker_id": speaker_id,
                "speaker_role": role,
                "speaker_content": raw_text,
                "speaker_content_corrected": corrected_text,
                "start_time": seg.get("start_time"),
                "end_time": seg.get("end_time"),
                "term_corrections": corrected_row.get("corrections", []),
                "uncertain_terms": corrected_row.get("uncertain_terms", []),
            }
        )
        print(f"[CorrectSpeakers] 完成纠错第 {idx}/{total} 段, id={seg_id}")

    return corrected


def clean_speakers(
    speakers: List[Dict[str, Any]],
    speaker_roles: Optional[Dict[str, str]] = None,
    term_hints: Optional[List[str]] = None,
    project_context: Optional[str] = None,
    interview_context: Optional[Dict[str, Any] | str] = None,
) -> List[Dict[str, Any]]:
    """
    对纠错后的 speakers 列表进行逐段清洗。
    """
    client = ModelClient()
    total = len(speakers)
    cleaned: List[Dict[str, Any]] = []
    for idx, seg in enumerate(speakers, start=1):
        seg_id = seg.get("id")
        speaker_id = str(seg.get("speaker_id", ""))
        raw_text = str(seg.get("speaker_content", "") or "")
        corrected_text = str(seg.get("speaker_content_corrected", raw_text) or raw_text)
        role = speaker_roles.get(speaker_id) if speaker_roles else None
        print(f"[CleanSpeakers] 开始清洗第 {idx}/{total} 段, id={seg_id}, speaker_id={speaker_id}")
        cleaned_item = client.clean_transcript_batch(
            transcript=[
                {
                    "uid": str(seg.get("uid") or f"u{idx:04d}"),
                    "id": seg_id,
                    "speaker_id": speaker_id,
                    "speaker_role": role,
                    "start_time": seg.get("start_time"),
                    "end_time": seg.get("end_time"),
                    "corrected_text": corrected_text,
                }
            ],
            term_hints=term_hints,
            project_context=project_context,
            interview_context=interview_context,
        )
        cleaned_row = cleaned_item[0] if cleaned_item else {}
        clean_text = cleaned_row.get("clean_text", corrected_text)
        cleaned_segment = {
            "id": seg_id,
            "uid": cleaned_row.get("uid", f"u{idx:04d}"),
            "speaker_id": speaker_id,
            "speaker_role": role,
            "speaker_content": raw_text,
            "speaker_content_corrected": corrected_text,
            "speaker_content_clean": clean_text,
            "start_time": seg.get("start_time"),
            "end_time": seg.get("end_time"),
            "term_corrections": seg.get("term_corrections", []),
            "uncertain_terms": seg.get("uncertain_terms", []),
        }
        cleaned.append(cleaned_segment)
        print(f"[CleanSpeakers] 完成清洗第 {idx}/{total} 段, id={seg_id}")

    return cleaned


def clean_file_content_json(
    file_content_json: str,
    speaker_roles: Optional[Dict[str, str]] = None,
    term_hints: Optional[List[str]] = None,
    project_context: Optional[str] = None,
    interview_context: Optional[Dict[str, Any] | str] = None,
) -> str:
    """
    针对 bh_project_interview.file_content 中的 JSON 结果进行清洗，
    在现有结构的基础上为每个说话轮次增加清洗结果。

    参数:
        file_content_json: 现有的 file_content JSON 字符串，
                           应包含 result.speakers 结构。
        speaker_roles:     可选，speaker_id 到角色的映射。
        term_hints:        可选，专业术语提示列表。
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
    )
    cleaned_speakers = clean_speakers(
        speakers=corrected_speakers,
        speaker_roles=speaker_roles,
        term_hints=term_hints,
        project_context=project_context,
        interview_context=interview_context,
    )

    enriched: List[Dict[str, Any]] = []
    transcript_enriched: List[Dict[str, Any]] = []
    for original, corrected, cleaned in zip(source_speakers, corrected_speakers, cleaned_speakers):
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
