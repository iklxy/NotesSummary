from __future__ import annotations

import json
import re
import subprocess
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Tuple


CARD_RENDER_WIDTH = 1200
CARD_RENDER_DPI_RATIO = 9525


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _frontend_root() -> Path:
    return _project_root() / "summarynotes-fe"


def _load_json_like(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def _extract_tags(card: Dict[str, Any]) -> List[str]:
    candidates = [
        card.get("final_json"),
        card.get("generated_json"),
    ]
    for candidate in candidates:
        payload = _load_json_like(candidate)
        if not isinstance(payload, dict):
            continue
        tags = payload.get("tags")
        if isinstance(tags, list):
            result = [str(tag).strip() for tag in tags if str(tag).strip()]
            if result:
                return result
    return []


def _resolve_card_payload(card: Dict[str, Any]) -> Dict[str, Any]:
    payload = _load_json_like(card.get("final_json"))
    if not isinstance(payload, dict):
        payload = _load_json_like(card.get("generated_json"))
    if not isinstance(payload, dict):
        payload = {}
    title = _normalize_text(card.get("card_title")) or _normalize_text(payload.get("title")) or "卡片"
    summary = _normalize_text(card.get("card_summary")) or _normalize_text(payload.get("summary"))
    tags = _extract_tags(card)
    if not tags and isinstance(payload.get("tags"), list):
        tags = [str(tag).strip() for tag in payload.get("tags") if str(tag).strip()]
    review_status = _normalize_text(card.get("review_status")) or "pending"
    order = card.get("card_order")
    return {
        "title": title,
        "summary": summary,
        "tags": tags,
        "review_status": review_status,
        "order": order,
    }


def _split_text_to_lines(text: str, max_chars: int) -> List[str]:
    if not text:
        return []
    result: List[str] = []
    paragraphs = text.split("\n")
    for paragraph in paragraphs:
        cleaned = paragraph.strip()
        if not cleaned:
            result.append("")
            continue
        if re.search(r"[A-Za-z0-9]", cleaned) and " " in cleaned:
            words = cleaned.split()
            current = ""
            for word in words:
                if not current:
                    current = word
                    continue
                if len(current) + len(word) + 1 <= max_chars:
                    current = f"{current} {word}"
                else:
                    result.append(current)
                    current = word
            if current:
                result.append(current)
        else:
            chunk = ""
            for ch in cleaned:
                if len(chunk) >= max_chars:
                    result.append(chunk)
                    chunk = ""
                chunk += ch
            if chunk:
                result.append(chunk)
    return result


def _estimate_tag_width(tag: str) -> int:
    base = 56
    text_len = len(tag)
    return min(220, base + text_len * 14)


def _build_card_svg(card: Dict[str, Any], width: int = CARD_RENDER_WIDTH) -> Tuple[str, int]:
    payload = _resolve_card_payload(card)
    title = payload["title"]
    summary = payload["summary"]
    tags = payload["tags"]
    review_status = payload["review_status"]
    order = payload["order"]

    title_lines = _split_text_to_lines(title, 24) or [title]
    summary_lines = _split_text_to_lines(summary, 34) or ["暂无摘要"]
    chip_rows: List[List[str]] = []
    current_row: List[str] = []
    current_width = 0
    for tag in tags:
        tag_width = _estimate_tag_width(tag)
        if current_row and current_width + tag_width > width - 120:
            chip_rows.append(current_row)
            current_row = []
            current_width = 0
        current_row.append(tag)
        current_width += tag_width + 12
    if current_row:
        chip_rows.append(current_row)

    padding = 48
    inner_width = width - padding * 2
    title_font = 34
    summary_font = 28
    meta_font = 18
    badge_font = 18
    title_line_height = 48
    summary_line_height = 42
    card_top = 36
    card_bottom = 36
    height = card_top + 84 + len(title_lines) * title_line_height + 22 + len(chip_rows) * 44 + 20 + len(summary_lines) * summary_line_height + card_bottom
    height = max(height, 360)

    lines: List[str] = []
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
    )
    lines.append(
        """
        <defs>
          <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#ffffff"/>
            <stop offset="100%" stop-color="#f7fafc"/>
          </linearGradient>
          <linearGradient id="accent" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#2563eb"/>
            <stop offset="100%" stop-color="#7c3aed"/>
          </linearGradient>
          <filter id="shadow" x="-10%" y="-10%" width="130%" height="140%">
            <feDropShadow dx="0" dy="14" stdDeviation="18" flood-color="#0f172a" flood-opacity="0.12"/>
          </filter>
        </defs>
        """
    )
    lines.append(
        f'<rect x="18" y="18" width="{width - 36}" height="{height - 36}" rx="34" fill="url(#bg)" stroke="#e2e8f0" stroke-width="2" filter="url(#shadow)"/>'
    )
    lines.append(f'<rect x="18" y="18" width="12" height="{height - 36}" rx="6" fill="url(#accent)"/>')
    badge_text = f"卡片 {order}" if order is not None else "卡片"
    lines.append(
        f'<rect x="{padding}" y="{padding - 4}" width="128" height="38" rx="19" fill="#dbeafe"/>'
        f'<text x="{padding + 64}" y="{padding + 22}" text-anchor="middle" font-size="{badge_font}" font-family="Arial, \'Noto Sans SC\', \'Microsoft YaHei\', sans-serif" fill="#1d4ed8" font-weight="700">{escape(badge_text)}</text>'
    )
    status_fill = {
        "approved": "#dcfce7",
        "rejected": "#fee2e2",
        "needs_revision": "#fef3c7",
        "pending": "#e2e8f0",
    }.get(review_status, "#e2e8f0")
    status_text = {
        "approved": "已通过",
        "rejected": "已驳回",
        "needs_revision": "待修改",
        "pending": "待审核",
    }.get(review_status, review_status or "待审核")
    status_x = width - padding - 152
    lines.append(
        f'<rect x="{status_x}" y="{padding - 4}" width="152" height="38" rx="19" fill="{status_fill}"/>'
        f'<text x="{status_x + 76}" y="{padding + 22}" text-anchor="middle" font-size="{badge_font}" font-family="Arial, \'Noto Sans SC\', \'Microsoft YaHei\', sans-serif" fill="#334155" font-weight="700">{escape(status_text)}</text>'
    )

    title_y = padding + 74
    for line_index, line in enumerate(title_lines):
        y = title_y + line_index * title_line_height
        lines.append(
            f'<text x="{padding}" y="{y}" font-size="{title_font}" font-family="Arial, \'Noto Sans SC\', \'Microsoft YaHei\', sans-serif" fill="#0f172a" font-weight="700">{escape(line)}</text>'
        )

    tag_start_y = title_y + len(title_lines) * title_line_height + 12
    chip_y = tag_start_y
    for row in chip_rows:
        x = padding
        for tag in row:
            tag_width = _estimate_tag_width(tag)
            lines.append(f'<rect x="{x}" y="{chip_y}" width="{tag_width}" height="34" rx="17" fill="#eff6ff" stroke="#bfdbfe" stroke-width="1"/>')
            lines.append(
                f'<text x="{x + tag_width / 2}" y="{chip_y + 22}" text-anchor="middle" font-size="{meta_font}" font-family="Arial, \'Noto Sans SC\', \'Microsoft YaHei\', sans-serif" fill="#1d4ed8" font-weight="600">{escape(tag)}</text>'
            )
            x += tag_width + 12
        chip_y += 44

    summary_start_y = chip_y + 18
    lines.append(
        f'<text x="{padding}" y="{summary_start_y}" font-size="{summary_font}" font-family="Arial, \'Noto Sans SC\', \'Microsoft YaHei\', sans-serif" fill="#334155" font-weight="500">'
    )
    summary_line_y = summary_start_y
    for idx, line in enumerate(summary_lines):
        dy = 0 if idx == 0 else summary_line_height
        if idx == 0:
            lines.append(f'<tspan x="{padding}" y="{summary_line_y}">{escape(line)}</tspan>')
        else:
            summary_line_y += summary_line_height
            lines.append(f'<tspan x="{padding}" y="{summary_line_y}">{escape(line)}</tspan>')
    lines.append("</text>")

    footer_text = "Word 导出保留当前卡片展示样式"
    footer_y = height - 34
    lines.append(
        f'<text x="{padding}" y="{footer_y}" font-size="{meta_font}" font-family="Arial, \'Noto Sans SC\', \'Microsoft YaHei\', sans-serif" fill="#64748b">{escape(footer_text)}</text>'
    )
    lines.append("</svg>")
    return "".join(lines), height


def render_card_png_bytes(card: Dict[str, Any], width: int = CARD_RENDER_WIDTH) -> Tuple[bytes, int, int]:
    """
    将卡片渲染为 PNG 图片。
    """
    svg, height = _build_card_svg(card, width=width)
    node_script = r"""
const sharp = require("sharp");
const chunks = [];
process.stdin.on("data", (chunk) => chunks.push(chunk));
process.stdin.on("end", async () => {
  try {
    const input = Buffer.concat(chunks);
    const png = await sharp(input).png().toBuffer();
    process.stdout.write(png);
  } catch (error) {
    process.stderr.write(String(error && error.stack ? error.stack : error));
    process.exit(1);
  }
});
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        input=svg.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=_frontend_root(),
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="ignore").strip()
        raise RuntimeError(f"render card image failed: {stderr or 'unknown error'}")
    return completed.stdout, CARD_RENDER_WIDTH, height

