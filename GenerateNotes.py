"@Date:2026-04-13"
"@author:lixinyang"

import os
import json
from typing import Any, Dict, List

import dotenv

from DbAccess import get_connection
from Model import ModelClient
from RagIndex import index_interview_summary, retrieve_segments_for_question


dotenv.load_dotenv()


def fetch_questions_for_interview(interview_id: int) -> List[Dict[str, Any]]:
    """
    根据访谈 ID 查询 bh_project_question 表中的题目列表。

    参数:
        interview_id: 访谈主键 ID，对应 bh_project_interview.id。

    返回:
        题目记录列表，每个元素为字典，至少包含:
            - id
            - project_interview_id
            - question_order
            - question_text
            - question_type
            - intent_id
    """
    sql = """
        SELECT
            id,
            project_interview_id,
            question_order,
            question_text,
            question_type,
            intent_id
        FROM bh_project_question
        WHERE project_interview_id = %s
        ORDER BY question_order ASC, id ASC
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (interview_id,))
            rows: List[Dict[str, Any]] = cursor.fetchall()
            return rows
    finally:
        conn.close()


def generate_notes_for_question_with_rag(
    interview_id: int,
    question_row: Dict[str, Any],
    top_k: int = 10,
) -> Dict[str, Any]:
    """
    针对单个题目执行 RAG 检索并调用大模型生成 Notes。

    参数:
        interview_id: 访谈主键 ID，用于限定检索范围。
        question_row: 单条题目记录，来自 fetch_questions_for_interview。
        top_k:        RAG 检索返回的片段数量上限。

    返回:
        字典结构，包含:
            - question_id
            - question_text
            - question_type
            - intent_id
            - segments: RAG 检索到的片段列表
            - notes:    大模型生成的 Notes 结果字典
    """
    question_id = question_row.get("id")
    question_text = question_row.get("question_text", "")
    question_type = question_row.get("question_type")
    intent_id = question_row.get("intent_id")

    print(f"[NOTES] 开始为问题 {question_id} 生成 Notes")

    segments = retrieve_segments_for_question(
        interview_id=interview_id,
        question_text=question_text,
        top_k=top_k,
    )
    print(f"[NOTES] 问题 {question_id} 检索到 {len(segments)} 条相关片段")

    model_client = ModelClient()
    notes = model_client.generate_notes_for_question(
        question_text=question_text,
        segments=segments,
        intent_name=None,
        question_type=question_type,
    )

    return {
        "question_id": question_id,
        "question_text": question_text,
        "question_type": question_type,
        "intent_id": intent_id,
        "segments": segments,
        "notes": notes,
    }


def run_generate_notes_for_interview(
    interview_id: int,
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    """
    针对单场访谈的所有题目执行 Notes 生成流程。

    参数:
        interview_id: 访谈主键 ID。
        top_k:        每道题目 RAG 检索返回的片段数量上限。

    返回:
        每个题目的 Notes 结果列表。
    """
    print(f"[NOTES] 为访谈 {interview_id} 构建/更新向量索引")
    index_interview_summary(interview_id)

    questions = fetch_questions_for_interview(interview_id)
    if not questions:
        print(f"[NOTES] 访谈 {interview_id} 下未找到任何题目记录")
        return []

    print(f"[NOTES] 共找到 {len(questions)} 条题目，开始生成 Notes")

    results: List[Dict[str, Any]] = []
    for row in questions:
        result = generate_notes_for_question_with_rag(
            interview_id=interview_id,
            question_row=row,
            top_k=top_k,
        )
        results.append(result)

    return results


def pretty_print_notes_results(results: List[Dict[str, Any]]) -> None:
    """
    将 Notes 生成结果以易读格式打印到控制台。

    参数:
        results: run_generate_notes_for_interview 的返回列表。
    """
    for idx, item in enumerate(results, start=1):
        qid = item.get("question_id")
        qtext = item.get("question_text", "")
        notes = item.get("notes", {})

        print("\n" + "=" * 80)
        print(f"[NOTES] 问题序号 {idx}，question_id={qid}")
        print(f"[NOTES] 问题内容: {qtext}")
        print("-" * 80)
        print("[NOTES] 生成的 Notes JSON:")
        print(json.dumps(notes, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    interview_id_str = os.getenv("TEST_INTERVIEW_ID")
    if not interview_id_str:
        raise RuntimeError("未在环境变量中找到 TEST_INTERVIEW_ID")
    interview_id = int(interview_id_str)
    all_results = run_generate_notes_for_interview(interview_id=interview_id, top_k=10)
    pretty_print_notes_results(all_results)

