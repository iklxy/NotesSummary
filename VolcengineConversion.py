"@Date: 2026-04-10"
"@Author: lixinyang"


import json
import time
from typing import Any, Dict, List, Tuple

import requests

from config import config


# ----------------------------------------------------------------------
# 请求构造与接口调用
# ----------------------------------------------------------------------
def _build_headers() -> dict[str, str]:
    """
    构造调用火山 ASR 接口所需的 HTTP 请求头。

    参数:
        无。鉴权信息统一从 `config.ASR_ACCESS_KEY` 读取。

    返回:
        请求头字典，当前仅包含 Bearer 鉴权头。
    """
    return {"Authorization": "Bearer; {}".format(config.ASR_ACCESS_KEY)}


def _build_submit_body(audio_url: str) -> Dict[str, Any]:
    """
    构造异步 ASR 提交任务的请求体。

    参数:
        audio_url: 已上传到 TOS 或其他可访问存储上的音频 URL，
            ASR 服务将通过该地址拉取音频文件。

    返回:
        符合当前火山 ASR 接口协议的请求体字典。
    """
    return {
        "app": {
            "appid": config.ASR_APP_KEY,
            "token": config.ASR_ACCESS_KEY,
            "cluster": config.VOLCANO_CLUSTER,
        },
        "user": {
            "uid": "388808087185088_demo",
        },
        "audio": {
            "format": "wav",
            "url": audio_url,
        },
        "request": {
            "boosting_table_name": "45e58261-236b-43f5-933f-9a90ab5781f0",
        },
        "additions": {
            "with_speaker_info": "True",
        },
    }


def _build_query_body(task_id: str) -> Dict[str, Any]:
    """
    构造异步 ASR 查询任务状态的请求体。

    参数:
        task_id: 提交 ASR 任务后返回的任务 ID。

    返回:
        用于 `/query` 接口的请求体字典。
    """
    return {
        "appid": config.ASR_APP_KEY,
        "token": config.ASR_ACCESS_KEY,
        "id": task_id,
        "cluster": config.VOLCANO_CLUSTER,
    }


