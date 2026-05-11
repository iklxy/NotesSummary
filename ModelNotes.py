"@Date: 2026-04-24"
"@Author: lixinyang"

import json
from typing import Any, Callable, Dict, List, Optional

from Fewshot import build_fewshot_prompt_block
from ModelTranscript import parse_json_payload


def escape_inner_quotes_in_field(text: str, field_name: str) -> str:
    """
    修复指定 JSON 字段值中的未转义双引号。

    参数:
        text: 原始 JSON 文本。
        field_name: 需要修复的字段名。

    返回:
        修复后的 JSON 文本。
    """
    key = f'"{field_name}"'
    result_parts: List[str] = []
    cursor = 0
    search_pos = 0
    length = len(text)

    while True:
        key_pos = text.find(key, search_pos)
        if key_pos == -1:
            break
        result_parts.append(text[cursor:key_pos])
        colon_pos = text.find(":", key_pos)
        if colon_pos == -1:
            result_parts.append(text[key_pos:])
            cursor = length
            break
        i = colon_pos + 1
        while i < length and text[i].isspace():
            i += 1
        if i >= length or text[i] != '"':
            result_parts.append(text[key_pos:i])
            cursor = i
            search_pos = i
            continue
        value_start = i
        result_parts.append(text[key_pos:value_start + 1])
        j = value_start + 1
        value_chars: List[str] = []
        while j < length:
            c = text[j]
            if c == '"' and text[j - 1] != "\\":
                k = j + 1
                while k < length and text[k].isspace():
                    k += 1
                if k < length and text[k] in [",", "}", "]"]:
                    break
                value_chars.append("\\\"")
                j += 1
                continue
            value_chars.append(c)
            j += 1
        result_parts.append("".join(value_chars))
        if j < length:
            result_parts.append(text[j])
            j += 1
        cursor = j
        search_pos = j

    if cursor < length:
        result_parts.append(text[cursor:])
    return "".join(result_parts)


def escape_inner_quotes_in_notes_json(text: str) -> str:
    """
    修复 Notes JSON 中 `summary` 和 `analysis` 的未转义双引号。

    参数:
        text: 原始 JSON 文本。

    返回:
        修复后的 JSON 文本。
    """
    fixed = escape_inner_quotes_in_field(text, "summary")
    fixed = escape_inner_quotes_in_field(fixed, "analysis")
    return fixed


