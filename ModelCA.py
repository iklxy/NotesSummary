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


def _normalize_ca_cells(raw_cells: Any, interview_ids: List[int]) -> Dict[str, str]:
    """
    归一化单元格映射。

    参数:
        raw_cells: 模型返回的 cells 字段。
        interview_ids: 需要输出的访谈 ID 列表。

    返回:
        统一为字符串键的单元格映射。
    """
    cells: Dict[str, str] = {str(i): "/" for i in interview_ids}
    if isinstance(raw_cells, dict):
        for key, value in raw_cells.items():
            interview_key = str(key)
            if interview_key in cells:
                text = str(value or "").strip()
                cells[interview_key] = text or "/"
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


def _normalize_ca_column_cells(raw_cells: Any, interview_ids: List[int]) -> Dict[str, str]:
    """
    归一化按问题列返回的单元格映射。
    """
    cells: Dict[str, str] = {str(i): "/" for i in interview_ids}
    if isinstance(raw_cells, dict):
        for key, value in raw_cells.items():
            interview_key = str(key)
            if interview_key not in cells:
                continue
            if isinstance(value, dict):
                text = str(value.get("value") or value.get("text") or "").strip()
            else:
                text = str(value or "").strip()
            cells[interview_key] = text or "/"
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
        "你的任务是针对同一个问卷问题，基于每个访谈对应的检索片段，分别输出各访谈的单元格内容。"
        "必须输出严格合法的 JSON，不要输出额外说明。"
    )
    user_prompt = (
        f"{project_context_block}"
        f"【问卷名称】\n{questionnaire_title}\n\n"
        f"【问题编号】\n{question_order}\n\n"
        f"【问题 ID】\n{question_uid}\n\n"
        f"【问题正文】\n{question_text}\n\n"
        + "\n\n".join(interview_lines)
        + "\n\n"
        "要求：\n"
        "1. 只基于对应访谈的片段总结，不要跨访谈串用信息。\n"
        "2. 如果该访谈没有相关内容，请填写 \"/\"。\n"
        "3. 如果信息明显不足但能看出该访谈有相关讨论，请用最简短的自然语言总结。\n"
        "4. 只输出 JSON，不要输出解释、不要输出 markdown。\n"
        "5. 输出结构必须是 {\"cells\": {\"35\": \"...\", \"40\": \"/\"}} 这种映射。\n"
    )
    raw_output = generate_fn(system_prompt, user_prompt)
    payload = parse_ca_column_cells_response(raw_output, interview_ids)
    return payload
