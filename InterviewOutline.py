#!/usr/bin/env python3
"""
@Date: 2026-05-06
@Author: lixinyang

从访谈文件夹中的问卷 Markdown 生成“智能纪要式大纲”。

这个模块的职责是：
1. 读取访谈目录中的问卷 md 文件；
2. 将问卷 md 交给模型做语义归纳，而不是硬编码拆分；
3. 输出章节 -> 小点的结构化 JSON；
4. 可选将结果同时渲染成可读文本，方便人工快速核对。

后续在正式工作流里，可以直接复用这里的函数，而不用再写一套
单独的 outline 生成逻辑。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Model import ModelClient
from ModelTranscript import parse_json_payload


DEFAULT_OUT_DIR_NAME = "outline_minutes"


def log(message: str) -> None:
    """输出统一前缀的进度日志。

    参数:
        message: 需要打印的日志内容。
    """

    print(f"[INTERVIEW-OUTLINE] {message}", flush=True)


def read_text_file(path: Path) -> str:
    """读取文本文件内容。

    参数:
        path: 文本文件路径。

    返回:
        文件的完整文本内容。
    """

    if not path.exists():
        raise FileNotFoundError(f"file not found: {path}")
    return path.read_text(encoding="utf-8")


def load_project_context(project_context_path: Path | None) -> str:
    """读取可选项目背景，并包装成 prompt 区块。

    参数:
        project_context_path: 项目背景文本路径；为空时返回空字符串。

    返回:
        可直接注入 prompt 的项目背景块。
    """

    if project_context_path is None:
        return ""
    content = read_text_file(project_context_path).strip()
    if not content:
        return ""
    return f"【项目背景】\n{content}\n\n"


def resolve_questionnaire_markdown_path(input_path: Path) -> Path:
    """解析输入路径，得到实际要处理的问卷 Markdown 文件。

    参数:
        input_path: 可以是具体的 md 文件，也可以是访谈文件夹路径。

    返回:
        可用于生成智能纪要大纲的 Markdown 文件路径。
    """

    if input_path.is_file():
        if input_path.suffix.lower() != ".md":
            raise ValueError(f"input file is not a markdown file: {input_path}")
        return input_path

    if not input_path.exists():
        raise FileNotFoundError(f"input path not found: {input_path}")
    if not input_path.is_dir():
        raise ValueError(f"input path is neither file nor directory: {input_path}")

    candidates = sorted(
        [
            path
            for path in input_path.glob("*.md")
            if path.is_file()
            and not path.name.startswith("outline_")
            and not path.name.startswith("minutes_")
            and not path.name.startswith("kbq_")
        ]
    )
    if not candidates:
        raise FileNotFoundError(f"no markdown questionnaire found in directory: {input_path}")
    if len(candidates) == 1:
        return candidates[0]

    questionnaire_candidates = [path for path in candidates if "questionnaire" in path.name.lower() or "问卷" in path.name]
    if len(questionnaire_candidates) == 1:
        return questionnaire_candidates[0]

    raise ValueError(
        f"multiple markdown files found in {input_path}, please pass the exact questionnaire md file:\n"
        + "\n".join(str(item) for item in candidates)
    )


def extract_document_title(markdown_text: str, fallback_name: str) -> str:
    """从 Markdown 中尽量提取文档标题。

    参数:
        markdown_text: 问卷 Markdown 原文。
        fallback_name: 提取失败时使用的兜底名称。

    返回:
        归一化后的文档标题。
    """

    for line in markdown_text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line.strip())
        if match:
            title = match.group(1).strip()
            if title:
                return title
    return fallback_name


def build_outline_prompt(
    document_title: str,
    markdown_text: str,
    project_context_block: str = "",
) -> tuple[str, str]:
    """构造“问卷 Markdown -> 智能纪要大纲”的提示词。

    参数:
        document_title: 文档标题。
        markdown_text: 原始问卷 Markdown 内容。
        project_context_block: 可选项目背景块。

    返回:
        (system_prompt, user_prompt) 二元组。
    """

    system_prompt = (
        "你是一名资深医学市场调研访谈分析专家，熟悉问卷结构归纳、纪要提纲生成和主题聚类。"
        "你的任务不是机械解析 Markdown，也不是逐条抄写问题，而是基于问卷内容的语义结构，"
        "整理出一份适合访谈纪要展示的层级大纲。"
    )
    user_prompt = (
        f"{project_context_block}"
        "下面是一份访谈问卷的 Markdown 文本，请你生成一份“智能纪要式大纲”。\n\n"
        "生成规则：\n"
        "1. 不要逐条复刻原始问题；要把相关问题聚合成章节和小点。\n"
        "2. 如果文档里有显式的第一部分、第二部分等结构，请优先保留这些章节边界。\n"
        "3. 每个章节下面放 2 到 6 个小点，小点应当是对同一主题的归纳总结。\n"
        "4. 小点标题要简洁，能够概括原始问题群的核心意思。\n"
        "5. 每个小点给出一到三句总结，不要展开证据，不要写分析过程。\n"
        "6. 如果文档中有表格、示意说明或重复的页眉页脚，请只吸收其中对章节判断有价值的信息，不要原样搬运。\n"
        "7. 如果某些内容无法明确归到某一章节，可以放进“其他 / 补充说明”类小点，但不要把无关信息硬塞进去。\n"
        "8. 输出必须是合法 JSON，且只输出 JSON，不要输出解释文字。\n\n"
        f"【文档标题】\n{document_title}\n\n"
        "【问卷 Markdown】\n"
        f"{markdown_text}\n\n"
        "请按照下面的结构输出：\n"
        "{\n"
        '  "document_title": "文档标题",\n'
        '  "outline": [\n'
        "    {\n"
        '      "order": 1,\n'
        '      "title": "第一部分：...",\n'
        '      "summary": "这一部分的总括",\n'
        '      "items": [\n'
        "        {\n"
        '          "order": 1,\n'
        '          "title": "小点标题",\n'
        '          "summary": "对该小点的纪要式总结"\n'
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}\n"
    )
    return system_prompt, user_prompt


def _normalize_outline_items(raw_items: Any) -> List[Dict[str, Any]]:
    """将模型返回的章节小点列表归一化。

    参数:
        raw_items: 模型返回的 items / points / children 原始内容。

    返回:
        归一化后的 item 列表。
    """

    if not isinstance(raw_items, list):
        return []

    items: List[Dict[str, Any]] = []
    for item_index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        summary = str(item.get("summary") or item.get("content") or "").strip()
        if not title and not summary:
            continue
        items.append({"order": item_index, "title": title, "summary": summary})
    return items


def _normalize_outline_sections(raw_outline: Any) -> List[Dict[str, Any]]:
    """将模型返回的章节列表归一化。

    参数:
        raw_outline: 模型返回的 outline / sections 原始内容。

    返回:
        归一化后的章节列表。
    """

    if not isinstance(raw_outline, list):
        return []

    sections: List[Dict[str, Any]] = []
    for section_index, section in enumerate(raw_outline, start=1):
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or section.get("name") or "").strip()
        summary = str(section.get("summary") or section.get("content") or "").strip()
        items = _normalize_outline_items(section.get("items") or section.get("points") or section.get("children"))
        if not title and not summary and not items:
            continue
        sections.append(
            {
                "order": section_index,
                "title": title,
                "summary": summary,
                "items": items,
            }
        )
    return sections


def parse_outline_response(content: str) -> Dict[str, Any]:
    """将模型返回解析成结构化大纲。

    参数:
        content: 模型原始输出文本。

    返回:
        归一化后的大纲字典。
    """

    payload = parse_json_payload(content)
    if not isinstance(payload, dict):
        return {"document_title": "", "outline": [], "llm_raw_output": content}

    outline = payload.get("outline")
    if outline is None:
        outline = payload.get("sections")

    normalized_outline = _normalize_outline_sections(outline)
    return {
        "document_title": str(payload.get("document_title") or payload.get("title") or "").strip(),
        "outline": normalized_outline,
        "llm_raw_output": content,
    }


def render_outline_text(payload: Dict[str, Any]) -> str:
    """将大纲结果渲染为可读文本。

    参数:
        payload: 结构化大纲字典。

    返回:
        可直接查看的文本内容。
    """

    lines: List[str] = []
    document_title = str(payload.get("document_title") or "").strip()
    if document_title:
        lines.append(f"# {document_title}")
        lines.append("")

    outline = payload.get("outline") or []
    if not isinstance(outline, list):
        return "\n".join(lines).strip()

    for section in outline:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").strip()
        summary = str(section.get("summary") or "").strip()
        if title:
            lines.append(f"## {title}")
        if summary:
            lines.append(summary)

        items = section.get("items") or []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_title = str(item.get("title") or "").strip()
                item_summary = str(item.get("summary") or "").strip()
                if item_title and item_summary:
                    lines.append(f"- {item_title}：{item_summary}")
                elif item_title:
                    lines.append(f"- {item_title}")
                elif item_summary:
                    lines.append(f"- {item_summary}")
        lines.append("")

    return "\n".join(lines).strip()


def _build_output_paths(md_path: Path, out_dir: Path | None = None) -> Tuple[Path, Path]:
    """根据输入 md 路径构造输出路径。

    参数:
        md_path: 实际处理的问卷 Markdown 文件路径。
        out_dir: 可选输出目录；为空时默认写到 md 文件同级目录下。

    返回:
        (json_path, txt_path) 二元组。
    """

    target_dir = out_dir if out_dir is not None else md_path.parent / DEFAULT_OUT_DIR_NAME
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / f"{md_path.stem}.outline.json"
    txt_path = target_dir / f"{md_path.stem}.outline.txt"
    return json_path, txt_path


def generate_outline_from_markdown(
    markdown_text: str,
    *,
    document_title: str,
    project_context_block: str = "",
) -> Dict[str, Any]:
    """基于问卷 Markdown 调用模型生成智能纪要大纲。

    参数:
        markdown_text: 问卷 Markdown 原文。
        document_title: 文档标题。
        project_context_block: 可选项目背景块。

    返回:
        结构化大纲字典。
    """

    system_prompt, user_prompt = build_outline_prompt(
        document_title=document_title,
        markdown_text=markdown_text,
        project_context_block=project_context_block,
    )
    client = ModelClient()
    raw_output = client.generate(system_prompt, user_prompt)
    payload = parse_outline_response(raw_output)
    if not payload.get("document_title"):
        payload["document_title"] = document_title
    return payload


def generate_outline_from_questionnaire_md(
    input_path: Path,
    *,
    project_context_path: Path | None = None,
    out_dir: Path | None = None,
) -> Dict[str, Any]:
    """从访谈文件夹中的问卷 md 生成智能纪要大纲并写盘。

    参数:
        input_path: 问卷 md 文件路径，或者包含问卷 md 的访谈目录。
        project_context_path: 可选项目背景文本路径。
        out_dir: 可选输出目录；为空时写到 md 文件同级的 outline_minutes 子目录。

    返回:
        包含输入路径、输出路径和大纲内容的结果字典。
    """

    md_path = resolve_questionnaire_markdown_path(input_path)
    markdown_text = read_text_file(md_path).strip()
    if not markdown_text:
        raise ValueError(f"questionnaire markdown is empty: {md_path}")

    document_title = extract_document_title(markdown_text, md_path.stem)
    project_context_block = load_project_context(project_context_path)
    payload = generate_outline_from_markdown(
        markdown_text,
        document_title=document_title,
        project_context_block=project_context_block,
    )

    payload["source_file"] = str(md_path)
    payload["input_path"] = str(input_path)

    json_path, txt_path = _build_output_paths(md_path, out_dir)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    txt_path.write_text(render_outline_text(payload) + "\n", encoding="utf-8")

    return {
        "success": True,
        "input_path": str(input_path),
        "markdown_path": str(md_path),
        "json_path": str(json_path),
        "txt_path": str(txt_path),
        "outline": payload,
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    """解析命令行参数。

    参数:
        argv: 去掉程序名后的命令行参数列表。

    返回:
        argparse 解析结果对象。
    """

    parser = argparse.ArgumentParser(description="Generate an interview outline from questionnaire markdown.")
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="问卷 md 文件路径，或者包含问卷 md 的访谈目录路径。",
    )
    parser.add_argument(
        "--project-context",
        type=Path,
        default=None,
        help="可选项目背景文本路径。",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="可选输出目录；为空时写到 md 同级的 outline_minutes 子目录。",
    )
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    """命令行入口。

    参数:
        argv: 去掉程序名后的命令行参数列表。

    返回:
        进程退出码，成功时返回 0。
    """

    args = parse_args(argv)
    log(f"读取输入：{args.input}")
    result = generate_outline_from_questionnaire_md(
        args.input,
        project_context_path=args.project_context,
        out_dir=args.out_dir,
    )
    outline_payload = result.get("outline") if isinstance(result.get("outline"), dict) else {}
    section_count = len(outline_payload.get("outline", [])) if isinstance(outline_payload, dict) else 0
    log(f"生成完成：{result['json_path']}")
    log(f"文本输出：{result['txt_path']}")
    log(f"章节数量：{section_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