def repair_notes_json(generate_fn: Callable[[str, str], str], raw_text: str) -> Optional[Dict[str, Any]]:
    """
    在本地修复失败后，使用 LLM 尝试二次修复 Notes JSON。

    参数:
        generate_fn: 实际执行 LLM 调用的函数。
        raw_text: 待修复的原始文本。

    返回:
        修复成功时返回解析后的字典，否则返回 `None`。
    """
    repair_system = (
        "你是一个 JSON 修复助手。"
        "当前有一段应该是 JSON 的文本，但可能存在转义错误、未转义的引号或换行等问题。"
        "你的任务是仅修复语法，使其成为可以被 json.loads 解析的严格 JSON。"
        "你只能修改引号、逗号、换行和转义相关问题，不得改写字段内容，不得增删字段名。"
        "输出时只返回修复后的 JSON，本身必须完全合法，不要添加额外说明。"
    )
    repair_user = (
        "下面是一段需要修复的 JSON 文本，请你修正其中的转义问题和语法错误，"
        "使其成为严格合法的 JSON：\n\n"
        f"{raw_text}"
    )
    fixed = generate_fn(repair_system, repair_user).strip()
    if fixed.startswith("```"):
        lines = fixed.splitlines()
        fixed = "\n".join(line for line in lines if not line.strip().startswith("```")).strip()
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        try:
            start = fixed.find("{")
            end = fixed.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(fixed[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def parse_notes_response(generate_fn: Callable[[str, str], str], content: str) -> Dict[str, Any]:
    """
    将模型返回的 Notes 文本解析成结构化字典。

    参数:
        generate_fn: 实际执行 LLM 调用的函数，用于兜底 JSON 修复。
        content: 模型原始输出文本。

    返回:
        至少包含 `summary`、`analysis`、`evidence`、`confidence`、`is_insufficient` 的字典。
    """
    content_stripped = content.strip()
    if content_stripped.startswith("```"):
        lines = content_stripped.splitlines()
        content_stripped = "\n".join(line for line in lines if not line.strip().startswith("```")).strip()
    try:
        try:
            result = json.loads(content_stripped)
        except json.JSONDecodeError:
            start = content_stripped.find("{")
            end = content_stripped.rfind("}")
            if start != -1 and end != -1 and end > start:
                result = json.loads(content_stripped[start : end + 1])
            else:
                raise
    except json.JSONDecodeError:
        locally_fixed = escape_inner_quotes_in_notes_json(content_stripped)
        try:
            result = json.loads(locally_fixed)
        except json.JSONDecodeError:
            repaired = repair_notes_json(generate_fn, locally_fixed)
            result = repaired if repaired is not None else {
                "summary": "",
                "analysis": "",
                "evidence": [],
                "confidence": 0.0,
                "llm_raw_output": content,
            }

    result.setdefault("summary", "")
    result.setdefault("analysis", "")
    result.setdefault("evidence", [])
    result.setdefault("confidence", 0.0)
    if "is_insufficient" not in result:
        summary_text = str(result.get("summary") or "").strip()
        analysis_text = str(result.get("analysis") or "").strip()
        result["is_insufficient"] = (
            "当前访谈中信息不足" in summary_text or "当前访谈中信息不足" in analysis_text
        )
    else:
        raw_flag = result.get("is_insufficient")
        if isinstance(raw_flag, str):
            result["is_insufficient"] = raw_flag.strip().lower() in {"1", "true", "yes", "y"}
        else:
            result["is_insufficient"] = bool(raw_flag)
    return result


def generate_notes_for_question(
    generate_fn: Callable[[str, str], str],
    project_context_block: str,
    question_text: str,
    segments: List[Dict[str, Any]],
    intent_name: Optional[str] = None,
    question_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    基于检索片段为单个问题生成结构化 Notes。

    参数:
        generate_fn: 实际执行 LLM 调用的函数。
        project_context_block: 已格式化好的项目背景块。
        question_text: 问题原文。
        segments: RAG 检索出的相关片段列表。
        intent_name: 可选的问题意图名称。
        question_type: 可选的问题类型。

    返回:
        结构化 Notes 字典。
    """
    context_lines: List[str] = []
    for idx, seg in enumerate(segments, start=1):
        sid = seg.get("summary_id", "")
        speaker = seg.get("speaker", "")
        text = str(seg.get("text", "")).replace("\n", " ")
        score = seg.get("score", 0.0)
        context_lines.append(f"[{idx}] summary_id={sid} speaker={speaker} score={score:.4f}\n{text}")
    context_block = "\n\n".join(context_lines) if context_lines else "（当前没有检索到相关片段）"

    intent_part = intent_name or "未指定"
    qtype_part = question_type or "未指定"
    system_prompt = (
        "你是一名医学、药学、体外诊断和市场调研领域的访谈分析专家，"
        "负责根据给定的访谈片段，针对指定问题生成结构化的研究 Notes。"
        "你必须严格基于提供的片段，不要编造事实，并且必须输出语法完全合法、"
        "可以被 json.loads 直接解析的 JSON。"
    )
    user_prompt = (
        f"{project_context_block}"
        "下面是一道研究问题及其相关的访谈片段，请你基于这些信息生成结构化的 Notes。\n\n"
        f"【问题类型】{qtype_part}\n"
        f"【问题意图】{intent_part}\n"
        f"【问题原文】{question_text}\n\n"
        "【相关访谈片段】\n"
        f"{context_block}\n\n"
        "请遵循以下要求完成任务:\n"
        "1. 只使用上述片段中的信息，不要引入任何未在片段中出现的事实。\n"
        "2. 如果信息不足以回答问题，请不要用其它委婉说法，必须在 summary 和 analysis 中都写“当前访谈中信息不足”，并将 is_insufficient 设为 true。\n"
        "3. 如果信息足以回答问题，请将 is_insufficient 设为 false。\n"
        "4. 如果片段无法支撑某个结论，不要猜测，也不要改写成其它表述。\n"
        "5. 请给出一个 0 到 1 之间的置信度 confidence。\n"
        "6. 输出时只返回 JSON，不要包含额外说明。\n"
        "JSON 的参考结构如下:\n"
        "{\n"
        '  "summary": "一句话或几句话的高度概括",\n'
        '  "analysis": "更详细的分析和解释，适合写入研究笔记",\n'
        '  "evidence": [{"summary_id": 0, "speaker": "speaker1", "text": "与结论直接相关的原文片段"}],\n'
        '  "confidence": 0.0,\n'
        '  "is_insufficient": false\n'
        "}\n"
    )
    return parse_notes_response(generate_fn, generate_fn(system_prompt, user_prompt))


def generate_notes_for_question_with_fewshot(
    generate_fn: Callable[[str, str], str],
    project_context_block: str,
    question_text: str,
    segments: List[Dict[str, Any]],
    intent_name: Optional[str],
    question_type: Optional[str],
    fewshot_samples: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    在 Notes 生成时注入 few-shot 示例。

    参数:
        generate_fn: 实际执行 LLM 调用的函数。
        project_context_block: 已格式化好的项目背景块。
        question_text: 问题原文。
        segments: 检索出的相关片段列表。
        intent_name: 问题意图名称。
        question_type: 问题类型标签。
        fewshot_samples: few-shot 样本列表。

    返回:
        结构化 Notes 字典。
    """
    context_lines: List[str] = []
    for idx, seg in enumerate(segments, start=1):
        sid = seg.get("summary_id", "")
        speaker = seg.get("speaker", "")
        text = str(seg.get("text", "")).replace("\n", " ")
        score = seg.get("score", 0.0)
        context_lines.append(f"[{idx}] summary_id={sid} speaker={speaker} score={score:.4f}\n{text}")
    context_block = "\n\n".join(context_lines) if context_lines else "（当前没有检索到相关片段）"

    intent_part = intent_name or "未指定"
    qtype_part = question_type or "未指定"
    system_prompt = (
        "你是一名医学、药学、体外诊断和市场调研领域的访谈分析专家，负责根据给定的访谈片段，"
        "针对指定问题生成结构化的研究 Notes。你必须严格基于提供的片段，不要编造事实，"
        "并且必须输出语法完全合法、可以被 json.loads 直接解析的 JSON。"
    )
    base_user_prompt = (
        f"{project_context_block}"
        "下面是一道研究问题及其相关的访谈片段，请你基于这些信息生成结构化的 Notes。\n\n"
        f"【问题类型】{qtype_part}\n"
        f"【问题意图】{intent_part}\n"
        f"【问题原文】{question_text}\n\n"
        "【相关访谈片段】\n"
        f"{context_block}\n\n"
        "请遵循以下要求完成任务:\n"
        "1. 只使用上述片段中的信息，不要引入任何未在片段中出现的事实；如果片段之间存在冲突，请直接写出冲突，不要强行统一。\n"
        "2. 如果信息不足以回答问题，请不要用其它委婉说法，必须在 summary 和 analysis 中都写“当前访谈中信息不足”，并将 is_insufficient 设为 true。\n"
        "3. 如果信息足以回答问题，请将 is_insufficient 设为 false。\n"
        "4. 如果片段无法支撑某个结论，不要猜测，也不要改写成其它表述。\n"
        "5. summary 只写 1 到 3 句高度概括；analysis 负责更详细的解释。\n"
        "6. 请给出一个 0 到 1 之间的置信度 confidence。\n"
        "7. evidence 中尽量引用与结论直接相关的原文短片段。\n"
        "8. 输出时只返回 JSON，不要包含额外说明。\n"
        "JSON 的参考结构如下:\n"
        "{\n"
        '  "summary": "一句话或几句话的高度概括",\n'
        '  "analysis": "更详细的分析和解释，适合写入研究笔记",\n'
        '  "evidence": [{"summary_id": 0, "speaker": "speaker1", "text": "与结论直接相关的原文片段"}],\n'
        '  "confidence": 0.0,\n'
        '  "is_insufficient": false\n'
        "}\n"
    )
    fewshot_block = build_fewshot_prompt_block(fewshot_samples)
    user_prompt = f"{fewshot_block}\n\n{base_user_prompt}" if fewshot_block else base_user_prompt
    return parse_notes_response(generate_fn, generate_fn(system_prompt, user_prompt))


def generate_overall_interview_note(
    generate_fn: Callable[[str, str], str],
    project_context_block: str,
    interview_context_block: str,
    key_bq_text: str,
    transcript_text: str,
) -> str:
    """
    基于整篇访谈转录生成访谈级整体 summary notes。

    参数:
        generate_fn: 实际执行 LLM 调用的函数。
        project_context_block: 已格式化好的项目背景块。
        interview_context_block: 已格式化好的访谈背景块。
        key_bq_text: 访谈 key BQ 的文本内容，通常已按行拼好。
        transcript_text: 经过纠错/清洗后的整篇访谈转录文本。

    返回:
        一段适合写入 `bh_project_interview.note_content` 的整体 summary 文本。
    """
    system_prompt = (
        "你是一名医学、药学、体外诊断和市场调研领域的访谈总结专家，"
        "负责根据整篇访谈转录和 key BQ 生成一段访谈级整体总结。"
        "你必须严格基于给定内容，不要编造，不要分点，输出一段 100 到 200 字的中文总结。"
    )
    user_prompt = (
        f"{project_context_block}"
        f"{interview_context_block}"
        "下面是该访谈的 key BQ 和整篇转录内容，请综合这些信息生成访谈级整体 summary notes。\n\n"
        f"【key BQ】\n{key_bq_text or '（未提供 key BQ）'}\n\n"
        "【整篇访谈转录】\n"
        f"{transcript_text}\n\n"
        "要求：\n"
        "1. 仅输出一段自然语言总结，不要输出标题、列表、JSON 或额外解释。\n"
        "2. 重点概括这场访谈的主题、主要结论、市场/业务关注点。\n"
        "3. 长度控制在 100 到 200 字之间，尽量简洁准确。\n"
        "4. 如果信息不足，仍需尽量给出最接近的概括，不要编造未出现的事实。\n"
    )
    content = generate_fn(system_prompt, user_prompt).strip()
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(line for line in lines if not line.strip().startswith("```")).strip()
    return content


def _normalize_minutes_outline_items(raw_items: Any) -> List[Dict[str, Any]]:
    """
    将模型返回的智能纪要小点列表归一化为统一结构。

    参数:
        raw_items: 模型返回的 items / points / children 原始内容。

    返回:
        规范化后的 item 列表。
    """
    if not isinstance(raw_items, list):
        return []

    items: List[Dict[str, Any]] = []
    for item_index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        summary = str(item.get("summary") or item.get("content") or "").strip()
        if not title and not summary:
            continue
        items.append(
            {
                "order": int(item.get("order") or item_index),
                "title": title,
                "summary": summary,
            }
        )
    return items


def _normalize_minutes_outline_sections(raw_sections: Any) -> List[Dict[str, Any]]:
    """
    将模型返回的智能纪要章节列表归一化为统一结构。

    参数:
        raw_sections: 模型返回的 sections / outline 原始内容。

    返回:
        规范化后的章节列表。
    """
    if not isinstance(raw_sections, list):
        return []

    sections: List[Dict[str, Any]] = []
    for section_index, section in enumerate(raw_sections, start=1):
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or section.get("name") or "").strip()
        summary = str(section.get("summary") or section.get("content") or "").strip()
        items = _normalize_minutes_outline_items(section.get("items") or section.get("points") or section.get("children"))
        if not title and not summary and not items:
            continue
        sections.append(
            {
                "order": int(section.get("order") or section_index),
                "title": title,
                "summary": summary,
                "items": items,
            }
        )
    return sections


def parse_minutes_outline_response(content: str) -> Dict[str, Any]:
    """
    将模型返回的智能纪要文本解析为结构化字典。

    参数:
        content: 模型原始输出文本。

    返回:
        归一化后的纪要大纲字典。
    """
    try:
        payload = parse_json_payload(content)
    except Exception:
        return {
            "document_title": "",
            "core_summary": "",
            "sections": [],
            "action_items": [],
            "highlights": [],
            "llm_raw_output": content,
        }
    if not isinstance(payload, dict):
        return {
            "document_title": "",
            "core_summary": "",
            "sections": [],
            "action_items": [],
            "highlights": [],
            "llm_raw_output": content,
        }

    raw_sections = payload.get("sections")
    if raw_sections is None:
        raw_sections = payload.get("outline")

    action_items = payload.get("action_items") or []
    if not isinstance(action_items, list):
        action_items = []
    highlights = payload.get("highlights") or []
    if not isinstance(highlights, list):
        highlights = []

    normalized_sections = _normalize_minutes_outline_sections(raw_sections)
    return {
        "document_title": str(payload.get("document_title") or payload.get("title") or "").strip(),
        "core_summary": str(payload.get("core_summary") or payload.get("summary") or "").strip(),
        "sections": normalized_sections,
        "outline": normalized_sections,
        "action_items": action_items,
        "highlights": [str(item).strip() for item in highlights if str(item).strip()],
        "llm_raw_output": content,
    }


def _build_legacy_minutes_outline_prompts(project_context_block: str, transcript_text: str) -> tuple[str, str]:
    """
    构建旧版智能纪要 prompt。

    参数:
        project_context_block: 已格式化好的项目背景块。
        transcript_text: 经清洗后的整篇访谈转录全文。

    返回:
        (system_prompt, user_prompt)。
    """
    system_prompt = (
        "你是专业的医疗咨询行业专家与信息提炼专家，精通医疗领域专业术语、咨询场景核心要点，"
        "擅长精准提取转录文本中的关键信息，规避口语化、冗余内容，同时严格遵循以下规则，完成转录文本的结构化总结："
        "一、核心规则（必严格遵守）"
        "1. 信息提取范围：仅提取文本中客观事实、明确结论、具体数据、医生观点、临床判断，不添加任何主观推理、不编造信息。"
        "2. 内容筛选：彻底去除口语、重复、冗余、寒暄、打断、无关对话。"
        "3. 结构要求：输出结构固定为三段式：① 1段整体核心总结（总览）② 按讨论主题分章节，每章提炼要点，用列表呈现③ 提取行动项/待办（若无则写“无”）。"
        "4. 关键信息保留：必须完整保留关键数字、比例、时间、患者量、处方占比、专业术语。"
        "5. 语言风格：语言简洁、专业、书面化，全程要点式输出，不写长段落。"
        "6. 信息严谨性：不确定内容不推测、不补充，只写文本中明确出现的信息。"
        "7. 关键信息高亮：关键数据、比例、阈值、核心结论加粗高亮。"
        "8. 严格忠实原文，不漏信息、不改观点、不合并语义、不跳模块。"
        "9. 医生关键原话用“”标注。"
        "10. 能用表格呈现比例/分布时，必须用表格。"
        "11. 章节 summary 和小点 summary 必须是自然语言正文，禁止输出 JSON 对象、键值对、大括号、代码块或字段名。"
        "只输出 JSON，不要输出额外解释。"
    )
    user_prompt = (
        f"{project_context_block}"
        "请对以下访谈转录文本进行**严格、完整、无遗漏**的结构化总结，必须遵守以下全部规则：\n\n"
        "1. 只提取客观事实、结论、数据、医生观点、临床判断，不添加任何主观推理、不编造信息。\n"
        "2. 彻底去除口语、重复、冗余、寒暄、打断、无关对话。\n"
        "3. 输出结构固定为三段式：① 1段整体核心总结（总览）② 按讨论主题分章节，每章提炼要点，用列表呈现③ 提取行动项/待办（若无则写“无”）。\n"
        "4. 必须完整保留：关键数字、比例、时间、患者量、处方占比、专业术语。\n"
        "5. 语言简洁、专业、书面化，全程要点式输出，不写长段落。\n"
        "6. 不确定内容不推测、不补充，只写文本中明确出现的信息。\n"
        "7. 关键数据、比例、阈值、核心结论加粗高亮。\n"
        "8. 严格忠实原文，不漏信息、不改观点、不合并语义、不跳模块。\n"
        "9. 医生关键原话用“”标注。\n"
        "10. 能用表格呈现比例/分布时，必须用表格。\n\n"
        "请输出 JSON，结构参考如下：\n"
        "{\n"
        '  "core_summary": "1段整体核心总结（总览）",\n'
        '  "sections": [\n'
        "    {\n"
        '      "order": 1,\n'
        '      "title": "第一部分：...",\n'
        '      "summary": "该部分的简短概述",\n'
        '      "items": [\n'
        "        {\n"
        '          "order": 1,\n'
        '          "title": "小点标题",\n'
        '          "summary": "小点要点总结"\n'
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ],\n"
        '  "action_items": [\n'
        "    {\n"
        '      "owner": "负责人，如有则写",\n'
        '      "time": "时间，如有则写",\n'
        '      "content": "待办内容"\n'
        "    }\n"
        "  ],\n"
        '  "highlights": ["关键数据、比例、数字、判断结论"]\n'
        "}\n\n"
        f"【整篇访谈转录】\n{transcript_text}\n\n"
        "补充要求：\n"
        "1. 章节数量不限，不要过少但是也不要过多。\n"
        "2. 每个章节下列出小点不限，旨在对章节进行完整全面的概括。\n"
        "3. 章节和小点要概括整场访谈的核心主题，而不是机械按问卷逐题抄写。\n"
        "4. 如果某些问题明显属于同一主题，请合并到同一章节或小点，但不能丢失原文信息。\n"
        "5. 如果原文没有对应内容，不要虚构章节或待办。\n"
        "6. 行动项若存在，必须标注负责人、时间；若无则输出“无”。\n"
        "7. 所有 summary 字段必须输出为自然语言正文，禁止输出 JSON 对象、键值对、大括号、代码块或字段名。\n"
    )
    return system_prompt, user_prompt


def _build_dg_minutes_outline_prompts(
    project_context_block: str,
    transcript_text: str,
    questionnaire_text: str,
) -> tuple[str, str]:
    """
    构建引入 DG 的智能纪要 prompt。

    参数:
        project_context_block: 已格式化好的项目背景块。
        transcript_text: 经清洗后的整篇访谈转录全文。
        questionnaire_text: 访谈使用的 DG / 问卷 Markdown 原文。

    返回:
        (system_prompt, user_prompt)。
    """
    dg_text = questionnaire_text.strip()
    system_prompt = (
        "你是专业医疗访谈纪要专家，擅长基于访谈原文（Transcript）与问卷（DG），生成严谨、客观、"
        "可直接交付、字数≥4000 字的标准化结构化访谈纪要。\n"
        "你不固定模块，完全以用户提供的 DG 为唯一框架，逐题对齐、逐题覆盖，适配所有科室、"
        "所有疾病、所有治疗领域。\n"
        "请严格执行以下铁律，无例外：\n\n"
        "一、核心信息提取规则\n"
        "1. 唯一信息来源\n"
        "仅使用访谈原文，不添加任何外部知识、行业常识、主观推断、脑补结论。\n"
        "2. DG 100% 覆盖\n"
        "以用户提供的DG / 提纲为最终结构，逐题对应、逐题回答，不遗漏、不跳过、不合并、不自行增删模块。\n"
        "3. 内容清洗\n"
        "自动过滤寒暄、重复、打断、噪音、无关对话，仅保留数据、观点、药物评价、诊疗流程、患者特征。\n"
        "4. 疾病 / 分型 / 分期严格准确\n"
        "自动识别并严格区分疾病名称、亚型、分期、分级，严禁混淆、错写、误归类。\n"
        "5. 原文忠实\n"
        "6. DG 中的每个大标题都必须在纪要中有对应的输出"
        "不漏信息、不改观点、不合并语义、不调整顺序，100% 还原专家原意。\n\n"
        "二、内容标注规则（通用）\n"
        "1. 提纲问题已明确回答：按原文整理输出。\n"
        "2. 访谈出现DG 未涉及的新增观点 / 数据：标注 【DG 未涉及，访谈新增内容】。"
        "需要结合上下文连贯的展示出来，不能很突兀的展示在结尾\n"
        "4. 访谈员提出的信息、产品介绍、数据引导：标注 【访谈员提出】。\n"
        "5. 专家原话、关键判断、核心结论：必须使用 “” 标出。\n\n"
        "三、药物 / 方案 / 器械精细化评价（强制通用）\n"
        "对访谈中出现的所有药物、治疗方案、手术、在研产品、器械、检查方法，必须逐条、独立、完整整理以下 3 项，颗粒度精细、不笼统、不省略：\n"
        "1. 适用 / 推荐人群（疾病 / 分型 / 分期、临床特征、场景偏好、使用条件）\n"
        "2. 优势 / 获益点（疗效、安全性、便利性、医保、可及性、依从性）\n"
        "3. 劣势 / 顾虑 / 限制（不良反应、禁忌、可及性、疗效短板、使用门槛）\n\n"
        "四、数据与格式规则（通用）\n"
        "1. 完整保留：患者量、例数、比例、年份、周期、费用、处方占比、发生率、评估周期、关键阈值。\n"
        "2. 关键数据、核心结论、专业术语必须加粗高亮。\n"
        "3. 能用表格呈现：分型占比、处方分布、药物对比、路径选择时，可以用表格呈现，切记不可以自己推断，只能根据原文来找数。\n"
        "4. 语言专业、书面、正式、通顺，仅输出最终纪要，不输出任何过程、解释、原文对话。\n\n"
        "五、输出结构规则（最重要）\n"
        "结构完全跟随 DG：\n"
        "--先思考出完整问卷（DG）的所有大纲模块（严格按问卷原题顺序、原题号、原模块标题） \n"
        "--再按问卷模块顺序，逐模块进行内容总结 \n\n"
        "--全程不新增、不删减、不调换模块顺序 \n\n"
        "- 最终仅输出一份完整、通顺、书面化的访谈纪要，需要大于4000字。\n"
        "- 切记不输出任何思考过程、中间步骤或原始对话、不添加任何主观推理、不编造信息。 \n"
        "-能用表格呈现比例/分布时，可以用表格呈现\n"
        "- 纪要按逻辑分段，结构清晰，语言专业。 \n"
        "- 关键数据、比例、阈值、核心结论必须加粗高亮。\n"
        "-切记任何数字 都不能自行推断得出，只能展示原文有的数字，百分比\n\n"
        "请再次注意以下要求：\n"
        "1. 原文复刻原则：所有内容需100%来源于访谈原文，如实呈现原文明确提及的表述、数值、观点，不增删、不修改、不延伸语义，未提及的内容统一标注【未提及】。\n"
        "2. 禁止自主计算：严禁AI通过原文已有数值进行任何推导、计算、换算（例：原文仅提及“某类人群误诊率不超过30%-40%”，仅保留该原文表述，不得计算、补充“正确率为60%-70%”；原文未提及相关数值计算结果，不得自行生成）。\n"
        "3. 禁止主观推导：严禁AI自行推导、补充原文未明确提及的信息（例：原文未提及“换药方向”相关具体比例，不得新增“90%以上的换药为升阶换药”等任何推导性表述，仅标注【未提及】或保留原文已有相关内容）。\n"
        "4. 数值与表述规范：原文中的关键数据、专家原话、专业术语需完整复刻，不得擅自修改、替换，不得添加任何AI自主判断的表述。\n"
        "5. 杜绝任何形式的\n"
        "6. 严厉禁止AI自主加工、计算、推导，一定要确保纪要的真实性、客观性和准确性。\n"
    )
    user_prompt = (
        "请基于以下 Transcript 和 DG 生成最终智能纪要。\n\n"
        "【Transcript 原文】\n"
        f"{transcript_text}\n\n"
        "【DG 原文】\n"
        f"{dg_text}\n\n"
        "补充要求：\n"
        "1. 所有数字只能保留原文明确出现的数字、百分比、比例、阈值，不得自行推断、计算、换算或补齐。\n"
        "2. DG 未涉及的新信息，需要在对应模块中结合上下文自然展示，不要集中堆在结尾。\n"
        "3. 原文未提及的内容统一标注【未提及】。\n"
    )
    return system_prompt, user_prompt


def generate_minutes_outline_from_transcript(
    generate_fn: Callable[[str, str], str],
    project_context_block: str,
    transcript_text: str,
    questionnaire_text: Optional[str] = None,
) -> Dict[str, Any]:
    """
    基于整篇转录文本直接生成智能纪要。

    参数:
        generate_fn: 实际执行 LLM 调用的函数。
        project_context_block: 已格式化好的项目背景块。
        transcript_text: 经清洗后的整篇访谈转录全文。
        questionnaire_text: 访谈关联的 DG / 问卷 Markdown 文本（可选）。

    返回:
        结构化智能纪要字典。
    """
    if questionnaire_text and questionnaire_text.strip():
        system_prompt, user_prompt = _build_dg_minutes_outline_prompts(
            project_context_block=project_context_block,
            transcript_text=transcript_text,
            questionnaire_text=questionnaire_text,
        )
        raw_output = generate_fn(system_prompt, user_prompt)
        payload: Dict[str, Any]
        parsed_payload = parse_minutes_outline_response(raw_output)
        if isinstance(parsed_payload, dict) and parsed_payload.get("sections"):
            payload = parsed_payload
        else:
            payload = {
                "document_title": "",
                "core_summary": "",
                "sections": [],
                "action_items": [],
                "highlights": [],
            }
        raw_text = raw_output.strip()
        payload["raw_minutes_text"] = raw_text
        payload["minutes_text"] = raw_text
        payload["llm_raw_output"] = raw_output
        if not payload.get("document_title"):
            payload["document_title"] = ""
        return payload
    else:
        system_prompt, user_prompt = _build_legacy_minutes_outline_prompts(
            project_context_block=project_context_block,
            transcript_text=transcript_text,
        )
    raw_output = generate_fn(system_prompt, user_prompt)
    payload = parse_minutes_outline_response(raw_output)

    if not payload.get("sections"):
        questionnaire_text_clean = questionnaire_text.strip() if questionnaire_text else ""
        retry_system_prompt = (
            system_prompt
            + "上一轮输出可能过长或不完整。请重新生成，必须输出完整 JSON，"
            + "summary 在准确的情况下保持简短，"
            + "不要输出多余解释，不要输出 markdown，不要省略任何 JSON 字段。"
        )
        if questionnaire_text_clean:
            retry_user_prompt = (
                "请重新生成一版更精简但完整的智能纪要大纲，仍然需要遵守 DG 作为参考框架的规则。\n"
                "要求：\n"
                "1. 只能输出合法 JSON。\n"
                "2. 必须包含 core_summary、sections、action_items、highlights。\n"
                "3. 章节数量不限，不要过少但是也不要过多。\n"
                "4. 每个章节和小点的 summary 要尽量精炼，避免长段落。\n"
                "5. 不要输出分析过程、不要输出说明文字、不要输出 markdown。\n"
                "6. DG 中未覆盖但访谈中出现的新主题可以保留，但仍需按语义顺序插入并标注为 DG 之外的内容。\n\n"
                "【讨论指南（DG）/ 访谈问卷】\n"
                "以下内容是本次访谈使用的讨论指南：\n\n"
                f"{questionnaire_text_clean}\n\n"
                "【整篇访谈转录】\n"
                f"{transcript_text}\n"
            )
        else:
            retry_user_prompt = (
                f"{project_context_block}"
                "请重新生成一版更精简但完整的智能纪要大纲。\n"
                "要求：\n"
                "1. 只能输出合法 JSON。\n"
                "2. 必须包含 core_summary、sections、action_items、highlights。\n"
                "3. 章节数量不限，不要过少但是也不要过多。\n"
                "4. 每个章节和小点的 summary 要尽量精炼，避免长段落。\n"
                "5. 不要输出分析过程、不要输出说明文字、不要输出 markdown。\n\n"
                f"【整篇访谈转录】\n{transcript_text}\n"
            )
        retry_raw_output = generate_fn(retry_system_prompt, retry_user_prompt)
        retry_payload = parse_minutes_outline_response(retry_raw_output)
        if retry_payload.get("sections"):
            payload = retry_payload
            payload["retry_used"] = True
            payload["retry_raw_output"] = retry_raw_output

    if not payload.get("document_title"):
        payload["document_title"] = ""
    return payload


def generate_minutes_item_summary(
    generate_fn: Callable[[str, str], str],
    project_context_block: str,
    interview_context_block: str,
    section_title: str,
    section_summary: str,
    item_title: str,
    item_summary: str,
    segments: List[Dict[str, Any]],
) -> str:
    """
    基于纪要大纲的小点与相关访谈片段，生成单个小点的纪要正文。

    参数:
        generate_fn: 实际执行 LLM 调用的函数。
        project_context_block: 已格式化好的项目背景块。
        interview_context_block: 已格式化好的访谈背景块。
        section_title: 章节标题，例如“第一部分：流行病学及就诊情况”。
        section_summary: 章节概述，用于帮助模型把握主题边界。
        item_title: 小点标题，例如“MS 总体发病趋势”。
        item_summary: 小点的原始概述，用于补充语义。
        segments: 针对该小点检索到的相关访谈片段。

    返回:
        适合直接写入纪要结果的中文总结文本。
    """
    context_lines: List[str] = []
    for idx, seg in enumerate(segments, start=1):
        sid = seg.get("summary_id", "")
        speaker = seg.get("speaker", "")
        text = str(seg.get("text", "")).replace("\n", " ")
        score = seg.get("score", 0.0)
        context_lines.append(f"[{idx}] summary_id={sid} speaker={speaker} score={score:.4f}\n{text}")
    context_block = "\n\n".join(context_lines) if context_lines else "（当前没有检索到相关片段）"

    system_prompt = (
        "你是专业的医疗咨询行业专家与信息提炼专家，精通医疗领域专业术语、咨询场景核心要点，"
        "擅长精准提取转录文本中的关键信息，规避口语化、冗余内容，同时严格遵循以下规则，完成转录文本的结构化总结："
        "一、核心规则（必严格遵守）"
        "1. 信息提取范围：仅提取文本中客观事实、明确结论、具体数据、核心观点、可落地行动项，严禁添加任何主观推理、猜测、补充性内容，不延伸文本未提及的信息。"
        "2. 内容筛选：彻底去除口语化表达（如“嗯、啊、这个、那个、其实”）、重复表述、冗余铺垫、寒暄问候（如“你好、辛苦、再见”）及与咨询核心无关的闲聊内容。"
        "3. 结构要求：严格按“核心总结 → 分点要点 → 结论收束”的逻辑分章节呈现，章节划分清晰，层次分明，符合医疗咨询文本的专业呈现习惯。"
        "4. 关键信息保留：完整保留文本中出现的关键数字、比例、时间节点、人名、医疗机构名称、医疗专业术语，不得遗漏或简化，确保信息的准确性和专业性。"
        "5. 语言风格：整体语言简洁、严谨、专业、书面化，采用要点式输出（分点不冗长，每点核心信息不重复），避免口语化、随意化表述。"
        "6. 信息严谨性：不确定、模糊不清的信息不编造、不补充，仅提炼文本中明确出现、无歧义的内容；若文本中存在矛盾信息，均如实提取，不主观判断对错。"
        "7. 核心总结要求：单独生成1段整体核心总结（总览），高度概括转录文本的核心内容，涵盖咨询主题、核心结论/观点，字数适中（不冗余、不遗漏关键），作为全文总起。"
        "8. 分点要点要求：按咨询讨论的主题，划分独立章节（每章对应一个核心讨论主题），每章内提炼具体要点，采用列表形式呈现（有序/无序均可，保持一致），要点之间不交叉、不重复。"
        "9. 待办/结论要求：单独提取文本中明确的行动项、待办事项（如有），需清晰标注负责人（明确提及的人名/岗位）、完成时间（明确提及的时间节点）；无待办事项则单独呈现文本核心结论，不强行添加。"
        "10. 关键信息高亮：对文本中的关键数据、比例、数字、明确判断结论进行高亮处理（可采用加粗形式），突出核心信息，方便快速抓取重点。"
        "11. 输出不要使用 JSON 大括号，不要输出字段名；请直接输出可读的正文内容，按“章节标题 + 分点 + 结论收束”的方式组织。"
        "12. 每个小点总结结束后，若有结论，请直接作为最后一行收束，不要单独设置“待办/结论”章节。"
    )
    user_prompt = (
        f"{project_context_block}"
        f"{interview_context_block}"
        "下面是一条纪要大纲小点及其相关访谈片段，请综合这些信息生成该小点的总结。\n\n"
        f"【章节标题】\n{section_title or '未命名章节'}\n\n"
        f"【章节概述】\n{section_summary or '（无）'}\n\n"
        f"【小点标题】\n{item_title or '未命名小点'}\n\n"
        f"【小点概述】\n{item_summary or '（无）'}\n\n"
        "【相关访谈片段】\n"
        f"{context_block}\n\n"
        "要求：\n"
        "1. 只基于片段中的信息进行总结，不要引入片段外事实；如果片段之间存在冲突，请直接写出冲突，不要强行统一。\n"
        "2. 输出内容要像智能纪要中的正文，严格、完整、无遗漏，简洁、准确、书面化。\n"
        "3. 必须保留与当前小点相关的关键数字、比例、时间、患者量、处方占比、专业术语。\n"
        "4. 关键数据、比例、阈值、核心结论加粗高亮；医生关键原话用“”标注。\n"
        "5. 如有必要，可使用表格或要点式表达，但不要展开分析过程。\n"
        "6. 如果当前片段不足以支撑这个小点，请直接输出“当前访谈中信息不足”。\n"
        "7. 不要输出 JSON、大括号、字段名、分析过程或证据引用。\n"
        "8. 输出风格必须是可直接渲染的正文：先给出该小点的分点要点，最后用一句总结性结论收束，不要单独输出“待办/结论”章节。\n"
    )
    content = generate_fn(system_prompt, user_prompt).strip()
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(line for line in lines if not line.strip().startswith("```")).strip()
    return content


def _parse_json_with_repair(
    generate_fn: Callable[[str, str], str],
    content: str,
) -> Optional[Dict[str, Any]]:
    """
    尝试将模型输出解析为 JSON；必要时调用 LLM 做语法修复。

    参数:
        generate_fn: 实际执行 LLM 调用的函数。
        content: 模型输出原文。

    返回:
        解析成功时返回字典，否则返回 None。
    """
    content_stripped = content.strip()
    if content_stripped.startswith("```"):
        lines = content_stripped.splitlines()
        content_stripped = "\n".join(line for line in lines if not line.strip().startswith("```")).strip()
    try:
        try:
            return json.loads(content_stripped)
        except json.JSONDecodeError:
            start = content_stripped.find("{")
            end = content_stripped.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(content_stripped[start : end + 1])
            raise
    except json.JSONDecodeError:
        repaired = repair_notes_json(generate_fn, content_stripped)
        if repaired is not None:
            return repaired
    return None


def _normalize_dimension_items(raw_dimensions: Any) -> List[Dict[str, Any]]:
    """
    将模型返回的维度列表归一化为统一结构。

    参数:
        raw_dimensions: 模型原始返回的 dimensions 字段。

    返回:
        规范化后的维度列表，每项包含 name 与 description。
    """
    if not isinstance(raw_dimensions, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for item in raw_dimensions:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("dimension") or item.get("title") or "").strip()
            description = str(item.get("description") or item.get("summary") or "").strip()
        else:
            name = str(item or "").strip()
            description = ""
        if not name:
            continue
        normalized.append(
            {
                "name": name,
                "description": description or None,
            }
        )
    return normalized


def _normalize_kbq_evidence(raw_evidence: Any) -> List[Dict[str, Any]]:
    """
    归一化 KBQ Notes 中的证据列表。

    参数:
        raw_evidence: 模型返回的 evidence 字段。

    返回:
        规范化后的证据列表。
    """
    if not isinstance(raw_evidence, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for item in raw_evidence:
        if not isinstance(item, dict):
            continue
        summary_id = item.get("summary_id")
        speaker = item.get("speaker")
        text = str(item.get("text") or "").strip()
        normalized.append(
            {
                "summary_id": summary_id,
                "speaker": str(speaker or "").strip() or None,
                "text": text,
            }
        )
    return normalized


def _normalize_dimension_notes(raw_dimension_notes: Any) -> List[Dict[str, Any]]:
    """
    将模型返回的 dimension_notes 归一化为统一结构。

    参数:
        raw_dimension_notes: 模型原始返回的 dimension_notes 字段。

    返回:
        规范化后的维度 notes 列表。
    """
    if not isinstance(raw_dimension_notes, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for item in raw_dimension_notes:
        if not isinstance(item, dict):
            continue
        dimension = str(item.get("dimension") or item.get("name") or "").strip()
        summary = str(item.get("summary") or "").strip()
        analysis = str(item.get("analysis") or "").strip()
        evidence = _normalize_kbq_evidence(item.get("evidence"))
        if not dimension:
            continue
        normalized.append(
            {
                "dimension": dimension,
                "summary": summary,
                "analysis": analysis,
                "evidence": evidence,
            }
        )
    return normalized


def parse_kbq_dimensions_response(
    generate_fn: Callable[[str, str], str],
    content: str,
) -> Dict[str, Any]:
    """
    将“维度抽取”模型输出解析为结构化字典。

    参数:
        generate_fn: 实际执行 LLM 调用的函数。
        content: 模型原始输出文本。

    返回:
        至少包含 `dimensions` 字段的字典。
    """
    result = _parse_json_with_repair(generate_fn, content)
    if not isinstance(result, dict):
        result = {"dimensions": [], "llm_raw_output": content}
    result["dimensions"] = _normalize_dimension_items(result.get("dimensions"))
    result.setdefault("llm_raw_output", content)
    return result


def parse_kbq_notes_response(
    generate_fn: Callable[[str, str], str],
    content: str,
) -> Dict[str, Any]:
    """
    将 KBQ Notes 模型输出解析为结构化字典。

    参数:
        generate_fn: 实际执行 LLM 调用的函数。
        content: 模型原始输出文本。

    返回:
        至少包含 `key_bq`、`dimension_notes`、`confidence` 的字典。
    """
    result = _parse_json_with_repair(generate_fn, content)
    if not isinstance(result, dict):
        result = {
            "key_bq": "",
            "dimension_notes": [],
            "confidence": 0.0,
            "llm_raw_output": content,
        }
    result.setdefault("key_bq", "")
    result["dimension_notes"] = _normalize_dimension_notes(result.get("dimension_notes"))
    confidence = result.get("confidence")
    try:
        result["confidence"] = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        result["confidence"] = 0.0
    result.setdefault("llm_raw_output", content)
    return result


def generate_kbq_dimensions(
    generate_fn: Callable[[str, str], str],
    project_context_block: str,
    interview_context_block: str,
    key_bq_text: str,
) -> Dict[str, Any]:
    """
    先从单条 key BQ 中抽取后续回答所需的分析维度。

    参数:
        generate_fn: 实际执行 LLM 调用的函数。
        project_context_block: 已格式化好的项目背景块。
        interview_context_block: 已格式化好的访谈背景块。
        key_bq_text: 单条 key BQ 文本。

    返回:
        包含 `dimensions` 的字典。
    """
    system_prompt = (
        "你是一名医学、药学、体外诊断和市场调研领域的分析专家。"
        "你的任务是把单条 key BQ 抽象成6个适合做纪要的分析维度。"
        "只输出严格合法的 JSON，不要输出额外说明。"
    )
    user_prompt = (
        f"{project_context_block}"
        f"{interview_context_block}"
        "下面是一条 key BQ，请你抽取 3 到 4 个适合后续生成 notes 的分析维度。"
        "维度应当是可操作的分析框架，而不是空泛标签。\n\n"
        f"【key BQ】\n{key_bq_text}\n\n"
        "请输出 JSON，结构参考如下：\n"
        "{\n"
        '  "dimensions": [\n'
        '    {"name": "维度名称", "description": "维度描述"}\n'
        "  ]\n"
        "}\n"
        "要求：\n"
        "1. 维度数量控制在6个。\n"
        "2. 维度应抽象、稳定、适合后续检索总结。\n"
        "3. 不要输出不必要的解释。\n"
        "4. 维度应该常见且普适，不要生成过于冗余的维度"
    )
    content = generate_fn(system_prompt, user_prompt)
    return parse_kbq_dimensions_response(generate_fn, content)


def generate_kbq_notes(
    generate_fn: Callable[[str, str], str],
    project_context_block: str,
    interview_context_block: str,
    key_bq_text: str,
    dimensions: List[Dict[str, Any]],
    segments: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    基于 key BQ、分析维度与检索片段生成 KBQ Notes。

    参数:
        generate_fn: 实际执行 LLM 调用的函数。
        project_context_block: 已格式化好的项目背景块。
        interview_context_block: 已格式化好的访谈背景块。
        key_bq_text: 单条 key BQ 文本。
        dimensions: 第一步抽取得到的维度列表。
        segments: RAG 检索得到的相关片段。

    返回:
        包含 `key_bq`、`dimension_notes`、`confidence` 的字典。
    """
    context_lines: List[str] = []
    for idx, seg in enumerate(segments, start=1):
        sid = seg.get("summary_id", "")
        speaker = seg.get("speaker", "")
        text = str(seg.get("text", "")).replace("\n", " ")
        score = seg.get("score", 0.0)
        context_lines.append(f"[{idx}] summary_id={sid} speaker={speaker} score={score:.4f}\n{text}")
    context_block = "\n\n".join(context_lines) if context_lines else "（当前没有检索到相关片段）"

    dimension_lines: List[str] = []
    for idx, item in enumerate(dimensions, start=1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        description = str(item.get("description") or "").strip()
        if not name:
            continue
        dimension_lines.append(f"[{idx}] {name}" + (f"：{description}" if description else ""))
    dimensions_block = "\n".join(dimension_lines) if dimension_lines else "（未抽取到维度）"

    system_prompt = (
        "你是一名医学、药学、体外诊断和市场调研领域的访谈纪要专家。"
        "你的任务是根据 key BQ、维度和相关访谈片段生成 KBQ Notes。"
        "只输出严格合法的 JSON，不要输出额外说明。"
    )
    user_prompt = (
        f"{project_context_block}"
        f"{interview_context_block}"
        "请基于以下 key BQ、已抽取的分析维度，以及相关访谈片段生成 KBQ Notes。\n\n"
        f"【key BQ】\n{key_bq_text}\n\n"
        f"【维度】\n{dimensions_block}\n\n"
        f"【相关访谈片段】\n{context_block}\n\n"
        "请输出 JSON，结构参考如下：\n"
        "{\n"
        '  "key_bq": "原始 key BQ",\n'
        '  "dimension_notes": [\n'
        '    {"dimension": "维度名称", "summary": "总结内容"}\n'
        "  ]\n"
        "}\n"
        "要求：\n"
        "1. 只基于片段内容进行总结。\n"
        "2. 不要输出分析过程和证据。\n"
        "3. 只输出 JSON。\n"
        "4. 维度总结要简洁、准确、书面化，适合直接写入研究笔记。\n"
    )
    content = generate_fn(system_prompt, user_prompt)
    return parse_kbq_notes_response(generate_fn, content)


def _normalize_ca_dimensions(raw_dimensions: Any) -> List[Dict[str, Any]]:
    """
    将 CA 维度列表归一化为统一结构。

    参数:
        raw_dimensions: 模型返回的维度原始内容。

    返回:
        规范化后的维度列表。
    """
    if not isinstance(raw_dimensions, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for index, item in enumerate(raw_dimensions, start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or item.get("dimension") or "").strip()
        summary = str(item.get("summary") or item.get("description") or "").strip()
        raw_sub_points = item.get("sub_points") or item.get("items") or item.get("points") or []
        sub_points: List[Dict[str, Any]] = []
        if isinstance(raw_sub_points, list):
            for sub_index, sub in enumerate(raw_sub_points, start=1):
                if not isinstance(sub, dict):
                    continue
                sub_title = str(sub.get("title") or sub.get("name") or "").strip()
                sub_summary = str(sub.get("summary") or sub.get("description") or "").strip()
                if not sub_title and not sub_summary:
                    continue
                sub_points.append(
                    {
                        "order": int(sub.get("order") or sub_index),
                        "title": sub_title,
                        "summary": sub_summary,
                    }
                )
        if not title:
            continue
        normalized.append(
            {
                "order": int(item.get("order") or index),
                "title": title,
                "summary": summary,
                "sub_points": sub_points,
            }
        )
    return normalized


def parse_ca_dimensions_response(
    generate_fn: Callable[[str, str], str],
    content: str,
) -> Dict[str, Any]:
    """
    解析 CA 维度抽取的模型输出。

    参数:
        generate_fn: 实际执行 LLM 调用的函数。
        content: 模型原始输出文本。

    返回:
        标准化后的 CA 维度字典。
    """
    result = _parse_json_with_repair(generate_fn, content)
    if not isinstance(result, dict):
        result = {"dimensions": [], "llm_raw_output": content}
    result["dimensions"] = _normalize_ca_dimensions(result.get("dimensions"))
    result.setdefault("llm_raw_output", content)
    return result


def _normalize_ca_cells(raw_cells: Any, interview_ids: List[int]) -> Dict[str, str]:
    """
    归一化 CA 单元格映射。
    """
    cells: Dict[str, str] = {str(item): "/" for item in interview_ids}
    if isinstance(raw_cells, dict):
        for key, value in raw_cells.items():
            interview_key = str(key)
            if interview_key in cells:
                text = str(value or "").strip()
                cells[interview_key] = text or "/"
    return cells


def parse_ca_cells_response(
    generate_fn: Callable[[str, str], str],
    content: str,
    interview_ids: List[int],
) -> Dict[str, Any]:
    """
    解析 CA 单元格填充输出。
    """
    result = _parse_json_with_repair(generate_fn, content)
    if not isinstance(result, dict):
        result = {"cells": _normalize_ca_cells(None, interview_ids), "llm_raw_output": content}
    result["cells"] = _normalize_ca_cells(result.get("cells"), interview_ids)
    result.setdefault("llm_raw_output", content)
    return result


def generate_ca_dimensions(
    generate_fn: Callable[[str, str], str],
    project_context_block: str,
    interviews_notes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    基于多份全文 Notes Markdown 生成 CA 的维度与小点骨架。
    """
    notes_blocks: List[str] = []
    for item in interviews_notes:
        interview_id = item.get("interview_id")
        name = str(item.get("name") or f"访谈 {interview_id}").strip()
        notes_markdown = str(item.get("notes_markdown") or "").strip()
        if not notes_markdown:
            continue
        notes_blocks.append(f"【访谈 {interview_id} | {name}】\n{notes_markdown}")
    notes_block = "\n\n".join(notes_blocks)

    system_prompt = (
        "你是专业的医疗咨询行业对比分析专家。"
        "你的任务是根据多份访谈全文 Notes Markdown，生成可跨访谈对比的 CA 表格骨架。"
        "必须输出严格合法的 JSON，不要输出额外说明。"
    )
    user_prompt = (
        f"{project_context_block}"
        "请基于以下多份访谈的全文 Notes Markdown 生成 CA 维度骨架。\n\n"
        f"{notes_block}\n\n"
        "要求：\n"
        "1. 维度必须稳定、可跨访谈比较，不要依赖某一位医生的个体化表述。\n"
        "2. 维度数量不限，每个维度下设置 2 到 4 个小点。\n"
        "3. 维度标题要短、明确、可直接作为表格行标题。\n"
        "4. 小点标题要具体，能体现比较维度。\n"
        "5. 只输出 JSON，不要输出解释、不要输出 markdown。\n"
        "6. 所有 summary 字段必须是自然语言正文，不要输出 JSON 对象或字段名。\n"
        "7. 如果某个维度不适合用于跨访谈对比，不要输出。\n"
        "JSON 结构参考如下：\n"
        "{\n"
        '  "dimensions": [\n'
        "    {\n"
        '      "order": 1,\n'
        '      "title": "维度标题",\n'
        '      "summary": "维度概述",\n'
        '      "sub_points": [\n'
        "        {\n"
        '          "order": 1,\n'
        '          "title": "小点标题",\n'
        '          "summary": "小点说明"\n'
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}\n"
    )
    raw_output = generate_fn(system_prompt, user_prompt)
    payload = parse_ca_dimensions_response(generate_fn, raw_output)
    if not payload.get("dimensions"):
        retry_system_prompt = (
            system_prompt
            + "上一轮输出可能过长或结构不完整。请重新生成更精简、更稳定的版本。"
        )
        retry_user_prompt = (
            f"{project_context_block}"
            "请重新生成一版更精简的 CA 维度骨架。\n"
            "要求：\n"
            "1. 只能输出 JSON。\n"
            "2. 维度数量不限。\n"
            "3. 每个维度 2 到 3 个小点。\n"
            "4. 不要输出任何解释文字。\n\n"
            f"{notes_block}\n"
        )
        retry_raw_output = generate_fn(retry_system_prompt, retry_user_prompt)
        retry_payload = parse_ca_dimensions_response(generate_fn, retry_raw_output)
        if retry_payload.get("dimensions"):
            payload = retry_payload
            payload["retry_used"] = True
            payload["retry_raw_output"] = retry_raw_output
    return payload


def generate_ca_cells_for_sub_point(
    generate_fn: Callable[[str, str], str],
    project_context_block: str,
    dimension_title: str,
    dimension_summary: str,
    sub_point_title: str,
    sub_point_summary: str,
    interview_blocks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    为某一个 CA 小点批量生成各访谈的单元格内容。
    """
    if not interview_blocks:
        return {"cells": {}}

    interview_lines: List[str] = []
    interview_ids: List[int] = []
    for item in interview_blocks:
        interview_id = int(item.get("interview_id") or 0)
        interview_ids.append(interview_id)
        name = str(item.get("name") or f"访谈 {interview_id}").strip()
        meta = item.get("meta") or {}
        segments = item.get("segments") or []
        segment_lines: List[str] = []
        if isinstance(segments, list):
            for seg_index, seg in enumerate(segments, start=1):
                if not isinstance(seg, dict):
                    continue
                sid = seg.get("summary_id", "")
                speaker = seg.get("speaker", "")
                text = str(seg.get("text") or "").replace("\n", " ").strip()
                score = seg.get("score", 0.0)
                if not text:
                    continue
                segment_lines.append(
                    f"[{seg_index}] summary_id={sid} speaker={speaker} score={float(score or 0.0):.4f}\n{text}"
                )
        if not segment_lines:
            segment_lines.append("（当前没有检索到相关片段）")
        meta_text = json.dumps(meta, ensure_ascii=False) if isinstance(meta, dict) else str(meta or "")
        interview_lines.append(
            f"【访谈 {interview_id} | {name}】\n【访谈元数据】\n{meta_text}\n\n【相关片段】\n"
            + "\n\n".join(segment_lines)
        )

    system_prompt = (
        "你是专业的医疗咨询行业对比分析专家。"
        "你的任务是针对同一个 CA 小点，基于每个访谈对应的检索片段，分别输出各访谈的单元格内容。"
        "必须输出严格合法的 JSON，不要输出额外说明。"
    )
    user_prompt = (
        f"{project_context_block}"
        "请根据以下维度、小点和各访谈片段，为每个访谈生成该单元格的内容。\n\n"
        f"【维度标题】\n{dimension_title}\n\n"
        f"【维度概述】\n{dimension_summary or '（无）'}\n\n"
        f"【小点标题】\n{sub_point_title}\n\n"
        f"【小点概述】\n{sub_point_summary or '（无）'}\n\n"
        + "\n\n".join(interview_lines)
        + "\n\n"
        "要求：\n"
        "1. 只基于对应访谈的片段总结，不要跨访谈串用信息。\n"
        "2. 如果该访谈没有相关内容，请填写 \"/\"。\n"
        "3. 如果信息明显不足但能看出该访谈有相关讨论，请用最简短的自然语言总结。\n"
        "4. 如果发生解析或生成失败，外层程序会单独标记为“生成失败”；这里不要主动输出该词。\n"
        "5. 只输出 JSON，不要输出解释、不要输出 markdown。\n"
        "6. 输出结构必须是 {\"cells\": {\"35\": \"...\", \"40\": \"/\"}} 这种映射。\n"
    )
    raw_output = generate_fn(system_prompt, user_prompt)
    payload = parse_ca_cells_response(generate_fn, raw_output, interview_ids)
    return payload
