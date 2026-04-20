"@Date: 2026-04-10"
"@Author: lixinyang"

import json
from typing import Any, Dict, List, Optional
from anthropic import Anthropic
from google import genai
from google.genai import types
from volcenginesdkarkruntime import Ark
from Fewshot import build_fewshot_prompt_block
from config import config


class BaseLLMProvider:
    """
    统一的大模型适配接口。

    目前实现 Claude / Anthropic、Gemini、豆包 / 火山方舟、OpenAI provider，后续可继续按这个协议扩展。
    """

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> str:
        raise NotImplementedError


class AnthropicProvider(BaseLLMProvider):
    """
    Anthropic Claude provider 适配层。
    """

    def __init__(self, api_key: str, base_url: Optional[str] = None) -> None:
        client_kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = Anthropic(**client_kwargs)

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> str:
        resp = self._client.messages.create(
            model=model_name,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": user_prompt,
                        }
                    ],
                }
            ],
        )

        if not resp.content:
            raise RuntimeError(f"LLM 返回内容为空: {resp}")

        first = resp.content[0]
        if getattr(first, "type", None) == "text":
            return first.text

        # 兼容非 text 类型的返回
        try:
            return json.dumps(resp.model_dump(), ensure_ascii=False)
        except Exception:
            return str(resp)


class GeminiProvider(BaseLLMProvider):
    """
    Gemini provider 适配层，基于 Google 官方 google-genai SDK。
    """

    def __init__(self, api_key: str, base_url: Optional[str] = None) -> None:
        self._client = genai.Client(
            api_key="sk-pkEHC9t8l1UNg73KBxKPUk1m2VfMTe9MWqoKWVhB2Mcp3UZu",
            vertexai=True,
            http_options={
                "base_url": "https://api.openai-proxy.org/google"
                #base_url_resource_scope=types.ResourceScope.COLLECTION,
         },
        )

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> str:
        response = self._client.models.generate_content(
            model=model_name,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=max_tokens,
                temperature=temperature,
            ),
        )

        text = getattr(response, "text", None)
        if isinstance(text, str) and text.strip():
            return text

        candidates = getattr(response, "candidates", None)
        if not candidates:
            raise RuntimeError(f"LLM 返回内容为空: {response}")

        for candidate in candidates:
            content = getattr(candidate, "content", None)
            if not content:
                continue
            parts: List[str] = []
            for part in getattr(content, "parts", []) or []:
                part_text = getattr(part, "text", None)
                if part_text:
                    parts.append(str(part_text))
            joined = "".join(parts).strip()
            if joined:
                return joined

        try:
            return json.dumps(response.model_dump(), ensure_ascii=False)
        except Exception:
            return str(response)


class DoubaoProvider(BaseLLMProvider):
    """
    豆包 / 火山方舟 provider 适配层，基于官方 volcengine-python-sdk[ark]。
    """

    def __init__(self, api_key: str, base_url: Optional[str] = None) -> None:
        ark_kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            ark_kwargs["base_url"] = base_url
        self._client = Ark(**ark_kwargs)

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> str:
        response = self._client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            stream=False,
        )

        if not getattr(response, "choices", None):
            raise RuntimeError(f"LLM 返回内容为空: {response}")

        choice = response.choices[0]
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return content

        if isinstance(content, list):
            parts: List[str] = []
            for part in content:
                part_text = getattr(part, "text", None)
                if part_text:
                    parts.append(str(part_text))
            joined = "".join(parts).strip()
            if joined:
                return joined

        try:
            return json.dumps(response.model_dump(), ensure_ascii=False)
        except Exception:
            return str(response)


class OpenAIProvider(BaseLLMProvider):
    """
    OpenAI provider 适配层，支持官方 OpenAI API 或 OpenAI 兼容接口。
    """

    def __init__(self, api_key: str, base_url: Optional[str] = None) -> None:
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "openai package 未安装，请先执行 `pip install openai` 后再使用 LLM_PROVIDER=openai"
            ) from exc

        client_kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = OpenAI(**client_kwargs)

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> str:
        response = self._client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_completion_tokens=max_tokens,
            temperature=temperature,
        )

        if not getattr(response, "choices", None):
            raise RuntimeError(f"LLM 返回内容为空: {response}")

        choice = response.choices[0]
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return content

        if isinstance(content, list):
            parts: List[str] = []
            for part in content:
                part_text = getattr(part, "text", None)
                if part_text:
                    parts.append(str(part_text))
            joined = "".join(parts).strip()
            if joined:
                return joined

        try:
            return json.dumps(response.model_dump(), ensure_ascii=False)
        except Exception:
            return str(response)


