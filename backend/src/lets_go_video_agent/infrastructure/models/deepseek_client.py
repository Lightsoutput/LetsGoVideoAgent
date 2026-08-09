from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from lets_go_video_agent.application.ports import ObservabilityRepository
from lets_go_video_agent.domain.observability import UsageEvent


@dataclass(frozen=True, slots=True)
class DeepSeekPrices:
    """DeepSeek V4 Flash 官方人民币价格（每 100 万 tokens）。"""

    cache_hit_input: Decimal = Decimal("0.02")
    cache_miss_input: Decimal = Decimal("1")
    output: Decimal = Decimal("2")


class CostLedger:
    """只记录计费元数据，不保存提示词、视频内容或 API Key。"""

    def __init__(
        self,
        path: Path,
        *,
        events: ObservabilityRepository | None = None,
    ) -> None:
        self.path = path
        self._events = events
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    async def record(self, record: dict[str, Any], usage: UsageEvent) -> None:
        """同时保留 P0 JSONL 兼容记录和 V1.0 可查询的统一用量事件。"""
        self.append(record)
        if self._events is not None:
            await self._events.append_usage_event(usage)

    def summary(self) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        total = sum((Decimal(str(item.get("cost_cny", "0"))) for item in records), Decimal())
        return {
            "currency": "CNY",
            "total_cost_cny": str(total.quantize(Decimal("0.000000001"))),
            "call_count": len(records),
            "records": records[-50:],
        }


class DeepSeekClient:
    """DeepSeek 的窄适配层，直接读取官方 usage 计算人民币实付估算。"""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        api_base: str,
        ledger: CostLedger,
        prices: DeepSeekPrices | None = None,
        proxy_url: str | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._api_base = api_base.rstrip("/")
        self._ledger = ledger
        self._prices = prices or DeepSeekPrices()
        self._proxy_url = proxy_url

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        purpose: str,
        video_id: str | None = None,
        max_tokens: int = 1800,
        thinking: bool = False,
        reasoning_effort: str = "high",
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "enabled" if thinking else "disabled"},
        }
        if thinking:
            payload["reasoning_effort"] = reasoning_effort
        else:
            payload["temperature"] = 0
        # 深度思考会先生成推理 token，同一问题通常比普通 JSON 回答耗时更长。
        # 这里仅放宽思考请求的读取窗口；普通请求仍保持较短超时，避免 Worker 假死。
        async with httpx.AsyncClient(
            timeout=120 if thinking else 90,
            proxy=self._proxy_url,
        ) as client:
            response = await client.post(
                f"{self._api_base}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
        response.raise_for_status()
        body = response.json()
        usage = body.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}
        hit = int(usage.get("prompt_cache_hit_tokens") or details.get("cached_tokens") or 0)
        prompt = int(usage.get("prompt_tokens") or 0)
        miss = int(usage.get("prompt_cache_miss_tokens") or max(0, prompt - hit))
        output = int(usage.get("completion_tokens") or 0)
        million = Decimal("1000000")
        cost = (
            Decimal(hit) * self._prices.cache_hit_input
            + Decimal(miss) * self._prices.cache_miss_input
            + Decimal(output) * self._prices.output
        ) / million
        record = {
                "timestamp": datetime.now(UTC).isoformat(),
                "provider": "deepseek",
                "model": body.get("model", self.model),
                "purpose": purpose,
                "video_id": video_id,
                "cache_hit_input_tokens": hit,
                "cache_miss_input_tokens": miss,
                "output_tokens": output,
                "total_tokens": int(usage.get("total_tokens") or prompt + output),
                "cost_cny": str(cost.quantize(Decimal("0.000000001"))),
                "pricing_source": "DeepSeek official V4 Flash pricing",
            }
        await self._ledger.record(
            record,
            UsageEvent(
                provider="deepseek",
                model=str(body.get("model", self.model)),
                purpose=purpose,
                input_tokens=prompt,
                output_tokens=output,
                original_cost=cost,
                cost_cny=cost,
                cache_hit=hit > 0,
                pricing_version="DeepSeek official V4 Flash pricing",
                video_id=_optional_uuid(video_id),
            ),
        )
        content = str(body["choices"][0]["message"].get("content") or "").strip()
        return _parse_json_object(content)


def _parse_json_object(content: str) -> dict[str, Any]:
    """兼容偶发 Markdown 围栏或 JSON 前后说明，避免有效结构化响应被误判。"""
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(lines[1:-1]).strip() if len(lines) >= 3 else content
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(content[start : end + 1])
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("expected JSON object", content, 0)
    return parsed


def _optional_uuid(value: str | None) -> UUID | None:
    try:
        return UUID(value) if value else None
    except ValueError:
        return None
