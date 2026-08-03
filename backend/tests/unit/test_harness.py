from uuid import uuid4

import pytest

from lets_go_video_agent.agents.harness.engine import (
    AgentHarness,
    BudgetExceededError,
    PolicyDeniedError,
)
from lets_go_video_agent.agents.harness.models import AgentRun, RunBudget
from lets_go_video_agent.agents.harness.tools import ToolRegistry, ToolSpec
from lets_go_video_agent.domain.common import DomainModel


class EchoPayload(DomainModel):
    value: str


def make_session(*, max_tool_calls: int = 2, max_repeat: int = 2):
    registry = ToolRegistry()

    async def echo(payload: DomainModel) -> EchoPayload:
        return EchoPayload.model_validate(payload)

    registry.register(
        ToolSpec(
            name="echo",
            description="测试工具",
            input_model=EchoPayload,
            output_model=EchoPayload,
            handler=echo,
        )
    )
    run = AgentRun(
        agent_name="test-agent",
        agent_version="1",
        video_id=uuid4(),
        conversation_id=uuid4(),
        budget=RunBudget(
            max_tool_calls=max_tool_calls,
            max_repeated_tool_call=max_repeat,
        ),
    )
    return AgentHarness(registry).start_session(run=run, allowed_tools={"echo"})


@pytest.mark.asyncio
async def test_unknown_tool_is_denied() -> None:
    session = make_session()
    with pytest.raises(PolicyDeniedError):
        await session.invoke_tool("shell", {"value": "whoami"})


@pytest.mark.asyncio
async def test_budget_stops_before_excessive_tool_call() -> None:
    session = make_session(max_tool_calls=1)
    await session.invoke_tool("echo", {"value": "one"})
    with pytest.raises(BudgetExceededError):
        await session.invoke_tool("echo", {"value": "two"})


@pytest.mark.asyncio
async def test_repeated_tool_loop_is_stopped() -> None:
    session = make_session(max_tool_calls=10, max_repeat=1)
    await session.invoke_tool("echo", {"value": "same"})
    with pytest.raises(PolicyDeniedError):
        await session.invoke_tool("echo", {"value": "same"})
