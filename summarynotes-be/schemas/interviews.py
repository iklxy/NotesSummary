"@Date: 2026-04-15"
"@Author: lixinyang"

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class RunInterviewResponse(BaseModel):
    """
    /api/interviews/{interview_id}/run 接口的返回结果模型。

    字段:
        success:
            布尔值，表示工作流是否整体执行成功。
        queued:
            可选，表示任务已提交到线程池，正在后台执行。
        summary_inserted:
            可选，写入 bh_project_interview_summary 的记录数。
        notes_inserted:
            可选，保留兼容字段，旧版 Notes 工作流的写入数。
        minutes_inserted:
            可选，写入智能纪要表的记录数。
        message:
            可选，在失败或部分失败时的人类可读错误信息。
    """
    success: bool
    queued: bool = False
    summary_inserted: Optional[int] = None
    notes_inserted: Optional[int] = None
    minutes_inserted: Optional[int] = None
    message: Optional[str] = None


class GenerateNotesResponse(BaseModel):
    """
    /api/interviews/{interview_id}/questions/{question_id}/generate-notes 接口返回值。
    """
    success: bool
    interview_id: int
    question_id: Optional[int] = None
    project_id: Optional[int] = None
    total_questions: int = 0
    generated: int = 0
    inserted: int = 0
    warnings: List[str] = Field(default_factory=list)
    message: Optional[str] = None


class GenerateMinutesResponse(BaseModel):
    """
    /api/interviews/{interview_id}/minutes/refresh 接口返回值。
    """
    success: bool
    interview_id: int
    project_id: Optional[int] = None
    outline_generated: int = 0
    generated: int = 0
    inserted: int = 0
    warnings: List[str] = Field(default_factory=list)
    message: Optional[str] = None


class InterviewCardItem(BaseModel):
    """
    单条全文模块卡片结构。
    """
    id: int
    cards_id: int
    project_id: int
    project_interview_id: int
    card_order: int
    card_title: str
    card_summary: Optional[str] = None
    generated_json: Any
    final_json: Optional[Any] = None
    review_status: Optional[str] = None
    review_comment: Optional[str] = None
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[str] = None
    updated_by: Optional[int] = None
    updated_at: Optional[str] = None


class InterviewCardsResponse(BaseModel):
    """
    /api/interviews/{interview_id}/cards 接口返回值。
    """
    interview_id: int
    project_id: Optional[int] = None
    status: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    items: List[InterviewCardItem] = Field(default_factory=list)


class InterviewCardItemCreateRequest(BaseModel):
    """
    创建一条卡片明细的请求体。
    """
    card_title: str
    card_order: Optional[int] = None
    card_summary: Optional[str] = None
    generated_json: Any
    final_json: Optional[Any] = None
    review_status: Optional[str] = None
    review_comment: Optional[str] = None
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[str] = None


class InterviewCardItemUpdateRequest(BaseModel):
    """
    更新一条卡片明细的请求体。
    """
    card_order: Optional[int] = None
    card_title: Optional[str] = None
    card_summary: Optional[str] = None
    generated_json: Optional[Any] = None
    final_json: Optional[Any] = None
    review_status: Optional[str] = None
    review_comment: Optional[str] = None
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[str] = None


class QuestionIntentItem(BaseModel):
    """
    单条 question intent 结构。
    """
    id: int
    code: str
    name: Optional[str] = None
    description: Optional[str] = None
    schema_name: Optional[str] = None
    status: Optional[int] = None


class QuestionnaireHotwordCandidateItem(BaseModel):
    """
    问卷解析得到的单条热词候选。
    """
    term: str
    normalized_term: str
    reason: Optional[str] = None
    confidence: Optional[float] = None


class QuestionnaireHotwordLoadResponse(BaseModel):
    """
    读取问卷热词候选或已审核热词的返回结果。
    """
    interview_id: int
    project_id: int
    review_required: bool = False
    candidates: List[QuestionnaireHotwordCandidateItem] = Field(default_factory=list)
    reviewed_hotwords: List[str] = Field(default_factory=list)


class QuestionnaireHotwordReviewRequest(BaseModel):
    """
    保存人工 review 后的问卷热词请求体。
    """
    hotwords: List[str] = Field(default_factory=list)


class QuestionnaireHotwordReviewResponse(BaseModel):
    """
    保存人工 review 后的问卷热词返回结果。
    """
    success: bool
    interview_id: int
    project_id: int
    reviewed_count: int = 0
    reviewed_path: Optional[str] = None
    reviewed_json_path: Optional[str] = None
    workflow_started: bool = False
    message: Optional[str] = None


class InterviewStatusResponse(BaseModel):
    """
    /api/interviews/{interview_id}/status 接口的返回结果模型。

    字段:
        interview_id:
            访谈主键 ID。
        status:
            当前处理状态，对应 bh_project_interview.status。
    """
    interview_id: int
    status: Optional[int] = None


class DeleteInterviewResponse(BaseModel):
    """
    /api/interviews/{interview_id} 删除接口返回值。
    """
    success: bool
    interview_id: int
    db_deleted: bool = False
    audio_deleted: bool = False
    local_audio_deleted: bool = False
    cloud_audio_deleted: bool = False
    qdrant_deleted: bool = False
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


class QuestionCreateItem(BaseModel):
    """
    新建题目时使用的单条输入结构。

    现在前端只提交 question_text，其余字段由后端默认写死：
        - question_type = OPEN
        - intent_id = 1
    """
    question_text: str


class QuestionCreateRequest(BaseModel):
    """
    /api/interviews/{interview_id}/questions 创建题目接口的请求体。
    """
    questions: List[QuestionCreateItem]