class ModelClient:
    """
    大模型调用封装类，内部通过 provider 适配不同官方模型。

    配置约定（从环境变量读取）:
        - LLM_PROVIDER:  provider 名称，默认 anthropic。
        - LLM_API_KEY: 模型访问的 API Key。
        - LLM_BASE_URL: 模型 API 基础 URL。
        - LLM_MODEL_NAME:    模型名称或版本标识。
    """

    _provider: Optional[BaseLLMProvider] = None
    _provider_name: Optional[str] = None
    _model_name: Optional[str] = None
    _api_key: Optional[str] = None
    _base_url: Optional[str] = None
    _config_revision: int = -1

    @classmethod
    def _resolve_provider_name(cls) -> str:
        provider_name = (config.LLM_PROVIDER or "anthropic").strip().lower()
        return provider_name or "anthropic"

    @classmethod
    def _build_provider(
        cls,
        provider_name: str,
        api_key: str,
        base_url: Optional[str],
    ) -> BaseLLMProvider:
        effective_base_url = cls._resolve_provider_base_url(provider_name, base_url)
        if provider_name == "anthropic":
            return AnthropicProvider(api_key=api_key, base_url=effective_base_url)
        if provider_name in {"gemini", "google", "google-genai"}:
            return GeminiProvider(api_key=api_key, base_url=effective_base_url)
        if provider_name in {"openai", "gpt", "chatgpt"}:
            return OpenAIProvider(api_key=api_key, base_url=effective_base_url)
        if provider_name in {"doubao", "ark", "volcengine", "volcano"}:
            return DoubaoProvider(api_key=api_key, base_url=effective_base_url)
        raise RuntimeError(f"暂不支持的 LLM_PROVIDER: {provider_name}")

    @classmethod
    def _resolve_provider_base_url(
        cls,
        provider_name: str,
        base_url: Optional[str],
    ) -> Optional[str]:
        if not base_url:
            return None
        if provider_name in {"gemini", "google", "google-genai"}:
            return None
        if provider_name in {"openai", "gpt", "chatgpt"}:
            return base_url
        if provider_name in {"doubao", "ark", "volcengine", "volcano"}:
            lowered = base_url.lower()
            if "ark.cn" in lowered or "volces.com" in lowered:
                return base_url
            return None
        return base_url

    @classmethod
    def _ensure_client(cls) -> None:
        provider_name = cls._resolve_provider_name()
        api_key = config.LLM_API_KEY
        base_url = config.LLM_BASE_URL
        model_name = config.LLM_MODEL_NAME
        if (
            cls._provider is not None
            and cls._provider_name == provider_name
            and cls._model_name == model_name
            and cls._api_key == api_key
            and cls._base_url == base_url
            and cls._config_revision == config.revision
        ):
            return
        if not api_key or not model_name:
            raise RuntimeError("LLM_PROVIDER / LLM_API_KEY / LLM_MODEL_NAME 未正确配置")
        cls._provider = cls._build_provider(provider_name, api_key, base_url)
        cls._provider_name = provider_name
        cls._model_name = model_name
        cls._api_key = api_key
        cls._base_url = base_url
        cls._config_revision = config.revision

    @classmethod
    def generate(cls, system_prompt: str, user_prompt: str) -> str:
        """
        调用当前配置的 LLM provider，返回文本形式的回复内容。

        参数:
            system_prompt: 系统提示，用于约束整体角色和输出规范。
            user_prompt:   用户输入内容，描述当前具体任务。

        返回:
            模型返回的文本内容（假定为单段字符串）。
        """
        cls._ensure_client()
        if cls._provider is None or cls._model_name is None:
            raise RuntimeError("LLM provider 未正确初始化")
        return cls._provider.generate(system_prompt, user_prompt, cls._model_name)

    @classmethod
    def clean_speaker_utterance(
        cls,
        speaker_text: str,
        speaker_role: Optional[str] = None,
        term_hints: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        使用大模型对单个 speaker 的发言进行纠错和清洗。

        参数:
            speaker_text: 原始转写文本。
            speaker_role: 说话人角色标签（如 interviewer / interviewee），可选。
            term_hints:   专业热词提示列表，用于纠正专有名词，格式为若干字符串。

        返回:
            一个字典，至少包含:
            {
                "clean_text": str,          # 清洗后的文本
                "term_corrections": [       # 可选的术语纠错记录列表
                    {"from": str, "to": str}
                ]
            }
        """
        role_text = speaker_role or "speaker"
        term_hint_text = ""
        if term_hints:
            joined_terms = ", ".join(term_hints)
            term_hint_text = f"专业术语提示: {joined_terms}\n"

        system_prompt = (
            "你是一个医学与药学访谈文本编辑助手，负责在不改变事实的前提下，"
            "对转写文本进行轻度编辑，包括去除口头禅、整理语序、统一专业术语。"
        )

        user_prompt = (
            f"{term_hint_text}"
            "请根据以下要求清洗这段访谈文本:\n"
            "1. 删除明显的语气词和重复口头禅，例如“呃、嗯、就是、然后、那个”等。\n"
            "2. 保留原始信息和结论，不添加新的事实或主观判断。\n"
            "3. 根据提供的专业术语提示，将可能的别名统一为标准术语；未出现在提示中的词不要随意更改。\n"
            "4. 将多句口语整理成一到两句书面化但仍然自然的表达，适合写入访谈纪要。\n"
            "5. 只返回 JSON，不要额外说明。JSON 结构如下:\n"
            "{\n"
            '  "clean_text": "清洗后的文本",\n'
            '  "term_corrections": [ {"from": "原始错误词", "to": "修正后的术语"} ]\n'
            "}\n"
            f"\n当前说话人角色: {role_text}\n"
            f"原始文本:\n{speaker_text}"
        )

        content = cls.generate(system_prompt, user_prompt)
        try:
            content_stripped = content.strip()
            if content_stripped.startswith("```"):
                lines = content_stripped.splitlines()
                inner_lines = [line for line in lines if not line.strip().startswith("```")]
                content_stripped = "\n".join(inner_lines).strip()
            try:
                result = json.loads(content_stripped)
            except json.JSONDecodeError:
                start = content_stripped.find("{")
                end = content_stripped.rfind("}")
                if start != -1 and end != -1 and end > start:
                    core = content_stripped[start : end + 1]
                    result = json.loads(core)
                else:
                    raise
        except json.JSONDecodeError:
            result = {
                "clean_text": speaker_text,
                "term_corrections": [],
                "llm_raw_output": content,
            }
        if "clean_text" not in result:
            result["clean_text"] = speaker_text
        if "term_corrections" not in result:
            result["term_corrections"] = []
        return result

    @classmethod
    def generate_notes_for_question(
        cls,
        question_text: str,
        segments: List[Dict[str, Any]],
        intent_name: Optional[str] = None,
        question_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        使用大模型针对单个问题生成结构化 Notes。

        参数:
            question_text: 问题原文。
            segments:      RAG 检索到的相关片段列表，每个元素至少包含:
                           - summary_id
                           - speaker
                           - text
                           - score
            intent_name:   可选，问题所属意图名称，用于提示模型关注的方向。
            question_type: 可选，问题类型标签，用于给模型提供额外背景。

        返回:
            一个字典，包含生成的 Notes 结果，约定结构为:
            {
                "summary": "简要总结",
                "analysis": "详细分析说明",
                "evidence": [
                    {
                        "summary_id": int,
                        "speaker": "speaker1",
                        "text": "引用的原文片段"
                    }
                ],
                "confidence": 0.0
            }
        """
        context_lines: List[str] = []
        for idx, seg in enumerate(segments, start=1):
            sid = seg.get("summary_id", "")
            speaker = seg.get("speaker", "")
            text = str(seg.get("text", "")).replace("\n", " ")
            score = seg.get("score", 0.0)
            context_lines.append(
                f"[{idx}] summary_id={sid} speaker={speaker} score={score:.4f}\n{text}"
            )
        context_block = "\n\n".join(context_lines) if context_lines else "（当前没有检索到相关片段）"

        intent_part = intent_name or "未指定"
        qtype_part = question_type or "未指定"

        system_prompt = (
            "你是一名医学与药学领域的访谈分析专家，负责根据给定的访谈片段，"
            "针对指定问题生成结构化的研究 Notes。你必须严格基于提供的片段，不要编造事实，"
            "并且必须输出语法完全合法、可以被 json.loads 直接解析的 JSON。"
        )

        user_prompt = (
            "下面是一道研究问题及其相关的访谈片段，请你基于这些信息生成结构化的 Notes。\n\n"
            f"【问题类型】{qtype_part}\n"
            f"【问题意图】{intent_part}\n"
            f"【问题原文】{question_text}\n\n"
            "【相关访谈片段】\n"
            f"{context_block}\n\n"
            "请遵循以下要求完成任务:\n"
            "1. 只使用上述片段中的信息，不要引入任何未在片段中出现的事实。\n"
            "2. 如果信息不足以回答问题，请在 summary 和 analysis 中明确说明“当前访谈中信息不足”。\n"
            "3. 请给出一个 0 到 1 之间的置信度 confidence，用于表示你对答案可靠性的主观判断。\n"
            "4. 输出时只返回 JSON，不要包含额外说明，不要使用 ``` 包裹，也不要输出任何 Markdown 标记（如 **、#、- 等）。\n"
            "5. 必须严格遵守 JSON 语法：键和值一律使用英文双引号 \" 包裹，不要使用中文引号或单引号；不要在 JSON 中添加注释；不要在数组或对象末尾保留多余的逗号。\n"
            "6. JSON 中字符串的换行必须编码为 \\n，而不是直接换行；同一字段的内容必须写在一行字符串中，由模型自动插入 \\n 作为换行标记。\n"
            "7. JSON 中字符串内部如需包含双引号，必须转义为 \\\"，避免破坏整体 JSON 结构。\n"
            "JSON 的参考结构如下:\n"
            "{\n"
            '  "summary": "一句话或几句话的高度概括",\n'
            '  "analysis": "更详细的分析和解释，适合写入研究笔记",\n'
            '  "evidence": [\n'
            '    {"summary_id": 0, "speaker": "speaker1", "text": "与结论直接相关的原文片段"}\n'
            "  ],\n"
            '  "confidence": 0.0\n'
            "}\n"
        )

        content = cls.generate(system_prompt, user_prompt)
        try:
            content_stripped = content.strip()
            if content_stripped.startswith("```"):
                lines = content_stripped.splitlines()
                inner_lines = [line for line in lines if not line.strip().startswith("```")]
                content_stripped = "\n".join(inner_lines).strip()
            try:
                result = json.loads(content_stripped)
            except json.JSONDecodeError:
                start = content_stripped.find("{")
                end = content_stripped.rfind("}")
                if start != -1 and end != -1 and end > start:
                    core = content_stripped[start : end + 1]
                    result = json.loads(core)
                else:
                    raise
        except json.JSONDecodeError:
            locally_fixed = cls._escape_inner_quotes_in_notes_json(content_stripped)
            try:
                result = json.loads(locally_fixed)
            except json.JSONDecodeError:
                repaired = cls._repair_notes_json(locally_fixed)
                if repaired is not None:
                    result = repaired
                else:
                    result = {
                        "summary": "",
                        "analysis": "",
                        "evidence": [],
                        "confidence": 0.0,
                        "llm_raw_output": content,
                    }
        if "summary" not in result:
            result["summary"] = ""
        if "analysis" not in result:
            result["analysis"] = ""
        if "evidence" not in result:
            result["evidence"] = []
        if "confidence" not in result:
            result["confidence"] = 0.0
        return result

    @classmethod
    def generate_notes_for_question_with_fewshot(
        cls,
        question_text: str,
        segments: List[Dict[str, Any]],
        intent_name: Optional[str],
        question_type: Optional[str],
        fewshot_samples: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        使用大模型针对单个问题生成结构化 Notes，并注入 few-shot 示例。

        参数:
            question_text:    问题原文。
            segments:         RAG 检索到的相关片段列表。
            intent_name:      问题所属意图名称或描述。
            question_type:    问题类型标签。
            fewshot_samples:  few-shot 样本列表，由 Fewshot.select_fewshot_samples 返回。

        返回:
            结构与 generate_notes_for_question 相同的 Notes 结果字典。
        """
        context_lines: List[str] = []
        for idx, seg in enumerate(segments, start=1):
            sid = seg.get("summary_id", "")
            speaker = seg.get("speaker", "")
            text = str(seg.get("text", "")).replace("\n", " ")
            score = seg.get("score", 0.0)
            context_lines.append(
                f"[{idx}] summary_id={sid} speaker={speaker} score={score:.4f}\n{text}"
            )
        context_block = "\n\n".join(context_lines) if context_lines else "（当前没有检索到相关片段）"

        intent_part = intent_name or "未指定"
        qtype_part = question_type or "未指定"

        system_prompt = (
            "你是一名医学与药学领域的访谈分析专家，负责根据给定的访谈片段，"
            "针对指定问题生成结构化的研究 Notes。你必须严格基于提供的片段，不要编造事实，"
            "并且必须输出语法完全合法、可以被 json.loads 直接解析的 JSON。"
        )

        base_user_prompt = (
            "下面是一道研究问题及其相关的访谈片段，请你基于这些信息生成结构化的 Notes。\n\n"
            f"【问题类型】{qtype_part}\n"
            f"【问题意图】{intent_part}\n"
            f"【问题原文】{question_text}\n\n"
            "【相关访谈片段】\n"
            f"{context_block}\n\n"
            "请遵循以下要求完成任务:\n"
            "1. 只使用上述片段中的信息，不要引入任何未在片段中出现的事实。\n"
            "2. 如果信息不足以回答问题，请在 summary 和 analysis 中明确说明“当前访谈中信息不足”。\n"
            "3. 请给出一个 0 到 1 之间的置信度 confidence，用于表示你对答案可靠性的主观判断。\n"
            "4. 输出时只返回 JSON，不要包含额外说明，不要使用 ``` 包裹，也不要输出任何 Markdown 标记（如 **、#、- 等）。\n"
            "5. 必须严格遵守 JSON 语法：键和值一律使用英文双引号 \" 包裹，不要使用中文引号或单引号；不要在 JSON 中添加注释；不要在数组或对象末尾保留多余的逗号。\n"
            "6. JSON 中字符串的换行必须编码为 \\n，而不是直接换行；同一字段的内容必须写在一行字符串中，由模型自动插入 \\n 作为换行标记。\n"
            "7. JSON 中字符串内部如需包含双引号，必须转义为 \\\"，避免破坏整体 JSON 结构。\n"
            "JSON 的参考结构如下:\n"
            "{\n"
            '  "summary": "一句话或几句话的高度概括",\n'
            '  "analysis": "更详细的分析和解释，适合写入研究笔记",\n'
            '  "evidence": [\n'
            '    {"summary_id": 0, "speaker": "speaker1", "text": "与结论直接相关的原文片段"}\n'
            "  ],\n"
            '  "confidence": 0.0\n'
            "}\n"
        )

        fewshot_block = build_fewshot_prompt_block(fewshot_samples)
        if fewshot_block:
            user_prompt = fewshot_block + "\n\n" + base_user_prompt
        else:
            user_prompt = base_user_prompt

        content = cls.generate(system_prompt, user_prompt)
        try:
            content_stripped = content.strip()
            if content_stripped.startswith("```"):
                lines = content_stripped.splitlines()
                inner_lines = [line for line in lines if not line.strip().startswith("```")]
                content_stripped = "\n".join(inner_lines).strip()
            try:
                result = json.loads(content_stripped)
            except json.JSONDecodeError:
                start = content_stripped.find("{")
                end = content_stripped.rfind("}")
                if start != -1 and end != -1 and end > start:
                    core = content_stripped[start : end + 1]
                    result = json.loads(core)
                else:
                    raise
        except json.JSONDecodeError:
            locally_fixed = cls._escape_inner_quotes_in_notes_json(content_stripped)
            try:
                result = json.loads(locally_fixed)
            except json.JSONDecodeError:
                repaired = cls._repair_notes_json(locally_fixed)
                if repaired is not None:
                    result = repaired
                else:
                    result = {
                        "summary": "",
                        "analysis": "",
                        "evidence": [],
                        "confidence": 0.0,
                        "llm_raw_output": content,
                    }
        if "summary" not in result:
            result["summary"] = ""
        if "analysis" not in result:
            result["analysis"] = ""
        if "evidence" not in result:
            result["evidence"] = []
        if "confidence" not in result:
            result["confidence"] = 0.0
        return result

    @classmethod
    def _escape_inner_quotes_in_notes_json(cls, text: str) -> str:
        """
        对 summary 和 analysis 字段中的内部未转义引号进行转义处理。

        参数:
            text: 原始 JSON 文本字符串。

        返回:
            处理后的 JSON 文本字符串。
        """
        fixed = cls._escape_inner_quotes_in_field(text, "summary")
        fixed = cls._escape_inner_quotes_in_field(fixed, "analysis")
        return fixed

    @classmethod
    def _escape_inner_quotes_in_field(cls, text: str, field_name: str) -> str:
        """
        在指定字段的字符串值内部，将可能导致 JSON 解析错误的未转义引号转为 \\\"。

        参数:
            text: 原始 JSON 文本字符串。
            field_name: 需要处理的字段名，例如 "summary" 或 "analysis"。

        返回:
            处理后的 JSON 文本字符串。
        """
        key = f'"{field_name}"'
        result_parts: List[str] = []
        cursor = 0
        search_pos = 0
        length = len(text)

        while True:
            key_pos = text.find(key, search_pos)
            if key_pos == -1:
                break
            result_parts.append(text[cursor:key_pos])
            colon_pos = text.find(":", key_pos)
            if colon_pos == -1:
                result_parts.append(text[key_pos:])
                cursor = length
                break
            i = colon_pos + 1
            while i < length and text[i].isspace():
                i += 1
            if i >= length or text[i] != '"':
                result_parts.append(text[key_pos:i])
                cursor = i
                search_pos = i
                continue
            value_start = i
            result_parts.append(text[key_pos:value_start + 1])
            j = value_start + 1
            value_chars: List[str] = []
            while j < length:
                c = text[j]
                if c == '"' and text[j - 1] != "\\":
                    k = j + 1
                    while k < length and text[k].isspace():
                        k += 1
                    if k < length and text[k] in [",", "}", "]"]:
                        break
                    else:
                        value_chars.append("\\\"")
                        j += 1
                        continue
                value_chars.append(c)
                j += 1
            result_parts.append("".join(value_chars))
            if j < length:
                result_parts.append(text[j])
                j += 1
            cursor = j
            search_pos = j

        if cursor < length:
            result_parts.append(text[cursor:])
        return "".join(result_parts)

    @classmethod
    def _repair_notes_json(cls, raw_text: str) -> Optional[Dict[str, Any]]:
        """
        在初次 JSON 解析失败时，使用 LLM 尝试对输出进行宽松修复。

        参数:
            raw_text: 初始清洗后的模型输出文本。

        返回:
            如果修复并成功解析，返回修复后的字典；否则返回 None。
        """
        repair_system = (
            "你是一个 JSON 修复助手。"
            "当前有一段应该是 JSON 的文本，但可能存在转义错误、未转义的引号或换行等问题。"
            "你的任务是仅修复语法，使其成为可以被 json.loads 解析的严格 JSON。"
            "必须保留原有的语义和字段结构，尤其是 summary、analysis、evidence、confidence 这四个字段。"
            "输出时只返回修复后的 JSON，本身必须完全合法，不要添加额外说明。"
        )

        repair_user = (
            "下面是一段需要修复的 JSON 文本，请你修正其中的转义问题和语法错误，"
            "使其成为严格合法的 JSON：\n\n"
            f"{raw_text}"
        )

        fixed = cls.generate(repair_system, repair_user)
        fixed_stripped = fixed.strip()
        if fixed_stripped.startswith("```"):
            lines = fixed_stripped.splitlines()
            inner_lines = [line for line in lines if not line.strip().startswith("```")]
            fixed_stripped = "\n".join(inner_lines).strip()
        try:
            return json.loads(fixed_stripped)
        except json.JSONDecodeError:
            try:
                start = fixed_stripped.find("{")
                end = fixed_stripped.rfind("}")
                if start != -1 and end != -1 and end > start:
                    core = fixed_stripped[start : end + 1]
                    return json.loads(core)
            except json.JSONDecodeError:
                return None
        return None
