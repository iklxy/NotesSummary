"@Date: 2026-04-13"
"@Author: lixinyang"


import json
from typing import Any, Dict, List, Optional

from DbAccess import DbAccess
from NotesWorkflow import fetch_questions_step, generate_notes_step
from config import config


def fetch_questions_for_interview(interview_id: int) -> List[Dict[str, Any]]:
    """
    查询某个访谈下配置的题目列表。

    参数:
        interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。

    返回:
        题目记录列表；若查询失败或没有题目，则返回空列表。
        该函数是对 `NotesWorkflow.fetch_questions_step` 的命令行友好包装。
    """
    result = fetch_questions_step(interview_id)
    if not result.get("success"):
        return []
    return result.get("questions") or []


def generate_notes_for_question_with_rag(
    interview_id: int,
    question_row: Dict[str, Any],
    top_k: int = 10,
) -> Dict[str, Any]:
    """
    为单个题目执行 RAG + LLM Notes 生成，并返回对应结果。

    参数:
        interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。
        question_row: 单条题目记录，通常来自 `fetch_questions_for_interview`。
        top_k: 每道题目的 RAG 检索片段上限。

    返回:
        单题 Notes 结果字典。若生成失败，则返回带 `error` 字段的结果。
    """
    interview = DbAccess.get_interview_by_id(interview_id)
    if not interview:
        return {
            "question_id": question_row.get("id"),
            "question_text": question_row.get("question_text", ""),
            "question_type": question_row.get("question_type"),
            "intent_id": question_row.get("intent_id"),
            "segments": [],
            "notes": {"error": f"interview {interview_id} not found"},
        }

    project_id = int(interview.get("parse_project_id") or 0)
    notes_block = generate_notes_step(
        project_id=project_id,
        interview_id=interview_id,
        questions=[question_row],
        top_k=top_k,
    )
    results = notes_block.get("results") or []
    if results:
        return results[0]

    return {
        "question_id": question_row.get("id"),
        "question_text": question_row.get("question_text", ""),
        "question_type": question_row.get("question_type"),
        "intent_id": question_row.get("intent_id"),
        "segments": [],
        "notes": {"error": notes_block.get("message") or "generate notes failed"},
    }


def run_generate_notes_for_interview(
    interview_id: int,
    top_k: int = 10,
    question_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    为指定访谈生成 Notes，但仅返回内存结果，不执行写库。

    参数:
        interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。
        top_k: 每道题目的 RAG 检索片段上限。
        question_id: 可选题目 ID；传入时仅生成单题结果。

    返回:
        Notes 结果列表。若访谈不存在、题目不存在或生成失败，则返回空列表。
    """
    interview = DbAccess.get_interview_by_id(interview_id)
    if not interview:
        print(f"[NOTES] interview {interview_id} not found")
        return []

    project_id = int(interview.get("parse_project_id") or 0)
    question_result = fetch_questions_step(interview_id)
    if not question_result.get("success"):
        print(f"[NOTES] {question_result.get('message')}")
        return []

    questions: List[Dict[str, Any]] = question_result.get("questions") or []
    if question_id is not None:
        target_question_id = int(question_id)
        questions = [row for row in questions if int(row.get("id") or 0) == target_question_id]
        if not questions:
            print(f"[NOTES] question {target_question_id} not found")
            return []

    notes_block = generate_notes_step(
        project_id=project_id,
        interview_id=interview_id,
        questions=questions,
        top_k=top_k,
    )
    if not notes_block.get("success"):
        print(f"[NOTES] {notes_block.get('message')}")
        return []
    return notes_block.get("results") or []


def pretty_print_notes_results(results: List[Dict[str, Any]]) -> None:
    """
    将 Notes 结果按控制台可读格式打印出来。

    参数:
        results: Notes 结果列表，通常来自 `run_generate_notes_for_interview`。

    返回:
        无返回值。函数直接向标准输出打印内容。
    """
    for idx, item in enumerate(results, start=1):
        question_id = item.get("question_id")
        question_text = item.get("question_text", "")
        notes = item.get("notes", {})

        print("\n" + "=" * 80)
        print(f"[NOTES] 问题序号 {idx}，question_id={question_id}")
        print(f"[NOTES] 问题内容: {question_text}")
        print("-" * 80)
        print("[NOTES] 生成的 Notes JSON:")
        print(json.dumps(notes, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    interview_id_str = config.TEST_INTERVIEW_ID
    if not interview_id_str:
        raise RuntimeError("未在环境变量中找到 TEST_INTERVIEW_ID")

    interview_id = int(interview_id_str)
    all_results = run_generate_notes_for_interview(interview_id=interview_id, top_k=10)
    pretty_print_notes_results(all_results)
