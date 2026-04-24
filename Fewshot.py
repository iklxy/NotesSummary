"@Date:2026-04-14"
"@Author:lixinyang"

import json
from typing import Any, Dict, List, Optional, Sequence

from DbAccess import DbAccess


def _append_unique_rows(
    results: List[Dict[str, Any]],
    rows: Sequence[Dict[str, Any]],
    seen_ids: set[int],
) -> None:
    """
    将查询结果按主键去重后追加到 few-shot 结果列表中。

    参数:
        results: 已收集的 few-shot 样本列表，会被原地追加。
        rows: 当前 SQL 查询返回的样本记录序列。
        seen_ids: 已出现样本 ID 的集合，用于防止重复追加同一条记录。

    返回:
        无返回值。函数会直接修改 `results` 与 `seen_ids`。
    """
    for row in rows:
        row_id = row.get("id")
        if row_id is None or row_id in seen_ids:
            continue
        seen_ids.add(row_id)
        results.append(row)


def select_fewshot_samples(
    project_id: int,
    question_id: int,
    question_type: str,
    research_phase: Optional[str],
    intent_id: int,
    limit: int = 2,
) -> List[Dict[str, Any]]:
    """
    从 `bh_project_fewshot_sample` 中挑选当前题目可复用的 few-shot 样本。

    当前选择策略按优先级依次回退：
    1. 同项目 + 同题目 + 同 intent + seed
    2. 同项目 + 同 intent + seed
    3. 跨项目 + 同 intent + seed

    参数:
        project_id: 当前项目 ID，用于优先匹配同项目样本。
        question_id: 当前题目 ID，用于优先匹配同题目样本。
        question_type: 当前题目类型。当前版本暂未参与 SQL 过滤，但保留参数位，
            便于后续按题型做样本优先级细化。
        research_phase: 当前题目的研究阶段。当前版本暂未参与 SQL 过滤，但保留参数位，
            便于后续按研究阶段增强匹配。
        intent_id: 当前题目对应的意图 ID，是 few-shot 选择的核心过滤条件。
        limit: 最多返回的样本数量上限。小于等于 0 时直接返回空列表。

    返回:
        few-shot 样本记录列表，按优先级顺序收集并去重。
        每个元素通常包含：
            - id
            - project_id
            - project_interview_id
            - question_id
            - intent_id
            - notes_result_id
            - sample_json
            - quality_score
            - source_kind
            - created_time
    """
    _ = question_type
    _ = research_phase

    if limit <= 0:
        return []

    sql_statements = [
        (
            """
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
            """,
            (project_id, question_id, intent_id),
        ),
        (
            """
            SELECT id, project_id, project_interview_id, question_id, intent_id,
                   notes_result_id, sample_json, quality_score, source_kind, created_time
            FROM bh_project_fewshot_sample
            WHERE project_id = %s
              AND intent_id = %s
              AND source_kind = 'seed'
              AND quality_score >= 80
            ORDER BY quality_score DESC, created_time DESC
            LIMIT %s
            """,
            (project_id, intent_id),
        ),
        (
            """
            SELECT id, project_id, project_interview_id, question_id, intent_id,
                   notes_result_id, sample_json, quality_score, source_kind, created_time
            FROM bh_project_fewshot_sample
            WHERE intent_id = %s
              AND source_kind = 'seed'
              AND quality_score >= 80
            ORDER BY quality_score DESC, created_time DESC
            LIMIT %s
            """,
            (intent_id,),
        ),
    ]

    conn = DbAccess.get_connection()
    results: List[Dict[str, Any]] = []
    seen_ids: set[int] = set()

    try:
        with conn.cursor() as cursor:
            for sql, base_params in sql_statements:
                remaining = limit - len(results)
                if remaining <= 0:
                    break
                cursor.execute(sql, (*base_params, remaining))
                rows = cursor.fetchall()
                _append_unique_rows(results, rows, seen_ids)
    finally:
        conn.close()

    return results


def build_fewshot_prompt_block(samples: List[Dict[str, Any]]) -> str:
    """
    将 few-shot 样本列表转换为可直接注入 Prompt 的文本块。

    参数:
        samples: few-shot 样本记录列表，通常来自 `select_fewshot_samples`。
            每条记录至少应包含 `sample_json` 字段。

    返回:
        可插入 LLM Prompt 的字符串。
        当 `samples` 为空时，返回空字符串。
    """
    if not samples:
        return ""

    lines: List[str] = [
        "以下是历史示例，仅用于学习输出结构和写法，不要复述其中的业务事实。"
    ]

    for idx, sample in enumerate(samples, start=1):
        raw = sample.get("sample_json")
        if isinstance(raw, dict):
            json_text = json.dumps(raw, ensure_ascii=False)
        else:
            json_text = str(raw)
        lines.append(f"【历史示例 {idx}】")
        lines.append("标准化 Notes（JSON）：")
        lines.append(json_text)
        lines.append("")

    lines.append("请只根据当前题目生成新的 JSON，不要复用示例中的具体业务内容。")
    return "\n".join(lines)
