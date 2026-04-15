"@Date: 2026-04-15"
"@Author: lixinyang"

from typing import Any, List, Optional

from pydantic import BaseModel


class RunInterviewResponse(BaseModel):
    """
    /api/interviews/{interview_id}/run 接口的返回结果模型。

    字段:
        success:
            布尔值，表示工作流是否整体执行成功。
        summary_inserted:
            可选，写入 bh_project_interview_summary 的记录数。
        notes_inserted:
            可选，写入 bh_project_interview_notes 的记录数。
        message:
            可选，在失败或部分失败时的人类可读错误信息。
    """
    success: bool
    summary_inserted: Optional[int] = None
    notes_inserted: Optional[int] = None
    message: Optional[str] = None


class NoteItem(BaseModel):
    """
    单条 Notes 结果的结构。

    字段:
        notes_id:
            Notes 主键 ID，对应 bh_project_interview_notes.id。
        intent_id:
            可选，本条 Notes 对应的意图 ID。
        note_json:
            LLM 生成的 Notes JSON 内容，结构由引擎服务定义。
        confidence:
            可选，模型置信度，0–1 的小数。
        status:
            可选，Notes 状态，例如 0 自动生成、1 已通过、4 错误等。
    """
    notes_id: int
    intent_id: Optional[int] = None
    note_json: Any
    confidence: Optional[float] = None
    status: Optional[int] = None


class QuestionWithNotes(BaseModel):
    """
    带有 Notes 列表的题目结构，用于按题目聚合展示 Notes。

    字段:
        question_id:
            题目主键 ID，对应 bh_project_question.id。
        question_order:
            题目在访谈中的顺序，用于前端排序展示。
        question_text:
            题目内容。
        question_type:
            可选，题目类型，例如 OPEN 等。
        intent_id:
            可选，题目对应的意图 ID。
        research_phase:
            可选，研究阶段或子场景标记。
        notes:
            该题目下的 Notes 列表，每项为 NoteItem。
    """
    question_id: int
    question_order: int
    question_text: str
    question_type: Optional[str] = None
    intent_id: Optional[int] = None
    research_phase: Optional[str] = None
    notes: List[NoteItem]


class InterviewNotesResponse(BaseModel):
    """
    /api/interviews/{interview_id}/notes 接口的返回结果模型。

    字段:
        interview_id:
            访谈主键 ID，对应 bh_project_interview.id。
        project_id:
            可选，所属项目 ID，对应 bh_project.id。
        questions:
            题目及其 Notes 列表，元素为 QuestionWithNotes。
    """
    interview_id: int
    project_id: Optional[int] = None
    questions: List[QuestionWithNotes]


class QuestionItem(BaseModel):
    """
    单条题目结构，用于 /api/interviews/{interview_id}/questions 接口。

    字段:
        id:
            题目主键 ID，对应 bh_project_question.id。
        project_interview_id:
            所属访谈 ID，对应 bh_project_interview.id。
        question_order:
            题目序号，用于排序展示。
        question_text:
            题目内容。
        question_type:
            可选，题目类型，例如 OPEN 等。
        research_phase:
            可选，研究阶段或子场景标记。
        intent_id:
            可选，题目对应的意图 ID。
    """
    id: int
    project_interview_id: int
    question_order: int
    question_text: str
    question_type: Optional[str] = None
    research_phase: Optional[str] = None
    intent_id: Optional[int] = None


class InterviewQuestionsResponse(BaseModel):
    """
    /api/interviews/{interview_id}/questions 接口的返回结果模型。

    字段:
        interview_id:
            访谈主键 ID。
        questions:
            该访谈下的题目列表，元素为 QuestionItem。
    """
    interview_id: int
    questions: List[QuestionItem]
