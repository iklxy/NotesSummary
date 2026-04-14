"@Date:2026-04-14"
"@Author:lixinyang"

import os
import sys
import json

import dotenv


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Fewshot import select_fewshot_samples, build_fewshot_prompt_block


dotenv.load_dotenv()


def run_test_fewshot() -> None:
    project_id = 1
    interview_id = 1

    print(f"[TEST-FEW] 测试项目 {project_id}、访谈 {interview_id} 的 few-shot 选择情况")

    cases = [
        {"question_id": 1, "question_type": "OPEN", "research_phase": None, "intent_id": 1},
        {"question_id": 2, "question_type": "OPEN", "research_phase": None, "intent_id": 2},
        {"question_id": 3, "question_type": "OPEN", "research_phase": None, "intent_id": 3},
        {"question_id": 4, "question_type": "OPEN", "research_phase": None, "intent_id": 1},
        {"question_id": 5, "question_type": "OPEN", "research_phase": None, "intent_id": 3},
    ]

    for case in cases:
        qid = case["question_id"]
        intent_id = case["intent_id"]
        print(f"\n[TEST-FEW] ------- question_id={qid}, intent_id={intent_id} -------")

        samples = select_fewshot_samples(
            project_id=project_id,
            question_id=qid,
            question_type=case["question_type"],
            research_phase=case["research_phase"],
            intent_id=intent_id,
            limit=2,
        )

        print(f"[TEST-FEW] 选出样本数量: {len(samples)}")
        for idx, s in enumerate(samples, start=1):
            print(f"[TEST-FEW] 样本 {idx}: id={s.get('id')}, project_id={s.get('project_id')}, "
                  f"question_id={s.get('question_id')}, intent_id={s.get('intent_id')}, "
                  f"quality_score={s.get('quality_score')}, source_kind={s.get('source_kind')}")

        prompt_block = build_fewshot_prompt_block(samples)
        print("[TEST-FEW] Prompt 片段预览:")
        print(prompt_block)


if __name__ == "__main__":
    run_test_fewshot()

