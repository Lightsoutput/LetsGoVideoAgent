from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from pydantic import Field

from lets_go_video_agent.agents.harness.engine import HarnessSession
from lets_go_video_agent.agents.tools.video_tools import EvidenceBatch
from lets_go_video_agent.domain.common import DomainModel
from lets_go_video_agent.domain.qa import (
    EvidenceCitation,
    FrameTarget,
    MomentTarget,
    Question,
)
from lets_go_video_agent.domain.timeline import Evidence, EvidenceKind
from lets_go_video_agent.infrastructure.models.deepseek_client import DeepSeekClient


class DraftAnswer(DomainModel):
    text: str
    citations: list[EvidenceCitation] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)


def _format_timestamp(timestamp_ms: int) -> str:
    total_seconds = timestamp_ms // 1_000
    hours, remaining = divmod(total_seconds, 3_600)
    minutes, seconds = divmod(remaining, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


class QAInvestigator:
    """负责 Agentic RAG 的证据调查，但不负责最终放行答案。"""

    name = "qa_investigator"
    version = "0.1.0"
    allowed_tools = frozenset({"search_timeline", "inspect_frame"})

    def __init__(self, llm: DeepSeekClient | None = None) -> None:
        self._llm = llm

    async def investigate(
        self,
        *,
        question: Question,
        session: HarnessSession,
        limit: int = 8,
    ) -> DraftAnswer:
        summary_question = question.target.kind == "global" and _is_summary_query(question.query)
        search_limit = max(limit, 16) if summary_question else limit
        search_result = await session.invoke_tool(
            "search_timeline",
            {
                "video_id": str(question.video_id),
                "query": question.query,
                "target": question.target.model_dump(mode="json"),
                "limit": search_limit,
            },
        )
        evidence = list(EvidenceBatch.model_validate(search_result).items)

        # “当前帧”和“这一刻”不是同一回事，但二者都需要画面证据。Moment 会同时
        # 保留邻域字幕；Frame 则把视觉/OCR 证据放在更高优先级。
        if isinstance(question.target, (FrameTarget, MomentTarget)):
            frame_result = await session.invoke_tool(
                "inspect_frame",
                {
                    "video_id": str(question.video_id),
                    "timestamp_ms": question.target.timestamp_ms,
                    "query": question.query,
                },
            )
            frame_evidence = list(EvidenceBatch.model_validate(frame_result).items)
            if isinstance(question.target, FrameTarget):
                # 当前帧问题优先使用即时抽帧；普通检索只补充声音/章节上下文，避免
                # 30 秒采样图抢在精确帧之前，造成尾页或相邻帧重复。
                context = [
                    item
                    for item in evidence
                    if item.kind not in {EvidenceKind.VISUAL, EvidenceKind.OCR, EvidenceKind.FRAME}
                ]
                evidence = [*frame_evidence, *context]
            else:
                evidence.extend(frame_evidence)

        evidence = self._deduplicate(evidence)[:search_limit]
        await session.reserve_model_call(
            estimated_input_tokens=max(100, sum(len(item.description) for item in evidence) // 2),
            estimated_output_tokens=1400 if summary_question else 700,
            estimated_cost_usd=Decimal("0"),
            model_name="mock-evidence-composer",
        )
        if self._llm and evidence:
            return await self._compose_with_llm(question, evidence, summary_question)
        return self._compose(question, evidence)

    async def _compose_with_llm(
        self, question: Question, evidence: list[Evidence], summary_question: bool
    ) -> DraftAnswer:
        """LLM 只能组织已检索证据；引用仍由代码映射，不能让模型伪造 ID。"""
        llm = self._llm
        if llm is None:
            return self._compose(question, evidence)
        # OCR 可能包含整页课件。限制单条长度并标明证据类型，避免模型退化成逐字复读器。
        evidence_clip = 2_800 if summary_question else 1_200
        evidence_text = "\n".join(
            (
                f"[{index}] 类型={item.kind.value} "
                f"时间={_format_timestamp(item.timestamp_ms or 0)} "
                f"内容={(item.quote or item.description)[:evidence_clip]}"
            )
            for index, item in enumerate(evidence)
        )
        summary_rules = (
            "这是全片总结任务。必须覆盖视频开头、中段、后段；先说明视频对象与核心目的，再按内容结构"
            "列出关键主题或建议并解释其含义。若视频声称有固定数量的要点（例如7条），应尽量逐项还原，"
            "无法还原的条目必须明确说明，不能拿零散OCR补造。保留角色名、版本号、系统名和玩法名等"
            "专业名词。过滤问候、关注提醒、告别语等低信息内容，除非用户明确询问。建议正文400至800字。"
            "字幕与画面文字冲突时，角色名、系统名等可见专名优先采用OCR写法，并保持前后一致。"
            "如果字幕或OCR中的专名明显不通顺，必须原样标注为识别不确定，禁止自行扩写其含义或猜测设定。"
            if summary_question
            else "根据问题所需粒度作答，不机械复述字幕。"
        )
        result, fallback_used = await self._complete_with_retry(
            llm=llm,
            system=(
                "你是自然、专业的视频理解助手，不是字幕复读器。只能依据编号证据回答，但要先理解"
                "用户意图，再综合声音、画面、OCR 和章节上下文。回答先给直接结论，再解释关键依据；"
                "不要逐条照抄字幕或整页 OCR，不要说‘根据证据1’，不要为了显得完整重复相同信息。"
                "画面问题要区分‘屏幕上写了什么’与‘这些内容表达什么’；整体问题要归纳主题、结构和"
                "逻辑关系。证据不足时明确说明边界，不得用常识冒充视频内容。"
                f"{summary_rules}"
                "输出 JSON：text、citation_indices（真正支持结论的整数编号数组）、"
                "confidence（0到1）、limitations（字符串数组）。"
            ),
            user=(
                f"用户问题：{question.query}\n"
                f"问题范围：{question.target.kind}\n"
                f"视频证据：\n{evidence_text}\n"
                "请像一个真正看过视频的人一样回答，保持简洁但有信息密度。"
            ),
            purpose="video_question_answer",
            video_id=str(question.video_id),
            # 思考 token 与最终答案共享 max_tokens；全片总结需要为推理预留足够空间。
            max_tokens=12_000 if summary_question else 6_000,
            thinking=True,
            reasoning_effort="high",
        )
        if result is None:
            draft = self._compose(question, evidence)
            draft.limitations.append("大模型回答超时，已使用全片证据生成保底回答。")
            return draft
        indices = [
            value
            for value in result.get("citation_indices", [])
            if isinstance(value, int) and 0 <= value < len(evidence)
        ]
        cited = [evidence[index] for index in dict.fromkeys(indices)] or evidence[:1]
        if summary_question:
            # 总结回答固定补充少量跨时间视觉证据，保证回放不只有无截图的字幕片段。
            visual = [
                item
                for item in evidence
                if item.kind in {EvidenceKind.VISUAL, EvidenceKind.OCR, EvidenceKind.FRAME}
                and item.snapshot_url
            ]
            for item in visual[:4]:
                if item.id not in {existing.id for existing in cited}:
                    cited.append(item)
        citations = []
        for item in cited:
            timestamp_ms = item.timestamp_ms or (item.time_range.start_ms if item.time_range else 0)
            citations.append(
                EvidenceCitation(
                    evidence_id=item.id,
                    timestamp_ms=timestamp_ms,
                    label=(item.quote or item.description)[:48],
                    snapshot_url=item.snapshot_url,
                )
            )
        return DraftAnswer(
            text=_remove_low_value_meta(str(result.get("text") or "证据不足，无法回答。")),
            citations=citations,
            evidence=cited,
            confidence=max(0, min(1, float(result.get("confidence", 0.5)))),
            limitations=[str(item) for item in result.get("limitations", [])]
            + (["深度思考超时，已使用同一份全片证据重新组织答案。"] if fallback_used else []),
        )

    async def _complete_with_retry(
        self, *, llm: Any, **kwargs: Any
    ) -> tuple[dict[str, Any] | None, bool]:
        """优先保证回答质量；思考模式超时时，再用相同证据做一次稳定的非思考重试。"""
        try:
            return await llm.complete_json(**kwargs), False
        except Exception:
            retry_kwargs = dict(kwargs)
            retry_kwargs["thinking"] = False
            retry_kwargs["max_tokens"] = min(int(retry_kwargs.get("max_tokens", 4_000)), 4_000)
            try:
                return await llm.complete_json(**retry_kwargs), True
            except Exception:
                return None, True

    def _compose(self, question: Question, evidence: list[Evidence]) -> DraftAnswer:
        if not evidence:
            return DraftAnswer(
                text="目前没有检索到足以回答这个问题的视频内证据。",
                limitations=["可能尚未完成对应时间段的字幕、OCR 或视觉索引。"],
            )

        prefix = {
            "global": "从当前已完成的多轨时间轴来看，视频主要包含：",
            "range": "在你指定的时间范围内，视频内容包括：",
            "moment": "在该时刻前后的声音、字幕与画面共同显示：",
            "frame": "仅依据目标帧附近可见的画面和 OCR：",
        }[question.target.kind]

        lines: list[str] = [prefix]
        citations: list[EvidenceCitation] = []
        selected = evidence[:5]
        if (
            question.target.kind == "global"
            and _is_summary_query(question.query)
            and len(evidence) > 5
        ):
            # 离线保底回答同样覆盖全片，避免只引用列表前五条而被覆盖率校验拒绝。
            chronological = sorted(evidence, key=lambda item: item.timestamp_ms or 0)
            last = len(chronological) - 1
            selected = [chronological[round(index * last / 4)] for index in range(5)]
        for item in selected:
            timestamp_ms = item.timestamp_ms
            if timestamp_ms is None and item.time_range is not None:
                timestamp_ms = item.time_range.start_ms
            timestamp_ms = timestamp_ms or 0
            display = item.quote or item.description
            display = display.replace("\n", " ").strip()
            if len(display) > 90:
                display = f"{display[:87]}..."
            lines.append(f"- [{_format_timestamp(timestamp_ms)}] {display}")
            citations.append(
                EvidenceCitation(
                    evidence_id=item.id,
                    timestamp_ms=timestamp_ms,
                    label=display[:48],
                    snapshot_url=item.snapshot_url,
                )
            )

        confidence = sum(item.confidence for item in selected) / len(selected)
        return DraftAnswer(
            text="\n".join(lines),
            citations=citations,
            evidence=evidence,
            confidence=min(0.98, confidence),
            limitations=(
                ["这是离线演示模型生成的结构化回答；接入真实模型后仍受同一证据约束。"]
                if all(item.provenance.model is None for item in evidence)
                else []
            ),
        )

    @staticmethod
    def _deduplicate(items: list[Evidence]) -> list[Evidence]:
        seen: set[tuple[object, ...]] = set()
        seen_snapshots: set[str] = set()
        result: list[Evidence] = []
        for item in items:
            key = (
                item.kind,
                item.timestamp_ms,
                item.quote,
                item.description,
                tuple(item.artifact_ids),
            )
            if item.snapshot_url and item.snapshot_url in seen_snapshots:
                continue
            if key not in seen:
                seen.add(key)
                if item.snapshot_url:
                    seen_snapshots.add(item.snapshot_url)
                result.append(item)
        return result


def _is_summary_query(query: str) -> bool:
    normalized = query.lower().replace(" ", "")
    return any(marker in normalized for marker in ("总结", "概括", "主要内容", "讲了什么", "大意"))


def _remove_low_value_meta(text: str) -> str:
    """过滤与用户内容理解无关的关注提醒、告别语等模板化尾声描述。"""
    patterns = (
        r"[，；]?最后(?:还)?(?:号召|提醒)[^。；\n]*(?:关注|点赞|投币)[^。；\n]*",
        r"视频以[^。\n]*(?:告别语|结束语)[^。\n]*结束",
    )
    cleaned = text
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned)
    return cleaned.replace("。。", "。").strip()
