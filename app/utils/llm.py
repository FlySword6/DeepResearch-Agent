"""LLM 调用封装，支持 OpenAI、DeepSeek 和 Anthropic。"""

import json
import os
from contextvars import ContextVar
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

_usage_meter: ContextVar[Optional[list]] = ContextVar("usage_meter", default=None)


class LLMConfig(BaseModel):
    """单次 LLM 调用配置。"""

    model: str = Field(default="gpt-4o")
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1)
    provider: str = Field(default="openai")
    base_url: str = Field(default="https://api.openai.com/v1")


class LLMProvider:
    """LLM 供应商枚举值。"""

    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    ANTHROPIC = "anthropic"


def set_usage_meter(meter: Optional[list]) -> None:
    """设置当前任务的 token 用量收集器。

    TaskManager 会在每个后台任务开始时传入一个 list，LLM 调用完成后
    将 usage 信息追加进去，最终用于报告统计。传 None 表示清理当前上下文。
    """
    _usage_meter.set(meter)


def _record_usage(response: Any, provider: str, model: str) -> None:
    """从模型响应中提取 token 用量，失败时静默跳过。"""
    meter = _usage_meter.get()
    if meter is None:
        return

    usage = getattr(response, "usage", None)
    if usage is None:
        return

    def _get(name: str) -> int:
        value = getattr(usage, name, 0)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    meter.append({
        "provider": provider,
        "model": model,
        "prompt_tokens": _get("prompt_tokens") or _get("input_tokens"),
        "completion_tokens": _get("completion_tokens") or _get("output_tokens"),
        "total_tokens": _get("total_tokens"),
    })


async def llm_call(
    system_prompt: str,
    user_prompt: str,
    config: Optional[LLMConfig] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """统一 LLM 调用入口。"""
    if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("ALLOW_LIVE_LLM_TESTS") != "1":
        raise ValueError("Live LLM calls are disabled during tests")

    if config is None:
        config = LLMConfig()

    provider = config.provider.lower()

    if provider in (LLMProvider.OPENAI, LLMProvider.DEEPSEEK):
        return await _call_openai(system_prompt, user_prompt, config, tools)
    elif provider == LLMProvider.ANTHROPIC:
        return await _call_anthropic(system_prompt, user_prompt, config, tools)
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")


async def _call_openai(
    system_prompt: str,
    user_prompt: str,
    config: LLMConfig,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """调用 OpenAI 兼容 API。

    DeepSeek 兼容 OpenAI Chat Completions 协议，因此共用这个调用路径。
    """
    from openai import AsyncOpenAI

    from app.config import settings
    from app.services.config_service import get_active_config

    rt = get_active_config()
    api_key = rt.api_key if (rt and rt.api_key) else ""
    if not api_key and config.provider.lower() == LLMProvider.DEEPSEEK:
        api_key = settings.DEEPSEEK_API_KEY or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        api_key = settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY or DEEPSEEK_API_KEY environment variable not set")

    base_url = rt.base_url if (rt and rt.base_url) else config.base_url
    client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=15.0, max_retries=1)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    kwargs = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }

    if tools:
        kwargs["tools"] = tools

    response = await client.chat.completions.create(**kwargs)
    _record_usage(response, config.provider.lower(), config.model)
    return response.choices[0].message.content or ""


async def _call_anthropic(
    system_prompt: str,
    user_prompt: str,
    config: LLMConfig,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """调用 Anthropic API。"""
    from anthropic import AsyncAnthropic

    from app.config import settings
    from app.services.config_service import get_active_config

    rt = get_active_config()
    api_key = rt.api_key if (rt and rt.api_key) else (settings.ANTHROPIC_API_KEY or os.getenv("ANTHROPIC_API_KEY"))
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")

    client = AsyncAnthropic(api_key=api_key, timeout=15.0, max_retries=1)

    kwargs = {
        "model": config.model,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }

    if tools:
        kwargs["tools"] = tools

    response = await client.messages.create(**kwargs)
    _record_usage(response, config.provider.lower(), config.model)
    return response.content[0].text if response.content else ""


def resolve_model(agent_model: Optional[str] = None) -> str:
    """解析模型名称：显式 Agent 模型 > 运行时配置 > 默认值。"""
    if agent_model:
        return agent_model
    from app.services.config_service import get_active_config

    rt = get_active_config()
    if rt and rt.model:
        return rt.model
    return "gpt-4o"


def extract_json_from_response(response: str) -> Dict[str, Any]:
    """从 LLM 响应中提取 JSON。"""
    import re

    json_str = response.strip()

    # 优先尝试提取 Markdown 代码块中的 JSON。
    match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", json_str)
    if match:
        json_str = match.group(1).strip()

    return json.loads(json_str)
