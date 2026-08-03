import pytest

from lets_go_video_agent.evaluation.cli import evaluate_synthetic_suite


@pytest.mark.asyncio
async def test_synthetic_eval_suite_passes_without_external_services() -> None:
    report = await evaluate_synthetic_suite()

    assert report.passed
    assert report.passed_cases == report.total_cases == 4
    assert report.total_estimated_cost_usd == "0"
