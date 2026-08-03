from lets_go_video_agent.agents.roles.processing_planner import (
    ProcessingPlanner,
    ProcessingProfile,
)
from lets_go_video_agent.domain.video import SyntheticSource, Video


def test_economy_plan_defers_expensive_visual_analysis() -> None:
    video = Video(
        title="test",
        source=SyntheticSource(fixture_name="test"),
        duration_ms=600_000,
    )
    plan = ProcessingPlanner().plan(video, ProcessingProfile.ECONOMY)

    visual_step = next(step for step in plan.steps if step.name == "visual_understanding")
    assert visual_step.parameters["on_demand"] is True
    assert plan.estimated_visual_calls == 50
