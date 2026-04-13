"@Date:2026-04-13"
"@author:lixinyang"

import os
import sys
from typing import List, Dict, Any

import dotenv


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from RagIndex import index_interview_summary, retrieve_segments_for_question


dotenv.load_dotenv()


def run_simple_rag_test() -> None:
    interview_id_str = os.getenv("TEST_INTERVIEW_ID", "1")
    interview_id = int(interview_id_str)

    print(f"[TEST] 使用访谈 ID = {interview_id} 进行简单 RAG 检索测试")

    indexed_count = index_interview_summary(interview_id)
    print(f"[TEST] 索引构建完成，本次共写入或更新 {indexed_count} 条向量")

    questions: List[str] = [
        "根据访谈内容，艾德生物2025年国内整体营收规模大约是多少？其中分子诊断业务和IHC业务各自的占比及大致金额是多少？",
        "针对Claudin 18.2靶点，访谈中提到的艾德生物定价策略变化是怎样的？其销售额是否达到了药企预期的2000万目标？",
        "在PCR肺癌检测领域，艾德生物占据高市场份额的核心产品特点是什么？访谈中提到了哪些关于基因检测数量的细节？",
        "访谈者提到的艾德生物PCR和NGS两个平台的增长率分别是多少？为什么公司在NGS增长不高的情况下仍坚持投入？",
        "在PD-L1抗体检测上，访谈中对艾德自研抗体与进口抗体（如22C3）的性能对比评价是什么？医院在选择这类产品时的主要决策因素有哪些？",
    ]

    for idx, q in enumerate(questions, start=1):
        if not q.strip():
            print(f"\n[TEST] 问题 {idx} 未填写，跳过检索")
            continue

        print(f"\n[TEST] ===== 问题 {idx} =====")
        print(f"[TEST] 问题内容: {q}")

        segments: List[Dict[str, Any]] = retrieve_segments_for_question(
            interview_id=interview_id,
            question_text=q,
            top_k=5,
        )

        if not segments:
            print("[TEST] 未检索到任何相关片段")
            continue

        for rank, seg in enumerate(segments, start=1):
            text = seg.get("text", "")
            speaker = seg.get("speaker", "")
            score = seg.get("score", 0.0)
            preview = text.replace("\n", " ")
            print(
                f"[TEST] Top{rank} score={score:.4f} speaker={speaker} "
                f"summary_id={seg.get('summary_id')} text={preview}"
            )


if __name__ == "__main__":
    run_simple_rag_test()
