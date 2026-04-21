"@Date:2026-04-10"
"@author:lixinyang"

import requests
import uuid
import json
import time

from config import config


def _build_headers() -> dict[str, str]:
    return {"Authorization": "Bearer; {}".format(config.ASR_ACCESS_KEY)}


def submit_task(audio_url: str):
    """
    提交异步语音识别任务。

    参数:
        audio_url: 已经上传到 TOS 后的音频预签名 URL，供 ASR 服务拉取音频使用。

    返回:
        由火山 ASR 提交接口返回的任务 ID，用于后续查询任务状态。

    关键逻辑:
        按照 openspeech 接口协议构造请求体，并调用 /submit 接口提交异步识别任务。
    """
    request_body = {
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
            "boosting_table_name":"45e58261-236b-43f5-933f-9a90ab5781f0"
        },
        "additions": {
            "with_speaker_info": "True",
        },
    }

    resp = requests.post(config.VOLCANO_SERVICE_URL + '/submit', data=json.dumps(request_body), headers=_build_headers())
    try:
        resp_dic = resp.json()
    except Exception:
        raise RuntimeError(f"提交接口返回非 JSON：{resp.status_code}, {resp.text}")

    print("提交响应：", resp_dic)
    if "resp" not in resp_dic or "id" not in resp_dic["resp"]:
        raise RuntimeError(f"提交失败，未获取到任务 ID：{resp_dic}")

    task_id = resp_dic["resp"]["id"]
    print("任务 ID:", task_id)
    return task_id


def query_task(task_id):
    query_dic = {
        "appid": config.ASR_APP_KEY,
        "token": config.ASR_ACCESS_KEY,
        "id": task_id,
        "cluster": config.VOLCANO_CLUSTER,
    }

    query_req = json.dumps(query_dic)
    print("查询请求体：", query_req)
    resp = requests.post(config.VOLCANO_SERVICE_URL + '/query', data=query_req, headers=_build_headers())

    try:
        resp_dic = resp.json()
    except Exception:
        raise RuntimeError(f"查询接口返回非 JSON：{resp.status_code}, {resp.text}")

    print("查询响应：", resp_dic)
    return resp_dic


def _extract_int(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_utterance_bounds(utt):
    """
    从单条 utterance 中提取起止时间。

    优先使用 utterance 级别的 start_time / end_time；
    如果缺失，则退化到 words 级别的最小/最大时间。
    """
    if not isinstance(utt, dict):
        return None, None

    start_time = _extract_int(utt.get("start_time"))
    end_time = _extract_int(utt.get("end_time"))

    if start_time is not None or end_time is not None:
        return start_time, end_time

    words = utt.get("words")
    if not isinstance(words, list):
        return None, None

    word_starts = []
    word_ends = []
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


def _normalize_bounds(start_time, end_time):
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


def run_asr(audio_url: str):
    """
    基于给定的音频 URL 执行异步语音识别流程。

    参数:
        audio_url: 已经上传到 TOS 的音频预签名 URL。

    返回:
        一个包含整场文本和按说话人轮次聚合内容的字典:
        {
            "full_text": str,                 # 整场转写文本
            "speakers": [
                {
                    "id": int,               # 说话轮次 ID，按时间顺序从 1 递增
                    "speaker_id": str,        # 说话人 ID，例如 "1" / "2"
                    "speaker_content": str    # 当前轮次中该说话人连续说的文本
                },
                ...
            ]
        }

    关键逻辑:
        1. 调用 submit_task 提交异步识别任务，获取 task_id。
        2. 周期性调用 query_task 轮询任务状态，直到成功、失败或超时。
    """
    task_id = submit_task(audio_url)
    start_time = time.time()
    text = ""
    while True:
        time.sleep(2)
        resp_dic = query_task(task_id)
        resp_obj = resp_dic.get("resp", {})
        code = resp_obj.get("code")

        if code == 1000:
            text = resp_obj.get("text") or ""
            utterances = resp_obj.get("utterances") or []
            if not text:
                parts = []
                for utt in utterances:
                    if isinstance(utt, dict):
                        if utt.get("text"):
                            parts.append(utt["text"])
                        elif isinstance(utt.get("words"), list):
                            words = [w.get("text", "") for w in utt["words"] if isinstance(w, dict) and w.get("text")]
                            if words:
                                parts.append("".join(words))
                if parts:
                    text = "\n".join(parts)

            segments: list[dict] = []
            current_speaker_id: str | None = None
            current_content = ""
            current_start_time: int | None = None
            current_end_time: int | None = None
            segment_id = 0

            for utt in utterances:
                if not isinstance(utt, dict):
                    continue
                additions = utt.get("additions") or {}
                speaker_id_raw = additions.get("speaker")
                if speaker_id_raw is None:
                    continue
                speaker_id = str(speaker_id_raw)

                utt_text = utt.get("text")
                if not utt_text and isinstance(utt.get("words"), list):
                    words = [w.get("text", "") for w in utt["words"] if isinstance(w, dict) and w.get("text")]
                    if words:
                        utt_text = "".join(words)
                if not utt_text:
                    continue

                utt_start_time, utt_end_time = _normalize_bounds(*_extract_utterance_bounds(utt))

                if current_speaker_id is None:
                    current_speaker_id = speaker_id
                    current_content = utt_text
                    current_start_time = utt_start_time
                    current_end_time = utt_end_time
                    continue

                if speaker_id == current_speaker_id:
                    if current_content:
                        current_content = f"{current_content} {utt_text}"
                    else:
                        current_content = utt_text
                    if current_start_time is None:
                        current_start_time = utt_start_time
                    elif utt_start_time is not None:
                        current_start_time = min(current_start_time, utt_start_time)
                    if current_end_time is None:
                        current_end_time = utt_end_time
                    elif utt_end_time is not None:
                        current_end_time = max(current_end_time, utt_end_time)
                else:
                    seg_start_time, seg_end_time = _normalize_bounds(current_start_time, current_end_time)
                    segment_id += 1
                    segments.append(
                        {
                            "id": segment_id,
                            "speaker_id": current_speaker_id,
                            "speaker_content": current_content,
                            "start_time": seg_start_time,
                            "end_time": seg_end_time,
                        }
                    )
                    current_speaker_id = speaker_id
                    current_content = utt_text
                    current_start_time = utt_start_time
                    current_end_time = utt_end_time

            if current_speaker_id is not None and current_content:
                seg_start_time, seg_end_time = _normalize_bounds(current_start_time, current_end_time)
                segment_id += 1
                segments.append(
                    {
                        "id": segment_id,
                        "speaker_id": current_speaker_id,
                        "speaker_content": current_content,
                        "start_time": seg_start_time,
                        "end_time": seg_end_time,
                    }
                )

            print("识别成功")
            if text:
                print("识别到整场文本内容")
            else:
                print("未在返回结果中找到文本内容")

            return {
                "full_text": text or "",
                "speakers": segments,
            }
        elif code is not None and code < 2000:
            print("识别失败，code=", code)
            return {
                "full_text": "",
                "speakers": [],
            }

        if time.time() - start_time > 300:
            print("等待超时（>300s）")
            return {
                "full_text": "",
                "speakers": [],
            }
