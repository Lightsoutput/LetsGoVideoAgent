from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID, uuid4

from lets_go_video_agent.agents.roles.skill_builder import SkillBuilderAgent, SkillSampleProfile
from lets_go_video_agent.application.errors import ApplicationError, NotFoundError
from lets_go_video_agent.application.ports import AppStore
from lets_go_video_agent.domain.common import utc_now
from lets_go_video_agent.domain.observability import TraceEvent, TraceEventType
from lets_go_video_agent.domain.skill import (
    Skill,
    SkillBinding,
    SkillContent,
    SkillDetail,
    SkillStatus,
    SkillValidationReport,
    SkillVersion,
)
from lets_go_video_agent.domain.timeline import TimelineKind


class SkillValidationError(ApplicationError):
    code = "skill_validation_failed"
    status_code = 422


class SkillPolicyValidator:
    """静态权限与内容检查；生成模型无权绕过该检查器。"""

    allowed_agents = frozenset(
        {
            "ingestion_agent",
            "audio_perception_agent",
            "visual_sampling_agent",
            "ocr_perception_agent",
            "vlm_understanding_agent",
            "speaker_analysis_agent",
            "timeline_curator_agent",
            "qa_investigator",
            "evidence_verifier",
            "web_research_agent",
        }
    )
    allowed_tools = frozenset({"search_timeline", "inspect_frame", "search_web"})
    allowed_mcps = frozenset({"search"})
    forbidden_patterns = (
        "忽略之前",
        "ignore previous",
        "api key",
        "rm -rf",
    )
    unsafe_permission_pattern = re.compile(
        r"(?:允许|获得|开放|启用|使用).{0,8}"
        r"(?:shell|powershell|cmd\.exe|subprocess|文件写入|任意文件|任意网络)",
        re.IGNORECASE,
    )

    def validate(self, content: SkillContent) -> SkillValidationReport:
        errors: list[str] = []
        warnings: list[str] = []
        unknown_agents = set(content.allowed_agents) - self.allowed_agents
        unknown_tools = set(content.allowed_tools) - self.allowed_tools
        unknown_mcps = set(content.allowed_mcps) - self.allowed_mcps
        if unknown_agents:
            errors.append(f"包含未授权 Agent：{', '.join(sorted(unknown_agents))}")
        if unknown_tools:
            errors.append(f"包含未授权工具：{', '.join(sorted(unknown_tools))}")
        if unknown_mcps:
            errors.append(f"包含未授权 MCP：{', '.join(sorted(unknown_mcps))}")

        serialized = content.model_dump_json().lower()
        matched = [item for item in self.forbidden_patterns if item in serialized]
        if self.unsafe_permission_pattern.search(serialized):
            matched.append("危险权限请求")
        if matched:
            errors.append(f"检测到越权或提示注入表述：{', '.join(matched)}")

        required = {
            "分析目标": content.objectives,
            "分段规则": content.segmentation_hints,
            "视觉关注": content.visual_focus,
            "问答策略": content.qa_strategy,
            "输出要求": content.output_requirements,
            "边界条件": content.boundary_conditions,
        }
        for label, values in required.items():
            if not values:
                errors.append(f"缺少{label}")
        if not content.terminology:
            warnings.append("尚未配置领域术语；专业名词纠错能力不会得到增强")
        if not content.negative_examples:
            warnings.append("缺少反例，模型可能过度套用该 Skill")
        if len(content.applicable_video_types) > 6:
            warnings.append("适用类型过宽，建议拆成更聚焦的 Skill")
        return SkillValidationReport(valid=not errors, errors=errors, warnings=warnings)


