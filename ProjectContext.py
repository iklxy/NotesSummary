"@Date: 2026-04-24"
"@Author: lixinyang"


from typing import Any, Dict, List

from DbAccess import DbAccess


def build_project_context(project_row: Dict[str, Any] | None) -> str:
    """
    将项目记录整理为可直接注入 prompt 的项目背景块。

    只保留纠错和 Notes 生成真正需要的字段，避免把整个项目对象传进模型。
    """
    if not project_row:
        return ""

    name = str(project_row.get("name") or "").strip()
    keywords = str(project_row.get("keywords") or "").strip()
    core_problem = str(project_row.get("core_problem") or "").strip()

    lines: List[str] = ["【项目背景】"]
    if name:
        lines.append(f"项目名称：{name}")
    if keywords:
        lines.append(f"项目关键词：{keywords}")
    if core_problem:
        lines.append(f"访谈核心描述：{core_problem}")

    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def load_project_context_by_id(project_id: int) -> str:
    """
    按项目 ID 查询项目记录，并返回格式化后的背景块。

    查询失败时返回空字符串，让上层流程可以继续运行，不把上下文加载失败升级成致命错误。
    """
    try:
        project_row = DbAccess.get_project_by_id(project_id)
    except Exception as exc:
        print(f"[PROJECT] 读取项目背景失败 project_id={project_id}: {exc}")
        return ""
    return build_project_context(project_row)
