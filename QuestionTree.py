#!/usr/bin/env python3
"""
@Date: 2026-04-29
@Author: lixinyang

将问卷树展开为叶子问题列表。

该模块负责把 ``DocxToMd.py`` 生成的问卷 JSON 转成后续访谈创建流程
使用的最小问题格式：``uid / order / text / title``。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


def load_questionnaire_document(json_path: Path) -> Dict[str, Any]:
    """从磁盘加载已解析的问卷 JSON。

    参数:
        json_path: ``DocxToMd.py`` 生成的问卷 JSON 文件路径。

    返回:
        解析后的问卷文档字典。
    """

    if not json_path.exists():
        raise FileNotFoundError(f"questionnaire json not found: {json_path}")
    return json.loads(json_path.read_text(encoding="utf-8"))


def node_display_text(node: Dict[str, Any]) -> str:
    """将问卷树节点渲染为可见文本。

    参数:
        node: 包含 ``text`` 与可选 ``continuations`` 字段的树节点。

    返回:
        拼接后的节点文本。
    """

    text = str(node.get("text") or "").strip()
    continuations = [str(item).strip() for item in node.get("continuations", []) if str(item).strip()]
    if continuations:
        parts = [text] if text else []
        parts.extend(continuations)
        return " ".join(parts).strip()
    return text


def flatten_leaf_questions(
    nodes: List[Dict[str, Any]],
    *,
    title: str,
    domain_index: int,
    path_texts: List[str] | None = None,
    order_start: int = 1,
) -> Tuple[List[Dict[str, Any]], int]:
    """递归展开问题树，仅保留叶子节点。

    参数:
        nodes: 当前层级的树节点列表。
        title: 领域标题，会附加到每条输出的叶子问题上。
        domain_index: 从 0 开始的领域索引，用于生成稳定 UID。
        path_texts: 从根节点到当前节点父级的祖先问题文本路径。
        order_start: 当前子树的起始序号。

    返回:
        一个二元组：
        - DFS 顺序下的叶子问题列表
        - 处理完该子树后的下一个序号
    """

    flat_items: List[Dict[str, Any]] = []
    path_texts = list(path_texts or [])
    current_order = order_start

    for node in nodes:
        visible_text = node_display_text(node)
        if not visible_text:
            continue

        current_path = path_texts + [visible_text]
        question_text = " ".join(current_path).strip()
        children = node.get("children") or []
        if children:
            child_flat, current_order = flatten_leaf_questions(
                children,
                title=title,
                domain_index=domain_index,
                path_texts=current_path,
                order_start=current_order,
            )
            flat_items.extend(child_flat)
            continue

        flat_items.append(
            {
                "uid": f"d{domain_index + 1}_{current_order:04d}",
                "order": current_order,
                "text": question_text,
                "title": title,
            }
        )
        current_order += 1

    return flat_items, current_order


def expand_questionnaire_document(document: Dict[str, Any]) -> Dict[str, Any]:
    """将解析后的问卷文档展开为仅包含叶子问题的结果。

    参数:
        document: 包含 ``domains`` 树结构的问卷文档。

    返回:
        仅包含 ``flat_questions`` 的 JSON 兼容字典。
    """

    flat_questions: List[Dict[str, Any]] = []
    order_counter = 1

    for domain_index, domain in enumerate(document.get("domains", [])):
        title = str(domain.get("title") or "").strip()
        questions = domain.get("questions") or []
        domain_flat, order_counter = flatten_leaf_questions(
            questions,
            title=title,
            domain_index=domain_index,
            order_start=order_counter,
        )
        flat_questions.extend(domain_flat)

    return {"flat_questions": flat_questions}


def build_question_insert_rows(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    """将问卷 JSON 转换为可直接入库的问题行。

    参数:
        document: 包含 ``domains`` 树结构的问卷文档。

    返回:
        可直接传入 ``insert_questions_for_interview`` 的题目行列表。
    """

    expanded = expand_questionnaire_document(document)
    rows: List[Dict[str, Any]] = []
    for item in expanded.get("flat_questions", []):
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        rows.append(
            {
                "question_order": item.get("order"),
                "question_text": text,
                "question_type": "OPEN",
                "intent_id": 1,
                "research_phase": None,
                "meta": {
                    "source_kind": "auto",
                    "question_title": item.get("title"),
                    "question_path": item.get("question_path"),
                },
            }
        )
    return rows


def save_flat_questions_json(document: Dict[str, Any], out_path: Path) -> Dict[str, Any]:
    """将扁平化后的问题结果保存到磁盘。

    参数:
        document: 已解析的问卷文档。
        out_path: 目标 JSON 文件路径。

    返回:
        已保存的扁平问题结果。
    """

    payload = expand_questionnaire_document(document)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
