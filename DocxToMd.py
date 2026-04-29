#!/usr/bin/env python3
"""
@Date: 2026-04-29
@Author: lixinyang

将问卷 DOCX 解析为 Markdown 和 JSON。

该模块不依赖额外第三方解析库，供后端和本地 test 脚本共用。
它会从 Warm-up 开始截取问卷内容，按领域分组，并结合编号样式递归构建问题树。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}


def _q(tag: str) -> str:
    """返回 WordprocessingML 命名空间下的完整标签名。"""

    return f"{{{W_NS}}}{tag}"


def normalize_text(text: str) -> str:
    """标准化从 Word XML 中提取出来的空白字符。"""

    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def extract_text_from_paragraph(paragraph: ET.Element) -> str:
    """提取段落节点中的可见文本。"""

    parts: List[str] = []
    for node in paragraph.iter():
        if node.tag == _q("t") and node.text:
            parts.append(node.text)
        elif node.tag == _q("tab"):
            parts.append("\t")
        elif node.tag in {_q("br"), _q("cr")}:
            parts.append("\n")
    return normalize_text("".join(parts))


def extract_paragraph_meta(paragraph: ET.Element) -> Dict[str, Any]:
    """提取段落的样式和编号元数据。"""

    style = None
    num_id = None
    ilvl = None

    p_style = paragraph.find("./w:pPr/w:pStyle", NS)
    if p_style is not None:
        style = p_style.attrib.get(_q("val"))

    num_pr = paragraph.find("./w:pPr/w:numPr", NS)
    if num_pr is not None:
        num_node = num_pr.find("./w:numId", NS)
        lvl_node = num_pr.find("./w:ilvl", NS)
        if num_node is not None:
            num_id = num_node.attrib.get(_q("val"))
        if lvl_node is not None:
            raw_level = lvl_node.attrib.get(_q("val"))
            try:
                ilvl = int(raw_level) if raw_level is not None else None
            except ValueError:
                ilvl = None

    return {"style": style, "num_id": num_id, "ilvl": ilvl}


def extract_table_rows(table: ET.Element) -> List[List[str]]:
    """将表格提取为纯文本单元格行列表。"""

    rows: List[List[str]] = []
    for row in table.findall("./w:tr", NS):
        cells: List[str] = []
        for cell in row.findall("./w:tc", NS):
            cell_parts: List[str] = []
            for paragraph in cell.findall("./w:p", NS):
                text = extract_text_from_paragraph(paragraph)
                if text:
                    cell_parts.append(text)
            cells.append(normalize_text("\n".join(cell_parts)))
        rows.append(cells)
    return rows


def table_rows_to_markdown(rows: List[List[str]]) -> str:
    """将表格行渲染为 Markdown。"""

    if not rows:
        return ""

    width = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (width - len(row)) for row in rows]
    header = normalized_rows[0]
    divider = ["---"] * width

    def render_row(row: List[str]) -> str:
        """
        将一行表格单元格渲染为 Markdown 表格行。

        参数:
            row: 已补齐列宽的一行单元格文本列表；单元格内的换行会被替换为 <br>。

        返回:
            对应的 Markdown 表格行字符串，形如 "| a | b | c |"。
        """
        return "| " + " | ".join(cell.replace("\n", "<br>") for cell in row) + " |"

    markdown_lines = [render_row(header), render_row(divider)]
    markdown_lines.extend(render_row(row) for row in normalized_rows[1:])
    return "\n".join(markdown_lines)


def extract_docx_blocks(docx_path: Path) -> List[Dict[str, Any]]:
    """按原始顺序提取 DOCX 主体中的段落块和表格块。"""

    if not docx_path.exists():
        raise FileNotFoundError(f"DOCX file not found: {docx_path}")

    with zipfile.ZipFile(docx_path) as archive:
        if "word/document.xml" not in archive.namelist():
            raise ValueError(f"{docx_path} is not a valid DOCX file")
        document = ET.fromstring(archive.read("word/document.xml"))

    body = document.find("./w:body", NS)
    if body is None:
        raise ValueError("DOCX document body is missing")

    blocks: List[Dict[str, Any]] = []
    index = 0
    for child in body:
        if child.tag == _q("p"):
            text = extract_text_from_paragraph(child)
            meta = extract_paragraph_meta(child)
            blocks.append({"index": index, "kind": "paragraph", "text": text, **meta})
            index += 1
        elif child.tag == _q("tbl"):
            rows = extract_table_rows(child)
            blocks.append(
                {
                    "index": index,
                    "kind": "table",
                    "rows": rows,
                    "text": "\n".join(" | ".join(row) for row in rows if row),
                    "markdown": table_rows_to_markdown(rows),
                }
            )
            index += 1
    return blocks


def extract_outline_modules(blocks: List[Dict[str, Any]]) -> List[str]:
    """从目录表中提取领域模块名称。"""

    for block in blocks:
        if block.get("kind") != "table":
            continue
        rows = block.get("rows", [])
        if len(rows) < 2:
            continue
        header = [normalize_text(cell) for cell in rows[0]]
        if "模块" not in header or "预计时间" not in header:
            continue
        modules: List[str] = []
        for row in rows[1:]:
            if row and normalize_text(row[0]):
                modules.append(normalize_text(row[0]))
        if modules:
            return modules
    return []


def find_warmup_anchor_index(blocks: List[Dict[str, Any]]) -> int:
    """定位第一个 Warm-up 段落的位置。"""

    for index, block in enumerate(blocks):
        if block.get("kind") == "paragraph" and normalize_text(block.get("text", "")) == "Warm-up":
            return index
    raise ValueError("Warm-up marker not found in questionnaire")


def build_domain_aliases(module_order: List[str]) -> List[str]:
    """构造可用于识别领域标题的别名集合。"""

    aliases: List[str] = []
    for module in module_order:
        normalized = normalize_text(module)
        if not normalized:
            continue
        aliases.append(normalized)
        for token in re.findall(r"[A-Za-z]+", normalized):
            aliases.append(token)

    seen = set()
    unique_aliases: List[str] = []
    for alias in aliases:
        if alias not in seen:
            seen.add(alias)
            unique_aliases.append(alias)
    return unique_aliases


def is_domain_heading(block: Dict[str, Any], module_order: List[str]) -> bool:
    """判断某个段落是否开启了新的领域。"""

    if block.get("kind") != "paragraph":
        return False

    text = normalize_text(block.get("text", ""))
    if not text:
        return False

    if text == "Warm-up":
        return True

    if re.match(r"^[一二三四五六七八九十]+[、.．:：]\s*", text):
        return True

    if "？" in text or "?" in text:
        return False

    for alias in build_domain_aliases(module_order):
        if alias and alias in text and len(text) <= 40:
            return True
    return False


def strip_question_prefix(text: str) -> str:
    """去掉题目文本中常见的编号前缀。"""

    cleaned = normalize_text(text)
    cleaned = re.sub(r"^\(?\d+[\).、．:：]?\s*", "", cleaned)
    cleaned = re.sub(r"^[a-zA-Z][\).、．:：]?\s*", "", cleaned)
    cleaned = re.sub(r"^[ivxlcdmIVXLCDM]+[\).、．:：]?\s*", "", cleaned)
    return normalize_text(cleaned)


def infer_question_level(block: Dict[str, Any]) -> Optional[int]:
    """推断问卷段落对应的树层级。"""

    if block.get("kind") != "paragraph":
        return None

    if block.get("ilvl") is not None:
        return int(block["ilvl"])

    text = normalize_text(block.get("text", ""))
    if not text:
        return None

    if re.match(r"^\(?\d+[\).、．:：]?\s*", text):
        return 0
    if re.match(r"^[a-zA-Z][\).、．:：]?\s*", text):
        return 1
    if re.match(r"^[ivxlcdmIVXLCDM]+[\).、．:：]?\s*", text):
        return 2
    return None


def build_question_tree(blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """为单个领域构建递归问题树。"""

    roots: List[Dict[str, Any]] = []
    notes: List[str] = []
    stack: List[Dict[str, Any]] = []

    for block in blocks:
        if block.get("kind") == "table":
            table_md = block.get("markdown", "").strip()
            if table_md:
                notes.append(table_md)
            continue

        if block.get("kind") != "paragraph":
            continue

        raw_text = normalize_text(block.get("text", ""))
        if not raw_text:
            continue

        level = infer_question_level(block)
        if level is None:
            if stack:
                stack[-1]["continuations"].append(raw_text)
            else:
                notes.append(raw_text)
            continue

        node = {
            "level": level,
            "text": strip_question_prefix(raw_text),
            "raw_text": raw_text,
            "source_index": block.get("index"),
            "num_id": block.get("num_id"),
            "ilvl": block.get("ilvl"),
            "style": block.get("style"),
            "continuations": [],
            "children": [],
        }

        while stack and stack[-1]["level"] >= level:
            stack.pop()

        if stack:
            stack[-1]["children"].append(node)
        else:
            roots.append(node)
        stack.append(node)

    return {"questions": roots, "notes": notes}


def parse_questionnaire(docx_path: Path) -> Dict[str, Any]:
    """解析问卷，只保留 Warm-up 及其之后的内容。"""

    blocks = extract_docx_blocks(docx_path)
    module_order = extract_outline_modules(blocks)
    start_index = find_warmup_anchor_index(blocks)
    content_blocks = blocks[start_index:]

    domains: List[Dict[str, Any]] = []
    current_domain: Optional[Dict[str, Any]] = None
    current_blocks: List[Dict[str, Any]] = []

    def flush_domain() -> None:
        """
        将当前已经收集到的领域块解析成一棵问题树并写入 domains。

        该闭包依赖外层的 current_domain 与 current_blocks：
        - current_domain 记录当前领域的标题与元信息
        - current_blocks 记录当前领域下待解析的原始段落块

        处理结束后会把当前领域追加到 domains，并清空临时状态，等待下一个领域。
        """
        nonlocal current_domain, current_blocks
        if current_domain is None:
            current_blocks = []
            return
        tree = build_question_tree(current_blocks)
        current_domain["questions"] = tree["questions"]
        current_domain["notes"] = tree["notes"]
        domains.append(current_domain)
        current_domain = None
        current_blocks = []

    for block in content_blocks:
        if block.get("kind") != "paragraph":
            if current_domain is not None:
                current_blocks.append(block)
            continue

        text = normalize_text(block.get("text", ""))
        if not text:
            continue

        if is_domain_heading(block, module_order):
            flush_domain()
            current_domain = {
                "title": text,
                "module_key": next((m for m in module_order if m in text or text == m), text),
                "source_index": block.get("index"),
                "questions": [],
                "notes": [],
            }
            current_blocks = []
            continue

        if current_domain is None:
            continue

        current_blocks.append(block)

    flush_domain()

    return {
        "source_file": str(docx_path),
        "questionnaire_title": docx_path.stem,
        "module_order": module_order,
        "start_anchor": "Warm-up",
        "domains": domains,
    }


def question_nodes_to_markdown(nodes: List[Dict[str, Any]], indent: int = 0) -> List[str]:
    """将问题树节点渲染为 Markdown 行。"""

    lines: List[str] = []
    for node in nodes:
        prefix = "  " * indent + "- "
        text = node.get("text", "")
        if node.get("continuations"):
            text = text + " " + " ".join(node["continuations"])
        lines.append(f"{prefix}{text}".rstrip())
        if node.get("children"):
            lines.extend(question_nodes_to_markdown(node["children"], indent + 1))
    return lines


def render_markdown(document: Dict[str, Any]) -> str:
    """将解析后的问卷渲染为 Markdown。"""

    lines: List[str] = []
    lines.append(f"# {document.get('questionnaire_title', '').strip()}")
    lines.append("")

    module_order = document.get("module_order", [])
    if module_order:
        lines.append("## 模块顺序")
        for module in module_order:
            lines.append(f"- {module}")
        lines.append("")

    for domain in document.get("domains", []):
        lines.append(f"## {domain.get('title', '').strip()}")
        for note in domain.get("notes", []):
            if note:
                lines.append(note)
        if domain.get("notes"):
            lines.append("")
        lines.extend(question_nodes_to_markdown(domain.get("questions", []), indent=0))
        lines.append("")

    return "\n".join(line.rstrip() for line in lines).strip() + "\n"


def ensure_output_dir(output_dir: Path) -> None:
    """在需要时创建输出目录。"""

    output_dir.mkdir(parents=True, exist_ok=True)


def convert_docx_questionnaire(docx_path: Path, out_dir: Path) -> Dict[str, Any]:
    """将 DOCX 问卷转换为 Markdown 和 JSON 文件。

    参数:
        docx_path: 待解析的问卷 DOCX 文件路径。
        out_dir: Markdown 和 JSON 文件的输出目录。

    返回:
        包含解析结果和输出文件路径的字典。
    """

    ensure_output_dir(out_dir)
    document = parse_questionnaire(docx_path)
    markdown = render_markdown(document)
    document["markdown_preview"] = markdown

    stem = docx_path.stem
    md_path = out_dir / f"{stem}.md"
    json_path = out_dir / f"{stem}.json"
    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "document": document,
        "markdown": markdown,
        "markdown_path": md_path,
        "json_path": json_path,
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="Convert a questionnaire DOCX into Markdown and JSON.")
    parser.add_argument("--input", type=Path, required=True, help="Input DOCX questionnaire path")
    parser.add_argument("--out-dir", type=Path, required=True, help="Output directory")
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    """命令行入口。"""

    args = parse_args(argv)
    result = convert_docx_questionnaire(args.input, args.out_dir)
    print(f"[OK] Parsed {args.input}")
    print(f"[OK] Markdown written to {result['markdown_path']}")
    print(f"[OK] JSON written to {result['json_path']}")
    print(f"[OK] Modules: {len(result['document'].get('module_order', []))}, domains: {len(result['document'].get('domains', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
