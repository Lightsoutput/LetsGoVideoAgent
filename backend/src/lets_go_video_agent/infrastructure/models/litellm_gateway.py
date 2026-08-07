from __future__ import annotations

import asyncio
import importlib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import Field

from lets_go_video_agent.domain.common import DomainModel, ModelUsage

CompletionCallable = Callable[..., Awaitable[object]]
CostCalculator = Callable[[object], Decimal]


class ModelGatewayError(RuntimeError):
    pass


class ModelCallTimeoutError(ModelGatewayError):
    pass


class ModelCallBudgetExceededError(ModelGatewayError):
    def __init__(self, message: str, *, actual_cost_usd: Decimal | None = None) -> None:
        super().__init__(message)
        self.actual_cost_usd = actual_cost_usd


class ChatMessage(DomainModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(min_length=1)


class ModelCompletion(DomainModel):
    content: str
    model: str
    finish_reason: str | None = None
    response_id: str | None = None
    usage: ModelUsage


class LiteLLMModelGateway:
    """LiteLLM 的薄适配层，不把供应商对象泄漏到 Agent 领域层。

    Harness 应在调用前按估算价格预留总预算；此处再次执行单次调用上限，并在
    响应后记录真实费用。后置检查无法追回已经产生的费用，因此不能替代 Harness
    的调用前预算预留。
    """

    def __init__(
        self,
        *,
        default_model: str,
        api_key: str | None = None,
        api_base: str | None = None,
        allowed_models: frozenset[str] | None = None,
        default_timeout_seconds: float = 60,
        max_output_tokens: int = 4_096,
        completion: CompletionCallable | None = None,
        cost_calculator: CostCalculator | None = None,
    ) -> None:
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens 必须大于 0")
        self._default_model = default_model
        self._api_key = api_key
        self._api_base = api_base
        self._allowed_models = allowed_models
        self._default_timeout_seconds = default_timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._completion = completion or _litellm_completion
        self._cost_calculator = cost_calculator or _litellm_cost

    async def complete(
        self,
        *,
        messages: Sequence[ChatMessage],
        model: str | None = None,
        temperature: float = 0,
        max_output_tokens: int | None = None,
        timeout_seconds: float | None = None,
        max_cost_usd: Decimal | None = None,
        estimated_cost_usd: Decimal = Decimal("0"),
        response_format: Mapping[str, object] | None = None,
    ) -> ModelCompletion:
        selected_model = model or self._default_model
        if self._allowed_models is not None and selected_model not in self._allowed_models:
            raise ModelGatewayError(f"模型不在允许列表中: {selected_model}")
        if not messages:
            raise ValueError("模型消息不能为空")
        output_limit = max_output_tokens or self._max_output_tokens
        if not 1 <= output_limit <= self._max_output_tokens:
            raise ValueError(f"max_output_tokens 必须位于 1 到 {self._max_output_tokens} 之间")
        effective_timeout = timeout_seconds or self._default_timeout_seconds
        if effective_timeout <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        if max_cost_usd is not None and estimated_cost_usd > max_cost_usd:
            raise ModelCallBudgetExceededError("模型调用的预估费用超过单次预算")

        request: dict[str, object] = {
            "model": selected_model,
            "messages": [message.model_dump(mode="json") for message in messages],
            "temperature": temperature,
            "max_tokens": output_limit,
            "timeout": effective_timeout,
        }
        if self._api_key:
            request["api_key"] = self._api_key
        if self._api_base:
            request["api_base"] = self._api_base
        if response_format is not None:
            request["response_format"] = dict(response_format)

        try:
            # 即使供应商 SDK 忽略 timeout 参数，外层 wait_for 仍会停止当前协程。
            # 不在网关内部自动重试，避免一次逻辑调用被重复计费；重试由 Harness
            # 在保留幂等记录和剩余预算的情况下显式决定。
            response = await asyncio.wait_for(
                self._completion(**request),
                timeout=effective_timeout,
            )
        except TimeoutError as exc:
            raise ModelCallTimeoutError(
                f"模型 {selected_model} 调用超过 {effective_timeout:g} 秒"
            ) from exc
        except ModelGatewayError:
            raise
        except Exception as exc:
            # 请求正文与 API Key 不进入异常消息和 Trace，避免用户视频内容或密钥泄漏。
            raise ModelGatewayError(
                f"模型 {selected_model} 调用失败: {type(exc).__name__}"
            ) from exc

        completion = _parse_completion(
            response,
            fallback_model=selected_model,
            cost_calculator=self._cost_calculator,
        )
        if max_cost_usd is not None and completion.usage.estimated_cost_usd > max_cost_usd:
            raise ModelCallBudgetExceededError(
                "模型调用的实际费用超过单次预算",
                actual_cost_usd=completion.usage.estimated_cost_usd,
            )
        return completion


async def _litellm_completion(**kwargs: object) -> object:
    module = importlib.import_module("litellm")
    return await module.acompletion(**kwargs)


def _litellm_cost(response: object) -> Decimal:
    hidden = _field(response, "_hidden_params")
    if isinstance(hidden, Mapping):
        value = hidden.get("response_cost")
        parsed = _decimal_or_none(value)
        if parsed is not None:
            return parsed
    module = importlib.import_module("litellm")
    try:
        value = module.completion_cost(completion_response=response)
    except Exception:
        return Decimal("0")
    return _decimal_or_none(value) or Decimal("0")


def _parse_completion(
    response: object,
    *,
    fallback_model: str,
    cost_calculator: CostCalculator,
) -> ModelCompletion:
    choices = _field(response, "choices")
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or not choices:
        raise ModelGatewayError("模型响应缺少 choices")
    choice = choices[0]
    message = _field(choice, "message")
    content_value = _field(message, "content")
    if not isinstance(content_value, str) or not content_value.strip():
        raise ModelGatewayError("模型响应没有文本内容")

    usage_value = _field(response, "usage")
    input_tokens = _nonnegative_int(_field(usage_value, "prompt_tokens"))
    output_tokens = _nonnegative_int(_field(usage_value, "completion_tokens"))
    try:
        cost = cost_calculator(response)
    except Exception:
        cost = Decimal("0")
    if cost < 0:
        cost = Decimal("0")

    model_value = _field(response, "model")
    model_name = str(model_value) if model_value else fallback_model
    finish_value = _field(choice, "finish_reason")
    response_id_value = _field(response, "id")
    return ModelCompletion(
        content=content_value,
        model=model_name,
        finish_reason=str(finish_value) if finish_value else None,
        response_id=str(response_id_value) if response_id_value else None,
        usage=ModelUsage(
            model_calls=1,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=cost,
        ),
    )


def _field(value: object, name: str) -> object | None:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _nonnegative_int(value: object) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None
