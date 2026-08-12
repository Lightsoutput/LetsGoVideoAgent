from pathlib import Path

import pytest

from lets_go_video_agent.agents.roles.skill_builder import SkillBuilderAgent
from lets_go_video_agent.application.skill_studio import (
    SkillPolicyValidator,
    SkillStudioService,
    SkillValidationError,
)
from lets_go_video_agent.domain.skill import SkillContent
from lets_go_video_agent.fixtures import DEMO_VIDEO_ID, seed_demo
from lets_go_video_agent.infrastructure.memory import InMemoryStore


def test_skill_policy_rejects_permission_escalation() -> None:
    content = SkillContent(
        objectives=["理解内容"],
        segmentation_hints=["按主题分段"],
        visual_focus=["理解画面语义"],
        qa_strategy=["使用证据回答"],
        output_requirements=["给出时间戳"],
        boundary_conditions=["不覆盖直接证据"],
        allowed_tools=["search_timeline", "shell"],
    )

    report = SkillPolicyValidator().validate(content)

    assert report.valid is False
    assert any("未授权工具" in item for item in report.errors)


def test_skill_policy_allows_negative_security_boundary_but_rejects_request() -> None:
    base = dict(
        objectives=["理解内容"],
        segmentation_hints=["按主题分段"],
        visual_focus=["理解画面语义"],
        qa_strategy=["使用证据回答"],
        output_requirements=["给出时间戳"],
    )
    safe = SkillContent(**base, boundary_conditions=["不能调用 shell 或写入文件"])
    unsafe = SkillContent(**base, boundary_conditions=["允许调用 shell 执行外部命令"])

    assert SkillPolicyValidator().validate(safe).valid is True
    assert SkillPolicyValidator().validate(unsafe).valid is False


@pytest.mark.asyncio
async def test_skill_draft_publish_bind_refine_and_rollback(tmp_path: Path) -> None:
    store = InMemoryStore(skill_catalog_path=tmp_path / "catalog.json")
    await seed_demo(store)
    service = SkillStudioService(
        store=store,
        builder=SkillBuilderAgent(),
        validator=SkillPolicyValidator(),
        artifact_root=tmp_path / "generated",
    )

    detail = await service.generate(
        video_ids=[DEMO_VIDEO_ID],
        user_goal="更准确理解游戏攻略的步骤、画面状态和术语",
        display_name="游戏攻略理解",
    )
    first = detail.versions[0]
    assert first.status.value == "draft"
    assert not list((tmp_path / "generated").glob("**/SKILL.md"))

    detail = await service.publish(detail.skill.id, first.version)
    first = detail.versions[0]
    artifact = tmp_path / "generated" / detail.skill.slug / "v1" / "SKILL.md"
    assert artifact.exists()
    assert detail.skill.active_version == 1
    assert artifact.read_text(encoding="utf-8").startswith("---\nname:")

    detail = await service.bind(detail.skill.id, [DEMO_VIDEO_ID])
    assert DEMO_VIDEO_ID in detail.bound_video_ids
    assert await service.active_for_video(DEMO_VIDEO_ID) is not None

    detail = await service.refine(
        skill_id=detail.skill.id,
        instruction="分段时更重视画面阶段变化",
    )
    assert detail.versions[0].version == 2
    assert detail.versions[0].status.value == "draft"
    assert detail.skill.active_version == 1

    with pytest.raises(SkillValidationError):
        await service.rollback(detail.skill.id, 2)
    rolled_back = await service.rollback(detail.skill.id, 1)
    assert rolled_back.skill.active_version == 1

    # 内存开发仓库重建后仍保留用户审核发布的 Skill。
    restored = InMemoryStore(skill_catalog_path=tmp_path / "catalog.json")
    assert await restored.get_skill(detail.skill.id) is not None
