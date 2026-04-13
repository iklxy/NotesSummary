"@Date:2026-04-13"
"@author:lixinyang"

import os
import sys

import dotenv


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from GenerateNotes import run_generate_notes_for_interview, pretty_print_notes_results


dotenv.load_dotenv()


def run_test_generate_notes() -> None:
    interview_id_str = os.getenv("TEST_INTERVIEW_ID")
    if not interview_id_str:
        raise RuntimeError("请在 .env 中配置 TEST_INTERVIEW_ID 以指定测试访谈 ID")

    interview_id = int(interview_id_str)
    print(f"[TEST-NOTES] 使用访谈 ID = {interview_id} 测试 Notes 生成流程")

    results = run_generate_notes_for_interview(interview_id=interview_id, top_k=10)
    if not results:
        print("[TEST-NOTES] 未生成任何 Notes 结果")
        return

    pretty_print_notes_results(results)


if __name__ == "__main__":
    run_test_generate_notes()

