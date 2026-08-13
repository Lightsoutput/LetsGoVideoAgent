from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from lets_go_video_agent.domain.common import DomainModel, utc_now
from lets_go_video_agent.domain.observability import TraceEvent
from lets_go_video_agent.domain.processing import ProcessingAgentTask


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


class SkillCategoryProfile(DomainModel):
    """从多样本中提炼的类别画像，只记录稳定共性，不记忆单条视频答案。"""

    category_name: str = Field(default="通用视频", max_length=120)
    style_summary: str = Field(default="", max_length=1_000)
    common_formats: list[str] = Field(default_factory=list, max_length=12)
    typical_content: list[str] = Field(default_factory=list, max_length=20)
    narrative_patterns: list[str] = Field(default_factory=list, max_length=20)
    visual_language: list[str] = Field(default_factory=list, max_length=20)
    audience_expectations: list[str] = Field(default_factory=list, max_length=12)
    stable_signals: list[str] = Field(default_factory=list, max_length=20)
    variable_signals: list[str] = Field(default_factory=list, max_length=20)


class SkillEssenceEvidence(DomainModel):
    """一条类别结论及其样本依据，避免把通用模板伪装成样本洞察。"""

    insight: str = Field(min_length=1, max_length=800)
    supporting_video_ids: list[UUID] = Field(default_factory=list, max_length=8)
    observations: list[str] = Field(default_factory=list, max_length=12)


class SkillCategoryEssence(DomainModel):
    """真正从样本中提炼出的类别精髓，与通用运行规则严格分层。"""

    extraction_status: str = Field(
        default="insufficient", pattern="^(sample-derived|insufficient)$"
    )
    one_sentence_essence: str = Field(default="", max_length=1_000)
    content_core: list[str] = Field(default_factory=list, max_length=20)
    visual_signature: list[str] = Field(default_factory=list, max_length=20)
    narration_copywriting: list[str] = Field(default_factory=list, max_length=20)
    storytelling_engine: list[str] = Field(default_factory=list, max_length=20)
    pacing_editing: list[str] = Field(default_factory=list, max_length=20)
    recurring_devices: list[str] = Field(default_factory=list, max_length=20)
    viewer_value: list[str] = Field(default_factory=list, max_length=16)
    evidence: list[SkillEssenceEvidence] = Field(default_factory=list, max_length=24)
    confidence_notes: list[str] = Field(default_factory=list, max_length=12)


class SkillRuntimeTarget(DomainModel):
    """明确 Skill 的某组规则装给哪类模型、用在哪些阶段。"""

    target_id: str = Field(pattern=r"^[a-z0-9_]+$", max_length=40)
    target_name: str = Field(max_length=120)
    provider: str = Field(max_length=80)
    model: str = Field(max_length=160)
    stages: list[str] = Field(default_factory=list, max_length=16)
    instructions: list[str] = Field(default_factory=list, max_length=20)


class SkillDefaultQuestion(DomainModel):
    question: str = Field(max_length=300)
    purpose: str = Field(max_length=500)
    answer_structure: list[str] = Field(default_factory=list, max_length=12)


class SkillOutputTemplate(DomainModel):
    name: str = Field(max_length=120)
    use_when: str = Field(max_length=500)
    fields: list[str] = Field(default_factory=list, max_length=20)


class SkillContent(DomainModel):
    """可注入 Agent 的领域能力契约；所有权限字段都只能缩小系统权限。"""

    applicable_video_types: list[str] = Field(default_factory=list, max_length=12)
    category_essence: SkillCategoryEssence = Field(default_factory=SkillCategoryEssence)
    category_profile: SkillCategoryProfile = Field(default_factory=SkillCategoryProfile)
    runtime_targets: list[SkillRuntimeTarget] = Field(default_factory=list, max_length=6)
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
    default_questions: list[SkillDefaultQuestion] = Field(default_factory=list, max_length=12)
    output_templates: list[SkillOutputTemplate] = Field(default_factory=list, max_length=8)

    def vision_instructions(self) -> str:
        """仅向视觉模型注入与画面观察有关的最小上下文。"""

        targets = [item for item in self.runtime_targets if item.target_id == "vision"]
        sections = [
            f"视频类别：{self.category_profile.category_name}",
            f"类别画面精髓：{'；'.join(self.category_essence.visual_signature)}",
            f"反复出现的视觉手法：{'；'.join(self.category_essence.recurring_devices)}",
            f"常见视觉语言：{'；'.join(self.category_profile.visual_language)}",
            f"视觉关注：{'；'.join(self.visual_focus)}",
            *(
                [f"类别视觉规则：{'；'.join(targets[0].instructions)}"]
                if targets
                else []
            ),
        ]
        return "\n".join(item for item in sections if not item.endswith("："))[:4_000]

    def text_instructions(self, stage: str = "qa") -> str:
        """按文本推理阶段注入类别规律，避免把视觉规则整包重复发送。"""

        targets = [
            item
            for item in self.runtime_targets
            if item.target_id == "reasoning" and (not item.stages or stage in item.stages)
        ]
        base = self.runtime_instructions()
        extra = "；".join(targets[0].instructions) if targets else ""
        return f"{base}\n当前阶段规则：{extra}"[:8_000] if extra else base

    def runtime_instructions(self) -> str:
        """生成短小的运行时上下文，避免整个 Skill 无条件占满模型上下文。"""

        terms = "；".join(f"{item.term}：{item.meaning}" for item in self.terminology[:20])
        sections = [
            f"类别精髓：{self.category_essence.one_sentence_essence}",
            f"内容内核：{'；'.join(self.category_essence.content_core)}",
            f"文案与讲述：{'；'.join(self.category_essence.narration_copywriting)}",
            f"叙事驱动：{'；'.join(self.category_essence.storytelling_engine)}",
            f"节奏与剪辑：{'；'.join(self.category_essence.pacing_editing)}",
            f"类别画像：{self.category_profile.style_summary}",
            f"常见形式：{'；'.join(self.category_profile.common_formats)}",
            f"叙事规律：{'；'.join(self.category_profile.narrative_patterns)}",
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


class SkillProjectStatus(StrEnum):
    ACTIVE = "active"
    PROCESSING = "processing"
    READY = "ready"
    ATTENTION = "attention"


class SkillProjectItemStatus(StrEnum):
    QUEUED = "queued"
    IMPORTING = "importing"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class SkillProjectChapterPreview(DomainModel):
    title: str = Field(max_length=300)
    summary: str = Field(default="", max_length=1_000)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)


