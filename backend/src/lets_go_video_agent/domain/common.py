from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    """返回带时区的 UTC 时间，避免数据库与 Trace 中出现歧义。"""

    return datetime.now(UTC)


class DomainModel(BaseModel):
    """所有领域对象的严格基类。

    `extra="forbid"` 很重要：Agent 工具参数或 API 字段拼错时应立刻失败，而不是被
    静默忽略，否则一次看似成功的运行可能实际上没有遵守用户指定的时间范围。
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=False,
    )


class TimeRange(DomainModel):
    """视频时间范围，统一使用整数毫秒。

    不用浮点秒可以避免序列化和多次换算后产生肉眼难以解释的小数误差。
    """

    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_bounds(self) -> TimeRange:
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms 必须大于 start_ms")
        return self

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    def overlaps(self, other: TimeRange) -> bool:
        return self.start_ms < other.end_ms and other.start_ms < self.end_ms

    def contains(self, timestamp_ms: int) -> bool:
        return self.start_ms <= timestamp_ms <= self.end_ms


class SpatialRegion(DomainModel):
    """归一化画面区域，数值与原始视频分辨率解耦。"""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def validate_canvas_bounds(self) -> SpatialRegion:
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("画面区域不能超出归一化画布")
        return self


class Provenance(DomainModel):
    """记录某条信息从哪里来，支持回答后的证据审计。"""

    producer: str
    producer_version: str = "0.1.0"
    model: str | None = None
    prompt_version: str | None = None
    tool_version: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ModelUsage(DomainModel):
    """模型与 Agent 调用用量；金额用 Decimal，避免费用统计出现浮点累积误差。"""

    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: Decimal = Field(default=Decimal("0"), ge=0)
    elapsed_ms: int = Field(default=0, ge=0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
