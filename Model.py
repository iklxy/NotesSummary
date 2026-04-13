"@Date: 2026-04-10"
"@Author: lixinyang"

import os
import json
from typing import Any, Dict, List, Optional
import dotenv
from anthropic import Anthropic

dotenv.load_dotenv()


class ModelClient:
    """
    大模型调用封装类，用于对接 Anthropic Claude，并提供上层任务接口。

    配置约定（从环境变量读取）:
        - LLM_API_KEY: 模型访问的 API Key。
        - LLM_BASE_URL: 模型 API 基础 URL。（如果使用Claude的官方API则无需配置该参数）
        - LLM_MODEL_NAME:    模型名称或版本标识。
    """

    def __init__(self) -> None:
        api_key = os.getenv("LLM_API_KEY")
        base_url = os.getenv("LLM_BASE_URL")
        model_name = os.getenv("LLM_MODEL_NAME")

        if not api_key or not model_name:
            raise RuntimeError("ANTHROPIC_API_KEY / LLM_MODEL_NAME 未正确配置")

        self.client = Anthropic(api_key=api_key,
                                base_url=base_url)
        
        self.model_name = model_name

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """
        调用 Anthropic Claude，返回文本形式的回复内容。

        参数:
            system_prompt: 系统提示，用于约束整体角色和输出规范。
            user_prompt:   用户输入内容，描述当前具体任务。

        返回:
            模型返回的文本内容（假定为单段字符串）。
        """
        resp = self.client.messages.create(
            model=self.model_name,
            max_tokens=2048,
            temperature=0.2,
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

    def clean_speaker_utterance(
        self,
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

        content = self.generate(system_prompt, user_prompt)
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

    def generate_notes_for_question(
        self,
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
            "针对指定问题生成结构化的研究 Notes。你必须严格基于提供的片段，不要编造事实。"
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
            "4. 输出时只返回 JSON，不要包含额外说明，也不要使用 ``` 包裹。\n"
            "JSON 结构如下:\n"
            "{\n"
            '  "summary": "一句话或几句话的高度概括",\n'
            '  "analysis": "更详细的分析和解释，适合写入研究笔记",\n'
            '  "evidence": [\n'
            '    {"summary_id": 0, "speaker": "speaker1", "text": "与结论直接相关的原文片段"}\n'
            "  ],\n"
            '  "confidence": 0.0\n'
            "}\n"
        )

        content = self.generate(system_prompt, user_prompt)
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
