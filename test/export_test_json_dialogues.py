"""
@Date: 2026-04-20
@author: lixinyang

批量读取 test 目录下的测试 JSON 文件，将其中的 speakers 按顺序导出为 txt。

输出格式:
    speaker_id: speaker_content_clean

规则:
    - 仅处理 test 目录下的 .json 文件。
    - 优先读取 result.speakers[*].speaker_content_clean。
    - 如果没有 speaker_content_clean，则回退到 speaker_content。
    - 每条说话记录单独一行，不同 speaker 之间自然换行，模拟对话。
    - 输出文件与 JSON 同名，仅扩展名改为 .txt。
"""

import json
import sys
from pathlib import Path
from typing import Any, Iterable


CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def iter_test_json_files() -> Iterable[Path]:
    """
    遍历 test 目录下可导出的 JSON 文件。

    这里只处理文件名以 .json 结尾、且不是临时输出文件的文件。
    """
    for path in sorted(CURRENT_DIR.glob("*.json")):
        if path.name.startswith("."):
            continue
        yield path


def load_json_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def render_dialogue_text(obj: dict[str, Any]) -> str:
    """
    将 JSON 中的 result.speakers 转成适合阅读的对话文本。
    """
    result = obj.get("result") or {}
    speakers = result.get("speakers") or []

    lines: list[str] = []
    for item in speakers:
        if not isinstance(item, dict):
            continue

        speaker_id = str(item.get("speaker_id", "")).strip()
        speaker_content_clean = item.get("speaker_content_clean")
        speaker_content = item.get("speaker_content", "")

        text = speaker_content_clean if isinstance(speaker_content_clean, str) and speaker_content_clean.strip() else speaker_content
        text = str(text).strip()
        if not text:
            continue

        if not speaker_id:
            speaker_id = str(item.get("id", "")).strip() or "unknown"

        lines.append(f"speaker_{speaker_id}: {text}")

    return "\n".join(lines) + ("\n" if lines else "")


def export_dialogues() -> None:
    """
    批量导出 test 目录下所有 JSON 为 txt。
    """
    exported = 0
    skipped = 0

    for json_path in iter_test_json_files():
        try:
            obj = load_json_file(json_path)
        except Exception as e:
            print(f"[SKIP] 无法读取 JSON: {json_path.name}, error={e}")
            skipped += 1
            continue

        if not isinstance(obj, dict) or "result" not in obj or "speakers" not in (obj.get("result") or {}):
            print(f"[SKIP] 不是目标结构的 JSON: {json_path.name}")
            skipped += 1
            continue

        dialogue_text = render_dialogue_text(obj)
        if not dialogue_text.strip():
            print(f"[SKIP] 没有可导出的 speakers: {json_path.name}")
            skipped += 1
            continue

        txt_path = json_path.with_suffix(".txt")
        try:
            with txt_path.open("w", encoding="utf-8") as f:
                f.write(dialogue_text)
            print(f"[OK] {json_path.name} -> {txt_path.name}")
            exported += 1
        except Exception as e:
            print(f"[FAIL] 写入失败: {txt_path.name}, error={e}")
            skipped += 1

    print(f"\n完成：导出 {exported} 个文件，跳过 {skipped} 个文件。")


if __name__ == "__main__":
    export_dialogues()
