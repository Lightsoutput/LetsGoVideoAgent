from pathlib import Path

import pytest

from lets_go_video_agent.agents.roles.skill_builder import SkillBuilderAgent, SkillSampleProfile
from lets_go_video_agent.application.services import VideoService
from lets_go_video_agent.application.skill_projects import SkillProjectService
from lets_go_video_agent.application.skill_studio import (
    SkillPolicyValidator,
    SkillStudioService,
    SkillValidationError,
)
from lets_go_video_agent.domain.processing import ProcessingRun, ProcessingStatus
from lets_go_video_agent.domain.skill import (
    SkillCategoryEssence,
    SkillCategoryProfile,
    SkillContent,
    SkillDefaultQuestion,
    SkillEssenceEvidence,
    SkillOutputTemplate,
    SkillProject,
    SkillRuntimeTarget,
)
from lets_go_video_agent.fixtures import DEMO_VIDEO_ID, seed_demo
from lets_go_video_agent.infrastructure.memory import InMemoryStore
from lets_go_video_agent.media.local_storage import LocalUploadStore
from lets_go_video_agent.media.url_policy import SourceUrlPolicy


class StubProcessingManager:
    def __init__(self) -> None:
        self.runs: dict = {}

    def start(self, video_id):
        run = ProcessingRun(
            video_id=video_id,
            status=ProcessingStatus.RUNNING,
            stage="transcribing",
            stage_label="语音转写",
            progress=0.35,
            message="正在识别语音",
        )
        self.runs[video_id] = run
        return run

    def get(self, video_id):
        return self.runs.get(video_id)


def test_skill_essence_does_not_copy_one_conclusion_into_every_dimension() -> None:
    sample_id = str(DEMO_VIDEO_ID)
    repeated = "固定角色通过连续误会推动日常故事"
    normalized = SkillBuilderAgent._normalize_essence(
        {
            "one_sentence_essence": repeated,
            "content_core": [repeated, repeated],
            "visual_signature": [repeated],
            "narration_copywriting": [repeated],
            "storytelling_engine": [repeated],
            "pacing_editing": [],
            "evidence": [
                {
                    "insight": repeated,
                    "supporting_video_ids": [sample_id],
                    "observations": ["多个样本出现同一角色关系"],
                }
            ],
        },
        [
            # normalization 只依赖样本 ID，这里使用最小样本即可验证维度去重。
            SkillSampleProfile(video_id=sample_id, title="样本")
        ],
    )

    assert normalized["content_core"] == [repeated]
    assert normalized["visual_signature"] == []
    assert normalized["narration_copywriting"] == []
    assert normalized["storytelling_engine"] == []
    assert any("尚未形成相互独立" in item for item in normalized["confidence_notes"])


def test_skill_essence_redistributes_mixed_conclusions_without_emptying_dimensions() -> None:
    sample_id = str(DEMO_VIDEO_ID)
    conclusions = [
        "固定角色关系与日常事件构成内容核心",
        "画面使用纯色背景、卡通人物与符号化表情",
        "第一人称口播采用短句、自嘲和轻松语气",
        "故事通过意外、冲突升级和结尾反转推进",
        "剪辑节奏紧凑，每个章节承担一个情节阶段",
    ]
    normalized = SkillBuilderAgent._normalize_essence(
        {
            "one_sentence_essence": "用荒诞日常和连续反转讲述朋友故事",
            "content_core": conclusions,
            "visual_signature": conclusions,
            "narration_copywriting": conclusions,
            "storytelling_engine": conclusions,
            "pacing_editing": conclusions,
            "evidence": [
                {
                    "insight": item,
                    "supporting_video_ids": [sample_id],
                    "observations": [f"样本中可观察到：{item}"],
                }
                for item in conclusions
            ],
        },
        [SkillSampleProfile(video_id=sample_id, title="样本")],
    )

    for field in (
        "content_core",
        "visual_signature",
        "narration_copywriting",
        "storytelling_engine",
        "pacing_editing",
    ):
        assert normalized[field]
    flattened = [
        item
        for field in (
            "content_core",
            "visual_signature",
            "narration_copywriting",
            "storytelling_engine",
            "pacing_editing",
        )
        for item in normalized[field]
    ]
    assert len(flattened) == len(set(flattened))


def test_skill_policy_rejects_permission_escalation() -> None:
    content = SkillContent(
        objectives=["理解内容"],
        segmentation_hints=["按主题分段"],
        visual_focus=["理解画面语义"],
        qa_strategy=["使用证据回答"],
        output_requirements=["给出时间戳"],
        category_profile=SkillCategoryProfile(
            style_summary="同类内容使用稳定叙事结构",
            narrative_patterns=["主题与画面变化共同决定分段"],
        ),
        runtime_targets=[
            SkillRuntimeTarget(
                target_id="vision",
                target_name="视觉模型",
                provider="test",
                model="vision-test",
            ),
            SkillRuntimeTarget(
                target_id="reasoning",
                target_name="推理模型",
                provider="test",
                model="reasoning-test",
            ),
        ],
        default_questions=[
            SkillDefaultQuestion(
                question="讲了什么",
                purpose="测试",
                answer_structure=["结论"],
            )
        ],
        output_templates=[SkillOutputTemplate(name="速览", use_when="完成后", fields=["结论"])],
        boundary_conditions=["不覆盖直接证据"],
        allowed_tools=["search_timeline", "shell"],
    )

    report = SkillPolicyValidator().validate(content)

    assert report.valid is False
    assert any("未授权工具" in item for item in report.errors)


