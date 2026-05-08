"""
@Date: 2026-05-08
@Author: lixinyang

访谈级日志记录工具。

用于将引擎、工作流、清洗、Notes、KBQ、Minutes 等阶段日志按访谈 ID
拆分落盘，方便单访谈排查与回放。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Optional


ROOT_DIR = Path(__file__).resolve().parent
LOG_ROOT = ROOT_DIR / "runtime" / "logs"
INTERVIEW_LOG_DIR = LOG_ROOT / "interviews"
SYSTEM_LOG_PATH = LOG_ROOT / "system.log"
_LOG_LOCK = Lock()


def _ensure_log_dir() -> None:
    """
    确保日志目录存在。

    返回:
        无。
    """
    INTERVIEW_LOG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_ROOT.mkdir(parents=True, exist_ok=True)


def _build_log_line(
    component: str,
    subject_id: Optional[int],
    message: str,
    subject_label: str = "interview_id",
) -> str:
    """
    构造统一格式的日志行。

    参数:
        component: 日志来源组件名。
        subject_id: 记录对象 ID；若为 None 则写为 -。
        message: 日志内容。
        subject_label: 记录对象字段名，默认 `interview_id`。

    返回:
        格式化后的单行日志字符串。
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject_label = subject_label.strip() or "interview_id"
    subject_value = subject_id if subject_id is not None else "-"
    return f"{timestamp} [{component}] {subject_label}={subject_value} {message}"


def _write_line(path: Path, line: str) -> None:
    """
    线程安全地追加一行日志到指定文件。

    参数:
        path: 目标日志文件路径。
        line: 待写入的日志文本。

    返回:
        无。
    """
    with _LOG_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def log_interview(
    component: str,
    interview_id: Optional[int],
    message: str,
    subject_label: str = "interview_id",
) -> None:
    """
    输出访谈级日志，同时写入对应访谈的独立日志文件。

    参数:
        component: 日志来源组件名，例如 WORKFLOW、TRANSCRIBE、NOTES。
        interview_id: 访谈 ID；若为空则只输出到系统日志。
        message: 日志内容。
        subject_label: 日志对象字段名，默认 `interview_id`。

    返回:
        无。
    """
    _ensure_log_dir()
    line = _build_log_line(component, interview_id, message, subject_label=subject_label)
    print(line, flush=True)
    if interview_id is None:
        _write_line(SYSTEM_LOG_PATH, line)
    else:
        _write_line(INTERVIEW_LOG_DIR / f"interview_{interview_id}.log", line)
