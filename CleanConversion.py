"@Date: 2026-04-10"
"@Author: lixinyang"
import json
from typing import Any, Dict, List, Optional

import dotenv

from Model import ModelClient

dotenv.load_dotenv()


def clean_speakers(
    speakers: List[Dict[str, Any]],
    speaker_roles: Optional[Dict[str, str]] = None,
    term_hints: Optional[List[str]] = None,
    project_context: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    对按说话轮次切分后的 speakers 列表进行逐段纠错与清洗。

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
        清洗后的轮次列表，每个元素扩展为:
        {
            "id": int,
            "speaker_id": str,
            "speaker_content_raw": str,
            "speaker_content_clean": str,
            "term_corrections": [
                {"from": str, "to": str}
            ]
        }
    """
    client = ModelClient()
    cleaned: List[Dict[str, Any]] = []

    total = len(speakers)
    for idx, seg in enumerate(speakers, start=1):
        seg_id = seg.get("id")
        speaker_id = str(seg.get("speaker_id", ""))
        raw_text = seg.get("speaker_content", "")

        print(f"[CleanSpeakers] 开始清洗第 {idx}/{total} 段, id={seg_id}, speaker_id={speaker_id}")

        role = None
        if speaker_roles:
            role = speaker_roles.get(speaker_id)

        result = client.clean_speaker_utterance(
            speaker_text=raw_text,
            speaker_role=role,
            term_hints=term_hints,
            project_context=project_context,
        )

        cleaned_segment = {
            "id": seg_id,
            "speaker_id": speaker_id,
            "speaker_content_clean": result.get("clean_text", raw_text),
            "term_corrections": result.get("term_corrections", []),
        }
        cleaned.append(cleaned_segment)

        print(f"[CleanSpeakers] 完成清洗第 {idx}/{total} 段, id={seg_id}")

    return cleaned


def clean_file_content_json(
    file_content_json: str,
    speaker_roles: Optional[Dict[str, str]] = None,
    term_hints: Optional[List[str]] = None,
    project_context: Optional[str] = None,
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
                "speakers": [
                    {
                        "id": int,
                        "speaker_id": str,
                        "speaker_content": str,
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

    cleaned_speakers = clean_speakers(
        speakers=speakers,
        speaker_roles=speaker_roles,
        term_hints=term_hints,
        project_context=project_context,
    )

    enriched: List[Dict[str, Any]] = []
    for original, cleaned in zip(speakers, cleaned_speakers):
        merged = dict(original)
        merged["speaker_content_clean"] = cleaned.get(
            "speaker_content_clean",
            merged.get("speaker_content", ""),
        )
        merged["term_corrections"] = cleaned.get("term_corrections", [])
        enriched.append(merged)

    result["speakers"] = enriched
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
