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
        client_kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["http_options"] = {"base_url": base_url}
        self._client = genai.Client(**client_kwargs)

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
    def _build_project_context_block(cls, project_context: Optional[str]) -> str:
        """
        将项目背景文本包装成统一的 prompt 区块。

        参数:
            project_context: 已整理好的项目背景文本，通常包含名称、关键词和核心描述。

        返回:
            适合直接拼接进 user prompt 的背景块字符串；如果没有内容则返回空串。
        """
        if not project_context:
            return ""
        cleaned = project_context.strip()
        if not cleaned:
            return ""
        return f"【项目背景】\n{cleaned}\n\n"

    @classmethod
    def _build_interview_context_block(cls, interview_context: Optional[Any]) -> str:
        if interview_context is None:
            return ""
        if isinstance(interview_context, dict):
            context_brief = str(interview_context.get("context_brief") or "").strip()
            key_terms = interview_context.get("key_terms") or []
            important_entities = interview_context.get("important_entities") or []
            lines: List[str] = ["【访谈背景】"]
            if context_brief:
                lines.append(f"背景说明：{context_brief}")
            if isinstance(key_terms, list) and key_terms:
                terms = ", ".join(str(item) for item in key_terms if str(item).strip())
                if terms:
                    lines.append(f"高频术语：{terms}")
            if isinstance(important_entities, list) and important_entities:
                entities = ", ".join(str(item) for item in important_entities if str(item).strip())
                if entities:
                    lines.append(f"关键实体：{entities}")
            if len(lines) == 1:
                return ""
            return "\n".join(lines) + "\n\n"

        cleaned = str(interview_context).strip()
        if not cleaned:
            return ""
        return f"【访谈背景】\n{cleaned}\n\n"

    @classmethod
    def _strip_code_fences(cls, text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            inner_lines = [line for line in lines if not line.strip().startswith("```")]
            return "\n".join(inner_lines).strip()
        return stripped

    @classmethod
    def _parse_json_payload(cls, content: str) -> Any:
        """
        尽量从模型输出中解析出 JSON 对象或数组。
        """
        content_stripped = cls._strip_code_fences(content)
        try:
            return json.loads(content_stripped)
        except json.JSONDecodeError:
            start_obj = content_stripped.find("{")
            end_obj = content_stripped.rfind("}")
            if start_obj != -1 and end_obj != -1 and end_obj > start_obj:
                try:
                    return json.loads(content_stripped[start_obj : end_obj + 1])
                except json.JSONDecodeError:
                    pass

            start_arr = content_stripped.find("[")
            end_arr = content_stripped.rfind("]")
            if start_arr != -1 and end_arr != -1 and end_arr > start_arr:
                return json.loads(content_stripped[start_arr : end_arr + 1])

            raise

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        if value is None or isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _normalize_transcript_records(
        cls,
        transcript: List[Dict[str, Any]],
        text_field: str,
    ) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for idx, item in enumerate(transcript, start=1):
            if not isinstance(item, dict):
                continue
            uid = str(item.get("uid") or item.get("id") or f"u{idx:04d}")
            speaker_id = str(item.get("speaker_id") or item.get("speaker") or "")
            start_time = item.get("start_time")
            if start_time is None:
                start_time = item.get("start_ms")
            end_time = item.get("end_time")
            if end_time is None:
                end_time = item.get("end_ms")
            normalized.append(
                {
                    "uid": uid,
                    "speaker_id": speaker_id,
                    "speaker_role": str(item.get("speaker_role") or ""),
                    "start_time": cls._coerce_int(start_time),
                    "end_time": cls._coerce_int(end_time),
                    "text": str(item.get(text_field) or item.get("text") or item.get("speaker_content") or ""),
                }
            )
        return normalized

    @classmethod
    def _build_transcript_prompt_block(cls, transcript: List[Dict[str, Any]]) -> str:
        return json.dumps({"transcript": transcript}, ensure_ascii=False, indent=2)

    @classmethod
    def _extract_transcript_items(cls, payload: Any) -> List[Dict[str, Any]]:
        if isinstance(payload, dict):
            transcript = payload.get("transcript")
        else:
            transcript = payload
        if not isinstance(transcript, list):
            return []
        return [item for item in transcript if isinstance(item, dict)]

    @classmethod
    def _merge_transcript_output(
        cls,
        input_records: List[Dict[str, Any]],
        output_records: List[Dict[str, Any]],
        output_text_field: str,
        preserve_raw_fields: bool = False,
    ) -> List[Dict[str, Any]]:
        output_by_uid: Dict[str, Dict[str, Any]] = {}
        for item in output_records:
            uid = str(item.get("uid") or "").strip()
            if uid:
                output_by_uid[uid] = item

        merged: List[Dict[str, Any]] = []
        for idx, original in enumerate(input_records):
            uid = str(original.get("uid") or original.get("id") or f"u{idx+1:04d}")
            candidate = output_by_uid.get(uid)
            if candidate is None and idx < len(output_records):
                candidate = output_records[idx]
            if not isinstance(candidate, dict):
                candidate = {}

            merged_item: Dict[str, Any] = {
                "uid": uid,
                "speaker_id": str(original.get("speaker_id") or ""),
                "speaker_role": str(original.get("speaker_role") or ""),
                "start_time": cls._coerce_int(original.get("start_time")),
                "end_time": cls._coerce_int(original.get("end_time")),
            }
            if preserve_raw_fields:
                merged_item["speaker_content"] = str(original.get("text") or original.get("speaker_content") or "")

            output_text = candidate.get(output_text_field)
            if not isinstance(output_text, str) or not output_text.strip():
                output_text = candidate.get("text")
            if not isinstance(output_text, str) or not output_text.strip():
                output_text = str(original.get("text") or original.get("speaker_content") or "")

            merged_item[output_text_field] = output_text
            merged_item["text"] = output_text

            if "corrected_text" in candidate:
                corrected_text = candidate.get("corrected_text")
                if isinstance(corrected_text, str) and corrected_text.strip():
                    merged_item["corrected_text"] = corrected_text
            if "clean_text" in candidate:
                clean_text = candidate.get("clean_text")
                if isinstance(clean_text, str) and clean_text.strip():
                    merged_item["clean_text"] = clean_text

            corrections = candidate.get("corrections")
            if isinstance(corrections, list):
                merged_item["corrections"] = corrections
            else:
                merged_item["corrections"] = []

            uncertain_terms = candidate.get("uncertain_terms")
            if isinstance(uncertain_terms, list):
                merged_item["uncertain_terms"] = uncertain_terms
            else:
                merged_item["uncertain_terms"] = []

            merged.append(merged_item)
        return merged

    @classmethod
    def correct_transcript_batch(
        cls,
        transcript: List[Dict[str, Any]],
        term_hints: Optional[List[str]] = None,
        project_context: Optional[str] = None,
        interview_context: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        对整篇访谈做一次性术语纠错，返回逐条记录的 corrected_text。
        """
        normalized = cls._normalize_transcript_records(transcript, text_field="text")
        if not normalized:
            return []

        term_hint_text = ""
        if term_hints:
            joined_terms = ", ".join(term_hints)
            term_hint_text = f"专业术语提示: {joined_terms}\n\n"
        project_context_text = cls._build_project_context_block(project_context)
        interview_context_text = cls._build_interview_context_block(interview_context)
        transcript_block = cls._build_transcript_prompt_block(normalized)

        system_prompt = (
            "你现在是一位拥有 15 年经验的医学与医疗行业访谈转录校对专家，"
            "熟悉实体瘤、靶向药、免疫治疗、分子检测、体外诊断、临床指标、公司名称和行业术语。"
        )
        user_prompt = (
            f"{project_context_text}"
            f"{interview_context_text}"
            f"{term_hint_text}"
            "你的任务是：结合【全文上下文】和【待校正文档】，对整篇访谈逐条进行高保真纠错。\n\n"
            "核心目标：\n"
            "- 只修正明确可判定的 ASR 错词、术语错写、药名错写、基因位点错写、公司名错写、检测名错写、数值和单位错误。\n"
            "- 不做总结，不做润色，不改写表达，不删减信息，不合并内容，不改变说话顺序。\n\n"
            "严格规则：\n"
            "1. 必须保留原始信息顺序、说话顺序和原有语义。\n"
            "2. 只允许修正高置信度错误。\n"
            "3. 如果某个词或术语无法明确判断，不要猜测，保留原文。\n"
            "4. 不要为了“更专业”而擅自改写没有把握的内容。\n"
            "5. 不要把口语改成书面语，这一步只做纠错，不做清洗。\n"
            "6. 保留所有数字、单位、时间、剂量、百分比、分数、缩写格式。\n"
            "7. 药物名、基因位点、检测名、抗体克隆号、公司名优先按行业通用写法统一。\n"
            "8. 如果全文上下文能明确支持某个纠错结果，可以据此修正待校正文段中的同音错词。\n"
            "9. 绝不输出解释、分析、备注或修正原因。\n\n"
            "特别注意：\n"
            "- 药物名要区分通用名和商品名，例如：帕博利珠单抗 / 可瑞达，奥希替尼 / 泰瑞沙。\n"
            "- 基因和突变位点必须保持标准写法，例如：EGFR exon 19 del、T790M、ALK fusion。\n"
            "- 临床指标必须保留原始数值和单位，例如：CEA、CA19-9、PD-L1 TPS。\n"
            "- 公司名称、检测平台、抗体克隆号、试剂名、医院名、项目名要尽量纠正为行业常用写法。\n"
            "- 对于“化疗 / 画了”“分子检测 / 纷子检测”这类明显同音错词，可以直接修正。\n\n"
            "输出要求：\n"
            "- 只输出合法 JSON。\n"
            "- 不要输出 markdown。\n"
            "- 不要输出多余文字。\n"
            "- 不要输出前缀、标题、解释。\n"
            "- 必须严格返回以下结构：\n\n"
            '{\n'
            '  "transcript": [\n'
            '    {\n'
            '      "uid": "u001",\n'
            '      "speaker_id": "speaker1",\n'
            '      "start_time": 12340,\n'
            '      "end_time": 15800,\n'
            '      "corrected_text": "纠错后的正文",\n'
            '      "corrections": [\n'
            '        {\n'
            '          "original": "原词",\n'
            '          "corrected": "修正词"\n'
            '        }\n'
            '      ],\n'
            '      "uncertain_terms": []\n'
            '    }\n'
            '  ]\n'
            '}\n\n'
            "示例：\n"
            '{\n'
            '  "transcript": [\n'
            '    {\n'
            '      "uid": "u001",\n'
            '      "speaker_id": "speaker1",\n'
            '      "start_time": 12340,\n'
            '      "end_time": 15800,\n'
            '      "corrected_text": "患者之前用过奥希替尼，后来考虑帕博利珠单抗。",\n'
            '      "corrections": [\n'
            '        {\n'
            '          "original": "奥西替尼",\n'
            '          "corrected": "奥希替尼"\n'
            '        }\n'
            '      ],\n'
            '      "uncertain_terms": []\n'
            '    }\n'
            '  ]\n'
            '}\n\n'
            "【待校正文档】\n"
            f"{transcript_block}\n\n"
            "请仅返回合法 JSON。"
        )

        content = cls.generate(system_prompt, user_prompt)
        try:
            parsed = cls._parse_json_payload(content)
        except json.JSONDecodeError:
            parsed = {}

        output_records = cls._extract_transcript_items(parsed)
        if not output_records:
            return [
                {
                    "uid": item["uid"],
                    "speaker_id": item["speaker_id"],
                    "start_time": item["start_time"],
                    "end_time": item["end_time"],
                    "corrected_text": item["text"],
                    "text": item["text"],
                    "corrections": [],
                    "uncertain_terms": [],
                }
                for item in normalized
            ]

        merged = cls._merge_transcript_output(
            normalized,
            output_records,
            output_text_field="corrected_text",
            preserve_raw_fields=False,
        )
        for item in merged:
            if not item.get("corrected_text"):
                item["corrected_text"] = item.get("text", "")
            item["text"] = item.get("corrected_text", item.get("text", ""))
        return merged

    @classmethod
    def clean_transcript_batch(
        cls,
        transcript: List[Dict[str, Any]],
        term_hints: Optional[List[str]] = None,
        project_context: Optional[str] = None,
        interview_context: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        对纠错后的整篇访谈做轻度清洗，返回逐条记录的 clean_text。
        """
        normalized = cls._normalize_transcript_records(transcript, text_field="corrected_text")
        if not normalized:
            return []

        term_hint_text = ""
        if term_hints:
            joined_terms = ", ".join(term_hints)
            term_hint_text = f"专业术语提示: {joined_terms}\n\n"
        project_context_text = cls._build_project_context_block(project_context)
        interview_context_text = cls._build_interview_context_block(interview_context)
        transcript_block = cls._build_transcript_prompt_block(normalized)

        system_prompt = (
            "你现在是一位拥有 15 年经验的医学与医疗行业访谈文本清洗专家，"
            "熟悉医学、药学、体外诊断、肿瘤访谈、市场调研访谈中的常见表达方式。"
        )
        user_prompt = (
            f"{project_context_text}"
            f"{interview_context_text}"
            f"{term_hint_text}"
            "你的任务是：对【待清洗文本】进行轻度清洗整理，使其更适合后续总结与分析，但必须保留原始事实、术语和信息粒度。\n\n"
            "核心目标：\n"
            "- 去除明显口头禅、重复赘词、无意义停顿和冗余语气。\n"
            "- 整理断裂句子、碎片化表达和明显不通顺的口语表达。\n"
            "- 保留原始信息顺序、说话顺序和事实内容。\n"
            "- 不做总结，不做扩写，不做改写，不做术语纠错。\n\n"
            "严格规则：\n"
            "1. 只能做清洗整理，不得重新纠正专业术语、药名、基因位点、公司名、检测名、数值和单位。\n"
            "2. 如果文本中已经出现纠错后的专业术语，不得再次改写这些术语。\n"
            "3. 不要把多句内容强行压缩成一句，也不要把一句话拆得过碎。\n"
            "4. 不要补充原文没有的信息，不要推断，不要发挥。\n"
            "5. 不要改变说话顺序，不要改变原意，不要改变结论。\n"
            "6. 可以删除明显的口头禅、重复词、无意义停顿词，但不能删除有实际语义作用的连接词。\n"
            "7. 对于不确定是否应删除的内容，优先保留。\n"
            "8. 只输出清洗后的正文，不要输出解释、备注、分析。\n\n"
            "特别注意：\n"
            "- 不要修改已经正确的医学术语。\n"
            "- 不要修改药物通用名、商品名、基因突变位点、检测名、抗体克隆号、临床指标。\n"
            "- 不要把口语表达改写得过度书面化。\n"
            "- 保留原文中的数据、百分比、剂量、时间、频次、单位和缩写。\n\n"
            "输出要求：\n"
            "- 只输出合法 JSON。\n"
            "- 不要输出 markdown。\n"
            "- 不要输出多余文字。\n"
            "- 不要输出前缀、标题、解释。\n"
            "- 必须严格返回以下结构：\n\n"
            '{\n'
            '  "transcript": [\n'
            '    {\n'
            '      "uid": "u001",\n'
            '      "speaker_id": "speaker1",\n'
            '      "start_time": 12340,\n'
            '      "end_time": 15800,\n'
            '      "clean_text": "清洗后的正文"\n'
            '    }\n'
            '  ]\n'
            '}\n\n'
            "示例：\n"
            '{\n'
            '  "transcript": [\n'
            '    {\n'
            '      "uid": "u001",\n'
            '      "speaker_id": "speaker1",\n'
            '      "start_time": 12340,\n'
            '      "end_time": 15800,\n'
            '      "clean_text": "患者之前已经用过奥希替尼，后来考虑帕博利珠单抗。整体来看，这个检测方案的接受度还可以，但价格和准入仍然是主要问题。"\n'
            '    }\n'
            '  ]\n'
            '}\n\n'
            "【待清洗文本】\n"
            f"{transcript_block}\n\n"
            "请仅返回合法 JSON。"
        )

        content = cls.generate(system_prompt, user_prompt)
        try:
            parsed = cls._parse_json_payload(content)
        except json.JSONDecodeError:
            parsed = {}

        output_records = cls._extract_transcript_items(parsed)
        if not output_records:
            return [
                {
                    "uid": item["uid"],
                    "speaker_id": item["speaker_id"],
                    "start_time": item["start_time"],
                    "end_time": item["end_time"],
                    "corrected_text": item["text"],
                    "clean_text": item["text"],
                    "text": item["text"],
                    "corrections": item.get("corrections", []),
                    "uncertain_terms": item.get("uncertain_terms", []),
                }
                for item in normalized
            ]

        merged = cls._merge_transcript_output(
            normalized,
            output_records,
            output_text_field="clean_text",
            preserve_raw_fields=False,
        )
        for idx, item in enumerate(merged):
            source = transcript[idx] if idx < len(transcript) and isinstance(transcript[idx], dict) else {}
            if idx < len(normalized):
                item["corrected_text"] = normalized[idx].get("text", "")
            if not item.get("corrections"):
                item["corrections"] = source.get("corrections", [])
            if not item.get("uncertain_terms"):
                item["uncertain_terms"] = source.get("uncertain_terms", [])
            if not item.get("clean_text"):
                item["clean_text"] = item.get("text", "")
            item["text"] = item.get("clean_text", item.get("text", ""))
        return merged

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
        project_context: Optional[str] = None,
        interview_context: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        兼容旧接口的单条清洗包装器。

        参数:
            speaker_text: 原始转写文本。
            speaker_role: 说话人角色标签（如 interviewer / interviewee），可选。
            term_hints:   专业热词提示列表，用于纠正专有名词，格式为若干字符串。
            project_context: 项目背景说明块，可选；用于帮助模型理解本项目的业务语境、
                             研究对象和行业术语。

        返回:
            一个字典，至少包含:
            {
                "clean_text": str,          # 清洗后的文本
                "term_corrections": [       # 可选的术语纠错记录列表
                    {"from": str, "to": str}
                ]
            }
        """
        transcript = [
            {
                "uid": "u001",
                "speaker_id": speaker_role or "speaker",
                "start_time": 0,
                "end_time": 0,
                "text": speaker_text,
            }
        ]
        corrected = cls.correct_transcript_batch(
            transcript=transcript,
            term_hints=term_hints,
            project_context=project_context,
            interview_context=interview_context,
        )
        cleaned = cls.clean_transcript_batch(
            transcript=corrected,
            term_hints=term_hints,
            project_context=project_context,
            interview_context=interview_context,
        )
        first = cleaned[0] if cleaned else {}
        return {
            "clean_text": first.get("clean_text", speaker_text),
            "term_corrections": first.get("corrections", []),
            "uncertain_terms": first.get("uncertain_terms", []),
            "corrected_text": first.get("corrected_text", speaker_text),
        }

    @classmethod
    def extract_interview_context(
        cls,
        full_text: str,
        project_context: Optional[str] = None,
        term_hints: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        基于整篇 ASR 全文，提炼供后续纠错/清洗使用的简短背景说明。
        """
        full_text = str(full_text or "").strip()
        if not full_text:
            return {
                "domain": "未知",
                "subdomain": "未知",
                "interview_type": "未知",
                "context_brief": "",
                "key_terms": [],
                "important_entities": [],
                "speaker_roles": {},
            }

        project_context_text = cls._build_project_context_block(project_context)
        term_hint_text = ""
        if term_hints:
            joined_terms = ", ".join(term_hints)
            term_hint_text = f"专业术语提示: {joined_terms}\n\n"

        system_prompt = (
            "你现在是一位资深医学与医疗行业访谈背景提炼专家，熟悉肿瘤、体外诊断、分子检测、市场调研、医院准入、竞品分析等访谈场景。"
        )
        user_prompt = (
            f"{project_context_text}"
            f"{term_hint_text}"
            "你的任务是：阅读整篇访谈全文，提炼一段供后续“纠错 + 清洗”流程使用的访谈背景说明。\n\n"
            "核心目标：\n"
            "- 只提炼背景，不做总结报告。\n"
            "- 只提炼有助于后续术语纠错、语境理解和清洗整理的信息。\n"
            "- 必须严格基于原始文本，不要编造，不要补充未提到的业务事实。\n"
            "- 如果某些信息无法明确判断，宁可不写，不要猜测。\n\n"
            "你需要重点识别以下内容：\n"
            "1. 访谈所属的大领域或业务方向。\n"
            "2. 访谈主题或核心关注点。\n"
            "3. 文本中反复出现的高频专有词、药名、检测名、公司名、靶点名、缩写。\n"
            "4. 说话人之间大致的角色关系。\n"
            "5. 这场访谈的语境特征。\n\n"
            "严格规则：\n"
            "1. 不要输出逐句复述。\n"
            "2. 不要输出过长内容，控制在简洁、可注入 prompt 的长度。\n"
            "3. 不要加入推断性结论，不要扩写，不要解释原因。\n"
            "4. 只使用原文中明确出现的信息。\n"
            "5. 不要输出与后续清洗无关的细节。\n"
            "6. 如果某项信息不明确，直接留空或写“未知”，不要猜。\n\n"
            "输出要求：\n"
            "- 只输出合法 JSON。\n"
            "- 不要输出 markdown。\n"
            "- 不要输出多余文字。\n"
            "- 不要输出前缀、标题、解释。\n"
            "- 必须严格返回以下结构：\n\n"
            '{\n'
            '  "domain": "大领域",\n'
            '  "subdomain": "细分领域或未知",\n'
            '  "interview_type": "访谈类型",\n'
            '  "context_brief": "一段可直接注入后续 prompt 的背景说明，建议 1 到 3 句，尽量简洁",\n'
            '  "key_terms": ["术语1", "术语2"],\n'
            '  "important_entities": ["公司名/药名/检测名/靶点名"],\n'
            '  "speaker_roles": {\n'
            '    "speaker1": "访谈方/提问方/未知",\n'
            '    "speaker2": "被访谈方/回答方/未知"\n'
            "  }\n"
            "}\n\n"
            "示例：\n"
            '{\n'
            '  "domain": "市场调研",\n'
            '  "subdomain": "伴随诊断",\n'
            '  "interview_type": "行业访谈",\n'
            '  "context_brief": "这是一场围绕主流伴随诊断市场展开的行业访谈，重点讨论肿瘤相关靶点、分子检测、免疫组化以及国产与进口产品之间的竞争情况。访谈中频繁出现 PD-L1、HER2、MSI、MMR 等术语，整体语境偏市场调研和产品布局分析。",\n'
            '  "key_terms": ["PD-L1", "HER2", "MSI", "MMR", "分子检测", "免疫组化"],\n'
            '  "important_entities": ["PD-L1", "HER2", "MSI", "MMR"],\n'
            '  "speaker_roles": {\n'
            '    "speaker1": "提问方",\n'
            '    "speaker2": "回答方"\n'
            "  }\n"
            "}\n\n"
            "【全文转录】\n"
            f"{full_text}\n\n"
            "请仅返回合法 JSON。"
        )

        content = cls.generate(system_prompt, user_prompt)
        try:
            parsed = cls._parse_json_payload(content)
        except json.JSONDecodeError:
            return {
                "domain": "未知",
                "subdomain": "未知",
                "interview_type": "未知",
                "context_brief": full_text[:500],
                "key_terms": [],
                "important_entities": [],
                "speaker_roles": {},
                "llm_raw_output": content,
            }

        if not isinstance(parsed, dict):
            return {
                "domain": "未知",
                "subdomain": "未知",
                "interview_type": "未知",
                "context_brief": full_text[:500],
                "key_terms": [],
                "important_entities": [],
                "speaker_roles": {},
                "llm_raw_output": content,
            }

        parsed.setdefault("domain", "未知")
        parsed.setdefault("subdomain", "未知")
        parsed.setdefault("interview_type", "未知")
        parsed.setdefault("context_brief", "")
        parsed.setdefault("key_terms", [])
        parsed.setdefault("important_entities", [])
        parsed.setdefault("speaker_roles", {})
        return parsed

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
            project_context: 项目背景说明块，可选；会作为问题生成 Notes 的全局上下文。

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
        project_context_text = cls._build_project_context_block(project_context)

        system_prompt = (
            "你是一名医学、药学、体外诊断和市场调研领域的访谈分析专家，"
            "负责根据给定的访谈片段，针对指定问题生成结构化的研究 Notes。"
            "你必须严格基于提供的片段，不要编造事实，并且必须输出语法完全合法、"
            "可以被 json.loads 直接解析的 JSON。"
        )

        user_prompt = (
            f"{project_context_text}"
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
        project_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        使用大模型针对单个问题生成结构化 Notes，并注入 few-shot 示例。

        参数:
            question_text:    问题原文。
            segments:         RAG 检索到的相关片段列表。
            intent_name:      问题所属意图名称或描述。
            question_type:    问题类型标签。
            fewshot_samples:  few-shot 样本列表，由 Fewshot.select_fewshot_samples 返回。
            project_context:  项目背景说明块，可选；会与 few-shot 示例一起注入到 prompt 中。

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
        project_context_text = cls._build_project_context_block(project_context)

        system_prompt = (
            "你是一名医学、药学、体外诊断和市场调研领域的访谈分析专家，负责根据给定的访谈片段，"
            "针对指定问题生成结构化的研究 Notes。你必须严格基于提供的片段，不要编造事实，"
            "并且必须输出语法完全合法、可以被 json.loads 直接解析的 JSON。"
        )

        base_user_prompt = (
            f"{project_context_text}"
            "下面是一道研究问题及其相关的访谈片段，请你基于这些信息生成结构化的 Notes。\n\n"
            f"【问题类型】{qtype_part}\n"
            f"【问题意图】{intent_part}\n"
            f"【问题原文】{question_text}\n\n"
            "【相关访谈片段】\n"
            f"{context_block}\n\n"
            "请遵循以下要求完成任务:\n"
            "1. 只使用上述片段中的信息，不要引入任何未在片段中出现的事实；如果片段之间存在冲突，请直接写出冲突，不要强行统一。\n"
            "2. 如果信息不足以回答问题，请在 summary 和 analysis 中明确说明“当前访谈中信息不足”。\n"
            "3. summary 只写 1 到 3 句高度概括；analysis 负责更详细的解释、边界条件和影响因素，避免两者重复。\n"
            "4. 请给出一个 0 到 1 之间的置信度 confidence，用于表示你对答案可靠性的主观判断。\n"
            "5. evidence 中尽量引用与结论直接相关的原文短片段，不要改写成总结句。\n"
            "6. 输出时只返回 JSON，不要包含额外说明，不要使用 ``` 包裹，也不要输出任何 Markdown 标记（如 **、#、- 等）。\n"
            "7. 必须严格遵守 JSON 语法：键和值一律使用英文双引号 \" 包裹，不要使用中文引号或单引号；不要在 JSON 中添加注释；不要在数组或对象末尾保留多余的逗号。\n"
            "8. JSON 中字符串的换行必须编码为 \\n，而不是直接换行；同一字段的内容必须写在一行字符串中，由模型自动插入 \\n 作为换行标记。\n"
            "9. JSON 中字符串内部如需包含双引号，必须转义为 \\\"，避免破坏整体 JSON 结构。\n"
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
            "你只能修改引号、逗号、换行和转义相关问题，不得改写字段内容，不得增删字段名。"
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