class SkillStudioService:
    """Skill 草案、审核、发布、绑定和回滚的应用服务。"""

    def __init__(
        self,
        *,
        store: AppStore,
        builder: SkillBuilderAgent,
        validator: SkillPolicyValidator,
        artifact_root: Path,
    ) -> None:
        self._store = store
        self._builder = builder
        self._validator = validator
        self._artifact_root = artifact_root

    async def list_skills(self) -> list[Skill]:
        return list(await self._store.list_skills())

    async def get(self, skill_id: UUID) -> SkillDetail:
        skill = await self._require_skill(skill_id)
        versions = list(await self._store.list_skill_versions(skill_id))
        bindings = await self._store.list_skill_bindings(skill_id)
        return SkillDetail(
            skill=skill,
            versions=sorted(versions, key=lambda item: item.version, reverse=True),
            bound_video_ids=[item.video_id for item in bindings],
        )

    async def generate(
        self,
        *,
        video_ids: list[UUID],
        user_goal: str,
        display_name: str | None = None,
    ) -> SkillDetail:
        if not 1 <= len(video_ids) <= 8:
            raise SkillValidationError("每次请选择 1 至 8 个样本视频")
        trace_id = uuid4()
        await self._trace(
            trace_id,
            1,
            TraceEventType.WORKFLOW_STARTED,
            "skill_builder_graph",
            "开始分析样本并生成 Skill 草案",
            video_ids[0],
            "running",
        )
        samples = await self._sample_profiles(video_ids)
        await self._trace(
            trace_id,
            2,
            TraceEventType.AGENT_STARTED,
            "sample_analysis_agent",
            f"已读取 {len(samples)} 个视频的叙事画像与章节结构",
            video_ids[0],
            "completed",
        )
        name, description, content, basis = await self._builder.generate(
            samples=samples,
            user_goal=user_goal,
            display_name=display_name,
        )
        await self._trace(
            trace_id,
            3,
            TraceEventType.AGENT_COMPLETED,
            "skill_builder_agent",
            "已把样本共性提炼为结构化 Skill 规则",
            video_ids[0],
            "completed",
        )
        report = self._validator.validate(content)
        await self._trace(
            trace_id,
            4,
            TraceEventType.SKILL_VALIDATED,
            "skill_policy_validator",
            "Skill 静态检查通过" if report.valid else "Skill 草案存在待修复问题",
            video_ids[0],
            "completed" if report.valid else "failed",
            {"errors": report.errors, "warnings": report.warnings},
        )
        skill = Skill(
            slug=await self._unique_slug(name),
            display_name=name,
            description=description,
        )
        version = SkillVersion(
            skill_id=skill.id,
            version=1,
            content=content,
            sample_video_ids=video_ids,
            user_goal=user_goal,
            generation_basis=basis,
            validation=report,
            trace_id=trace_id,
        )
        await self._store.upsert_skill(skill)
        await self._store.add_skill_version(version)
        await self._trace(
            trace_id,
            5,
            TraceEventType.WORKFLOW_COMPLETED,
            "skill_draft_ready",
            "草案已生成，等待人工审核；尚未注入运行时",
            video_ids[0],
            "completed",
        )
        return await self.get(skill.id)

    async def refine(
        self,
        *,
        skill_id: UUID,
        instruction: str,
        base_version: int | None = None,
    ) -> SkillDetail:
        skill = await self._require_skill(skill_id)
        versions = list(await self._store.list_skill_versions(skill_id))
        if not versions:
            raise NotFoundError("该 Skill 没有可修改的版本")
        base_number = base_version or max(item.version for item in versions)
        base = await self._require_version(skill_id, base_number)
        samples = await self._sample_profiles(base.sample_video_ids)
        trace_id = uuid4()
        await self._trace(
            trace_id,
            1,
            TraceEventType.WORKFLOW_STARTED,
            "skill_builder_graph",
            f"基于 v{base.version} 处理用户修改要求",
            base.sample_video_ids[0] if base.sample_video_ids else None,
            "running",
        )
        content, basis = await self._builder.refine(
            content=base.content,
            samples=samples,
            instruction=instruction,
        )
        await self._trace(
            trace_id,
            2,
            TraceEventType.AGENT_COMPLETED,
            "skill_builder_agent",
            "已根据用户要求生成完整的新版本草案",
            base.sample_video_ids[0] if base.sample_video_ids else None,
            "completed",
        )
        report = self._validator.validate(content)
        next_number = max(item.version for item in versions) + 1
        version = SkillVersion(
            skill_id=skill_id,
            version=next_number,
            content=content,
            sample_video_ids=base.sample_video_ids,
            user_goal=base.user_goal,
            generation_basis=[*base.generation_basis, *basis][:20],
            validation=report,
            trace_id=trace_id,
            parent_version=base.version,
            change_summary=instruction,
        )
        await self._store.add_skill_version(version)
        skill.updated_at = utc_now()
        await self._store.upsert_skill(skill)
        await self._trace(
            trace_id,
            3,
            TraceEventType.SKILL_VALIDATED,
            "skill_policy_validator",
            "新版本草案已检查，等待人工发布",
            base.sample_video_ids[0] if base.sample_video_ids else None,
            "completed" if report.valid else "failed",
            {"version": next_number, "errors": report.errors, "warnings": report.warnings},
        )
        await self._trace(
            trace_id,
            4,
            TraceEventType.WORKFLOW_COMPLETED,
            "skill_draft_ready",
            f"v{next_number} 草案已生成",
            base.sample_video_ids[0] if base.sample_video_ids else None,
            "completed",
        )
        return await self.get(skill_id)

    async def publish(self, skill_id: UUID, version_number: int) -> SkillDetail:
        skill = await self._require_skill(skill_id)
        version = await self._require_version(skill_id, version_number)
        report = self._validator.validate(version.content)
        version.validation = report
        if not report.valid:
            await self._trace(
                version.trace_id,
                await self._next_sequence(version.trace_id),
                TraceEventType.HUMAN_REJECTED,
                "human_approval",
                "人工发布被安全检查阻止",
                version.sample_video_ids[0] if version.sample_video_ids else None,
                "rejected",
                {"errors": report.errors},
            )
            await self._store.add_skill_version(version)
            raise SkillValidationError("；".join(report.errors))

        artifact = self._write_artifact(skill, version)
        version.status = SkillStatus.PUBLISHED
        version.published_at = utc_now()
        version.artifact_path = str(artifact.relative_to(self._artifact_root.parent.parent))
        skill.status = SkillStatus.PUBLISHED
        skill.active_version = version.version
        skill.updated_at = utc_now()
        await self._store.add_skill_version(version)
        await self._store.upsert_skill(skill)
        await self._trace(
            version.trace_id,
            await self._next_sequence(version.trace_id),
            TraceEventType.HUMAN_APPROVED,
            "human_approval",
            f"用户已发布 {skill.display_name} v{version.version}",
            version.sample_video_ids[0] if version.sample_video_ids else None,
            "approved",
            {"skill_id": str(skill.id), "version": version.version},
        )
        return await self.get(skill_id)

    async def rollback(self, skill_id: UUID, version_number: int) -> SkillDetail:
        skill = await self._require_skill(skill_id)
        version = await self._require_version(skill_id, version_number)
        if version.status is not SkillStatus.PUBLISHED:
            raise SkillValidationError("只能回滚到已发布版本")
        skill.active_version = version_number
        skill.status = SkillStatus.PUBLISHED
        skill.updated_at = utc_now()
        await self._store.upsert_skill(skill)
        await self._trace(
            version.trace_id,
            await self._next_sequence(version.trace_id),
            TraceEventType.HUMAN_APPROVED,
            "skill_rollback",
            f"运行时已回滚到 v{version_number}",
            version.sample_video_ids[0] if version.sample_video_ids else None,
            "completed",
        )
        return await self.get(skill_id)

    async def bind(self, skill_id: UUID, video_ids: list[UUID]) -> SkillDetail:
        skill = await self._require_skill(skill_id)
        if skill.status is not SkillStatus.PUBLISHED or skill.active_version is None:
            raise SkillValidationError("Skill 发布后才能绑定视频")
        for video_id in video_ids:
            if await self._store.get(video_id) is None:
                raise NotFoundError(f"未找到视频: {video_id}")
            await self._store.upsert_skill_binding(
                SkillBinding(video_id=video_id, skill_id=skill_id)
            )
        return await self.get(skill_id)

    async def unbind(self, video_id: UUID) -> None:
        await self._store.delete_skill_binding(video_id)

    async def active_for_video(self, video_id: UUID) -> tuple[Skill, SkillVersion] | None:
        binding = await self._store.get_skill_binding(video_id)
        if binding is None:
            return None
        skill = await self._store.get_skill(binding.skill_id)
        if (
            skill is None
            or skill.status is not SkillStatus.PUBLISHED
            or skill.active_version is None
        ):
            return None
        version = await self._store.get_skill_version(skill.id, skill.active_version)
        if version is None or version.status is not SkillStatus.PUBLISHED:
            return None
        return skill, version

    async def _sample_profiles(self, video_ids: list[UUID]) -> list[SkillSampleProfile]:
        profiles: list[SkillSampleProfile] = []
        for video_id in video_ids:
            video = await self._store.get(video_id)
            if video is None:
                raise NotFoundError(f"未找到样本视频: {video_id}")
            narrative = await self._store.get_narrative_context(video_id)
            artifacts = await self._store.list_for_video(video_id)
            chapter_titles = [
                item.title or item.text[:80]
                for item in artifacts
                if item.kind is TimelineKind.CHAPTER
            ][:20]
            profiles.append(
                SkillSampleProfile(
                    video_id=str(video_id),
                    title=video.title,
                    video_format=narrative.video_format if narrative else "通用视频",
                    purpose=narrative.purpose if narrative else "",
                    summary=narrative.summary[:2_000] if narrative else "",
                    themes=narrative.themes[:12] if narrative else [],
                    chapter_titles=chapter_titles,
                )
            )
        return profiles

    async def _require_skill(self, skill_id: UUID) -> Skill:
        skill = await self._store.get_skill(skill_id)
        if skill is None:
            raise NotFoundError(f"未找到 Skill: {skill_id}")
        return skill

    async def _require_version(self, skill_id: UUID, version: int) -> SkillVersion:
        item = await self._store.get_skill_version(skill_id, version)
        if item is None:
            raise NotFoundError(f"未找到 Skill 版本: v{version}")
        return item

    async def _unique_slug(self, display_name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-")[:48]
        if not slug:
            slug = f"video-skill-{uuid4().hex[:8]}"
        existing = {item.slug for item in await self._store.list_skills()}
        if slug not in existing:
            return slug
        return f"{slug[:54]}-{uuid4().hex[:8]}"

    def _write_artifact(self, skill: Skill, version: SkillVersion) -> Path:
        directory = self._artifact_root / skill.slug / f"v{version.version}"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "SKILL.md"
        content = version.content
        terms = (
            "\n".join(
                f"- **{item.term}**：{item.meaning}（核验：{item.verification}）"
                for item in content.terminology
            )
            or "- 暂无；运行时仍需结合字幕、OCR、视觉与联网搜索交叉核验。"
        )
        markdown = f"""---
name: {skill.slug}
description: {skill.description.replace(chr(10), " ")}
---

# {skill.display_name}

本 Skill 是人工发布的 v{version.version} 领域规则。
它只能补充分析方法，不能覆盖视频直接证据、Harness 权限或系统安全策略。

## 目标

{self._bullets(content.objectives)}

## 分段与视觉理解

{self._bullets(content.segmentation_hints)}

{self._bullets(content.visual_focus)}

## 问答与输出

{self._bullets(content.qa_strategy)}

{self._bullets(content.output_requirements)}

## 术语与核验

{terms}

## 边界与反例

{self._bullets(content.boundary_conditions)}

{self._bullets(content.negative_examples)}

## 已知限制

{self._bullets(content.known_limitations)}
"""
        target.write_text(markdown, encoding="utf-8")
        return target

    @staticmethod
    def _bullets(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items) or "- 暂无"

    async def _next_sequence(self, trace_id: UUID) -> int:
        events = await self._store.list_trace_events(trace_id)
        return max((item.sequence for item in events), default=0) + 1

    async def _trace(
        self,
        trace_id: UUID,
        sequence: int,
        event_type: TraceEventType,
        name: str,
        summary: str,
        video_id: UUID | None,
        status: str,
        attributes: dict[str, object] | None = None,
    ) -> None:
        await self._store.append_trace_event(
            TraceEvent(
                trace_id=trace_id,
                sequence=sequence,
                event_type=event_type,
                name=name,
                status=status,
                summary=summary,
                video_id=video_id,
                agent_id=name,
                attributes={"phase": "Skill Studio", "node_id": name, **(attributes or {})},
            )
        )
