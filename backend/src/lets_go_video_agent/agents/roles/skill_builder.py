from __future__ import annotations

import json
from typing import Any, cast

from pydantic import Field

from lets_go_video_agent.domain.common import DomainModel
from lets_go_video_agent.domain.skill import (
    SkillCategoryEssence,
    SkillCategoryProfile,
    SkillContent,
    SkillDefaultQuestion,
    SkillEssenceEvidence,
    SkillOutputTemplate,
    SkillRuntimeTarget,
)


class SkillSampleProfile(DomainModel):
    """给 Builder 的高信息密度样本：保留内容、画面、文案和结构证据。"""

    video_id: str
    title: str
    video_format: str = "通用视频"
    purpose: str = ""
    summary: str = ""
    themes: list[str] = Field(default_factory=list)
    chapter_titles: list[str] = Field(default_factory=list)
    chapter_summaries: list[str] = Field(default_factory=list)
    representative_visuals: list[str] = Field(default_factory=list)
    visual_observations: list[str] = Field(default_factory=list)
    transcript_excerpts: list[str] = Field(default_factory=list)
    structure_statistics: list[str] = Field(default_factory=list)
    settings: list[str] = Field(default_factory=list)
    audience: list[str] = Field(default_factory=list)
    participant_roles: list[str] = Field(default_factory=list)
    event_patterns: list[str] = Field(default_factory=list)


