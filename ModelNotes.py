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
        "你是一名医学、药学、体外诊断和市场调研领域的访谈分析专家。"
        "你的任务是：针对单条 key BQ 抽取后续生成答案所需的分析维度。"
        "你必须只输出语法完全合法、可以被 json.loads 直接解析的 JSON。"
    )
    user_prompt = (
        f"{project_context_block}"
        f"{interview_context_block}"
        "下面是一条 key BQ，请你抽取 2 到 4 个适合后续生成 notes 的分析维度。"
        "维度应当是可操作的分析框架，而不是空泛标签。\n\n"
        f"【key BQ】\n{key_bq_text or '（未提供 key BQ）'}\n\n"
        "要求：\n"
        "1. 优先抽出能覆盖问题核心的 2 到 4 个维度；如果 key BQ 很窄，可以少于 2 个。\n"
        "2. 维度名称要简洁、明确、可用于后续检索和分段回答。\n"
        "3. 维度说明要指出该维度关注的具体信息点。\n"
        "4. 只输出 JSON，不要添加解释性文字。\n"
        "JSON 的参考结构如下：\n"
        "{\n"
        '  "dimensions": [\n'
        '    {"name": "疾病构成", "description": "关注患者疾病类型、构成和分布情况"},\n'
        '    {"name": "患者规模", "description": "关注患者规模、覆盖范围和病例量"}\n'
        "  ]\n"
        "}\n"
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
        "你是一名医学、药学、体外诊断和市场调研领域的访谈分析专家，"
        "负责根据 key BQ、分析维度和检索到的访谈片段生成结构化的 KBQ Notes。"
        "你必须严格基于给定的片段和维度，不要编造事实，并且必须输出语法完全合法、"
        "可以被 json.loads 直接解析的 JSON。"
    )
    user_prompt = (
        f"{project_context_block}"
        f"{interview_context_block}"
        "下面是一条 key BQ、已抽取的分析维度，以及相关访谈片段。请按照维度生成 KBQ Notes。\n\n"
        f"【key BQ】\n{key_bq_text or '（未提供 key BQ）'}\n\n"
        "【分析维度】\n"
        f"{dimensions_block}\n\n"
        "【相关访谈片段】\n"
        f"{context_block}\n\n"
        "要求：\n"
        "1. 只使用上述片段中的信息；如果某个维度没有原文证据，就不要输出该维度。\n"
        "2. summary 只写 1 到 3 句高度概括；analysis 负责更详细的分析。\n"
        "3. evidence 中尽量引用与该维度直接相关的原文短片段。\n"
        "4. 请给出一个 0 到 1 之间的置信度 confidence。\n"
        "5. 只输出 JSON，不要包含额外说明。\n"
        "JSON 的参考结构如下：\n"
        "{\n"
        '  "key_bq": "原始 key BQ",\n'
        '  "dimension_notes": [\n'
        '    {\n'
        '      "dimension": "疾病构成",\n'
        '      "summary": "一句话或几句话的概括",\n'
        '      "analysis": "更详细的分析和解释",\n'
        '      "evidence": [{"summary_id": 0, "speaker": "speaker1", "text": "与该维度直接相关的原文片段"}]\n'
        '    }\n'
        "  ],\n"
        '  "confidence": 0.0\n'
        "}\n"
    )
    content = generate_fn(system_prompt, user_prompt)
    return parse_kbq_notes_response(generate_fn, content)
