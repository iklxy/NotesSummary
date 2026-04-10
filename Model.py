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
