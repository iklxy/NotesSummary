"@Date: 2026-04-24"
"@Author: lixinyang"

import json
from typing import Any, Callable, Dict, List, Optional

from Fewshot import build_fewshot_prompt_block


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
        至少包含 `summary`、`analysis`、`evidence`、`confidence` 的字典。
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
        "2. 如果信息不足以回答问题，请在 summary 和 analysis 中明确说明“当前访谈中信息不足”。\n"
        "3. 请给出一个 0 到 1 之间的置信度 confidence。\n"
        "4. 输出时只返回 JSON，不要包含额外说明。\n"
        "JSON 的参考结构如下:\n"
        "{\n"
        '  "summary": "一句话或几句话的高度概括",\n'
        '  "analysis": "更详细的分析和解释，适合写入研究笔记",\n'
        '  "evidence": [{"summary_id": 0, "speaker": "speaker1", "text": "与结论直接相关的原文片段"}],\n'
        '  "confidence": 0.0\n'
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
        "2. 如果信息不足以回答问题，请在 summary 和 analysis 中明确说明“当前访谈中信息不足”。\n"
        "3. summary 只写 1 到 3 句高度概括；analysis 负责更详细的解释。\n"
        "4. 请给出一个 0 到 1 之间的置信度 confidence。\n"
        "5. evidence 中尽量引用与结论直接相关的原文短片段。\n"
        "6. 输出时只返回 JSON，不要包含额外说明。\n"
        "JSON 的参考结构如下:\n"
        "{\n"
        '  "summary": "一句话或几句话的高度概括",\n'
        '  "analysis": "更详细的分析和解释，适合写入研究笔记",\n'
        '  "evidence": [{"summary_id": 0, "speaker": "speaker1", "text": "与结论直接相关的原文片段"}],\n'
        '  "confidence": 0.0\n'
        "}\n"
    )
    fewshot_block = build_fewshot_prompt_block(fewshot_samples)
    user_prompt = f"{fewshot_block}\n\n{base_user_prompt}" if fewshot_block else base_user_prompt
    return parse_notes_response(generate_fn, generate_fn(system_prompt, user_prompt))
