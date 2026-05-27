#!/usr/bin/env python3
"""
@Date: 2026-05-08
@Author: lixinyang

CA 表格生成所需的大模型提示词与解析逻辑。

该模块只负责：
1. 从多份全文 Notes Markdown 中抽取稳定的对比维度；
2. 基于单个维度小点与各访谈片段生成单元格内容。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from ModelTranscript import parse_json_payload


def _strip_code_fences(text: str) -> str:
    """
    去除模型输出中的代码块包裹。

    参数:
        text: 原始输出文本。

    返回:
        去除 ``` 包裹后的文本。
    """
    content = text.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(line for line in lines if not line.strip().startswith("```")).strip()
    return content


def _parse_json_response(content: str) -> Optional[Dict[str, Any]]:
    """
    解析模型输出的 JSON 字符串。

    参数:
        content: 模型原始输出文本。

    返回:
        解析成功则返回字典，否则返回 None。
    """
    content = _strip_code_fences(content)
    try:
        return json.loads(content)
    except Exception:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(content[start : end + 1])
            except Exception:
                return None
    return None


def _normalize_ca_dimensions(raw_dimensions: Any) -> List[Dict[str, Any]]:
    """
    归一化维度列表。

    参数:
        raw_dimensions: 模型返回的 dimensions 原始内容。

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
                sub_title = str(sub.get("title") or sub.get("name") or sub.get("dimension") or "").strip()
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


def parse_ca_dimensions_response(content: str) -> Dict[str, Any]:
    """
    解析 CA 维度抽取的模型输出。

    参数:
        content: 模型原始输出文本。

    返回:
        标准化后的字典，至少包含 dimensions。
    """
    payload = _parse_json_response(content)
    if not isinstance(payload, dict):
        payload = {"dimensions": [], "llm_raw_output": content}
    payload["dimensions"] = _normalize_ca_dimensions(payload.get("dimensions"))
    payload.setdefault("llm_raw_output", content)
    return payload


def _normalize_ca_evidence(raw_evidence: Any) -> List[str]:
    """
    归一化证据列表。
    """
    if isinstance(raw_evidence, str):
        text = raw_evidence.strip()
        return [text] if text else []
    if not isinstance(raw_evidence, list):
        return []
    evidence: List[str] = []
    for item in raw_evidence:
        text = str(item or "").strip()
        if text:
            evidence.append(text)
    return evidence[:3]


def _normalize_ca_cell(raw_cell: Any) -> Dict[str, Any]:
    """
    归一化单个 CA 单元格。
    """
    if isinstance(raw_cell, dict):
        answer = str(raw_cell.get("answer") or raw_cell.get("value") or raw_cell.get("text") or "").strip()
        evidence = _normalize_ca_evidence(raw_cell.get("evidence") or raw_cell.get("sources") or raw_cell.get("quotes"))
        locked = bool(raw_cell.get("locked"))
        source = str(raw_cell.get("source") or "framework")
        numeric_value_raw = raw_cell.get("numeric_value")
        if numeric_value_raw is None:
            numeric_value_raw = raw_cell.get("numericValue")
        numeric_value: Optional[float] = None
        if isinstance(numeric_value_raw, (int, float)):
            numeric_value = float(numeric_value_raw)
        elif isinstance(numeric_value_raw, str):
            numeric_text = numeric_value_raw.strip()
            if numeric_text:
                try:
                    numeric_value = float(numeric_text)
                except Exception:
                    numeric_value = None
        return {
            "value": answer or "/",
            "evidence": evidence,
            "locked": locked,
            "source": source,
            "numeric_value": numeric_value,
        }
    text = str(raw_cell or "").strip()
    return {
        "value": text or "/",
        "evidence": [],
        "locked": False,
        "source": "framework",
        "numeric_value": None,
    }


def _normalize_ca_cells(raw_cells: Any, interview_ids: List[int]) -> Dict[str, Dict[str, Any]]:
    """
    归一化单元格映射。

    参数:
        raw_cells: 模型返回的 cells 字段。
        interview_ids: 需要输出的访谈 ID 列表。

    返回:
        统一为字符串键的单元格映射。
    """
    cells: Dict[str, Dict[str, Any]] = {str(i): _normalize_ca_cell(None) for i in interview_ids}
    if isinstance(raw_cells, dict):
        for key, value in raw_cells.items():
            interview_key = str(key)
            if interview_key in cells:
                cells[interview_key] = _normalize_ca_cell(value)
    return cells


def parse_ca_cells_response(content: str, interview_ids: List[int]) -> Dict[str, Any]:
    """
    解析 CA 单元格填充结果。

    参数:
        content: 模型原始输出文本。
        interview_ids: 需要填充的访谈 ID 列表。

    返回:
        至少包含 cells 的字典。
    """
    payload = _parse_json_response(content)
    if not isinstance(payload, dict):
        payload = {"cells": _normalize_ca_cells(None, interview_ids), "llm_raw_output": content}
    payload["cells"] = _normalize_ca_cells(payload.get("cells"), interview_ids)
    payload.setdefault("llm_raw_output", content)
    return payload


def _normalize_ca_column_cells(raw_cells: Any, interview_ids: List[int]) -> Dict[str, Dict[str, Any]]:
    """
    归一化按问题列返回的单元格映射。
    """
    cells: Dict[str, Dict[str, Any]] = {str(i): _normalize_ca_cell(None) for i in interview_ids}
    if isinstance(raw_cells, dict):
        for key, value in raw_cells.items():
            interview_key = str(key)
            if interview_key not in cells:
                continue
            cells[interview_key] = _normalize_ca_cell(value)
    return cells


def parse_ca_column_cells_response(content: str, interview_ids: List[int]) -> Dict[str, Any]:
    """
    解析按问题列生成的单元格结果。
    """
    payload = _parse_json_response(content)
    if not isinstance(payload, dict):
        payload = {"cells": _normalize_ca_column_cells(None, interview_ids), "llm_raw_output": content}
    payload["cells"] = _normalize_ca_column_cells(payload.get("cells"), interview_ids)
    payload.setdefault("llm_raw_output", content)
    return payload


def _normalize_ca_diff_cells(raw_cells: Any, interview_ids: List[int]) -> Dict[str, Dict[str, Any]]:
    """
    归一化差异行单元格映射。
    """
    return _normalize_ca_column_cells(raw_cells, interview_ids)


def parse_ca_diff_row_response(content: str, interview_ids: List[int]) -> Dict[str, Any]:
    """
    解析 CA 差异行结果。
    """
    payload = _parse_json_response(content)
    if not isinstance(payload, dict):
        payload = {"diff_row": _normalize_ca_diff_cells(None, interview_ids), "llm_raw_output": content}
    payload["diff_row"] = _normalize_ca_diff_cells(payload.get("diff_row"), interview_ids)
    payload.setdefault("llm_raw_output", content)
    return payload


def _normalize_ca_row_summary(raw_summary: Any) -> Dict[str, Any]:
    """
    归一化 CA 行总结结果。
    """
    summary = ""
    if isinstance(raw_summary, dict):
        summary = str(
            raw_summary.get("summary")
            or raw_summary.get("summary_text")
            or raw_summary.get("text")
            or raw_summary.get("answer")
            or ""
        ).strip()
    elif isinstance(raw_summary, str):
        summary = raw_summary.strip()
    if not summary:
        summary = "/"
    return {"summary": summary}


def parse_ca_row_summary_response(content: str) -> Dict[str, Any]:
    """
    解析 CA 行总结结果。
    """
    payload = _parse_json_response(content)
    if not isinstance(payload, dict):
        payload = {"summary": "/", "llm_raw_output": content}
    payload.update(_normalize_ca_row_summary(payload))
    payload.setdefault("llm_raw_output", content)
    return payload


def _normalize_ca_question_display_texts(
    raw_questions: Any,
    fallback_questions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    规范化模型返回的精简问题列表。
    """
    display_by_uid: Dict[str, str] = {}
    if isinstance(raw_questions, list):
        for item in raw_questions:
            if not isinstance(item, dict):
                continue
            uid = str(item.get("uid") or item.get("question_uid") or item.get("column_id") or "").strip()
            if not uid:
                continue
            display_text = str(
                item.get("display_text")
                or item.get("simplified_text")
                or item.get("question_text")
                or item.get("text")
                or ""
            ).strip()
            if display_text:
                display_by_uid[uid] = display_text

    normalized: List[Dict[str, Any]] = []
    for index, question in enumerate(fallback_questions, start=1):
        if not isinstance(question, dict):
            continue
        uid = str(question.get("uid") or question.get("question_uid") or question.get("column_id") or "").strip()
        if not uid:
            uid = f"q{index:04d}"
        original_text = str(question.get("text") or question.get("question_text") or "").strip()
        display_text = display_by_uid.get(uid)
        if not display_text:
            continue
        normalized.append(
            {
                "uid": uid,
                "order": int(question.get("order") or index),
                "question_text": original_text,
                "display_text": display_text or original_text,
                "title": str(question.get("title") or "").strip(),
            }
        )
    return normalized