def _post_json(url: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """
    以 JSON 形式发送 POST 请求，并强制解析响应为 JSON。

    参数:
        url: 请求目标地址。
        body: 需要提交的 JSON 请求体字典。

    返回:
        解析后的响应 JSON 字典。

    异常:
        RuntimeError: 当接口返回非 JSON 内容时抛出。
    """
    response = requests.post(url, data=json.dumps(body), headers=_build_headers())
    try:
        return response.json()
    except Exception:
        raise RuntimeError(f"接口返回非 JSON：{response.status_code}, {response.text}")


def submit_task(audio_url: str) -> str:
    """
    提交异步语音识别任务。

    参数:
        audio_url: 已上传好的音频 URL，供 ASR 服务异步拉取。

    返回:
        火山 ASR 返回的任务 ID，用于后续轮询查询。

    异常:
        RuntimeError: 当提交成功响应中未返回任务 ID 时抛出。
    """
    response = _post_json(config.VOLCANO_SERVICE_URL + "/submit", _build_submit_body(audio_url))
    print("提交响应：", response)
    if "resp" not in response or "id" not in response["resp"]:
        raise RuntimeError(f"提交失败，未获取到任务 ID：{response}")

    task_id = response["resp"]["id"]
    print("任务 ID:", task_id)
    return task_id


def query_task(task_id: str) -> Dict[str, Any]:
    """
    查询异步语音识别任务状态。

    参数:
        task_id: 提交 ASR 后返回的任务 ID。

    返回:
        查询接口返回的完整响应 JSON 字典。
    """
    request_body = _build_query_body(task_id)
    print("查询请求体：", json.dumps(request_body))
    response = _post_json(config.VOLCANO_SERVICE_URL + "/query", request_body)
    print("查询响应：", response)
    return response


# ----------------------------------------------------------------------
# 响应解析与标准化
# ----------------------------------------------------------------------
def _extract_int(value: Any) -> int | None:
    """
    将任意值安全地解析为整数。

    参数:
        value: 原始输入值，允许为数字、字符串、布尔值或 `None`。

    返回:
        成功时返回整数；无法转换时返回 `None`。
        布尔值会被视为无效输入并返回 `None`。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_utterance_bounds(utterance: Dict[str, Any]) -> Tuple[int | None, int | None]:
    """
    从单条 utterance 中提取起止时间。

    参数:
        utterance: 单条 utterance 字典，可能包含：
            - start_time / end_time: utterance 级别起止时间
            - words: 词级时间列表

    返回:
        `(start_time, end_time)` 元组。
        若 utterance 级别时间缺失，则退化为基于 `words` 的最小/最大时间。
        若完全无法解析时间，则返回 `(None, None)`。
    """
    if not isinstance(utterance, dict):
        return None, None

    start_time = _extract_int(utterance.get("start_time"))
    end_time = _extract_int(utterance.get("end_time"))
    if start_time is not None or end_time is not None:
        return start_time, end_time

    words = utterance.get("words")
    if not isinstance(words, list):
        return None, None

    word_starts: List[int] = []
    word_ends: List[int] = []
    for word in words:
        if not isinstance(word, dict):
            continue
        word_start = _extract_int(word.get("start_time"))
        word_end = _extract_int(word.get("end_time"))
        if word_start is not None:
            word_starts.append(word_start)
        if word_end is not None:
            word_ends.append(word_end)

    return (
        min(word_starts) if word_starts else None,
        max(word_ends) if word_ends else None,
    )


def _normalize_bounds(start_time: int | None, end_time: int | None) -> Tuple[int | None, int | None]:
    """
    规范化起止时间边界，保证输出区间可用且有序。

    参数:
        start_time: 起始时间，允许为 `None`。
        end_time: 结束时间，允许为 `None`。

    返回:
        规范化后的 `(start_time, end_time)` 元组。
        若只有一端存在，则另一端会补齐为相同值。
        若两端都不存在，则返回 `(None, None)`。
    """
    if start_time is None and end_time is None:
        return None, None
    if start_time is None:
        start_time = end_time
    if end_time is None:
        end_time = start_time
    if start_time is None or end_time is None:
        return None, None
    if end_time < start_time:
        start_time, end_time = end_time, start_time
    return start_time, end_time


def _extract_utterance_text(utterance: Dict[str, Any]) -> str:
    """
    从单条 utterance 中提取可用文本。

    参数:
        utterance: 单条 utterance 字典，可能包含：
            - text: utterance 级别文本
            - words: 词级文本列表

    返回:
        该 utterance 对应的文本字符串。
        若 `text` 为空，则尝试从 `words` 拼接；仍失败时返回空字符串。
    """
    text = utterance.get("text")
    if text:
        return str(text)

    words = utterance.get("words")
    if not isinstance(words, list):
        return ""

    parts = [word.get("text", "") for word in words if isinstance(word, dict) and word.get("text")]
    return "".join(parts) if parts else ""


def _extract_full_text(response_payload: Dict[str, Any], utterances: List[Dict[str, Any]]) -> str:
    """
    从 ASR 成功响应中提取整场转录文本。

    参数:
        response_payload: `resp` 节点字典，通常来自查询接口返回值中的 `resp`。
        utterances: 已提取出的 utterance 列表，用于在 `resp.text` 缺失时回退拼接。

    返回:
        整场转录文本字符串。
        优先使用 `resp.text`；若为空，则按 utterance 文本拼接。
    """
    text = response_payload.get("text") or ""
    if text:
        return text

    parts: List[str] = []
    for utterance in utterances:
        if not isinstance(utterance, dict):
            continue
        utterance_text = _extract_utterance_text(utterance)
        if utterance_text:
            parts.append(utterance_text)
    return "\n".join(parts) if parts else ""


def _build_segments(utterances: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    将 utterance 列表按连续说话人聚合为标准 `speakers` 结构。

    参数:
        utterances: ASR 返回的 utterance 列表。每条 utterance 通常包含：
            - additions.speaker: 说话人 ID
            - text 或 words: utterance 文本
            - start_time / end_time 或词级时间

    返回:
        聚合后的说话轮次列表。每个元素包含：
            - id: 轮次 ID，按时间顺序递增
            - speaker_id: 说话人 ID
            - speaker_content: 连续发言文本
            - start_time: 本轮开始时间
            - end_time: 本轮结束时间
    """
    segments: List[Dict[str, Any]] = []
    current_speaker_id: str | None = None
    current_content = ""
    current_start_time: int | None = None
    current_end_time: int | None = None
    segment_id = 0

    for utterance in utterances:
        if not isinstance(utterance, dict):
            continue

        additions = utterance.get("additions") or {}
        speaker_id_raw = additions.get("speaker")
        if speaker_id_raw is None:
            continue

        speaker_id = str(speaker_id_raw)
        utterance_text = _extract_utterance_text(utterance)
        if not utterance_text:
            continue

        utterance_start, utterance_end = _normalize_bounds(*_extract_utterance_bounds(utterance))

        if current_speaker_id is None:
            current_speaker_id = speaker_id
            current_content = utterance_text
            current_start_time = utterance_start
            current_end_time = utterance_end
            continue

        if speaker_id == current_speaker_id:
            current_content = f"{current_content} {utterance_text}" if current_content else utterance_text
            if current_start_time is None:
                current_start_time = utterance_start
            elif utterance_start is not None:
                current_start_time = min(current_start_time, utterance_start)

            if current_end_time is None:
                current_end_time = utterance_end
            elif utterance_end is not None:
                current_end_time = max(current_end_time, utterance_end)
            continue

        segment_start, segment_end = _normalize_bounds(current_start_time, current_end_time)
        segment_id += 1
        segments.append(
            {
                "id": segment_id,
                "speaker_id": current_speaker_id,
                "speaker_content": current_content,
                "start_time": segment_start,
                "end_time": segment_end,
            }
        )

        current_speaker_id = speaker_id
        current_content = utterance_text
        current_start_time = utterance_start
        current_end_time = utterance_end

    if current_speaker_id is not None and current_content:
        segment_start, segment_end = _normalize_bounds(current_start_time, current_end_time)
        segment_id += 1
        segments.append(
            {
                "id": segment_id,
                "speaker_id": current_speaker_id,
                "speaker_content": current_content,
                "start_time": segment_start,
                "end_time": segment_end,
            }
        )

    return segments


def _parse_success_response(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 ASR 成功响应解析为 engine 统一使用的结果结构。

    参数:
        response: 查询接口返回的完整 JSON 字典。

    返回:
        标准化后的识别结果字典，包含：
            - full_text: 整场转录文本
            - speakers: 按连续说话人聚合后的发言列表
    """
    response_payload = response.get("resp", {})
    utterances = response_payload.get("utterances") or []
    full_text = _extract_full_text(response_payload, utterances)
    speakers = _build_segments(utterances)
    return {
        "full_text": full_text or "",
        "speakers": speakers,
    }


def _is_failed_code(code: Any) -> bool:
    """
    判断当前 ASR 状态码是否表示失败。

    参数:
        code: 查询接口返回的 `resp.code` 值，可能为整数、字符串或 `None`。

    返回:
        当状态码在当前协议下表示失败时返回 `True`，否则返回 `False`。
    """
    if code is None:
        return False
    try:
        return int(code) < 2000
    except (TypeError, ValueError):
        return False


# ----------------------------------------------------------------------
# 对外入口
# ----------------------------------------------------------------------
def run_asr(audio_url: str) -> Dict[str, Any]:
    """
    基于给定音频 URL 执行完整的异步语音识别流程。

    参数:
        audio_url: 已上传到 TOS 的音频预签名 URL，供火山 ASR 服务拉取使用。

    返回:
        统一格式的识别结果字典：
            - full_text: 整场转录文本
            - speakers: 按连续说话人聚合后的发言列表

        当识别失败或轮询超时时，返回空结果：
            - full_text = ""
            - speakers = []
    """
    task_id = submit_task(audio_url)
    started_at = time.time()

    while True:
        time.sleep(2)
        response = query_task(task_id)
        response_payload = response.get("resp", {})
        code = response_payload.get("code")

        if code == 1000:
            result = _parse_success_response(response)
            print("识别成功")
            if result["full_text"]:
                print("识别到整场文本内容")
            else:
                print("未在返回结果中找到文本内容")
            return result

        if _is_failed_code(code):
            print("识别失败，code=", code)
            return {"full_text": "", "speakers": []}

        if time.time() - started_at > 3600:
            print("等待超时（>3600s）")
            return {"full_text": "", "speakers": []}