class QuestionCreateResponse(BaseModel):
    """
    /api/interviews/{interview_id}/questions 创建题目接口的返回值。
    """
    success: bool
    interview_id: int
    inserted: int


class QuestionDeleteResponse(BaseModel):
    """
    /api/interviews/{interview_id}/questions/{question_id} 删除接口返回值。
    """
    success: bool
    interview_id: int
    question_id: int
    question_deleted: bool = False
    fewshot_deleted: int = 0
    notes_deleted: int = 0
    message: Optional[str] = None


class FewshotEvidenceItem(BaseModel):
    """
    few-shot 样本中的单条 evidence。
    """
    summary_id: int
    speaker: Optional[str] = None
    text: str


class FewshotSampleCreateRequest(BaseModel):
    """
    创建 few-shot 冷启动种子的请求体。
    """
    intent_id: int
    summary: str
    analysis: str
    evidence: List[FewshotEvidenceItem]
    confidence: Optional[float] = 0.95
    quality_score: Optional[int] = 95
    source_kind: Optional[str] = "seed"
    notes_result_id: Optional[int] = None


class FewshotSampleCreateResponse(BaseModel):
    """
    创建 few-shot 冷启动种子的返回值。
    """
    success: bool
    interview_id: int
    question_id: int
    sample_id: int


class FewshotSampleItem(BaseModel):
    """
    few-shot 样本条目。
    """
    id: int
    project_id: int
    project_interview_id: int
    question_id: int
    question_order: Optional[int] = None
    question_text: Optional[str] = None
    question_type: Optional[str] = None
    research_phase: Optional[str] = None
    intent_id: int
    notes_result_id: Optional[int] = None
    sample_json: Any
    sample_summary: Optional[str] = None
    sample_analysis: Optional[str] = None
    evidence_count: int = 0
    quality_score: Optional[int] = None
    source_kind: Optional[str] = None
    created_time: Optional[str] = None


class InterviewFewshotSamplesResponse(BaseModel):
    """
    /api/interviews/{interview_id}/fewshot-samples 接口返回值。
    """
    interview_id: int
    samples: List[FewshotSampleItem]


class FewshotSampleDeleteResponse(BaseModel):
    """
    /api/interviews/{interview_id}/fewshot-samples/{sample_id} 删除接口返回值。
    """
    success: bool
    interview_id: int
    sample_id: int
    question_id: Optional[int] = None
    deleted: bool = False
    message: Optional[str] = None


class InterviewSummaryItem(BaseModel):
    """
    单条 summary 结构，用于前端展示与编辑回填。
    """
    id: int
    project_interview_id: int
    timestamp: Optional[str] = None
    speaker: Optional[str] = None
    text: Optional[str] = None


class InterviewSummaryResponse(BaseModel):
    """
    /api/interviews/{interview_id}/summary 接口的返回结果模型。
    """
    interview_id: int
    items: List[InterviewSummaryItem]


class InterviewMinutesItem(BaseModel):
    """
    单个纪要小点的展示结构。
    """
    order: int
    title: str
    summary: Optional[str] = None


class InterviewMinutesSection(BaseModel):
    """
    单个纪要章节的展示结构。
    """
    order: int
    title: str
    summary: Optional[str] = None
    items: List[InterviewMinutesItem] = Field(default_factory=list)


class InterviewMinutesActionItem(BaseModel):
    """
    智能纪要中的单条待办/结论。
    """
    owner: Optional[str] = None
    time: Optional[str] = None
    content: Optional[str] = None


class InterviewMinutesResponse(BaseModel):
    """
    /api/interviews/{interview_id}/overall-notes 中的智能纪要结构。
    """
    interview_id: int
    project_id: Optional[int] = None
    document_title: Optional[str] = None
    core_summary: Optional[str] = None
    minutes_text: Optional[str] = None
    outline: Any = None
    sections: List[InterviewMinutesSection] = Field(default_factory=list)
    action_items: List[InterviewMinutesActionItem] = Field(default_factory=list)
    highlights: List[str] = Field(default_factory=list)
    status: Optional[str] = None
    error_message: Optional[str] = None
    generated_at: Optional[str] = None


class SummaryUpdateRequest(BaseModel):
    """
    更新单条 summary 的请求体。
    """
    text: str


class SummaryUpdateResponse(BaseModel):
    """
    更新单条 summary 的返回结果。
    """
    success: bool
    summary: Optional[InterviewSummaryItem] = None
    reindex_succeeded: bool = False
    reindex_indexed: Optional[int] = None
    reindex_warning: Optional[str] = None
    corrections_inserted: Optional[int] = None


class OverallNotesSummaryUpdateRequest(BaseModel):
    """
    更新全文 Notes 中 A 区块的请求体。
    """
    text: str


class OverallNotesSummaryUpdateResponse(BaseModel):
    """
    更新全文 Notes 中 A 区块的返回结果。
    """
    success: bool
    interview_id: int
    note_content: Optional[str] = None


class OverallNotesKbqUpdateRequest(BaseModel):
    """
    更新全文 Notes 中单条 KBQ Notes 的请求体。
    """
    note_json: Any


class OverallNotesKbqUpdateResponse(BaseModel):
    """
    更新全文 Notes 中单条 KBQ Notes 的返回结果。
    """
    success: bool
    interview_id: int
    kbq_id: int
    note_json: Any = None


class OverallNotesMinutesUpdateRequest(BaseModel):
    """
    更新全文 Notes 中 C 区块的请求体。
    """
    minutes_json: Any


class OverallNotesMinutesUpdateResponse(BaseModel):
    """
    更新全文 Notes 中 C 区块的返回结果。
    """
    success: bool
    interview_id: int
    minutes_json: Any = None
    minutes_text: Optional[str] = None
