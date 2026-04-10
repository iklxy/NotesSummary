"@Date:2026-04-10"
"@author:lixinyang"

import os
import json

import dotenv

from VolcUpload import (
    upload_local_file,
    build_local_file_path,
    build_object_key,
)
from DbAccess import (
    get_interview_by_id,
    update_interview_after_upload,
)   


dotenv.load_dotenv()


def test_upload_for_interview() -> None:
    """
    使用 interview_id 测试本地音/视频文件上云以及写入数据库的完整流程。

    配置约定:
        - TEST_INTERVIEW_ID: 需要测试的 bh_project_interview.id。
        - LOCAL_AUDIO_ROOT: 本地文件根目录，默认 ./audio。
        - TOS_AUDIO_PREFIX: TOS 对象前缀，例如 audio。
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

    local_file_path = build_local_file_path(project_id, interview_id, file_name)
    object_key = build_object_key(project_id, interview_id, file_name)

    print("开始上传本地文件到 TOS")
    print(f"local_file_path = {local_file_path}")
    print(f"object_key      = {object_key}")

    result = upload_local_file(local_file_path, object_key)
    print("上传结果 JSON：")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result.get("success"):
        print("上传失败，不进行数据库更新")
        return

    audio_url = result.get("data", {}).get("audio_url")

    try:
        update_interview_after_upload(
            interview_id=interview_id,
            object_key=object_key,
            status=1,
            file_id=object_key,
            audio_url=audio_url,
        )
        print("数据库更新成功: file_path / status 已写入")
    except Exception as e:
        print(f"数据库更新失败: {e}")
        return

    updated = get_interview_by_id(interview_id)
    print("更新后的访谈记录：")
    print(json.dumps(updated, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    test_upload_for_interview()

