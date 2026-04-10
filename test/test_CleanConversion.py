"@Date: 2026-04-10"
"@Author: lixinyang"
""
import os
import sys
import json

import dotenv

# 确保可以从项目根目录导入业务模块
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from DbAccess import get_interview_by_id
from CleanConversion import clean_file_content_json


dotenv.load_dotenv()


def test_clean_conversion_for_interview() -> None:
    """
    使用 interview_id 测试调用 Claude 对 speakers 进行纠错与清洗，
    并将清洗后的 JSON 结果输出到本地文件。

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

    file_content = interview.get("file_content")
    if not file_content:
        print(f"访谈记录 file_content 为空，id={interview_id}")
        return

    print(f"开始对访谈 {interview_id} 的 speakers 进行清洗")

    # 可根据需要指定说话人角色映射，例如 1=interviewer, 2=interviewee
    speaker_roles = {
        "1": "interviewer",
        "2": "interviewee",
    }

    # term_hints 可以根据项目实际从配置或数据库中加载，这里仅作为示例保留空列表
    term_hints = []

    try:
        updated_json = clean_file_content_json(
            file_content_json=file_content,
            speaker_roles=speaker_roles,
            term_hints=term_hints,
        )
    except Exception as e:
        print(f"调用模型进行清洗时出错: {e}")
        return

    try:
        updated_obj = json.loads(updated_json)
    except Exception:
        updated_obj = None

    output_path = os.path.join(CURRENT_DIR, f"cleaned_interview_{interview_id}.json")
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            if updated_obj:
                json.dump(updated_obj, f, ensure_ascii=False, indent=2)
            else:
                f.write(updated_json)
        print(f"已将清洗后的结果输出到文件: {output_path}")
    except Exception as e:
        print(f"写入本地 JSON 文件失败: {e}")


if __name__ == "__main__":
    test_clean_conversion_for_interview()
