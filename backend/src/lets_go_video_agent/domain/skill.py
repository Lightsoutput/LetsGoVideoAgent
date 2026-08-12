from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from lets_go_video_agent.domain.common import DomainModel, utc_now


class SkillStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class SkillTerm(DomainModel):
    """领域术语不是关键词替换表，而是带核验策略的概念说明。"""

    term: str = Field(min_length=1, max_length=120)
    meaning: str = Field(min_length=1, max_length=500)
    aliases: list[str] = Field(default_factory=list, max_length=12)
    verification: str = Field(default="结合字幕、OCR、上下文与搜索交叉核验", max_length=500)


class SkillContent(DomainModel):
    """可注入 Agent 的领域能力契约；所有权限字段都只能缩小系统权限。"""

    applicable_video_types: list[str] = Field(default_factory=list, max_length=12)
    objectives: list[str] = Field(default_factory=list, max_length=16)
    terminology: list[SkillTerm] = Field(default_factory=list, max_length=80)
    segmentation_hints: list[str] = Field(default_factory=list, max_length=20)
    visual_focus: list[str] = Field(default_factory=list, max_length=20)
    qa_strategy: list[str] = Field(default_factory=list, max_length=20)
    output_requirements: list[str] = Field(default_factory=list, max_length=20)
    allowed_agents: list[str] = Field(
        default_factory=lambda: ["qa_investigator", "evidence_verifier"],
        max_length=12,
    )
    allowed_tools: list[str] = Field(
        default_factory=lambda: ["search_timeline", "inspect_frame", "search_web"],
        max_length=12,
    )
    allowed_mcps: list[str] = Field(default_factory=lambda: ["search"], max_length=8)
    model_guidance: str = Field(
        default="优先使用经济模型，证据冲突时再升级模型。",
        max_length=1_500,
    )
    positive_examples: list[str] = Field(default_factory=list, max_length=12)
    negative_examples: list[str] = Field(default_factory=list, max_length=12)
    boundary_conditions: list[str] = Field(default_factory=list, max_length=16)
    known_limitations: list[str] = Field(default_factory=list, max_length=16)

    def runtime_instructions(self) -> str:
        """生成短小的运行时上下文，避免整个 Skill 无条件占满模型上下文。"""

        terms = "；".join(f"{item.term}：{item.meaning}" for item in self.terminology[:20])
        sections = [
            f"适用类型：{'、'.join(self.applicable_video_types)}",
            f"分析目标：{'；'.join(self.objectives)}",
            f"分段线索：{'；'.join(self.segmentation_hints)}",
            f"视觉关注：{'；'.join(self.visual_focus)}",
            f"问答策略：{'；'.join(self.qa_strategy)}",
            f"输出要求：{'；'.join(self.output_requirements)}",
            f"领域术语：{terms}",
            f"边界条件：{'；'.join(self.boundary_conditions)}",
        ]
        return "\n".join(item for item in sections if not item.endswith("："))[:8_000]


class SkillValidationReport(DomainModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=utc_now)


class Skill(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=63)
    display_name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=600)
    author: str = Field(default="local-user", max_length=120)
    status: SkillStatus = SkillStatus.DRAFT
    active_version: int | None = Field(default=None, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SkillVersion(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    skill_id: UUID
    version: int = Field(ge=1)
    status: SkillStatus = SkillStatus.DRAFT
    content: SkillContent
    sample_video_ids: list[UUID] = Field(default_factory=list, max_length=8)
    user_goal: str = Field(min_length=1, max_length=2_000)
    generation_basis: list[str] = Field(default_factory=list, max_length=20)
    validation: SkillValidationReport
    trace_id: UUID = Field(default_factory=uuid4)
    parent_version: int | None = Field(default=None, ge=1)
    change_summary: str = Field(default="初始草案", max_length=1_000)
    artifact_path: str | None = Field(default=None, max_length=1_024)
    created_at: datetime = Field(default_factory=utc_now)
    published_at: datetime | None = None


class SkillBinding(DomainModel):
    """视频绑定 Skill，而版本始终跟随 Skill 当前发布版本，便于统一回滚。"""

    video_id: UUID
    skill_id: UUID
    created_at: datetime = Field(default_factory=utc_now)


class SkillDetail(DomainModel):
    skill: Skill
    versions: list[SkillVersion]
    bound_video_ids: list[UUID] = Field(default_factory=list)
