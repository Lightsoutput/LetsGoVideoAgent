from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel

ToolHandler = Callable[[BaseModel], Awaitable[BaseModel]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Agent 工具的强类型说明。

    Handler 不直接暴露数据库、Shell 或网络客户端。工具门面先校验参数，再调用应用端口，
    因此字幕或 OCR 中即使出现“请执行命令”也只会被当作普通证据文本。
    """

    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: ToolHandler
    timeout_seconds: float = 15.0


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"工具已注册: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._tools)
