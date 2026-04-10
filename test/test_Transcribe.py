import os
import json

import dotenv

from VolcUpload import build_object_key, get_tos_client, bucket_name, TOS_URL_EXPIRE_SECONDS, tos
from DbAccess import get_interview_by_id, update_interview_file_content
from VolcengineConversion import run_asr


dotenv.load_dotenv()


def build_audio_format(file_name: str) -> str:
    """
    根据文件名推导音频格式。

    参数:
        file_name: 文件名，例如 "1.wav" 或 "audio.mp3"。

    返回:
        推导出的格式字符串（扩展名小写，不含点），如果无法解析则返回 "wav"。
    """
    base = file_name.rsplit("/", 1)[-1]
    if "." not in base:
        return "wav"
    ext = base.rsplit(".", 1)[-1].lower()
    if not ext:
        return "wav"
    return ext


def build_file_content_json(
    project_id: int,
    interview_id: int,
    object_key: str,
    audio_url: str,
    file_name: str,
    full_text: str,
    speakers: list[dict],
) -> str:
    """
    构造写入 bh_project_interview.file_content 字段的 JSON 字符串。

    JSON 结构:
        {
            "audio": {
                "project_id": int,
                "interview_id": int,
                "object_key": str,
                "bucket_name": str,
                "url": str,
                "format": str
            },
            "result": {
                "full_text": str,
                "speakers": [
                    {
                        "id": int,
                        "speaker_id": str,
                        "speaker_content": str
                    }
                ]
            }
        }
    """
    audio_format = build_audio_format(file_name)
    payload = {
        "audio": {
            "project_id": project_id,
            "interview_id": interview_id,
            "object_key": object_key,
            "bucket_name": bucket_name,
            "url": audio_url,
            "format": audio_format,
        },
        "result": {
            "full_text": full_text,
            "speakers": speakers,
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def test_transcribe_for_interview() -> None:
    """
    使用 interview_id 测试：
        1. 从数据库获取访谈信息与对象 key。
        2. 生成 TOS 预签名 URL。
        3. 调用 ASR 接口完成转录。
        4. 将 JSON 结果写入 bh_project_interview.file_content。

    配置约定:
        - TEST_INTERVIEW_ID: 需要测试的 bh_project_interview.id。
    """
    interview_id_str = os.getenv("TEST_INTERVIEW_ID")
    if not interview_id_str:
        print("请先在环境变量或 .env 中配置 TEST_INTERVIEW_ID")
        return

    try:
        interview_id = int(interview_id_str)
    except ValueError:
        print(f"TEST_INTERVIEW_ID 非法: {interview_id_str}")
        return

    interview = get_interview_by_id(interview_id)
    if not interview:
        print(f"找不到访谈记录，id={interview_id}")
        return

    project_id = interview.get("parse_project_id")
    if not project_id:
        print(f"访谈记录中缺少 parse_project_id，id={interview_id}")
        return

    file_name = interview.get("file_name") or f"{interview_id}.wav"

    if interview.get("file_path"):
        object_key = interview["file_path"]
    else:
        object_key = build_object_key(project_id, interview_id, file_name)

    client = get_tos_client()
    pre = client.pre_signed_url(
        tos.HttpMethodType.Http_Method_Get,
        bucket=bucket_name,
        key=object_key,
        expires=TOS_URL_EXPIRE_SECONDS,
    )
    audio_url = pre.signed_url

    print("开始调用 ASR 接口进行转录")
    print(f"audio_url = {audio_url}")
    asr_result = run_asr(audio_url) or {}
    full_text = asr_result.get("full_text", "")
    speakers = asr_result.get("speakers", [])

    print("整场转写结果：")
    print(full_text)
    if speakers:
        print("按说话人聚合结果：")
        for seg in speakers:
            print(f"speaker_{seg['speaker_id']}: {seg['speaker_content']}")

    file_content_json = build_file_content_json(
        project_id=project_id,
        interview_id=interview_id,
        object_key=object_key,
        audio_url=audio_url,
        file_name=file_name,
        full_text=full_text,
        speakers=speakers,
    )

    try:
        update_interview_file_content(interview_id, file_content_json)
        print("已将转写结果 JSON 写入 bh_project_interview.file_content")
    except Exception as e:
        print(f"写入 file_content 失败: {e}")


if __name__ == "__main__":
    test_transcribe_for_interview()