class SkillBuilderAgent:
    """从一个或多个视频提炼可复用规则，而不是记住某个视频的答案。"""

    name = "skill_builder_agent"
    version = "1.0.0"

    def __init__(self, llm: Any | None = None) -> None:
        self._llm = llm

    async def generate(
        self,
        *,
        samples: list[SkillSampleProfile],
        user_goal: str,
        display_name: str | None,
        trace_id: str | None = None,
        baseline: SkillContent | None = None,
    ) -> tuple[str, str, SkillContent, list[str]]:
        if self._llm is not None:
            learned = await self._extract_category_knowledge(
                samples=samples,
                user_goal=user_goal,
                display_name=display_name,
                trace_id=trace_id,
                baseline=baseline,
            )
            if learned is not None:
                name, description, essence, profile, basis = learned
                # Harness 负责稳定、安全、可测试的运行规则；LLM 只负责必须依靠语义
                # 归纳的类别知识，避免几十个工程字段挤占内容研究的输出预算。
                _, _, content, fallback_basis = self._fallback(
                    samples=samples,
                    user_goal=user_goal,
                    display_name=display_name,
                )
                content.category_essence = essence
                content.category_profile = profile
                content.known_limitations = essence.confidence_notes[:12]
                return name, description, content, [*basis, *fallback_basis[:1]][:20]
        return self._fallback(samples=samples, user_goal=user_goal, display_name=display_name)

    async def _extract_category_knowledge(
        self,
        *,
        samples: list[SkillSampleProfile],
        user_goal: str,
        display_name: str | None,
        trace_id: str | None,
        baseline: SkillContent | None = None,
    ) -> (
        tuple[
            str,
            str,
            SkillCategoryEssence,
            SkillCategoryProfile,
            list[str],
        ]
        | None
    ):
        """让模型专注研究类别本身，不同时承担 Agent 工程模板生成。"""

        llm = self._llm
        if llm is None:
            return None
        compact_samples = []
        for sample in samples:
            payload = sample.model_dump()
            payload["chapter_summaries"] = sample.chapter_summaries[:5]
            payload["representative_visuals"] = sample.representative_visuals[:4]
            payload["visual_observations"] = sample.visual_observations[:3]
            payload["transcript_excerpts"] = sample.transcript_excerpts[:2]
            payload["event_patterns"] = sample.event_patterns[:5]
            compact_samples.append(payload)
        baseline_payload = None
        if baseline is not None:
            baseline_payload = {
                "category_essence": baseline.category_essence.model_dump(mode="json"),
                "category_profile": baseline.category_profile.model_dump(mode="json"),
            }
        baseline_json = (
            json.dumps(baseline_payload, ensure_ascii=False) if baseline_payload else "无"
        )
        try:
            result = await llm.complete_json(
                system=self._category_research_prompt(),
                user=(
                    f"用户目标：{user_goal}\n"
                    f"建议名称：{display_name or '根据类别特征命名'}\n"
                    "样本研究材料："
                    f"{json.dumps(compact_samples, ensure_ascii=False)}\n"
                    "上一版本类别画像（仅作为稳定基线；必须由本轮样本重新验证）：\n"
                    f"{baseline_json}"
                ),
                purpose="skill_category_essence_generation",
                video_id=samples[0].video_id,
                trace_id=trace_id,
                task_id=trace_id,
                agent_id="skill_builder_agent",
                max_tokens=6_000,
                thinking=True,
            )
            # 部分 OpenAI 兼容模型会自发增加 content 包装层；这里兼容包装，但不放宽
            # 类别精髓自身的证据和字段校验。
            payload = self._find_research_payload(result)
            essence = SkillCategoryEssence.model_validate(
                self._normalize_essence(payload["category_essence"], samples)
            )
            if baseline is not None:
                essence = self._stabilize_with_baseline(essence, baseline, samples)
            profile = SkillCategoryProfile.model_validate(
                self._normalize_profile(payload["category_profile"])
            )
            if essence.extraction_status != "sample-derived":
                return None
            return (
                str(result.get("display_name") or display_name or "视频理解 Skill"),
                str(
                    result.get("description")
                    or f"根据 {len(samples)} 个样本提炼的类别视频理解能力。"
                ),
                essence,
                profile,
                [str(item) for item in result.get("generation_basis", [])][:20],
            )
        except Exception:
            return None

    @staticmethod
    def _stabilize_with_baseline(
        essence: SkillCategoryEssence,
        baseline: SkillContent,
        samples: list[SkillSampleProfile],
    ) -> SkillCategoryEssence:
        """新样本包含旧样本时，保留已验证且本轮模型漏填的稳定类别知识。"""

        current_ids = {sample.video_id for sample in samples}
        baseline_ids = {
            str(video_id)
            for evidence in baseline.category_essence.evidence
            for video_id in evidence.supporting_video_ids
        }
        overlap = current_ids & baseline_ids
        if len(overlap) < min(2, len(baseline_ids)):
            return essence

        stable = baseline.category_essence
        updated = essence.model_copy(deep=True)
        for field in (
            "content_core",
            "visual_signature",
            "narration_copywriting",
            "storytelling_engine",
            "pacing_editing",
            "recurring_devices",
            "viewer_value",
        ):
            if not getattr(updated, field):
                setattr(updated, field, list(getattr(stable, field)))
        retained_evidence = []
        for item in stable.evidence:
            supporting = [
                video_id
                for video_id in item.supporting_video_ids
                if str(video_id) in overlap
            ]
            if supporting:
                retained_evidence.append(
                    item.model_copy(update={"supporting_video_ids": supporting})
                )
        known = {item.insight for item in updated.evidence}
        updated.evidence = [
            *updated.evidence,
            *(item for item in retained_evidence if item.insight not in known),
        ][:24]
        note = "本轮样本包含历史已验证样本；模型漏填维度已由最完整历史版本补齐并保留证据。"
        if note not in updated.confidence_notes:
            updated.confidence_notes = [*updated.confidence_notes, note][:12]
        return updated

    @staticmethod
    def _find_research_payload(result: dict[str, Any]) -> dict[str, Any]:
        """兼容常见包装层，但不猜测类别研究字段。"""

        candidates = [
            result,
            result.get("content"),
            result.get("skill"),
            result.get("data"),
        ]
        for candidate in candidates:
            if (
                isinstance(candidate, dict)
                and {
                    "category_essence",
                    "category_profile",
                }
                <= candidate.keys()
            ):
                return cast(dict[str, Any], candidate)
        raise KeyError("category research payload is missing")

    @staticmethod
    def _normalize_essence(raw: object, samples: list[SkillSampleProfile]) -> dict[str, Any]:
        """收紧模型输出的长度和 UUID 形态，不改变语义结论。"""

        if not isinstance(raw, dict):
            raise TypeError("category_essence must be an object")
        allowed_ids = {sample.video_id for sample in samples}
        value = dict(raw)
        value["extraction_status"] = "sample-derived"
        value["one_sentence_essence"] = str(value.get("one_sentence_essence") or "")[:1_000]
        limits = {
            "content_core": 20,
            "visual_signature": 20,
            "narration_copywriting": 20,
            "storytelling_engine": 20,
            "pacing_editing": 20,
            "recurring_devices": 20,
            "viewer_value": 16,
            "confidence_notes": 12,
        }
        aliases = {
            "content_core": (
                "core_content",
                "content_essence",
                "content_themes",
                "content_essence_and_themes",
                "fixed_characters_and_relationships",
                "event_motifs",
            ),
            "visual_signature": (
                "visual_style",
                "visual_patterns",
                "visual_language",
                "visual_grammar",
                "visual_materials_and_layout",
                "visual_content",
            ),
            "narration_copywriting": (
                "narration_style",
                "copywriting_style",
                "language_style",
                "narration_and_copywriting",
                "narration_perspective_and_tone",
                "verbal_style",
            ),
            "storytelling_engine": (
                "narrative_engine",
                "storytelling_patterns",
                "narrative_patterns",
                "conflict_escalation_and_reversal",
                "story_structure",
                "comedy_mechanism",
            ),
            "pacing_editing": (
                "pacing",
                "editing_style",
                "rhythm",
                "editing_rhythm",
                "pacing_and_editing",
            ),
            "recurring_devices": ("recurring_elements", "recurring_motifs", "devices"),
            "viewer_value": ("audience_value", "viewer_benefits"),
        }
        for field, limit in limits.items():
            items = value.get(field)
            if not items:
                matched: list[object] = []
                for alias in aliases.get(field, ()):
                    alias_value = value.get(alias)
                    if isinstance(alias_value, list):
                        matched.extend(alias_value)
                    elif alias_value:
                        matched.append(alias_value)
                items = matched
            # 每个维度只保留自身结论。模型偶尔会把同一段总括文本复制到多个字段；
            # 若不在入口去重，UI 看起来像四份内容，运行时也会重复污染提示词。
            normalized_items: list[str] = []
            for item in items[:limit] if isinstance(items, list) else []:
                text = str(item).strip()
                if text and text not in normalized_items:
                    normalized_items.append(text)
            value[field] = normalized_items
        evidence_items = value.get("evidence")
        dimension_fields = (
            "content_core",
            "visual_signature",
            "narration_copywriting",
            "storytelling_engine",
            "pacing_editing",
        )
        original_dimensions = {field: list(value[field]) for field in dimension_fields}
        claimed_conclusions: set[str] = set()
        for field in dimension_fields:
            # 不再使用同一组 evidence insight 补齐所有空字段。缺失维度应保持为空并阻止发布，
            # 这样用户看到的是“证据不足”，而不是貌似完整、实际重复的 Skill。
            distinct = [item for item in value[field] if item not in claimed_conclusions]
            value[field] = distinct
            claimed_conclusions.update(distinct)
        # 若模型把同一组跨模态结论复制到了多个字段，顺序去重会导致后续字段全空。
        # 此时根据结论自身的语义将其重新归位，而不是简单丢弃。
        for field in dimension_fields:
            if value[field]:
                continue
            candidates = [
                item
                for items in original_dimensions.values()
                for item in items
                if SkillBuilderAgent._classify_dimension(item) == field
            ]
            value[field] = list(dict.fromkeys(candidates))[: limits[field]]
        # 最终确保每条结论只归属于一个维度。若是跨字段复制，优先保留语义分类结果。
        assignments: dict[str, str] = {}
        for field in dimension_fields:
            for item in original_dimensions[field]:
                classified = SkillBuilderAgent._classify_dimension(item)
                target = classified if classified in dimension_fields else field
                assignments.setdefault(item, target)
        value.update(
            {
                field: [item for item, target in assignments.items() if target == field][
                    : limits[field]
                ]
                for field in dimension_fields
            }
        )
        if any(not value[field] for field in dimension_fields):
            notes = value.get("confidence_notes")
            notes = notes if isinstance(notes, list) else []
            missing = "、".join(field for field in dimension_fields if not value[field])
            note = f"以下维度尚未形成相互独立、可核验的结论：{missing}"
            value["confidence_notes"] = [*notes, note][: limits["confidence_notes"]]
        normalized_evidence = []
        for item in evidence_items[:24] if isinstance(evidence_items, list) else []:
            if not isinstance(item, dict):
                continue
            ids = item.get("supporting_video_ids")
            ids = ids if isinstance(ids, list) else [ids]
            supporting_ids = [str(video_id) for video_id in ids if str(video_id) in allowed_ids]
            observations = item.get("observations")
            observations = observations if isinstance(observations, list) else [observations]
            if supporting_ids and any(observations):
                normalized_evidence.append(
                    {
                        "insight": str(item.get("insight") or "")[:800],
                        "supporting_video_ids": supporting_ids,
                        "observations": [
                            str(observation) for observation in observations if observation
                        ][:12],
                    }
                )
        value["evidence"] = normalized_evidence
        # 证据本身已经通过样本 ID 与观察记录校验，可用于补足模型漏填的维度。
        # 这里只复制结论，不从无证据文本中猜测。
        for item in normalized_evidence:
            insight = item["insight"].strip()
            field = SkillBuilderAgent._classify_dimension(insight)
            if field in dimension_fields and insight not in value[field]:
                value[field].append(insight)
        for field in dimension_fields:
            value[field] = value[field][: limits[field]]
        return value

    @staticmethod
    def _classify_dimension(text: str) -> str | None:
        lowered = text.lower()
        keywords = {
            "visual_signature": (
                "画面", "视觉", "镜头", "构图", "背景", "色彩", "界面", "布局",
                "特写", "字幕", "visual", "camera", "layout", "color",
            ),
            "narration_copywriting": (
                "口播", "文案", "语气", "句法", "第一人称", "旁白", "措辞", "台词",
                "narration", "copywriting", "tone", "wording",
            ),
            "pacing_editing": (
                "节奏", "剪辑", "转场", "时长", "快切", "章节", "段落",
                "pacing", "editing", "transition", "duration",
            ),
            "storytelling_engine": (
                "叙事", "故事", "冲突", "反转", "铺垫", "悬念", "因果", "推进", "结局",
                "story", "narrative", "conflict", "reversal",
            ),
            "content_core": (
                "内容", "主题", "核心", "人物", "角色", "关系", "事件", "观点", "知识",
                "content", "theme", "character", "topic",
            ),
        }
        scores = {
            field: sum(1 for keyword in words if keyword in lowered)
            for field, words in keywords.items()
        }
        best_score = max(scores.values())
        winners = [field for field, score in scores.items() if score == best_score and score > 0]
        # 多个维度同分时不武断改写字段归属，保留模型原始放置位置。
        return winners[0] if len(winners) == 1 else None

    @staticmethod
    def _normalize_profile(raw: object) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise TypeError("category_profile must be an object")
        value = dict(raw)
        value["category_name"] = str(value.get("category_name") or "通用视频")[:120]
        value["style_summary"] = str(value.get("style_summary") or "")[:1_000]
        limits = {
            "common_formats": 12,
            "typical_content": 20,
            "narrative_patterns": 20,
            "visual_language": 20,
            "audience_expectations": 12,
            "stable_signals": 20,
            "variable_signals": 20,
        }
        for field, limit in limits.items():
            items = value.get(field)
            value[field] = [str(item) for item in items[:limit]] if isinstance(items, list) else []
        return value

    @staticmethod
    def _category_research_prompt() -> str:
        return (
            "你是视频类型研究 Agent，只研究这组视频独有的类别规律，不编写通用 Agent 工程模板。"
            "先横向比较所有样本，再输出简洁 JSON。禁止把每条视频依次复述，禁止用‘结合音频画面’"
            "‘理解上下文’等通用套话。必须回答：内容精髓是什么；固定人物/关系与事件母题是什么；"
            "画面实际由哪些素材、布局、镜头或视觉符号构成；口播的视角、语气、句法、铺垫与包袱"
            "是什么；冲突如何升级和反转；剪辑节奏与段落功能是什么；观众为什么愿意看。"
            "输出仅包含 display_name、description、generation_basis、category_essence、"
            "category_profile。category_essence 必须含 extraction_status='sample-derived'、"
            "one_sentence_essence、content_core、visual_signature、narration_copywriting、"
            "storytelling_engine、pacing_editing、recurring_devices、viewer_value、evidence、"
            "confidence_notes。每个 evidence 含 insight、supporting_video_ids、observations；"
            "ID 必须"
            "原样取自输入，跨样本规律尽量至少两个 ID 支持。evidence 最多 5 条、每条最多 2 个"
            "observations；其他列表控制在 3 到 6 条，每条不超过"
            "180 字。category_profile 含 category_name、style_summary、common_formats、"
            "typical_content、narrative_patterns、visual_language、audience_expectations、"
            "stable_signals、variable_signals。证据不足的维度写 confidence_notes，不得编造。"
            "字段名必须完全使用以上英文 snake_case，不要翻译字段名，也不要自创近义字段。"
        )

    async def _repair_result(
        self,
        *,
        result: dict[str, Any],
        validation_error: str,
        sample_video_id: str,
        trace_id: str | None,
    ) -> dict[str, Any] | None:
        """只修复结构和长度，不允许在修复阶段改写样本结论。"""

        llm = self._llm
        if llm is None:
            return None
        try:
            repaired = await llm.complete_json(
                system=(
                    "你是 Skill JSON 校验修复器。保持原有类别结论和证据含义，只修复字段缺失、"
                    "类型、枚举、UUID、字段长度与数组数量问题。必须返回完整 JSON，顶层仍包含"
                    "display_name、description、generation_basis、content。不要添加说明文字。"
                ),
                user=(
                    f"Pydantic 校验错误：{validation_error[:8_000]}\n"
                    "待修复 JSON："
                    f"{json.dumps(result, ensure_ascii=False)[:50_000]}"
                ),
                purpose="skill_draft_schema_repair",
                video_id=sample_video_id,
                trace_id=trace_id,
                task_id=trace_id,
                agent_id="skill_builder_agent",
                max_tokens=8_000,
                thinking=False,
            )
            return cast(dict[str, Any], repaired)
        except Exception:
            return None

    async def refine(
        self,
        *,
        content: SkillContent,
        samples: list[SkillSampleProfile],
        instruction: str,
        trace_id: str | None = None,
    ) -> tuple[SkillContent, list[str]]:
        if self._llm is not None:
            result = await self._complete(
                purpose="skill_draft_refinement",
                system=self._system_prompt(),
                user=(
                    f"现有草案：{content.model_dump_json()}\n"
                    f"用户修改要求：{instruction}\n"
                    "样本画像："
                    f"{json.dumps([item.model_dump() for item in samples], ensure_ascii=False)}\n"
                    "输出修改后的完整 content，并说明 generation_basis。"
                ),
                video_id=samples[0].video_id if samples else None,
                trace_id=trace_id,
            )
            if result is not None:
                try:
                    refined = SkillContent.model_validate(result.get("content", result))
                    basis = [str(item) for item in result.get("generation_basis", [])][:20]
                    return refined, basis
                except (TypeError, ValueError):
                    pass

        # 离线模式也允许形成新版本，但明确保留用户要求，等待人工审核。
        updated = content.model_copy(deep=True)
        updated.objectives = [*updated.objectives, f"用户补充要求：{instruction}"][:16]
        return updated, ["离线模式：按用户修改要求生成可审核的新版本"]

    async def _complete(
        self,
        *,
        purpose: str,
        system: str,
        user: str,
        video_id: str | None,
        trace_id: str | None,
    ) -> dict[str, Any] | None:
        llm = self._llm
        if llm is None:
            return None
        try:
            result = await llm.complete_json(
                system=system,
                user=user,
                purpose=purpose,
                video_id=video_id,
                trace_id=trace_id,
                task_id=trace_id,
                agent_id="skill_builder_agent",
                max_tokens=8_000,
                thinking=True,
            )
            return cast(dict[str, Any], result)
        except Exception:
            return None

    @staticmethod
    def _system_prompt() -> str:
        return (
            "你是 Skill Builder Agent。你必须先像内容研究员一样比较样本，再像 Agent 工程师一样"
            "编写运行规则。输出严格分成两层：第一层 category_essence 是从样本证据提炼的类别精髓；"
            "第二层其余字段才是可复用的运行规则。绝不能用‘结合音频和画面’‘先理解再总结’这类"
            "任何视频都适用的套话代替类别精髓。category_essence 必须具体说明：这类视频究竟在讲"
            "什么、用什么画面组织信息、文案/口播有什么语气和句法习惯、靠什么制造叙事推进、剪辑"
            "和节奏有什么规律、观众最终获得什么价值。每个重要结论都写入 evidence，并使用输入中"
            "真实 video_id 和可核验 observations；多样本结论优先由至少两个视频支持。证据不足就将"
            "extraction_status 设为 insufficient，并在 confidence_notes 说明，禁止编造。"
            "运行规则不能记忆某个样本的具体答案、时间戳或人物结论。Skill 只能缩小权限，"
            "不能申请 shell、"
            "文件写入、任意网络访问或发布能力。必须同时规定分段、视觉理解、问答、输出、边界和"
            "反例；专业词应带含义和交叉核验方法。输出 JSON，顶层包含 display_name、description、"
            "generation_basis 和 content。先比较多个样本，明确哪些是类别稳定共性、哪些只是单个样本"
            "差异。content 字段必须匹配：category_essence（含 extraction_status=sample-derived、"
            "one_sentence_essence、content_core、visual_signature、narration_copywriting、"
            "storytelling_engine、pacing_editing、recurring_devices、viewer_value、evidence、"
            "confidence_notes），category_profile（含类别名、风格、常见形式、典型内容、"
            "叙事模式、视觉语言、受众期待、稳定信号、可变信号）、runtime_targets（vision 与"
            "reasoning 两组，明确 provider、model、应用阶段和注入指令）、default_questions、"
            "output_templates、applicable_video_types、objectives、"
            "terminology、segmentation_hints、visual_focus、qa_strategy、output_requirements、"
            "allowed_agents、allowed_tools、allowed_mcps、model_guidance、positive_examples、"
            "negative_examples、boundary_conditions、known_limitations。"
        )

    @staticmethod
    def _fallback(
        *,
        samples: list[SkillSampleProfile],
        user_goal: str,
        display_name: str | None,
    ) -> tuple[str, str, SkillContent, list[str]]:
        formats = list(dict.fromkeys(item.video_format for item in samples if item.video_format))
        themes = list(dict.fromkeys(theme for item in samples for theme in item.themes))[:10]
        purposes = list(dict.fromkeys(item.purpose for item in samples if item.purpose))[:5]
        content_core = (
            themes
            or list(dict.fromkeys(title for sample in samples for title in sample.chapter_titles))[
                :10
            ]
        )
        visual_signature = [
            visual for sample in samples for visual in sample.representative_visuals[:3]
        ][:12]
        narration = [excerpt for sample in samples for excerpt in sample.transcript_excerpts[:2]][
            :10
        ]
        story_engine = [
            pattern
            for sample in samples
            for pattern in (sample.event_patterns or sample.chapter_summaries[:3])
        ][:12]
        evidence = [
            SkillEssenceEvidence(
                insight=f"样本《{sample.title}》呈现的内容、画面与讲述组织方式",
                supporting_video_ids=[sample.video_id],
                observations=[
                    *([sample.summary[:500]] if sample.summary else []),
                    *sample.chapter_summaries[:2],
                    *sample.representative_visuals[:2],
                    *sample.transcript_excerpts[:1],
                ][:8],
            )
            for sample in samples
            if sample.summary
            or sample.chapter_summaries
            or sample.representative_visuals
            or sample.transcript_excerpts
        ]
        has_evidence_baseline = bool(
            content_core and visual_signature and narration and story_engine and evidence
        )
        content = SkillContent(
            applicable_video_types=formats or ["通用视频"],
            category_essence=SkillCategoryEssence(
                extraction_status=(
                    "sample-derived"
                    if has_evidence_baseline and len(samples) == 1
                    else "insufficient"
                ),
                one_sentence_essence=(
                    "；".join(
                        item.summary[:280]
                        or item.purpose[:280]
                        or "、".join(item.chapter_titles[:4])
                        for item in samples
                    )[:1_000]
                ),
                content_core=content_core,
                visual_signature=visual_signature,
                narration_copywriting=narration,
                storytelling_engine=story_engine,
                pacing_editing=[stat for sample in samples for stat in sample.structure_statistics][
                    :10
                ],
                evidence=evidence,
                confidence_notes=(
                    ["单样本 LLM 提炼失败；当前为样本证据基线，建议人工复核表达质量。"]
                    if has_evidence_baseline and len(samples) == 1
                    else ["未完成跨样本语义归纳；即使原始证据充足，也不能把样本拼接当成类别精髓。"]
                ),
            ),
            category_profile=SkillCategoryProfile(
                category_name=formats[0] if formats else "通用视频",
                style_summary=(
                    f"这类视频通常围绕{'、'.join(themes[:5]) or '一个中心主题'}，"
                    "通过语音叙述与关键画面共同推进内容。"
                ),
                common_formats=formats or ["待通过更多样本确认"],
                typical_content=themes or ["主题引入", "主体展开", "结论或结果"],
                narrative_patterns=[
                    "先识别视频的真实组织方式，再按问题、步骤、事件或观点推进分段",
                    "章节边界需要语音主题与画面语义至少一项发生持续变化",
                ],
                visual_language=[
                    "画面中的主体、动作、界面状态和空间关系用于解释叙事推进",
                    "字幕与 OCR 是可见证据，但不能替代对整个画面意义的判断",
                ],
                audience_expectations=["快速理解全片结构", "可回放地定位关键证据"],
                stable_signals=["语音主题、画面语义、内容结构之间的共同变化"],
                variable_signals=["具体人物、专名、时间戳与单条视频结论"],
            ),
            runtime_targets=[
                SkillRuntimeTarget(
                    target_id="vision",
                    target_name="视觉理解模型",
                    provider="siliconflow",
                    model="Qwen/Qwen3-VL-32B-Instruct",
                    stages=["visual_understanding", "frame_qa"],
                    instructions=[
                        "先判断画面形态与布局，再识别主体、状态、动作、关系和事件含义",
                        "根据类别视觉语言关注稳定区域，但不得臆造不可见信息",
                    ],
                ),
                SkillRuntimeTarget(
                    target_id="reasoning",
                    target_name="文本推理模型",
                    provider="deepseek",
                    model="当前配置的 DeepSeek 模型",
                    stages=["subtitle_review", "timeline", "qa", "default_answers"],
                    instructions=[
                        "使用类别叙事模式辅助分段、总结和问答，不复制样本答案",
                        "专业名词结合字幕、OCR、视觉上下文与联网证据交叉核验",
                    ],
                ),
            ],
            objectives=[user_goal, "先理解整段叙事目的，再解释局部画面与上下文的关系"],
            segmentation_hints=[
                "综合话题转移、说话人轮次、场景变化和画面语义确定边界",
                "口头停顿、单帧变化和零散 OCR 不能单独构成章节",
            ],
            visual_focus=[
                "识别画面中的主体、动作、界面状态和它们在当前叙事中的作用",
                "OCR 只作为画面证据之一，不能替代视觉语义理解",
            ],
            qa_strategy=[
                "回答前检索跨模态证据，并区分视频原述、视觉观察和外部补充",
                "证据冲突时明确不确定性，不用样本知识补造当前视频事实",
            ],
            output_requirements=[
                "先给直接结论，再给结构化解释和可回放时间证据",
                "过滤问候、口水话和与用户目标无关的低信息内容",
            ],
            model_guidance="默认使用经济模型；仅在复杂画面或证据冲突时升级到视觉大模型。",
            positive_examples=["章节名称应概括该段作用，而非复制字幕或 OCR"],
            negative_examples=["不要把某个样本视频中的专名、结论或时间戳写成固定规则"],
            boundary_conditions=["Skill 规则不能覆盖系统安全策略和直接视频证据"],
            known_limitations=[
                "若 generation_basis 标记 LLM 失败，当前类别精髓只是证据基线，需人工复核"
            ],
            default_questions=[
                SkillDefaultQuestion(
                    question="这期视频主要讲了什么？",
                    purpose="帮助用户在不提问的情况下先掌握核心内容与组织逻辑",
                    answer_structure=["核心结论", "内容脉络", "关键时间段"],
                ),
                SkillDefaultQuestion(
                    question="有哪些最值得回看的片段？",
                    purpose="按这一类视频的价值判断筛选关键片段",
                    answer_structure=["片段名称", "时间范围", "为什么重要", "画面证据"],
                ),
            ],
            output_templates=[
                SkillOutputTemplate(
                    name="类别化视频速览",
                    use_when="视频处理完成后的默认理解页",
                    fields=["一句话结论", "大纲", "关键术语", "代表画面", "建议追问"],
                ),
                SkillOutputTemplate(
                    name="类别化章节卡片",
                    use_when="生成时间轴大节与小节",
                    fields=["编号", "语义标题", "该段在全片中的作用", "关键证据"],
                ),
            ],
        )
        name = display_name or (f"{formats[0]}理解 Skill" if formats else "通用视频理解 Skill")
        basis = [
            f"读取了 {len(samples)} 个样本的总结、章节、代表画面、视觉观察和口播片段",
            "LLM 类别提炼失败，未用通用模板冒充样本结论",
            *([f"共同主题：{'、'.join(themes)}"] if themes else []),
            *([f"样本目的：{'；'.join(purposes)}"] if purposes else []),
        ]
        return name, f"围绕“{user_goal}”提炼的可审核视频理解规则。", content, basis
