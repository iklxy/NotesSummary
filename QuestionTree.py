#!/usr/bin/env python3
"""Expand parsed questionnaire trees into flat leaf questions.

This module converts the questionnaire JSON produced by ``DocxToMd.py`` into
the minimal question format used by the interview creation flow:
``uid / order / text / title``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


def load_questionnaire_document(json_path: Path) -> Dict[str, Any]:
    """Load a parsed questionnaire JSON document from disk.

    Parameters:
        json_path: Path to the questionnaire JSON produced by ``DocxToMd.py``.

    Returns:
        Parsed questionnaire document.
    """

    if not json_path.exists():
        raise FileNotFoundError(f"questionnaire json not found: {json_path}")
    return json.loads(json_path.read_text(encoding="utf-8"))


def node_display_text(node: Dict[str, Any]) -> str:
    """Render a questionnaire tree node into visible text.

    Parameters:
        node: Tree node with ``text`` and optional ``continuations`` fields.

    Returns:
        Concatenated node text.
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
    """Flatten a recursive question tree and keep only leaf nodes.

    Parameters:
        nodes: Current layer tree nodes.
        title: Domain title to attach to every emitted leaf question.
        domain_index: Zero-based domain index used to build stable UIDs.
        path_texts: Ancestor question texts from root to the parent node.
        order_start: Starting order number for the current subtree.

    Returns:
        A tuple of:
        - leaf question rows in DFS order
        - next order counter after processing this subtree
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
    """Expand a parsed questionnaire document into flat questions only.

    Parameters:
        document: Parsed questionnaire document with a ``domains`` tree.

    Returns:
        A minimal JSON-compatible payload containing only ``flat_questions``.
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
    """Convert questionnaire JSON into database-ready question rows.

    Parameters:
        document: Parsed questionnaire document with a ``domains`` tree.

    Returns:
        Rows ready for ``insert_questions_for_interview``.
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
    """Save the flat-question payload to disk.

    Parameters:
        document: Parsed questionnaire document.
        out_path: Target JSON path.

    Returns:
        The saved payload.
    """

    payload = expand_questionnaire_document(document)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