class SkillProjectFramePreview(DomainModel):
    title: str = Field(max_length=300)
    description: str = Field(default="", max_length=1_000)
    timestamp_ms: int = Field(ge=0)
    snapshot_filename: str | None = Field(default=None, max_length=300)


class SkillProjectVideoInsight(DomainModel):
    """流水线卡片使用的视频理解结果摘要，不再只展示处理状态。"""

    video_format: str = Field(default="通用视频", max_length=120)
    purpose: str = Field(default="", max_length=1_000)
    summary: str = Field(default="", max_length=3_000)
    themes: list[str] = Field(default_factory=list, max_length=12)
    chapters: list[SkillProjectChapterPreview] = Field(default_factory=list, max_length=20)
    representative_frames: list[SkillProjectFramePreview] = Field(
        default_factory=list, max_length=8
    )


class SkillProject(DomainModel):
    """围绕一类视频长期积累样本与 Skill 的工作空间。"""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=600)
    goal: str = Field(min_length=4, max_length=2_000)
    status: SkillProjectStatus = SkillProjectStatus.ACTIVE
    skill_id: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SkillProjectItem(DomainModel):
    """项目中的单条视频任务；保留来源 URL，支持失败重试和服务重启恢复。"""

    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    source_url: str = Field(min_length=8, max_length=2_048)
    video_id: UUID | None = None
    title: str = Field(default="等待读取视频信息", max_length=300)
    status: SkillProjectItemStatus = SkillProjectItemStatus.QUEUED
    trace_id: UUID | None = None
    stage: str = "queued"
    stage_label: str = "等待分配"
    progress: float = Field(default=0, ge=0, le=1)
    current_agent: str | None = Field(default=None, max_length=160)
    message: str = Field(default="已加入项目队列", max_length=1_000)
    error: str | None = Field(default=None, max_length=2_000)
    agent_tasks: list[ProcessingAgentTask] = Field(default_factory=list)
    insight: SkillProjectVideoInsight | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SkillProjectAgent(DomainModel):
    """面向用户的 Agent 工位快照，不暴露模型隐藏推理。"""

    id: str
    display_name: str
    role: str
    avatar: str
    status: str = "idle"
    video_id: UUID | None = None
    video_title: str | None = None
    task: str = "等待新任务"
    progress: float = Field(default=0, ge=0, le=1)
    trace_id: UUID | None = None
    active_tasks: int = Field(default=0, ge=0)
    message: str = "等待新任务"
    completed_units: int = Field(default=0, ge=0)
    total_units: int | None = Field(default=None, ge=0)
    model_provider: str | None = None
    model: str | None = None
    assignments: list[SkillProjectAgentAssignment] = Field(default_factory=list)


class SkillProjectAgentAssignment(DomainModel):
    """一个 Agent 当前在某条样本视频上的具体分工。"""

    video_id: UUID
    video_title: str
    trace_id: UUID | None = None
    task: str
    message: str
    progress: float = Field(default=0, ge=0, le=1)
    completed_units: int = Field(default=0, ge=0)
    total_units: int | None = Field(default=None, ge=0)


class SkillProjectCostSummary(DomainModel):
    """按当前 Skill 项目归属的模型/API 成本，不与其他视频任务混算。"""

    total_cost_cny: Decimal = Field(default=Decimal(), ge=0)
    call_count: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    image_count: int = Field(default=0, ge=0)
    by_model: dict[str, Decimal] = Field(default_factory=dict)
    by_agent: dict[str, Decimal] = Field(default_factory=dict)
    by_video: dict[str, Decimal] = Field(default_factory=dict)
    by_purpose: dict[str, Decimal] = Field(default_factory=dict)


class SkillProjectModelRoute(DomainModel):
    target: str
    provider: str
    model: str
    agent_id: str
    agent_display_name: str
    stages: list[str] = Field(default_factory=list)
    configured: bool = True


class SkillProjectWorkspace(DomainModel):
    project: SkillProject
    items: list[SkillProjectItem] = Field(default_factory=list)
    agents: list[SkillProjectAgent] = Field(default_factory=list)
    recent_logs: list[TraceEvent] = Field(default_factory=list)
    cost_summary: SkillProjectCostSummary = Field(default_factory=SkillProjectCostSummary)
    model_routes: list[SkillProjectModelRoute] = Field(default_factory=list)
