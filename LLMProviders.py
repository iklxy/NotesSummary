"@Date: 2026-04-24"
"@Author: lixinyang"

import base64
import json
from typing import Any, Dict, List, Optional


class BaseLLMProvider:
    """
    统一的大模型 provider 接口。

    所有 provider 都需要实现 `generate`，并返回字符串结果。
    """

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        max_tokens: int = 130000,
        temperature: float = 0.2,
    ) -> str:
        """
        执行一次模型调用。

        参数:
            system_prompt: 系统提示词，用于约束模型角色和输出规则。
            user_prompt: 业务侧拼装的用户提示词。
            model_name: 具体模型名称或版本标识。
            max_tokens: 模型本次调用允许返回的最大 token 数。
            temperature: 采样温度，用于控制结果的发散程度。

        返回:
            模型返回的文本结果。
        """
        raise NotImplementedError

    def generate_with_images(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        images: List[Dict[str, Any]],
        max_tokens: int = 130000,
        temperature: float = 0.2,
    ) -> str:
        """
        执行一次多模态生成。

        默认实现只用于提示不支持图像输入的 provider。
        """
        raise NotImplementedError


class AnthropicProvider(BaseLLMProvider):
    """
    Anthropic Claude provider 适配层。
    """

    def __init__(self, api_key: str, base_url: Optional[str] = None) -> None:
        """
        初始化 Anthropic 客户端。

        参数:
            api_key: Anthropic API key。
            base_url: 可选的自定义网关地址；不传时使用官方默认地址。
        """
        try:
            from anthropic import Anthropic  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "anthropic package 未安装，请先执行 `pip install anthropic` 后再使用 LLM_PROVIDER=anthropic"
            ) from exc
        client_kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = Anthropic(**client_kwargs)

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        max_tokens: int = 130000,
        temperature: float = 0.2,
    ) -> str:
        """
        调用 Anthropic messages API。

        参数:
            system_prompt: 系统提示词。
            user_prompt: 用户提示词。
            model_name: 模型名称。
            max_tokens: 最大输出 token 数。
            temperature: 采样温度。

        返回:
            文本结果；若返回结构不是纯文本，则回退成 JSON 字符串。
        """
        resp = self._client.messages.create(
            model=model_name,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": [{"type": "text", "text": user_prompt}]}],
        )
        if not resp.content:
            raise RuntimeError(f"LLM 返回内容为空: {resp}")

        first = resp.content[0]
        if getattr(first, "type", None) == "text":
            return first.text

        try:
            return json.dumps(resp.model_dump(), ensure_ascii=False)
        except Exception:
            return str(resp)

    def generate_with_images(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        images: List[Dict[str, Any]],
        max_tokens: int = 130000,
        temperature: float = 0.2,
    ) -> str:
        """
        调用 Anthropic messages API，支持图片输入。
        """
        content: List[Dict[str, Any]] = [{"type": "text", "text": user_prompt}]
        for image in images:
            image_bytes = image.get("data")
            mime_type = str(image.get("mime_type") or "image/png").strip() or "image/png"
            if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
                continue
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": base64.b64encode(bytes(image_bytes)).decode("ascii"),
                    },
                }
            )

        resp = self._client.messages.create(
            model=model_name,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": content}],
        )
        if not resp.content:
            raise RuntimeError(f"LLM 返回内容为空: {resp}")

        first = resp.content[0]
        if getattr(first, "type", None) == "text":
            return first.text

        try:
            return json.dumps(resp.model_dump(), ensure_ascii=False)
        except Exception:
            return str(resp)


