from __future__ import annotations

import json
from typing import Any, cast

from pydantic import Field

from lets_go_video_agent.domain.common import DomainModel
from lets_go_video_agent.domain.skill import SkillContent


class SkillSampleProfile(DomainModel):
    """提供给 Skill Builder 的去原始数据化样本，避免把整段字幕塞进提示词。"""

    video_id: str
    title: str
    video_format: str = "通用视频"
    purpose: str = ""
    summary: str = ""
    themes: list[str] = Field(default_factory=list)
    chapter_titles: list[str] = Field(default_factory=list)


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
    ) -> tuple[str, str, SkillContent, list[str]]:
        if self._llm is not None:
            result = await self._complete(
                purpose="skill_draft_generation",
                system=self._system_prompt(),
                user=(
                    f"用户目标：{user_goal}\n"
                    f"建议名称：{display_name or '请根据共性命名'}\n"
                    "样本画像："
                    f"{json.dumps([item.model_dump() for item in samples], ensure_ascii=False)}\n"
                    "请生成第一版领域 Skill 草案。"
                ),
                video_id=samples[0].video_id,
            )
            if result is not None:
                try:
                    content = SkillContent.model_validate(result.get("content", result))
                    name = str(result.get("display_name") or display_name or "视频理解 Skill")
                    description = str(
                        result.get("description")
                        or f"根据 {len(samples)} 个样本提炼的视频理解规则。"
                    )
                    basis = [str(item) for item in result.get("generation_basis", [])][:20]
                    return name, description, content, basis
                except (TypeError, ValueError):
                    # 模型结构不合格时回到可预测草案，不能发布半解析结果。
                    pass
        return self._fallback(samples=samples, user_goal=user_goal, display_name=display_name)

    async def refine(
        self,
        *,
        content: SkillContent,
        samples: list[SkillSampleProfile],
        instruction: str,
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
                max_tokens=5_000,
                thinking=False,
            )
            return cast(dict[str, Any], result)
        except Exception:
            return None

    @staticmethod
    def _system_prompt() -> str:
        return (
            "你是 Skill Builder Agent。任务是从多视频共性中提炼通用的视频理解规则，绝不能"
            "记忆某个样本的具体答案、时间戳或人物结论。Skill 只能缩小权限，不能申请 shell、"
            "文件写入、任意网络访问或发布能力。必须同时规定分段、视觉理解、问答、输出、边界和"
            "反例；专业词应带含义和交叉核验方法。输出 JSON，顶层包含 display_name、description、"
            "generation_basis 和 content。content 字段必须匹配：applicable_video_types、"
            "objectives、"
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
        content = SkillContent(
            applicable_video_types=formats or ["通用视频"],
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
            known_limitations=["当前草案由规则模板生成，发布前需要人工核对领域术语"],
        )
        name = display_name or (f"{formats[0]}理解 Skill" if formats else "通用视频理解 Skill")
        basis = [
            f"分析了 {len(samples)} 个样本的视频格式、目的、主题与章节结构",
            *([f"共同主题：{'、'.join(themes)}"] if themes else []),
            *([f"样本目的：{'；'.join(purposes)}"] if purposes else []),
        ]
        return name, f"围绕“{user_goal}”提炼的可审核视频理解规则。", content, basis