def parse_ca_question_display_texts_response(
    content: str,
    fallback_questions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    解析 CA 问题精简结果。
    """
    payload = _parse_json_response(content)
    if not isinstance(payload, dict):
        payload = {"questions": [], "llm_raw_output": content}
    payload["questions"] = _normalize_ca_question_display_texts(payload.get("questions"), fallback_questions)
    payload.setdefault("llm_raw_output", content)
    return payload


def generate_ca_dimensions(
    generate_fn: Callable[[str, str], str],
    project_context_block: str,
    interviews_notes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    基于多份全文 Notes Markdown 生成 CA 的维度与小点骨架。

    参数:
        generate_fn: 实际执行 LLM 调用的函数。
        project_context_block: 已格式化好的项目背景块。
        interviews_notes: 多访谈全文 Notes 列表，每项应包含 interview_id、name、notes_markdown。

    返回:
        标准化后的 CA 维度字典。
    """
    interview_blocks: List[str] = []
    for item in interviews_notes:
        interview_id = item.get("interview_id")
        name = str(item.get("name") or f"访谈 {interview_id}").strip()
        notes_markdown = str(item.get("notes_markdown") or "").strip()
        if not notes_markdown:
            continue
        interview_blocks.append(
            f"【访谈 {interview_id} | {name}】\n{notes_markdown}"
        )
    notes_block = "\n\n".join(interview_blocks)

    system_prompt = (
        "你是专业的医疗咨询行业对比分析专家。"
        "你的任务是根据多份访谈全文 Notes Markdown，生成一张可跨访谈对比的 CA 表格骨架。"
        "必须输出严格合法的 JSON，不要输出额外说明。"
    )
    user_prompt = (
        f"{project_context_block}"
        "下面给出多份访谈的全文 Notes Markdown，请你生成用于 CA 表格的稳定对比维度。\n\n"
        f"{notes_block}\n\n"
        "要求：\n"
        "1. 维度必须稳定、可跨访谈比较，不要依赖某一位医生的个体化表述。\n"
        "2. 维度数量控制在 3 到 6 个，每个维度下设置 2 到 4 个小点。\n"
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
    payload = parse_ca_dimensions_response(raw_output)
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
            "2. 维度数量 3 到 5 个。\n"
            "3. 每个维度 2 到 3 个小点。\n"
            "4. 不要输出任何解释文字。\n\n"
            f"{notes_block}\n"
        )
        retry_raw_output = generate_fn(retry_system_prompt, retry_user_prompt)
        retry_payload = parse_ca_dimensions_response(retry_raw_output)
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

    参数:
        generate_fn: 实际执行 LLM 调用的函数。
        project_context_block: 已格式化好的项目背景块。
        dimension_title: 维度标题。
        dimension_summary: 维度概述。
        sub_point_title: 小点标题。
        sub_point_summary: 小点概述。
        interview_blocks: 每个访谈的输入块，至少包含 interview_id、name、segments。

    返回:
        标准化后的 cells 映射。
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
                segment_lines.append(f"[{seg_index}] summary_id={sid} speaker={speaker} score={float(score or 0.0):.4f}\n{text}")
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
    payload = parse_ca_cells_response(raw_output, interview_ids)
    return payload


def generate_ca_cells_for_question(
    generate_fn: Callable[[str, str], str],
    project_context_block: str,
    questionnaire_title: str,
    question_uid: str,
    question_order: int,
    question_text: str,
    interview_blocks: List[Dict[str, Any]],
    question_type: str = "qualitative",
) -> Dict[str, Any]:
    """
    为某一个问卷叶子问题批量生成各访谈单元格内容。
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
        source_text = str(item.get("source_text") or "").strip()
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
                segment_lines.append(f"[{seg_index}] summary_id={sid} speaker={speaker} score={float(score or 0.0):.4f}\n{text}")
        if not segment_lines:
            if source_text:
                segment_lines.append(source_text)
            else:
                segment_lines.append("（当前没有检索到相关片段）")
        meta_text = json.dumps(meta, ensure_ascii=False) if isinstance(meta, dict) else str(meta or "")
        interview_lines.append(
            f"【访谈 {interview_id} | {name}】\n【访谈元数据】\n{meta_text}\n\n【相关片段】\n"
            + "\n\n".join(segment_lines)
        )

    system_prompt = (
        "你是专业的医疗咨询行业对比分析专家。"
        "你的任务是针对同一个问卷问题，基于每个访谈提供的全文 Notes 或相关片段，分别输出各访谈的简短答案和原文引用。"
        "必须输出严格合法的 JSON，不要输出额外说明。"
    )
    normalized_question_type = str(question_type or "qualitative").strip().lower()
    if normalized_question_type not in {"qualitative", "quantitative"}:
        normalized_question_type = "qualitative"
    user_prompt = (
        f"{project_context_block}"
        f"【问卷名称】\n{questionnaire_title}\n\n"
        f"【问题编号】\n{question_order}\n\n"
        f"【问题 ID】\n{question_uid}\n\n"
        f"【问题类型】\n{normalized_question_type}\n\n"
        f"【问题正文】\n{question_text}\n\n"
        + "\n\n".join(interview_lines)
        + "\n\n"
        "要求：\n"
        "1. 只基于对应访谈的片段总结，不要跨访谈串用信息。\n"
        "2. 答案要尽量简短，直击关键点，优先 1 句，必要时 2 句，避免冗长解释。\n"
        "3. 如果问题类型是 quantitative，答案必须极简，只输出数字结论，不要写解释性完整句。\n"
        "   - 优先保留百分比、人数、例数、均值、中位数、范围等明确数值。\n"
        "   - answer 使用 bullet points 风格的短句；每个 bullet 只表达一个核心数据。\n"
        "   - 数值输出格式：单一数值用 \"- 40%\"；存在补充/下属数值时用 \"- 40%（其中非共价 0%）\"。\n"
        "   - 如果原文只提供一个核心数值，输出格式为：\"- 40%\"、\"- 5 例\"。\n"
        "   - 如果原文同时提供主数据和其下属/补充数据，必须合并到同一个 bullet 中，格式为：\"- 40%（其中非共价 0%）\"。\n"
        "   - 不得在存在补充数据时只输出主数据，例如原文同时提到 BTKi 单药 40%、非共价 BTKi 0%，不得只输出 \"- 40%\"。\n"
        "   - 括号中的补充数据包括但不限于：其中、分别、具体为、非共价、共价、联合、单药、不同亚组、不同线数、不同药物类型等。\n"
        "   - 如果同一访谈中有多个并列数据，分成多个 bullet，每行一个数据。\n"
        "   - 如果某个主数据下面有补充数据，补充数据放在括号中。\n"
        "   - 不要重复问题中的主体名称，除非不写会导致数据含义不清。\n"
        "   - 不要添加原文没有明确表达的单位、分母、解释或推断。\n"
        "   - numeric_value 填最核心主数值；如果是百分比，填百分号前的数字，例如 40% 填 40。\n"
        "   - 如果有多个同等重要的数字，numeric_value 填最贴合问题正文的主数字；无法确定主数字时设为 null。\n"
        "   - 如果无法确认明确数字，numeric_value 设为 null。\n"
        "   - 示例：\n"
        "     问题：初治CLL BTKi单药治疗占比\n"
        "     错误输出：\"1L CLL BTKi单药使用率为40%，其中非共价BTKi使用率为0%\"\n"
        "     正确输出：\"- 40%（其中非共价 0%）\"\n"
        "4. 如果问题类型是 qualitative，答案必须精简概括，避免冗长分析。\n"
        "   - 优先用一句话概括核心结论；如果一句话可以清楚表达，就不要拆分 bullet。\n"
        "   - 整体风格要求精简、只留核心、能够快速浏览、极简、无冗余。\n"
        "   - 不输出口语、修饰、废话"
        "   - 如果内容包含多个并列观点、多个影响因素、多个治疗路径或多个判断标准，才使用精简 bullet points。\n"
        "   - 使用 bullet points 时，每个 bullet 只表达一个核心观点，避免展开解释。\n"
        "   - bullet 数量通常控制在 1 到 3 条，除非原文信息确实更多且都与问题直接相关。\n"
        "   - 不要复述问题本身，不要添加背景介绍，不要写推理过程。\n"
        "   - 不要加入原文没有明确表达的判断、原因、结论或行业常识。\n"
        "   - bullet points 风格的短句：一句话精简，要求能够快速浏览、极简、无冗余。\n"
        "   - 示例：\n"
        "     问题：医生选择BTKi治疗时主要考虑哪些因素？\n"
        "     原文信息：主要看患者年龄、合并症和心血管风险。\n"
        "     正确输出：\"患者年龄、合并症和心血管风险。\"\n"
        "   - 示例：\n"
        "     问题：围术期治疗路径的关键决策节点是什么？\n"
        "     原文信息：先看分期，再看是否可手术，还会结合PD-L1和ctDNA结果。\n"
        "     正确输出：\"- 分期和可手术性\\n- PD-L1检测结果\\n- ctDNA检测结果\"\n"
        "5. 每个访谈必须额外给出 2 到 3 条原文引用，引用内容尽量直接摘自下方文本，不要自行改写。\n"
        "6. 不要输出任何定位信息，例如段落号、summary_id、页码等；只展示引用文本本身。\n"
        "7. 如果该访谈没有相关内容，引用数组写空数组，numeric_value 设为 null。\n"
        "8. 只输出 JSON，不要输出解释、不要输出 markdown。\n"
        "9. 输出结构必须是 {\"cells\": {\"35\": {\"answer\": \"...\", \"evidence\": [\"...\", \"...\"], \"numeric_value\": 12.5}}} 这种映射。\n"
    )
    raw_output = generate_fn(system_prompt, user_prompt)
    payload = parse_ca_column_cells_response(raw_output, interview_ids)
    return payload


def generate_ca_diff_row_for_interviews(
    generate_fn: Callable[[str, str], str],
    project_context_block: str,
    questionnaire_title: str,
    questions: List[Dict[str, Any]],
    interview_blocks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    为每个访谈生成“问卷未提及但访谈提到”的差异行内容。
    """
    if not interview_blocks:
        return {"diff_row": {}}

    def _has_meaningful_diff_row(diff_row: Dict[str, Any], interview_ids: List[int]) -> bool:
        for interview_id in interview_ids:
            payload = _normalize_ca_cell(diff_row.get(str(interview_id)))
            value = str(payload.get("value") or "").strip()
            if value and value != "/":
                return True
        return False

    question_lines: List[str] = []
    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            continue
        uid = str(question.get("uid") or question.get("question_uid") or question.get("column_id") or "").strip()
        text = str(question.get("text") or question.get("question_text") or "").strip()
        display_text = str(question.get("display_text") or "").strip()
        title = str(question.get("title") or "").strip()
        if not uid and not text and not display_text:
            continue
        question_lines.append(
            f"[{index}] uid={uid}\n"
            f"标题：{title or '（无）'}\n"
            f"问卷问题：{text or '（空）'}\n"
            f"展示文案：{display_text or text or '（空）'}"
        )

    interview_lines: List[str] = []
    interview_ids: List[int] = []
    for item in interview_blocks:
        interview_id = int(item.get("interview_id") or 0)
        interview_ids.append(interview_id)
        name = str(item.get("name") or f"访谈 {interview_id}").strip()
        meta = item.get("meta") or {}
        source_text = str(item.get("source_text") or "").strip()
        meta_text = json.dumps(meta, ensure_ascii=False) if isinstance(meta, dict) else str(meta or "")
        interview_lines.append(
            f"【访谈 {interview_id} | {name}】\n【访谈元数据】\n{meta_text}\n\n【相关片段】\n"
            + (source_text or "（当前没有全文 trans）")
        )

    system_prompt = (
        "你是专业的医疗咨询行业对比分析专家。"
        "你的任务是严格对比每个访谈的全文 trans 与该 CA 所用的 DG 问卷。"
        "只抽取“全文中明确出现、但问卷中没有明确提及”的内容，作为 CA 最后一行。"
        "必须输出严格合法的 JSON，不要输出额外说明。"
    )
    user_prompt = (
        f"{project_context_block}"
        f"【问卷名称】\n{questionnaire_title}\n\n"
        "下面先给出当前问卷问题列表，再给出每个访谈的全文 trans。\n"
        "你的任务不是总结全文，而是找出全文里出现、但问卷没有问到的差异内容。\n\n"
        f"【当前问卷问题】\n{chr(10).join(question_lines) or '（无）'}\n\n"
        + "\n\n".join(interview_lines)
        + "\n\n"
        "要求：\n"
        "1. 先判断全文 trans 中有哪些内容没有被当前问卷覆盖。\n"
        "2. 只输出真正的差异内容，不要把问卷里已经明确出现过的内容重复写进来。\n"
        "3. 每个访谈输出 1 到 3 条最有信息量的差异内容，必须使用分点格式输出。\n"
        "   - 每一个 bullet 代表一个独立差异点。\n"
        "   - 每个差异点要尽量短，但必须具体，不能只写泛泛概括。\n"
        "   - answer 字段是字符串，可以用换行符表示多个 bullet，例如：\"- 差异点1\\n- 差异点2\"。\n"
        "   - 如果只有 1 条差异内容，也必须写成 1 个 bullet，例如：\"- 差异点1\"。\n"
        "   - 不要把多个差异点合并成一个长句。\n"
        "4. 仍然给出 2 到 3 条原文引用，引用必须直接来自全文 trans，不要改写。\n"
        "5. 不要输出任何定位信息，例如段落号、summary_id、页码等；只展示引用文本本身。\n"
        "6. 如果该访谈全文里确实没有任何问卷未提及的内容，答案写 \"/\"，引用数组写空数组。\n"
        "7. 只输出 JSON，不要输出解释、不要输出 markdown。\n"
        "8. 输出结构必须是 {\"diff_row\": {\"35\": {\"answer\": \"...\", \"evidence\": [\"...\", \"...\"]}}} 这种映射。\n"
    )
    raw_output = generate_fn(system_prompt, user_prompt)
    payload = parse_ca_diff_row_response(raw_output, interview_ids)
    if not _has_meaningful_diff_row(payload.get("diff_row") or {}, interview_ids):
        retry_system_prompt = (
            "你是专业的医疗咨询行业对比分析专家。"
            "上一轮输出过于保守，很多访谈被错误地写成了空值。"
            "请重新严格对比每个访谈全文 trans 与该 CA 所用的 DG 问卷，主动识别全文中问卷没有覆盖但明确出现的具体信息。"
            "必须输出严格合法的 JSON，不要输出额外说明。"
        )
        retry_user_prompt = (
            f"{project_context_block}"
            f"【问卷名称】\n{questionnaire_title}\n\n"
            "请重新做一次“全文 trans vs 问卷”的差异比对。\n"
            "判断标准：只要全文里出现了问卷没有明确提到的具体诊疗细节、用药细节、流程细节、患者特征、比例、偏好、障碍、经验总结，就可以作为差异内容输出。\n"
            "不要因为内容和问卷主题接近就忽略它；只要问卷没有明确问到，就算差异内容。\n\n"
            f"【当前问卷问题】\n{chr(10).join(question_lines) or '（无）'}\n\n"
            + "\n\n".join(interview_lines)
            + "\n\n"
            "要求：\n"
            "1. 每个访谈都重新独立判断，不要跨访谈串用。\n"
            "2. 每个访谈输出 1 到 3 条差异内容，尽量具体。\n"
            "3. 原文引用必须来自全文 trans。\n"
            "4. 如果确实没有差异内容，才输出 \"/\"。\n"
            "5. 只输出 JSON，不要输出解释、不要输出 markdown。\n"
            "6. 输出结构必须是 {\"diff_row\": {\"35\": {\"answer\": \"...\", \"evidence\": [\"...\", \"...\"]}}} 这种映射。\n"
        )
        retry_raw_output = generate_fn(retry_system_prompt, retry_user_prompt)
        retry_payload = parse_ca_diff_row_response(retry_raw_output, interview_ids)
        if _has_meaningful_diff_row(retry_payload.get("diff_row") or {}, interview_ids):
            payload = retry_payload
    return payload


def generate_ca_row_summary_for_question(
    generate_fn: Callable[[str, str], str],
    project_context_block: str,
    questionnaire_title: str,
    question_uid: str,
    question_order: int,
    question_text: str,
    question_type: str,
    question_group: str,
    question_group_summary: str,
    interview_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    基于同一问题行的全部访谈答案生成整行总结。
    """
    if not interview_rows:
        return {"summary": "/"}

    answer_lines: List[str] = []
    has_meaningful_answer = False
    for index, item in enumerate(interview_rows, start=1):
        interview_id = int(item.get("interview_id") or 0)
        name = str(item.get("name") or f"访谈 {interview_id}").strip()
        answer = str(item.get("answer") or "").strip()
        evidence = item.get("evidence") or []
        numeric_value = item.get("numeric_value")
        source = str(item.get("source") or "").strip()
        if answer and answer != "/":
            has_meaningful_answer = True
        evidence_text = "/"
        if isinstance(evidence, list) and evidence:
            evidence_text = "\n".join(
                f"- {str(line or '').strip()}" for line in evidence if str(line or "").strip()
            ) or "/"
        answer_lines.append(
            f"[{index}] 访谈 {interview_id} | {name}\n"
            f"回答：{answer or '/'}\n"
            f"数值：{numeric_value if numeric_value is not None else '/'}\n"
            f"来源：{source or '/'}\n"
            f"引用：\n{evidence_text}"
        )

    if not has_meaningful_answer:
        return {"summary": "/"}

    normalized_question_type = str(question_type or "qualitative").strip().lower()
    if normalized_question_type not in {"qualitative", "quantitative"}:
        normalized_question_type = "qualitative"

    system_prompt = (
    "你是专业的医疗咨询行业对比分析专家。"
    "你的任务是根据同一问题下各访谈的回答，生成一条适合放在 CA 表格总结列里的行级总结。"
    "总结必须体现各访谈观点的分布情况，包括多少个访谈支持某类观点，以及该观点的关键细节。"
    "必须输出严格合法的 JSON，不要输出额外说明。"
)

    user_prompt = (
    f"{project_context_block}"
    f"【问卷名称】\n{questionnaire_title}\n\n"
    f"【问题编号】\n{question_order}\n\n"
    f"【问题 ID】\n{question_uid}\n\n"
    f"【问题类型】\n{normalized_question_type}\n\n"
    f"【问题标题】\n{question_text}\n\n"
    f"【主题分组】\n{question_group or '（无）'}\n\n"
    f"【主题说明】\n{question_group_summary or '（无）'}\n\n"
    + "\n\n".join(answer_lines)
    + "\n\n"
    "要求：\n"
    "1. 只能基于这一行里各访谈的回答进行总结，不要回到全文 trans，也不要新增未给出的事实。\n"
    "2. 如果这一行所有访谈都没有有效答案，或都只是 \"/\"，请直接输出 \"/\"。\n"
    "3. 总结要围绕“各访谈观点汇总”展开，而不是逐访谈罗列。\n"
    "4. 需要先识别不同访谈回答中的主要观点类型，将含义相近的回答归为同一类观点。\n"
    "5. 对每一类观点，必须写明该类观点覆盖的访谈数量，格式固定为“x/y:观点，认为xxx”。\n"
    "6. x 表示支持该类观点的有效访谈数，y 表示该行中有有效答案的访谈总数；只统计非空、非“/”的有效答案。\n"
    "7. 比例后的内容必须精简干练，只保留最核心观点和 1 个关键细节，避免解释性长句。\n"
    "8. 如果存在少数不同观点，也要单独输出一条，例如“1/5:认为xxx”。\n"
    "9. 不要机械罗列每个访谈编号，不要写成“访谈1认为、访谈2认为……”。\n"
    "10. 多类观点之间用中文分号“；”分隔，不要使用 markdown 列表。\n"
    "11. 如果存在少数不同观点，也要单独输出一条，例如“1/5:支付能力优先，关注药物可及性”。\n"
    "12. 不要机械罗列每个访谈编号，不要写成“访谈1认为、访谈2认为……”。\n"
    "13. 定量问题总结可按数值区间或结论倾向聚类，例如：\"3/5:集中在30%-40%，认为该比例处于较高水平；2/5:低于20%，认为实际使用仍有限。\"；不要重复统计列中已经计算好的复杂统计结果。\n"
    "14. 总结控制在 1 到 2 句，尽量短而直接。\n"
    "15. 一句总结一行，不要连续书写，清晰区分。\n"
    "16. 不要输出引用、不要输出列表、不要输出 markdown。\n"
    "17. 只输出 JSON，结构必须是 {\"summary\": \"...\"}。\n"
    "18. 输出示例：\n"
   "    {\"summary\": \"4/5:疗效安全性优先，影响治疗选择；1/5:支付可及性优先，影响用药决策。\"}\n"
)
    raw_output = generate_fn(system_prompt, user_prompt)
    payload = parse_ca_row_summary_response(raw_output)
    summary = str(payload.get("summary") or "").strip()
    payload["summary"] = summary or "/"
    return payload


def generate_ca_question_display_texts(
    generate_fn: Callable[[str, str], str],
    project_context_block: str,
    questionnaire_title: str,
    questions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    为一组问卷问题生成精简后的展示文案。
    """
    if not questions:
        return {"questions": []}

    question_lines: List[str] = []
    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            continue
        uid = str(question.get("uid") or question.get("question_uid") or question.get("column_id") or "").strip()
        order = int(question.get("order") or index)
        title = str(question.get("title") or "").strip()
        question_text = str(question.get("text") or question.get("question_text") or "").strip()
        question_lines.append(
            f"[{order}] uid={uid}\n"
            f"标题：{title or '（无）'}\n"
            f"原问题：{question_text or '（空）'}"
        )

    system_prompt = (
        "你是专业的医疗咨询问卷文案精简专家。"
        "你的任务是把问卷中的每一条原问题压缩成更短、更适合在 CA 矩阵中展示的精简版问题。"
        "必须输出严格合法的 JSON，不要输出额外说明。"
    )
    user_prompt = (
        f"{project_context_block}"
        f"【问卷名称】\n{questionnaire_title}\n\n"
        "请将下面的每条原问题改写为更短的展示版本，但必须保持原意不变。\n"
        "注意：很多题目前面的【】内容只是主题/标签/章节名，不是问题本体，改写时要直接去掉，不要出现在展示文案里。\n"
        "同时把“您”“请”“请问”“您认为”“您的”等问卷提问话术尽量删掉，只保留问题的核心信息。\n"
        "如果某一项明显不是问题本体，而是系统解析残留、流程提示、章节标题、出示视卡、项目名称、访谈说明等内容，不要输出这一项。\n"
        "你需要自己判断哪些条目是真实问题，哪些条目只是结构或残留；只输出真实问题，不要把非问题内容改写成问题。\n"
        "展示文案优先用陈述式标题，不要刻意写成疑问句；如果原问题是问句，改写后也尽量转成陈述式表达，不要保留问号。\n\n"
        "严格要求：\n"
        "1. 只能做压缩表达，不得改变语义。\n"
        "2. 不得新增问题，不得合并问题，不得拆分问题。\n"
        "3. 不得删掉限定词、对象、时间范围、条件、比较对象等关键信息。\n"
        "4. 如果某条并非真正的问题，直接不输出该条，不要硬改成问题。\n"
        "5. 必须保留 uid 对应关系，输出顺序应与输入一致。\n"
        "6. 只输出 JSON，不要输出解释、不要输出 markdown。\n\n"
        "示例：\n"
        "原问题：\n"
        "【围术期决策逻辑】II/III期需围术期治疗的UC患者，您的决策逻辑是什么？哪些关键节点决定治疗路径选择？不同检测结果的患者占比多少？\n"
        "精简后：\n"
        "II/III期需围术期治疗的UC患者，如何决策治疗路径？关键节点和不同检测结果占比如何？\n\n"
        "原问题：\n"
        "如何评估DMT药物治疗效果？低效、高效药物表现如何？满意度如何？\n"
        "精简后：\n"
        "评估DMT药物治疗效果的方法，低效高效药物的表现以及满意度\n\n"
        "原问题：\n"
        "（出示视卡按表格填写）指定时段内科室在治MS、NMOSD患者数各多少？MS、NMOSD患者中初诊、随访治疗患者比例？第二部分：诊断流程\n"
        "精简后：\n"
        "指定时段内科室在治MS、NMOSD患者数及初诊、随访治疗患者比例\n\n"
        "原问题：\n"
        "S Market Understanding\n"
        "精简后：\n"
        "（不输出）\n\n"
        "输出结构必须是：\n"
        "{\n"
        '  "questions": [\n'
        "    {\n"
        '      "uid": "d1_0001",\n'
        '      "display_text": "精简后的展示问题"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "【待精简问题】\n"
        + "\n\n".join(question_lines)
        + "\n\n"
        "请仅返回合法 JSON。"
    )
    raw_output = generate_fn(system_prompt, user_prompt)
    return parse_ca_question_display_texts_response(raw_output, questions)