def test_skill_policy_allows_negative_security_boundary_but_rejects_request() -> None:
    category_essence = SkillCategoryEssence(
        extraction_status="sample-derived",
        one_sentence_essence="通过稳定的画面阶段和讲述结构解释游戏操作",
        content_core=["操作步骤与决策原因"],
        visual_signature=["游戏界面状态随操作阶段变化"],
        narration_copywriting=["先说结论，再解释操作原因"],
        storytelling_engine=["目标、执行、结果和复盘"],
        pacing_editing=["按目标、执行、结果和复盘切分节奏"],
        evidence=[
            SkillEssenceEvidence(
                insight="画面状态和口播共同推进步骤解释",
                supporting_video_ids=[DEMO_VIDEO_ID],
                observations=["编队、实战与复盘阶段具有不同画面和讲述任务"],
            )
        ],
    )
    base = dict(
        category_essence=category_essence,
        objectives=["理解内容"],
        segmentation_hints=["按主题分段"],
        visual_focus=["理解画面语义"],
        qa_strategy=["使用证据回答"],
        output_requirements=["给出时间戳"],
        category_profile=SkillCategoryProfile(
            style_summary="同类内容使用稳定叙事结构",
            narrative_patterns=["主题与画面变化共同决定分段"],
        ),
        runtime_targets=[
            SkillRuntimeTarget(
                target_id="vision", target_name="视觉模型", provider="test", model="vision-test"
            ),
            SkillRuntimeTarget(
                target_id="reasoning", target_name="推理模型", provider="test", model="text-test"
            ),
        ],
        default_questions=[
            SkillDefaultQuestion(question="讲了什么", purpose="测试", answer_structure=["结论"])
        ],
        output_templates=[SkillOutputTemplate(name="速览", use_when="完成后", fields=["结论"])],
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

    regenerated = await service.regenerate(
        skill_id=detail.skill.id,
        video_ids=[DEMO_VIDEO_ID],
        user_goal="验证加入新样本后的类别精髓是否仍然独立准确",
    )
    assert regenerated.skill.id == detail.skill.id
    assert regenerated.versions[0].version == 3
    assert regenerated.versions[0].parent_version == 2
    assert regenerated.versions[0].sample_video_ids == [DEMO_VIDEO_ID]
    assert regenerated.skill.active_version == 1

    with pytest.raises(SkillValidationError):
        await service.rollback(detail.skill.id, 2)
    rolled_back = await service.rollback(detail.skill.id, 1)
    assert rolled_back.skill.active_version == 1

    # 内存开发仓库重建后仍保留用户审核发布的 Skill。
    restored = InMemoryStore(skill_catalog_path=tmp_path / "catalog.json")
    assert await restored.get_skill(detail.skill.id) is not None


@pytest.mark.asyncio
async def test_delete_skill_removes_versions_bindings_artifact_and_project_reference(
    tmp_path: Path,
) -> None:
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
        user_goal="验证 Skill 删除会清理关联数据",
        display_name="待删除 Skill",
    )
    detail = await service.publish(detail.skill.id, 1)
    await service.bind(detail.skill.id, [DEMO_VIDEO_ID])
    project = SkillProject(
        name="删除测试项目",
        goal="验证项目引用可以安全清理",
        skill_id=detail.skill.id,
    )
    await store.upsert_skill_project(project)
    artifact = tmp_path / "generated" / detail.skill.slug / "v1" / "SKILL.md"
    assert artifact.exists()

    await service.delete_many([detail.skill.id])

    assert await store.get_skill(detail.skill.id) is None
    assert list(await store.list_skill_versions(detail.skill.id)) == []
    assert await store.get_skill_binding(DEMO_VIDEO_ID) is None
    stored_project = await store.get_skill_project(project.id)
    assert stored_project is not None and stored_project.skill_id is None
    assert not artifact.exists()


@pytest.mark.asyncio
async def test_skill_project_persists_batch_items_and_exposes_agent_work(tmp_path: Path) -> None:
    store = InMemoryStore(skill_catalog_path=tmp_path / "catalog.json")
    processing = StubProcessingManager()
    videos = VideoService(
        videos=store,
        timeline=store,
        upload_store=LocalUploadStore(root=tmp_path / "videos", max_bytes=1_000_000),
        url_policy=SourceUrlPolicy(),
    )
    service = SkillProjectService(
        store=store,
        videos=videos,
        processing=processing,
    )

    workspace = await service.create(
        name="Zc故事",
        goal="理解故事类视频的叙事结构、人物和视觉线索",
    )
    workspace = await service.add_urls(
        project_id=workspace.project.id,
        urls=[
            "https://www.bilibili.com/video/BV1111111111/",
            "https://www.bilibili.com/video/BV2222222222/",
        ],
        rights_confirmed=True,
    )

    assert len(workspace.items) == 2
    assert all(item.status.value == "processing" for item in workspace.items)
    audio_agent = next(agent for agent in workspace.agents if agent.id == "audio_perception_agent")
    assert audio_agent.active_tasks == 2

    restored = InMemoryStore(skill_catalog_path=tmp_path / "catalog.json")
    assert len(await restored.list_skill_projects()) == 1
    assert len(await restored.list_skill_project_items(workspace.project.id)) == 2
