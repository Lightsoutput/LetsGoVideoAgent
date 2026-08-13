from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from lets_go_video_agent.domain.observability import UsageEvent
from lets_go_video_agent.infrastructure.models.deepseek_client import CostLedger


@dataclass(frozen=True, slots=True)
class SiliconFlowVisionPrices:
    """Qwen3-VL-32B-Instruct 官方人民币价格（每 100 万 tokens）。"""

    input: Decimal = Decimal("1")
    output: Decimal = Decimal("4")


class SiliconFlowVisionClient:
    """硅基流动 OpenAI 兼容多模态适配器，并通过余额差记录真实人民币扣费。"""

    provider = "siliconflow"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        api_base: str,
        ledger: CostLedger,
        timeout_seconds: float = 180,
        proxy_url: str | None = None,
        prices: SiliconFlowVisionPrices | None = None,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._api_base = api_base.rstrip("/")
        self._ledger = ledger
        self._timeout = timeout_seconds
        self._proxy_url = proxy_url
        self._prices = prices or SiliconFlowVisionPrices()

    async def _balance(self, client: httpx.AsyncClient) -> Decimal | None:
        try:
            response = await client.get(
                f"{self._api_base}/user/info",
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=5,
            )
            response.raise_for_status()
            value = (response.json().get("data") or {}).get("totalBalance")
            return Decimal(str(value)) if value is not None else None
        except (httpx.HTTPError, ValueError, TypeError, ArithmeticError):
            return None

    async def analyze_frames(
        self,
        frames: list[dict[str, Any]],
        *,
        video_id: str | None = None,
        question: str | None = None,
        skill_context: str | None = None,
        trace_id: str | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not frames:
            return []
        timestamps = [int(item["timestamp_ms"]) for item in frames]
        prompt = (
            "你正在按时间顺序观察同一视频的采样画面，时间戳（毫秒）依次为："
            f"{timestamps}。不要只抄写OCR，要理解每张画面的场景、主体、人物动作、"
            "游戏或软件界面状态、事件含义以及与前后画面的变化。输出严格JSON："
            '{"observations":[{"timestamp_ms":整数,"scene":"场景",'
            '"subjects":["主体"],"actions":["动作或事件"],"meaning":"画面表达的含义",'
            '"entities":["需要核验的专名"],"importance":0到1,"uncertainty":"不确定项"}]}。'
            "每个输入时间戳必须恰好对应一条 observation，不得补造画面外信息。"
        )
        # 通用视觉协议只规定观察方法和输出结构；垂类知识应由后续 Skill 注入。
        prompt = (
            f"按输入顺序分析同一视频的画面，时间戳（毫秒）为：{timestamps}。"
            "先识别内容形态和画面布局，再逐区域说明可见对象、文字、状态、动作、关系与事件，"
            "最后概括画面在当前语境中表达的意义。区分直接可见事实与推断，不得沿用其他帧信息，"
            "不得只复述OCR。输出严格JSON："
            '{"observations":[{"timestamp_ms":整数,"scene":"内容形态与场景",'
            '"subjects":["可见主体"],"actions":["动作或状态变化"],'
            '"meaning":"该画面的整体意义","entities":["画面中的专有名词"],'
            '"importance":0到1,"uncertainty":"不确定项"}]}。'
            "每张输入图片必须恰好对应一条 observation。"
        )
        if question:
            prompt += (
                f"\n用户问题：{question}。围绕问题检查相关区域和细节，但不要预设视频类别或字段；"
                "若画面不足以回答，明确指出缺失信息。"
            )
        if skill_context:
            prompt += (
                "\n以下是用户审核发布的类别 Skill 视觉规则，只用于提示应关注的画面结构；"
                "不得用样本规律覆盖当前画面直接证据：\n"
                f"{skill_context[:4_000]}"
            )
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for frame in frames:
            image_bytes = await asyncio.to_thread(Path(frame["path"]).read_bytes)
            encoded = base64.b64encode(image_bytes).decode()
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                }
            )
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": 2_400,
        }
        async with httpx.AsyncClient(
            timeout=self._timeout,
            proxy=self._proxy_url,
        ) as client:
            before = await self._balance(client)
            response = await client.post(
                f"{self._api_base}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            response.raise_for_status()
            after = await self._balance(client)
        body = response.json()
        usage = body.get("usage") or {}
        balance_cost = (
            max(Decimal(), before - after)
            if before is not None and after is not None
            else Decimal()
        )
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        token_cost = (
            Decimal(input_tokens) * self._prices.input
            + Decimal(output_tokens) * self._prices.output
        ) / Decimal("1000000")
        # 余额接口的展示精度可能低于单次请求费用，前后差值会得到 0。
        # 此时不能把一次真实 VLM 调用误报为免费，改用官方 token 单价回算。
        actual_cost = balance_cost if balance_cost > 0 else token_cost
        pricing_source = (
            "SiliconFlow account balance delta"
            if balance_cost > 0
            else "SiliconFlow official token pricing (CNY 1 input / 4 output per M tokens)"
        )
        record = {
                "timestamp": datetime.now(UTC).isoformat(),
                "provider": "siliconflow",
                "model": body.get("model", self.model),
                "purpose": "video_visual_understanding",
                "video_id": video_id,
                "trace_id": trace_id,
                "task_id": task_id,
                "agent_id": agent_id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": int(usage.get("total_tokens") or 0),
                "image_count": len(frames),
                "cost_cny": str(actual_cost.quantize(Decimal("0.000000001"))),
                "pricing_source": pricing_source,
            }
        await self._ledger.record(
            record,
            UsageEvent(
                provider="siliconflow",
                model=str(body.get("model", self.model)),
                purpose="video_visual_understanding",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                image_count=len(frames),
                original_cost=actual_cost,
                cost_cny=actual_cost,
                pricing_version=pricing_source,
                video_id=_optional_uuid(video_id),
                trace_id=_optional_uuid(trace_id),
                task_id=_optional_uuid(task_id),
                agent_id=agent_id,
            ),
        )
        content_text = str(body["choices"][0]["message"].get("content") or "")
        parsed = json.loads(content_text)
        observations = parsed.get("observations", [])
        if not isinstance(observations, list):
            return []
        valid_timestamps = set(timestamps)
        return [
            item
            for item in observations
            if isinstance(item, dict) and int(item.get("timestamp_ms", -1)) in valid_timestamps
        ]


def _optional_uuid(value: str | None) -> UUID | None:
    try:
        return UUID(value) if value else None
    except ValueError:
        return None
