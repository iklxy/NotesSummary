"@Date:2026-04-14"
"@Author:lixinyang"

import json
from typing import Any, Dict, List, Optional

from DbAccess import DbAccess


def select_fewshot_samples(
    project_id: int,
    question_id: int,
    question_type: str,
    research_phase: Optional[str],
    intent_id: int,
    limit: int = 2,
) -> List[Dict[str, Any]]:
    """
    从 bh_project_fewshot_sample 中选择适用于当前题目的 few-shot 样本。

    优先级:
        1) 同项目 + 同题目 + 同 intent + seed
        2) 同项目 + 同 intent + seed
        3) 跨项目 + 同 intent + seed

    参数:
        project_id:     项目 ID。
        question_id:    题目 ID。
        question_type:  题目类型，用于后续扩展优先级时使用。
        research_phase: 研究阶段，可为空，当前实现未使用。
        intent_id:      意图 ID。
        limit:          期望返回的样本数量上限。

    返回:
        few-shot 样本列表，每个元素为一条 bh_project_fewshot_sample 记录的字典形式。
    """
    if limit <= 0:
        return []

    conn = DbAccess.get_connection()
    results: List[Dict[str, Any]] = []
    seen_ids: set[int] = set()

    try:
        with conn.cursor() as cursor:
            remaining = limit

            sql1 = """
                SELECT id, project_id, project_interview_id, question_id, intent_id,
                       notes_result_id, sample_json, quality_score, source_kind, created_time
                FROM bh_project_fewshot_sample
                WHERE project_id = %s
                  AND question_id = %s
                  AND intent_id = %s
                  AND source_kind = 'seed'
                  AND quality_score >= 80
                ORDER BY quality_score DESC, created_time DESC
                LIMIT %s
            """
            cursor.execute(sql1, (project_id, question_id, intent_id, remaining))
            rows = cursor.fetchall()
            for r in rows:
                rid = r.get("id")
                if rid is None or rid in seen_ids:
                    continue
                seen_ids.add(rid)
                results.append(r)
            remaining = limit - len(results)
            if remaining <= 0:
                return results

            sql2 = """
                SELECT id, project_id, project_interview_id, question_id, intent_id,
                       notes_result_id, sample_json, quality_score, source_kind, created_time
                FROM bh_project_fewshot_sample
                WHERE project_id = %s
                  AND intent_id = %s
                  AND source_kind = 'seed'
                  AND quality_score >= 80
                ORDER BY quality_score DESC, created_time DESC
                LIMIT %s
            """
            cursor.execute(sql2, (project_id, intent_id, remaining))
            rows = cursor.fetchall()
            for r in rows:
                rid = r.get("id")
                if rid is None or rid in seen_ids:
                    continue
                seen_ids.add(rid)
                results.append(r)
            remaining = limit - len(results)
            if remaining <= 0:
                return results

            sql3 = """
                SELECT id, project_id, project_interview_id, question_id, intent_id,
                       notes_result_id, sample_json, quality_score, source_kind, created_time
                FROM bh_project_fewshot_sample
                WHERE intent_id = %s
                  AND source_kind = 'seed'
                  AND quality_score >= 80
                ORDER BY quality_score DESC, created_time DESC
                LIMIT %s
            """
            cursor.execute(sql3, (intent_id, remaining))
            rows = cursor.fetchall()
            for r in rows:
                rid = r.get("id")
                if rid is None or rid in seen_ids:
                    continue
                seen_ids.add(rid)
                results.append(r)
    finally:
        conn.close()

    return results


def build_fewshot_prompt_block(samples: List[Dict[str, Any]]) -> str:
    """
    将 few-shot 样本列表转换为可插入到 LLM Prompt 的文本块。

    参数:
        samples: 由 select_fewshot_samples 返回的样本记录列表。

    返回:
        适合作为 Prompt 一部分的字符串，如果 samples 为空则返回空字符串。
    """
    if not samples:
        return ""

    lines: List[str] = []
    lines.append("下面是若干个历史示例。每个示例包含【标准化的 Notes JSON】。\n")

    for idx, sample in enumerate(samples, start=1):
        raw = sample.get("sample_json")
        if isinstance(raw, dict):
            json_text = json.dumps(raw, ensure_ascii=False)
        else:
            json_text = str(raw)
        lines.append(f"示例 {idx}：")
        lines.append("标准化 Notes（JSON）：")
        lines.append(json_text)
        lines.append("")

    lines.append("请参照上述示例的结构和书写风格，对当前题目生成 Notes。")
    return "\n".join(lines)
