# -*- coding: utf-8 -*-

"""
Kiro 转换器工具函数

包含 Extended Thinking 模式支持函数
"""

from typing import Any, Dict, Optional, Union
import logging
import uuid

logger = logging.getLogger(__name__)


# ==================================================================================================
# Thinking Mode 支持
# ==================================================================================================

# 默认最大思考长度
DEFAULT_MAX_THINKING_LENGTH = 200000


def is_thinking_enabled(thinking_config: Optional[Union[Dict[str, Any], bool, str]]) -> bool:
    """
    检测 thinking 是否启用。

    支持多种格式：
    - None: 未启用
    - bool: True/False
    - str: "enabled"
    - dict: {"type": "enabled", "budget_tokens": 10000}

    Args:
        thinking_config: thinking 配置

    Returns:
        是否启用 thinking
    """
    if thinking_config is None:
        return False
    if isinstance(thinking_config, bool):
        return thinking_config
    if isinstance(thinking_config, str):
        return thinking_config.lower() == "enabled"
    if isinstance(thinking_config, dict):
        type_val = str(thinking_config.get("type", "")).lower()
        if type_val == "enabled":
            return True
        budget = thinking_config.get("budget_tokens")
        if isinstance(budget, (int, float)) and budget > 0:
            return True
    return False


def get_thinking_budget(thinking_config: Optional[Union[Dict[str, Any], bool, str]]) -> int:
    """
    获取 thinking 的 token 预算。

    Args:
        thinking_config: thinking 配置

    Returns:
        token 预算，默认为 DEFAULT_MAX_THINKING_LENGTH
    """
    if isinstance(thinking_config, dict):
        budget = thinking_config.get("budget_tokens")
        if isinstance(budget, (int, float)) and budget > 0:
            return int(budget)
    return DEFAULT_MAX_THINKING_LENGTH


def generate_thinking_hint(thinking_config: Optional[Union[Dict[str, Any], bool, str]]) -> str:
    """
    生成 thinking 模式的提示标签。

    Args:
        thinking_config: thinking 配置

    Returns:
        thinking 提示标签字符串
    """
    budget = get_thinking_budget(thinking_config)
    return f"<thinking_mode>enabled</thinking_mode>\n<max_thinking_length>{budget}</max_thinking_length>"


def inject_thinking_hint(system_prompt: str, thinking_config: Optional[Union[Dict[str, Any], bool, str]]) -> str:
    """
    将 thinking 提示注入到 system prompt 中。

    如果 system prompt 已经包含 thinking 标签，则不重复注入。

    Args:
        system_prompt: 原始 system prompt
        thinking_config: thinking 配置

    Returns:
        注入后的 system prompt
    """
    if not is_thinking_enabled(thinking_config):
        return system_prompt

    # 检查是否已经包含 thinking 标签
    if "<thinking_mode>" in system_prompt or "<max_thinking_length>" in system_prompt:
        return system_prompt

    thinking_hint = generate_thinking_hint(thinking_config)

    if not system_prompt:
        return thinking_hint

    # 将 thinking hint 添加到 system prompt 开头
    return f"{thinking_hint}\n\n{system_prompt}"


def add_kiro_conversation_state(payload: Dict[str, Any]) -> None:
    """
    为 Kiro payload 添加 conversationState 字段。

    Args:
        payload: Kiro 请求 payload（会被原地修改）
    """
    if "conversationState" not in payload:
        payload["conversationState"] = {}

    payload["conversationState"]["agentContinuationId"] = str(uuid.uuid4())
    payload["conversationState"]["agentTaskType"] = "vibe"


def apply_thinking_to_request(
    openai_request: Dict[str, Any],
    thinking_config: Optional[Union[Dict[str, Any], bool, str]] = None
) -> Dict[str, Any]:
    """
    将 thinking 配置应用到 OpenAI 格式的请求中。

    Args:
        openai_request: OpenAI 格式的请求
        thinking_config: thinking 配置

    Returns:
        修改后的请求（原地修改并返回）
    """
    if not is_thinking_enabled(thinking_config):
        return openai_request

    messages = openai_request.get("messages", [])
    if not isinstance(messages, list):
        messages = []
        openai_request["messages"] = messages

    injected = False
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "system":
            system_prompt = msg.get("content", "")
            if isinstance(system_prompt, str):
                msg["content"] = inject_thinking_hint(system_prompt, thinking_config)
                injected = True
                logger.debug("Injected thinking hint into existing system prompt")
                break

    # 没有 system prompt 时，创建一个仅包含 thinking hint 的 system 消息
    if not injected:
        messages.insert(0, {"role": "system", "content": generate_thinking_hint(thinking_config)})
        logger.debug("Inserted system prompt with thinking hint")

    return openai_request
