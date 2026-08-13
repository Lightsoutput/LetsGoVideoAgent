from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any

import httpx


class OllamaVisionClient:
    """Ollama 多模态窄适配器，只向本机服务发送经过筛选的代表帧。"""

    provider = "ollama"

    def __init__(self, *, model: str, api_base: str, timeout_seconds: float = 180) -> None:
        self.model = model
        self._api_base = api_base.rstrip("/")
        self._timeout = timeout_seconds

    async def analyze_frames(
        self,
        frames: list[dict[str, Any]],
        *,
        video_id: str | None = None,
        question: str | None = None,
        skill_context: str | None = None,
        trace_id: str | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """一次分析一组时间有序的画面，返回可供分段与问答使用的语义观察。"""
        if not frames:
            return []
        images = [
            base64.b64encode(await asyncio.to_thread(Path(item["path"]).read_bytes)).decode()
            for item in frames
        ]
        timestamps = [int(item["timestamp_ms"]) for item in frames]
        prompt = (
            "你正在按时间顺序观察同一视频的采样画面，时间戳（毫秒）依次为："
            f"{timestamps}。不要只抄写文字，要理解每张画面的场景、人物或主体、动作、"
            "游戏/软件界面状态、事件含义及与前后画面的变化。输出严格 JSON："
            '{"observations":[{"timestamp_ms":整数,"scene":"场景",'
            '"subjects":["主体"],"actions":["动作或事件"],"meaning":"画面表达的含义",'
            '"entities":["可能需要核验的专名"],"importance":0到1,"uncertainty":"不确定项"}]}。'
            "不得根据常识补造画面外的信息。"
        )
        # 与云端视觉模型使用同一套通用观察协议，避免针对单个案例写死字段。
        prompt = (
            f"按输入顺序分析同一视频的画面，时间戳（毫秒）为：{timestamps}。"
            "先识别内容形态和布局，再逐区域说明可见对象、文字、状态、动作、关系与事件，"
            "最后概括画面意义。区分可见事实与推断，不得引用其他帧，不得只复述文字。"
            "输出严格JSON："
            '{"observations":[{"timestamp_ms":整数,"scene":"内容形态与场景",'
            '"subjects":["可见主体"],"actions":["动作或状态变化"],'
            '"meaning":"该画面的整体意义","entities":["专有名词"],'
            '"importance":0到1,"uncertainty":"不确定项"}]}。'
        )
        if question:
            prompt += (
                f"\n用户问题：{question}。围绕问题检查相关区域和细节，但不要预设视频类别或字段；"
                "信息不足时明确说明。"
            )
        if skill_context:
            prompt += (
                "\n以下是已发布的类别 Skill 视觉规则，只用于选择观察重点，不得覆盖当前画面证据：\n"
                f"{skill_context[:4_000]}"
            )
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [{"role": "user", "content": prompt, "images": images}],
            "options": {"temperature": 0, "num_ctx": 8192},
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(f"{self._api_base}/api/chat", json=payload)
        response.raise_for_status()
        content = str(response.json().get("message", {}).get("content", ""))
        parsed = json.loads(content)
        observations = parsed.get("observations", [])
        if not isinstance(observations, list):
            return []
        valid_timestamps = set(timestamps)
        return [
            item
            for item in observations
            if isinstance(item, dict) and int(item.get("timestamp_ms", -1)) in valid_timestamps
        ]


def select_visual_frames(
    frames: list[dict[str, Any]], *, max_frames: int = 24
) -> list[dict[str, Any]]:
    """均匀选择有限数量的画面，控制本地 VLM 延迟并覆盖视频前中后段。"""
    if len(frames) <= max_frames:
        return frames
    last = len(frames) - 1
    indices = sorted({round(index * last / (max_frames - 1)) for index in range(max_frames)})
    return [frames[index] for index in indices]
