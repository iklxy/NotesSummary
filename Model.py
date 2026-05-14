"@Date: 2026-04-24"
"@Author: lixinyang"

from typing import Any, Dict, List, Optional

from LLMProviders import BaseLLMProvider, build_provider
from ModelNotes import (
    escape_inner_quotes_in_field,
    escape_inner_quotes_in_notes_json,
    generate_ca_cells_for_sub_point,
    generate_ca_dimensions,
    generate_kbq_dimensions,
    generate_kbq_notes,
    generate_minutes_outline_from_transcript,
    generate_minutes_item_summary,
    generate_notes_for_question,
    generate_notes_for_question_with_fewshot,
    generate_overall_interview_note,
    repair_notes_json,
)
from ModelTranscript import (
    apply_correction_fallback_batch,
    build_correction_rules_block,
    build_interview_context_block,
    clean_speaker_utterance,
    clean_transcript_batch,
    correct_transcript_batch,
    extract_interview_context,
    parse_json_payload,
    strip_code_fences,
)
from config import config


class ModelClient:
    """
    大模型调用协调层。

    该类只负责：
    1. 解析运行时配置。
    2. 维护 provider 单例。
    3. 对外暴露 transcript / notes / 背景提炼接口。

    具体 provider、转录纠错和 Notes 生成逻辑已拆到独立模块。
    """

    _notes_provider: Optional[BaseLLMProvider] = None
    _notes_provider_name: Optional[str] = None
    _notes_model_name: Optional[str] = None
    _notes_api_key: Optional[str] = None
    _notes_base_url: Optional[str] = None
    _notes_config_revision: int = -1

    _transcript_provider: Optional[BaseLLMProvider] = None
    _transcript_provider_name: Optional[str] = None
    _transcript_model_name: Optional[str] = None
    _transcript_api_key: Optional[str] = None
    _transcript_base_url: Optional[str] = None
    _transcript_config_revision: int = -1

    @classmethod
    def _resolve_provider_name(cls, kind: str) -> str:
        """
        解析当前启用的 provider 名称。

        参数:
            无。配置从全局 `config` 中读取。

        返回:
            归一化后的 provider 名称，小写字符串。
        """
        if kind == "transcript":
            provider_name = (config.TRANSCRIPT_LLM_PROVIDER or config.LLM_PROVIDER or "openai").strip().lower()
        else:
            provider_name = (config.NOTES_LLM_PROVIDER or config.LLM_PROVIDER or "openai").strip().lower()
        return provider_name or "anthropic"

    @classmethod
    def _resolve_runtime_profile(cls, kind: str) -> tuple[str, Optional[str], Optional[str], Optional[str]]:
        """
        解析指定用途的运行时模型配置。

        参数:
            kind: 配置用途，`transcript` 表示纠错/清洗，`notes` 表示 Notes / minutes。

        返回:
            (provider_name, api_key, base_url, model_name) 四元组。
        """
        if kind == "transcript":
            provider_name = cls._resolve_provider_name("transcript")
            api_key = config.TRANSCRIPT_LLM_API_KEY or config.LLM_API_KEY
            base_url = config.TRANSCRIPT_LLM_BASE_URL or config.LLM_BASE_URL
            model_name = config.TRANSCRIPT_LLM_MODEL_NAME or config.LLM_MODEL_NAME
        else:
            provider_name = cls._resolve_provider_name("notes")
            api_key = config.NOTES_LLM_API_KEY or config.LLM_API_KEY
            base_url = config.NOTES_LLM_BASE_URL or config.LLM_BASE_URL
            model_name = config.NOTES_LLM_MODEL_NAME or config.LLM_MODEL_NAME
        return provider_name, api_key, base_url, model_name

    @classmethod
    def _ensure_client(cls, kind: str) -> None:
        """
        按当前运行时配置初始化或刷新 provider。

        参数:
            无。配置从全局 `config` 中读取。

        返回:
            无返回值；如果配置不完整则抛出异常。
        """
        provider_name, api_key, base_url, model_name = cls._resolve_runtime_profile(kind)
        if kind == "transcript":
            cached_provider = cls._transcript_provider
            cached_provider_name = cls._transcript_provider_name
            cached_model_name = cls._transcript_model_name
            cached_api_key = cls._transcript_api_key
            cached_base_url = cls._transcript_base_url
            cached_revision = cls._transcript_config_revision
        else:
            cached_provider = cls._notes_provider
            cached_provider_name = cls._notes_provider_name
            cached_model_name = cls._notes_model_name
            cached_api_key = cls._notes_api_key
            cached_base_url = cls._notes_base_url
            cached_revision = cls._notes_config_revision

        if (
            cached_provider is not None
            and cached_provider_name == provider_name
            and cached_model_name == model_name
            and cached_api_key == api_key
            and cached_base_url == base_url
            and cached_revision == config.revision
        ):
            return
        if not api_key or not model_name:
            if kind == "transcript":
                raise RuntimeError("TRANSCRIPT_LLM_PROVIDER / TRANSCRIPT_LLM_API_KEY / TRANSCRIPT_LLM_MODEL_NAME 未正确配置")
            raise RuntimeError("NOTES_LLM_PROVIDER / NOTES_LLM_API_KEY / NOTES_LLM_MODEL_NAME 未正确配置")
        provider = build_provider(provider_name, api_key, base_url)
        if kind == "transcript":
            cls._transcript_provider = provider
            cls._transcript_provider_name = provider_name
            cls._transcript_model_name = model_name
            cls._transcript_api_key = api_key
            cls._transcript_base_url = base_url
            cls._transcript_config_revision = config.revision
        else:
            cls._notes_provider = provider
            cls._notes_provider_name = provider_name
            cls._notes_model_name = model_name
            cls._notes_api_key = api_key
            cls._notes_base_url = base_url
            cls._notes_config_revision = config.revision

    @classmethod
    def _generate_with_kind(
        cls,
        kind: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 130000,
    ) -> str:
        """
        使用指定用途的 provider 执行一次文本生成。

        参数:
            kind: 模型用途，`transcript` 或 `notes`。
            system_prompt: 系统提示词，用于定义角色和输出规范。
            user_prompt: 用户提示词，用于描述当前任务。
            max_tokens: 本次调用允许返回的最大 token 数。

        返回:
            模型返回的文本字符串。
        """
        cls._ensure_client(kind)
        if kind == "transcript":
            provider = cls._transcript_provider
            model_name = cls._transcript_model_name
        else:
            provider = cls._notes_provider
            model_name = cls._notes_model_name
        if provider is None or model_name is None:
            raise RuntimeError("LLM provider 未正确初始化")
        return provider.generate(system_prompt, user_prompt, model_name, max_tokens=max_tokens)

    @classmethod
    def _build_project_context_block(cls, project_context: Optional[str]) -> str:
        """
        将项目背景包装成统一的 prompt 区块。

        参数:
            project_context: 已整理好的项目背景文本。

        返回:
            可直接注入 prompt 的背景块；若为空则返回空字符串。
        """
        if not project_context:
            return ""
        cleaned = project_context.strip()
        if not cleaned:
            return ""
        return f"【项目背景】\n{cleaned}\n\n"

    @classmethod
    def generate(cls, system_prompt: str, user_prompt: str) -> str:
        """
        使用当前 provider 执行一次文本生成。

        参数:
            system_prompt: 系统提示词，用于定义角色和输出规范。
            user_prompt: 用户提示词，用于描述当前任务。

        返回:
            模型返回的文本字符串。
        """
        return cls._generate_with_kind("notes", system_prompt, user_prompt)

    @classmethod
    def generate_transcript(cls, system_prompt: str, user_prompt: str) -> str:
        """
        使用 transcript 专用 provider 执行一次文本生成。

        参数:
            system_prompt: 系统提示词，用于定义角色和输出规范。
            user_prompt: 用户提示词，用于描述当前任务。

        返回:
            模型返回的文本字符串。
        """
        return cls._generate_with_kind("transcript", system_prompt, user_prompt)

    @classmethod
    def _strip_code_fences(cls, text: str) -> str:
        """
        去掉最外层 markdown code fence。

        参数:
            text: 原始文本。

        返回:
            去除 fence 后的文本。
        """
        return strip_code_fences(text)

    @classmethod
    def _parse_json_payload(cls, content: str) -> Any:
        """
        从模型输出里尽量解析 JSON。

        参数:
            content: 模型输出的原始文本。

        返回:
            解析出的 JSON 对象。
        """
        return parse_json_payload(content)

    @classmethod
    def _build_interview_context_block(cls, interview_context: Optional[Any]) -> str:
        """
        将访谈背景对象格式化为 prompt 区块。

        参数:
            interview_context: 访谈背景对象或字符串。

        返回:
            格式化后的 prompt 文本。
        """
        return build_interview_context_block(interview_context)

    @classmethod
    def _build_correction_rules_block(cls, correction_rules: Optional[List[str]]) -> str:
        """
        将兜底纠错规则格式化为 prompt 区块。

        参数:
            correction_rules: 兜底纠错规则列表。

        返回:
            格式化后的 prompt 文本。
        """
        return build_correction_rules_block(correction_rules)

    @classmethod
    def correct_transcript_batch(
        cls,
        transcript: List[Dict[str, Any]],
        term_hints: Optional[List[str]] = None,
        project_context: Optional[str] = None,
        interview_context: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        对整篇 transcript 执行主纠错。

        参数:
            transcript: 待处理的逐段记录列表。
            term_hints: 可选热词提示列表。
            project_context: 可选项目背景文本。
            interview_context: 可选访谈背景摘要。

        返回:
            带 `corrected_text`、`corrections`、`uncertain_terms` 的记录列表。
        """
        return correct_transcript_batch(
            generate_fn=cls.generate_transcript,
            project_context_block=cls._build_project_context_block(project_context),
            transcript=transcript,
            term_hints=term_hints,
            interview_context=interview_context,
        )

    @classmethod
    def apply_correction_fallback_batch(
        cls,
        transcript: List[Dict[str, Any]],
        correction_rules: Optional[List[str]] = None,
        term_hints: Optional[List[str]] = None,
        project_context: Optional[str] = None,
        interview_context: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        在主纠错后执行兜底纠错。

        参数:
            transcript: 主纠错后的逐段记录列表。
            correction_rules: 兜底纠错规则列表。
            term_hints: 可选热词提示列表。
            project_context: 可选项目背景文本。
            interview_context: 可选访谈背景摘要。

        返回:
            带 `corrected_text`、`corrections`、`uncertain_terms` 的记录列表。
        """
        return apply_correction_fallback_batch(
            generate_fn=cls.generate_transcript,
            project_context_block=cls._build_project_context_block(project_context),
            transcript=transcript,
            correction_rules=correction_rules,
            term_hints=term_hints,
            interview_context=interview_context,
        )

    @classmethod
    def clean_transcript_batch(
        cls,
        transcript: List[Dict[str, Any]],
        term_hints: Optional[List[str]] = None,
        project_context: Optional[str] = None,
        interview_context: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        对纠错结果执行轻度清洗。

        参数:
            transcript: 待清洗的逐段记录列表。
            term_hints: 可选热词提示列表。
            project_context: 可选项目背景文本。
            interview_context: 可选访谈背景摘要。

        返回:
            带 `clean_text` 的记录列表。
        """
        return clean_transcript_batch(
            generate_fn=cls.generate_transcript,
            project_context_block=cls._build_project_context_block(project_context),
            transcript=transcript,
            term_hints=term_hints,
            interview_context=interview_context,
        )

    @classmethod
    def clean_speaker_utterance(
        cls,
        speaker_text: str,
        speaker_role: Optional[str] = None,
        term_hints: Optional[List[str]] = None,
        correction_rules: Optional[List[str]] = None,
        project_context: Optional[str] = None,
        interview_context: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        兼容旧接口的单条文本处理入口。

        参数:
            speaker_text: 单条转录文本。
            speaker_role: 说话人角色标签。
            term_hints: 可选热词提示列表。
            correction_rules: 可选兜底纠错规则列表。
            project_context: 可选项目背景文本。
            interview_context: 可选访谈背景摘要。

        返回:
            兼容旧接口的单条结果字典。
        """
        return clean_speaker_utterance(
            generate_fn=cls.generate_transcript,
            project_context_block=cls._build_project_context_block(project_context),
            speaker_text=speaker_text,
            speaker_role=speaker_role,
            term_hints=term_hints,
            correction_rules=correction_rules,
            interview_context=interview_context,
        )

    @classmethod
    def extract_interview_context(
        cls,
        full_text: str,
        project_context: Optional[str] = None,
        term_hints: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        从整篇 ASR 全文中提炼访谈背景。

        参数:
            full_text: ASR 全文文本。
            project_context: 可选项目背景文本。
            term_hints: 可选热词提示列表。

        返回:
            访谈背景字典。
        """
        return extract_interview_context(
            generate_fn=cls.generate_transcript,
            project_context_block=cls._build_project_context_block(project_context),
            full_text=full_text,
            term_hints=term_hints,
        )

    @classmethod
    def generate_notes_for_question(
        cls,
        question_text: str,
        segments: List[Dict[str, Any]],
        intent_name: Optional[str] = None,
        question_type: Optional[str] = None,
        project_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        基于检索片段生成结构化 Notes。

        参数:
            question_text: 问题原文。
            segments: 检索片段列表。
            intent_name: 可选意图名称。
            question_type: 可选问题类型。
            project_context: 可选项目背景文本。

        返回:
            结构化 Notes 字典。
        """
        return generate_notes_for_question(
            generate_fn=lambda system_prompt, user_prompt: cls._generate_with_kind(
                "notes",
                system_prompt,
                user_prompt,
                max_tokens=130000,
            ),
            project_context_block=cls._build_project_context_block(project_context),
            question_text=question_text,
            segments=segments,
            intent_name=intent_name,
            question_type=question_type,
        )

    @classmethod
    def generate_notes_for_question_with_fewshot(
        cls,
        question_text: str,
        segments: List[Dict[str, Any]],
        intent_name: Optional[str],
        question_type: Optional[str],
        fewshot_samples: List[Dict[str, Any]],
        project_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        基于检索片段和 few-shot 样本生成结构化 Notes。

        参数:
            question_text: 问题原文。
            segments: 检索片段列表。
            intent_name: 问题意图名称。
            question_type: 问题类型标签。
            fewshot_samples: few-shot 样本列表。
            project_context: 可选项目背景文本。

        返回:
            结构化 Notes 字典。
        """
        return generate_notes_for_question_with_fewshot(
            generate_fn=lambda system_prompt, user_prompt: cls._generate_with_kind(
                "notes",
                system_prompt,
                user_prompt,
                max_tokens=130000,
            ),
            project_context_block=cls._build_project_context_block(project_context),
            question_text=question_text,
            segments=segments,
            intent_name=intent_name,
            question_type=question_type,
            fewshot_samples=fewshot_samples,
        )

    @classmethod
    def generate_overall_interview_note(
        cls,
        key_bq_text: str,
        transcript_text: str,
        project_context: Optional[str] = None,
        interview_context: Optional[Any] = None,
    ) -> str:
        """
        根据整篇转录和 key BQ 生成访谈级整体 summary notes。

        参数:
            key_bq_text: 访谈 key BQ 的拼接文本。
            transcript_text: 经纠错后的整篇访谈转录文本。
            project_context: 可选项目背景文本。
            interview_context: 可选访谈背景摘要。

        返回:
            适合写入 `bh_project_interview.note_content` 的总结文本。
        """
        return generate_overall_interview_note(
            generate_fn=lambda system_prompt, user_prompt: cls._generate_with_kind(
                "transcript",
                system_prompt,
                user_prompt,
                max_tokens=130000,
            ),
            project_context_block=cls._build_project_context_block(project_context),
            interview_context_block=cls._build_interview_context_block(interview_context),
            key_bq_text=key_bq_text,
            transcript_text=transcript_text,
        )

    @classmethod
    def generate_kbq_dimensions(
        cls,
        key_bq_text: str,
        project_context: Optional[str] = None,
        interview_context: Optional[Any] = None,
        user_dimensions: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        先从单条 key BQ 中抽取后续回答所需的分析维度。

        参数:
            key_bq_text: 单条 key BQ 的原文文本。
            project_context: 可选项目背景文本。
            interview_context: 可选访谈背景摘要。
            user_dimensions: 用户已配置的维度列表，可选。

        返回:
            包含 `dimensions` 的字典。
        """
        return generate_kbq_dimensions(
            generate_fn=lambda system_prompt, user_prompt: cls._generate_with_kind(
                "notes",
                system_prompt,
                user_prompt,
                max_tokens=130000,
            ),
            project_context_block=cls._build_project_context_block(project_context),
            interview_context_block=cls._build_interview_context_block(interview_context),
            key_bq_text=key_bq_text,
            user_dimensions=user_dimensions,
        )

    @classmethod
    def generate_kbq_notes(
        cls,
        key_bq_text: str,
        demension: List[Dict[str, Any]],
        segments: List[Dict[str, Any]],
        project_context: Optional[str] = None,
        interview_context: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        根据 key BQ、合并后的 demension 与检索片段生成 KBQ Notes。

        参数:
            key_bq_text: 单条 key BQ 的原文文本。
            dimensions: 第一步抽取出的维度列表。
            segments: RAG 检索到的相关片段。
            project_context: 可选项目背景文本。
            interview_context: 可选访谈背景摘要。

        返回:
            包含 `key_bq`、`dimension_notes`、`confidence` 的字典。
        """
        return generate_kbq_notes(
            generate_fn=lambda system_prompt, user_prompt: cls._generate_with_kind(
                "notes",
                system_prompt,
                user_prompt,
                max_tokens=130000,
            ),
            project_context_block=cls._build_project_context_block(project_context),
            interview_context_block=cls._build_interview_context_block(interview_context),
            key_bq_text=key_bq_text,
            demension=demension,
            segments=segments,
        )

    @classmethod
    def generate_minutes_item_summary(
        cls,
        section_title: str,
        section_summary: str,
        item_title: str,
        item_summary: str,
        segments: List[Dict[str, Any]],
        project_context: Optional[str] = None,
        interview_context: Optional[Any] = None,
    ) -> str:
        """
        基于纪要大纲小点与检索片段生成单个小点的纪要正文。

        参数:
            section_title: 章节标题。
            section_summary: 章节概述。
            item_title: 小点标题。
            item_summary: 小点概述。
            segments: 检索得到的相关片段。
            project_context: 可选项目背景文本。
            interview_context: 可选访谈背景摘要。

        返回:
            一段适合写入智能纪要的小点总结文本。
        """
        return generate_minutes_item_summary(
            generate_fn=lambda system_prompt, user_prompt: cls._generate_with_kind(
                "notes",
                system_prompt,
                user_prompt,
                max_tokens=130000,
            ),
            project_context_block=cls._build_project_context_block(project_context),
            interview_context_block=cls._build_interview_context_block(interview_context),
            section_title=section_title,
            section_summary=section_summary,
            item_title=item_title,
            item_summary=item_summary,
            segments=segments,
        )

    @classmethod
    def generate_minutes_outline_from_transcript(
        cls,
        transcript_text: str,
        project_context: Optional[str] = None,
        questionnaire_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        基于整篇访谈转录直接生成智能纪要。

        参数:
            transcript_text: 经清洗后的整篇访谈转录全文。
            project_context: 可选项目背景文本。
            questionnaire_text: 访谈关联的 DG / 问卷 Markdown 文本（可选）。

        返回:
            结构化智能纪要字典。
        """
        return generate_minutes_outline_from_transcript(
            generate_fn=lambda system_prompt, user_prompt: cls._generate_with_kind(
                "notes",
                system_prompt,
                user_prompt,
                max_tokens=130000,
            ),
            project_context_block=cls._build_project_context_block(project_context),
            transcript_text=transcript_text,
            questionnaire_text=questionnaire_text,
        )

    @classmethod
    def generate_ca_dimensions(
        cls,
        project_context: Optional[str] = None,
        interviews_notes: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        基于多份全文 Notes 生成 CA 维度骨架。

        参数:
            project_context: 可选项目背景文本。
            interviews_notes: 多访谈全文 Notes 列表。

        返回:
            结构化 CA 维度字典。
        """
        return generate_ca_dimensions(
            generate_fn=lambda system_prompt, user_prompt: cls._generate_with_kind(
                "notes",
                system_prompt,
                user_prompt,
                max_tokens=130000,
            ),
            project_context_block=cls._build_project_context_block(project_context),
            interviews_notes=interviews_notes or [],
        )

    @classmethod
    def generate_ca_cells_for_sub_point(
        cls,
        project_context: Optional[str] = None,
        dimension_title: str = "",
        dimension_summary: str = "",
        sub_point_title: str = "",
        sub_point_summary: str = "",
        interview_blocks: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        基于某个 CA 小点为所有访谈生成单元格内容。

        参数:
            project_context: 可选项目背景文本。
            dimension_title: 维度标题。
            dimension_summary: 维度概述。
            sub_point_title: 小点标题。
            sub_point_summary: 小点概述。
            interview_blocks: 各访谈的检索片段输入块。

        返回:
            标准化后的 cells 映射字典。
        """
        return generate_ca_cells_for_sub_point(
            generate_fn=lambda system_prompt, user_prompt: cls._generate_with_kind(
                "notes",
                system_prompt,
                user_prompt,
                max_tokens=130000,
            ),
            project_context_block=cls._build_project_context_block(project_context),
            dimension_title=dimension_title,
            dimension_summary=dimension_summary,
            sub_point_title=sub_point_title,
            sub_point_summary=sub_point_summary,
            interview_blocks=interview_blocks or [],
        )

    @classmethod
    def _escape_inner_quotes_in_notes_json(cls, text: str) -> str:
        """
        修复 Notes JSON 中常见的未转义双引号问题。

        参数:
            text: 原始 JSON 文本。

        返回:
            修复后的 JSON 文本。
        """
        return escape_inner_quotes_in_notes_json(text)

    @classmethod
    def _escape_inner_quotes_in_field(cls, text: str, field_name: str) -> str:
        """
        修复指定字段中的未转义双引号。

        参数:
            text: 原始 JSON 文本。
            field_name: 需要修复的字段名。

        返回:
            修复后的 JSON 文本。
        """
        return escape_inner_quotes_in_field(text, field_name)

    @classmethod
    def _repair_notes_json(cls, raw_text: str) -> Optional[Dict[str, Any]]:
        """
        使用 LLM 尝试修复非法 Notes JSON。

        参数:
            raw_text: 待修复的原始 JSON 文本。

        返回:
            修复成功时返回字典，否则返回 `None`。
        """
        return repair_notes_json(cls.generate, raw_text)