class GeminiProvider(BaseLLMProvider):
    """
    Gemini provider 适配层。
    """

    def __init__(self, api_key: str, base_url: Optional[str] = None) -> None:
        """
        初始化 Gemini 客户端。

        参数:
            api_key: Gemini API key。
            base_url: 可选的基础地址；Gemini 官方 SDK 对自定义地址支持有限，通常会忽略。
        """
        try:
            from google import genai  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "google-genai package 未安装，请先执行 `pip install google-genai` 后再使用 Gemini provider"
            ) from exc
        client_kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["http_options"] = {"base_url": base_url}
        self._client = genai.Client(**client_kwargs)

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        max_tokens: int = 130000,
        temperature: float = 0.2,
    ) -> str:
        """
        调用 Gemini generate_content。

        参数:
            system_prompt: 系统提示词。
            user_prompt: 用户提示词。
            model_name: 模型名称。
            max_tokens: 最大输出 token 数。
            temperature: 采样温度。

        返回:
            文本结果；若 SDK 没有直接给 text，则从 candidates 中提取。
        """
        try:
            from google.genai import types  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "google-genai package 未安装，请先执行 `pip install google-genai` 后再使用 Gemini provider"
            ) from exc
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

    def generate_with_images(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        images: List[Dict[str, Any]],
        max_tokens: int = 130000,
        temperature: float = 0.2,
    ) -> str:
        """
        调用 OpenAI chat.completions，支持图片输入。
        """
        content: List[Dict[str, Any]] = [{"type": "text", "text": user_prompt}]
        for image in images:
            image_bytes = image.get("data")
            mime_type = str(image.get("mime_type") or "image/png").strip() or "image/png"
            if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
                continue
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{base64.b64encode(bytes(image_bytes)).decode('ascii')}",
                    },
                }
            )

        response = self._client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
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

    def generate_with_images(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        images: List[Dict[str, Any]],
        max_tokens: int = 130000,
        temperature: float = 0.2,
    ) -> str:
        """
        调用 Gemini generate_content，支持图片输入。
        """
        try:
            from google.genai import types  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "google-genai package 未安装，请先执行 `pip install google-genai` 后再使用 Gemini provider"
            ) from exc

        contents: List[Any] = [user_prompt]
        for image in images:
            image_bytes = image.get("data")
            mime_type = str(image.get("mime_type") or "image/png").strip() or "image/png"
            if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
                continue
            contents.append(types.Part.from_bytes(data=bytes(image_bytes), mime_type=mime_type))

        response = self._client.models.generate_content(
            model=model_name,
            contents=contents,
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
    豆包 / 火山方舟 provider 适配层。
    """

    def __init__(self, api_key: str, base_url: Optional[str] = None) -> None:
        """
        初始化豆包 / Ark 客户端。

        参数:
            api_key: Ark API key。
            base_url: 可选的自定义网关地址。
        """
        try:
            from volcenginesdkarkruntime import Ark  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "volcenginesdkarkruntime package 未安装，请先执行 `pip install 'volcengine-python-sdk[ark]'`"
            ) from exc
        ark_kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            ark_kwargs["base_url"] = base_url
        self._client = Ark(**ark_kwargs)

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        max_tokens: int = 130000,
        temperature: float = 0.2,
    ) -> str:
        """
        调用 Ark chat.completions。

        参数:
            system_prompt: 系统提示词。
            user_prompt: 用户提示词。
            model_name: 模型名称。
            max_tokens: 最大输出 token 数。
            temperature: 采样温度。

        返回:
            文本结果；若响应不是纯文本，则回退为 JSON 字符串。
        """
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

    def generate_with_images(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        images: List[Dict[str, Any]],
        max_tokens: int = 130000,
        temperature: float = 0.2,
    ) -> str:
        """
        调用 Ark chat.completions，支持图片输入。
        """
        content: List[Dict[str, Any]] = [{"type": "text", "text": user_prompt}]
        for image in images:
            image_bytes = image.get("data")
            mime_type = str(image.get("mime_type") or "image/png").strip() or "image/png"
            if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
                continue
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{base64.b64encode(bytes(image_bytes)).decode('ascii')}",
                    },
                }
            )

        response = self._client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
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
    OpenAI provider 适配层，同时兼容 OpenAI 风格接口。
    """

    def __init__(self, api_key: str, base_url: Optional[str] = None) -> None:
        """
        初始化 OpenAI 客户端。

        参数:
            api_key: OpenAI API key 或兼容接口的访问 key。
            base_url: 可选的自定义兼容接口地址。
        """
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
        max_tokens: int = 130000,
        temperature: float = 0.2,
    ) -> str:
        """
        调用 OpenAI chat.completions。

        参数:
            system_prompt: 系统提示词。
            user_prompt: 用户提示词。
            model_name: 模型名称。
            max_tokens: 最大输出 token 数。
            temperature: 采样温度。

        返回:
            文本结果；若响应不是纯文本，则回退为 JSON 字符串。
        """
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

    def generate_with_images(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        images: List[Dict[str, Any]],
        max_tokens: int = 130000,
        temperature: float = 0.2,
    ) -> str:
        """
        调用 OpenAI chat.completions，支持图片输入。
        """
        content: List[Dict[str, Any]] = [{"type": "text", "text": user_prompt}]
        for image in images:
            image_bytes = image.get("data")
            mime_type = str(image.get("mime_type") or "image/png").strip() or "image/png"
            if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
                continue
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{base64.b64encode(bytes(image_bytes)).decode('ascii')}",
                    },
                }
            )

        response = self._client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
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


def resolve_provider_base_url(provider_name: str, base_url: Optional[str]) -> Optional[str]:
    """
    规范化不同 provider 对 `base_url` 的接受方式。

    参数:
        provider_name: provider 名称，例如 `anthropic`、`openai`、`gemini`。
        base_url: 环境变量中配置的基础地址。

    返回:
        适合传给对应 provider 的基础地址；不适用时返回 `None`。
    """
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


def build_provider(provider_name: str, api_key: str, base_url: Optional[str]) -> BaseLLMProvider:
    """
    根据 provider 名称构造具体 provider 实例。

    参数:
        provider_name: provider 名称。
        api_key: 访问对应模型服务的 API key。
        base_url: 可选的服务基础地址。

    返回:
        实例化后的 provider 对象。
    """
    effective_base_url = resolve_provider_base_url(provider_name, base_url)
    if provider_name == "anthropic":
        return AnthropicProvider(api_key=api_key, base_url=effective_base_url)
    if provider_name in {"gemini", "google", "google-genai"}:
        return GeminiProvider(api_key=api_key, base_url=effective_base_url)
    if provider_name in {"openai", "gpt", "chatgpt"}:
        return OpenAIProvider(api_key=api_key, base_url=effective_base_url)
    if provider_name in {"doubao", "ark", "volcengine", "volcano"}:
        return DoubaoProvider(api_key=api_key, base_url=effective_base_url)
    raise RuntimeError(f"暂不支持的 LLM_PROVIDER: {provider_name}")
