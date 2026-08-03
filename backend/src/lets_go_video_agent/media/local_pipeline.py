from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import Callable
from difflib import SequenceMatcher
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Any
from uuid import UUID

from lets_go_video_agent.domain.common import Provenance, TimeRange, utc_now
from lets_go_video_agent.domain.processing import ProcessingRun, ProcessingStatus
from lets_go_video_agent.domain.timeline import ObservationType, TimelineArtifact, TimelineKind
from lets_go_video_agent.domain.video import VideoStatus, WebSource
from lets_go_video_agent.infrastructure.models.deepseek_client import DeepSeekClient
from lets_go_video_agent.media.ytdlp import YtDlpAdapter


@lru_cache(maxsize=1)
def _traditional_to_simplified_converter() -> Any:
    """延迟加载 OpenCC，避免不处理本地视频时增加应用启动成本。"""
    from opencc import OpenCC  # type: ignore[import-untyped]

    return OpenCC("t2s")


def normalize_chinese_text(text: str) -> str:
    """把 ASR/OCR 中的繁体字统一为简体，同时清理多余空白。"""
    compact = " ".join(text.split())
    return str(_traditional_to_simplified_converter().convert(compact)).strip()


def probe_video(path: Path) -> dict[str, Any]:
    """使用 PyAV 探测媒体；Windows wheel 已内置 FFmpeg 动态库。"""
    import av

    with av.open(str(path)) as container:
        video = container.streams.video[0]
        return {
            "duration_ms": int((container.duration or 0) / 1000),
            "width": video.width,
            "height": video.height,
            "fps": float(video.average_rate or 0),
            "codec": video.codec_context.name,
        }


def extract_keyframes(
    path: Path, output_dir: Path, duration_ms: int, interval_seconds: int = 15
) -> list[dict[str, Any]]:
    """按时间采样关键帧；长视频自动放宽间隔，避免 OCR 数量随时长无限增长。"""
    import av

    output_dir.mkdir(parents=True, exist_ok=True)
    result: list[dict[str, Any]] = []
    max_frames = 72
    adaptive_interval = max(
        interval_seconds,
        math.ceil(duration_ms / max_frames / 1000),
    )
    timestamps = list(range(0, max(1, duration_ms), adaptive_interval * 1000))
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        for timestamp_ms in timestamps:
            # 不传 stream 时 offset 使用 AV_TIME_BASE（微秒）。旧实现同时传 stream 和
            # 微秒，单位不匹配会把大量采样错误地寻址到视频末尾。
            container.seek(int(timestamp_ms * 1000), any_frame=False, backward=True)
            frame = next(container.decode(stream), None)
            if frame is None:
                continue
            frame_path = output_dir / f"{timestamp_ms:010d}.jpg"
            image = frame.to_image()
            # OCR 不需要保留 1080p/4K 原始分辨率；限制长边可显著降低 CPU 推理时间。
            image.thumbnail((1280, 1280))
            image.save(frame_path, quality=88)  # type: ignore[no-untyped-call]
            result.append({"timestamp_ms": timestamp_ms, "path": frame_path})
    return result


async def extract_frame_at(source: Path, target: Path, timestamp_ms: int) -> None:
    """在工作线程按 PTS 精确寻址，避免阻塞 FastAPI 事件循环。"""

    def _extract() -> None:
        import av

        target.parent.mkdir(parents=True, exist_ok=True)
        with av.open(str(source)) as container:
            stream = container.streams.video[0]
            container.seek(timestamp_ms * 1000, any_frame=False, backward=True)
            selected = None
            for frame in container.decode(stream):
                selected = frame
                frame_ms = int(float(frame.time or 0) * 1000)
                if frame_ms >= timestamp_ms:
                    break
            if selected is None:
                raise RuntimeError("目标时间戳没有可解码帧")
            selected.to_image().save(target, quality=90)  # type: ignore[no-untyped-call]

    await asyncio.to_thread(_extract)


def transcribe(path: Path, model_name: str) -> list[dict[str, Any]]:
    """本地 ASR。CPU int8 可在无 CUDA 环境稳定运行，首次会下载模型。"""
    from faster_whisper import WhisperModel  # type: ignore[import-untyped]

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(path), language="zh", vad_filter=True, beam_size=3)
    return [
        {
            "start_ms": int(item.start * 1000),
            "end_ms": max(int(item.end * 1000), int(item.start * 1000) + 1),
            "text": normalize_chinese_text(item.text),
        }
        for item in segments
        if item.text.strip()
    ]


def diarize_speakers(
    path: Path,
    transcript: list[dict[str, Any]],
    ocr_items: list[dict[str, Any]] | None = None,
    max_speakers: int = 4,
) -> list[str]:
    """使用本地声谱特征做轻量说话人聚类；无需云端 API 或 HuggingFace Token。

    这是通用 P0 基线：能够区分音色差异明显的访谈参与者。生产环境可通过相同输出
    契约替换为 pyannote/ECAPA，以获得更可靠的重叠语音和短句识别。
    """
    import av
    import numpy as np

    if len(transcript) < 4:
        return ["Speaker 1"] * len(transcript)
    chunks: list[Any] = []
    with av.open(str(path)) as container:
        if not container.streams.audio:
            return ["Speaker 1"] * len(transcript)
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=8_000)
        for frame in container.decode(stream):
            converted = resampler.resample(frame)
            for audio_frame in converted:
                chunks.append(audio_frame.to_ndarray().reshape(-1))
    if not chunks:
        return ["Speaker 1"] * len(transcript)
    samples = np.concatenate(chunks).astype(np.float32) / 32768.0
    sample_rate = 8_000
    features: list[Any] = []
    for item in transcript:
        start = max(0, int(item["start_ms"]) * sample_rate // 1000)
        end = min(len(samples), int(item["end_ms"]) * sample_rate // 1000)
        # 太短的语气词向两侧扩展，最长只取4秒，避免长句在内存计算上占优势。
        if end - start < sample_rate // 2:
            padding = sample_rate // 3
            start, end = max(0, start - padding), min(len(samples), end + padding)
        if end - start > sample_rate * 4:
            center = (start + end) // 2
            start, end = center - sample_rate * 2, center + sample_rate * 2
        signal = samples[start:end]
        if len(signal) < 512:
            features.append(np.zeros(22, dtype=np.float32))
            continue
        frame_size, hop = 512, 256
        frame_count = 1 + (len(signal) - frame_size) // hop
        indices = np.arange(frame_size)[None, :] + hop * np.arange(frame_count)[:, None]
        framed = signal[indices] * np.hanning(frame_size)[None, :]
        power = np.abs(np.fft.rfft(framed, axis=1)) ** 2
        # 20个对数频带近似刻画音色包络，另加过零率和谱质心。
        bands = np.array_split(power[:, 1:], 20, axis=1)
        band_feature = np.array([np.log1p(band.mean()) for band in bands])
        zcr = np.mean(np.abs(np.diff(np.signbit(signal))))
        frequencies = np.fft.rfftfreq(frame_size, 1 / sample_rate)
        centroid = (
            np.mean(
                (power * frequencies[None, :]).sum(axis=1) / np.maximum(power.sum(axis=1), 1e-9)
            )
            / sample_rate
        )
        features.append(np.concatenate([band_feature, [zcr, centroid]]))
    matrix = np.asarray(features, dtype=np.float64)
    matrix = (matrix - matrix.mean(axis=0)) / np.maximum(matrix.std(axis=0), 1e-6)
    anchored = _assign_identity_anchors(matrix, transcript, ocr_items or [])
    if anchored is not None:
        return anchored
    labels = _select_speaker_clusters(matrix, max_speakers=max_speakers)
    # 去除单句抖动：前后属于同一音色时，中间短句沿用相邻说话人。
    for index in range(1, len(labels) - 1):
        if labels[index - 1] == labels[index + 1] != labels[index]:
            labels[index] = labels[index - 1]
    order: dict[int, int] = {}
    return [f"Speaker {order.setdefault(int(label), len(order) + 1)}" for label in labels]


def _assign_identity_anchors(
    matrix: Any,
    transcript: list[dict[str, Any]],
    ocr_items: list[dict[str, Any]],
) -> list[str] | None:
    """从自我介绍/称呼中提取姓名，并用这些句子的音色作为有监督身份锚点。"""
    import numpy as np

    candidates: list[tuple[int, str]] = []
    patterns = (
        r"我是主持人([\u4e00-\u9fffA-Za-z0-9]{1,8})",
        r"这里是([\u4e00-\u9fffA-Za-z0-9]{1,8})",
        r"我叫([\u4e00-\u9fffA-Za-z0-9]{1,8})",
        r"叫我([\u4e00-\u9fffA-Za-z0-9]{1,8}?)(?:就好|即可|吧|$)",
    )
    for index, item in enumerate(transcript):
        text = str(item["text"])
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                candidates.append((index, match.group(1)))
                break
        # 节目前两分钟的“我是某某”通常就是嘉宾自我介绍；后半片则容易是普通陈述。
        if int(item["start_ms"]) <= 120_000:
            match = re.fullmatch(r"(?:哈[啰喽]|大家好)?我是([\u4e00-\u9fffA-Za-z0-9]{2,10})", text)
            if match:
                candidates.append((index, match.group(1)))
    rejected_prefixes = ("一个", "来自", "做", "在", "很", "说", "想")
    candidates = [
        (index, name.strip("，。！？ "))
        for index, name in candidates
        if name and not name.startswith(rejected_prefixes)
    ]
    # “我是罗德岛的克斯 / 叫我克斯就好”视为同一身份，并采用更短的自称。
    merged: list[tuple[list[int], str]] = []
    for index, name in candidates:
        target = next(
            (
                item
                for item in merged
                if abs(index - item[0][-1]) <= 10
                and (item[1].endswith(name) or name.endswith(item[1]))
            ),
            None,
        )
        if target:
            target[0].append(index)
            if len(name) < len(target[1]):
                target_index = merged.index(target)
                merged[target_index] = (target[0], name)
        else:
            merged.append(([index], name))
    if not 2 <= len(merged) <= 8:
        return None

    visible_text = " ".join(str(item.get("text", "")) for item in ocr_items)
    host_match = re.search(r"主持人[:：]\s*@?([^\s/，,、]{1,12})", visible_text)
    guests_match = re.search(r"嘉宾[:：]\s*([^/]{2,100})", visible_text)
    canonical_names: list[str] = []
    if host_match:
        canonical_names.append(host_match.group(1).strip())
    if guests_match:
        canonical_names.extend(
            part.strip().lstrip("@").strip()
            for part in re.split(r"[、,，]", guests_match.group(1))
            if part.strip()
        )
    if len(canonical_names) >= len(merged):
        normalized_names: list[str] = []
        for name in canonical_names[: len(merged)]:
            if name.upper().startswith("MR") and f"{name[2:]}：" in visible_text:
                name = name[2:]
            short_name = name.rsplit("的", maxsplit=1)[-1]
            if short_name != name and f"{short_name}：" in visible_text:
                name = short_name
            normalized_names.append(name)
        merged = [(indices, normalized_names[index]) for index, (indices, _) in enumerate(merged)]

    names = [name for _indices, name in merged]
    ocr_anchors = _extract_ocr_speaker_anchors(names, transcript, ocr_items)

    # 每位说话人保留一组分散在全片的音色样本，而不是压成一个均值中心。
    # 人声会随情绪、音量、设备处理发生变化；多原型的最近邻距离能减少“同一个人
    # 激动后被识别成另一个人”的情况。开场自我介绍可向后扩展，OCR 标签则只采用
    # 与屏幕发言内容匹配最好的精确字幕段，避免把相邻主持人的提问混入声纹。
    prototype_banks: list[Any] = []
    hard_anchors: dict[int, int] = {}
    for speaker_index, (intro_indices, _name) in enumerate(merged):
        anchor_indices: set[int] = set()
        for index in intro_indices:
            anchor_indices.update(range(index, min(len(matrix), index + 6)))
            hard_anchors[index] = speaker_index
        for index in ocr_anchors.get(names[speaker_index], []):
            anchor_indices.add(index)
            hard_anchors[index] = speaker_index
        prototype_banks.append(matrix[sorted(anchor_indices)])

    emissions: list[Any] = []
    for prototypes in prototype_banks:
        distances = np.square(matrix[:, None, :] - prototypes[None, :, :]).mean(axis=2)
        # 取最接近的至多 3 个原型，兼顾局部音色变化和单帧 OCR/ASR 噪声。
        nearest_count = min(3, distances.shape[1])
        nearest = np.partition(distances, nearest_count - 1, axis=1)[:, :nearest_count]
        emissions.append(nearest.mean(axis=1))
    emission = np.stack(emissions, axis=1)

    # 画面已经明确写出“姓名：发言内容”时，它比轻量声学特征更可靠。
    # 直接施加强约束，保证后续 Viterbi 不会为了减少切换而覆盖这条证据。
    for row, speaker_index in hard_anchors.items():
        emission[row, :] += 100.0
        emission[row, speaker_index] -= 100.0
    # Viterbi：一次身份切换需要付出代价，避免同一个连续回答被逐句拆成不同人。
    switch_penalty = 0.65
    costs = np.full_like(emission, np.inf)
    backtrack = np.zeros_like(emission, dtype=np.int64)
    costs[0] = emission[0]
    for row in range(1, len(matrix)):
        for speaker in range(len(names)):
            previous = costs[row - 1] + switch_penalty
            previous[speaker] = costs[row - 1, speaker]
            best = int(previous.argmin())
            costs[row, speaker] = previous[best] + emission[row, speaker]
            backtrack[row, speaker] = best
    labels = np.zeros(len(matrix), dtype=np.int64)
    labels[-1] = int(costs[-1].argmin())
    for row in range(len(matrix) - 1, 0, -1):
        labels[row - 1] = backtrack[row, labels[row]]

    # 自我介绍是一段强对话证据：从介绍开始到“下一位/最后请/再次欢迎”等主持转场前，
    # 整段归属同一嘉宾，修正“谢谢、大家好”等短句因声学信息不足而错分的问题。
    transition_pattern = re.compile(r"下一位|最后请|再次欢迎|先从.+开始")
    for speaker_index, (indices, _name) in enumerate(merged):
        start = min(indices)
        if start > 0 and re.search(r"大家好|哈[啰喽]|好的", str(transcript[start - 1]["text"])):
            start -= 1
        end = min(len(labels), max(indices) + 8)
        for row in range(min(indices) + 1, end):
            if transition_pattern.search(str(transcript[row]["text"])):
                end = row
                break
        labels[start:end] = speaker_index

    return [names[int(label)] for label in labels]


def _extract_ocr_speaker_anchors(
    names: list[str],
    transcript: list[dict[str, Any]],
    ocr_items: list[dict[str, Any]],
    search_window_ms: int = 20_000,
) -> dict[str, list[int]]:
    """把画面中的“姓名：发言内容”对齐到 ASR 字幕，生成全片身份锚点。

    访谈/播客字幕条往往直接显示当前发言人。采样帧时间与 Whisper 分段边界可能
    相差数秒，因此不能只选择时间最近的字幕；这里会在时间窗口内同时比较文字
    相似度和时间距离。角色名单中的“主持人：/嘉宾：”会被明确排除。
    """

    anchors: dict[str, list[int]] = {name: [] for name in names}
    if not names or not transcript:
        return anchors

    def compact(value: str) -> str:
        return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", value).lower()

    name_pattern = "|".join(sorted((re.escape(name) for name in names), key=len, reverse=True))
    label_pattern = re.compile(
        rf"(?:^|[/\n])\s*@?(?P<name>{name_pattern})\s*[：:]\s*(?P<quote>[^/\n]{{1,100}})"
    )
    question_pattern = re.compile(
        r"(?:^|[/\n])\s*Q\s*[：:]\s*(?P<quote>[^/\n]{1,100})",
        re.IGNORECASE,
    )
    for ocr_item in ocr_items:
        text = str(ocr_item.get("text", ""))
        timestamp_ms = int(ocr_item.get("timestamp_ms", 0))
        evidence = [
            (match.group("name"), match.group("quote")) for match in label_pattern.finditer(text)
        ]
        # 访谈画面常用“Q：”代替主持人姓名。canonical names 的首位来自
        # “主持人：”名单，因此可把问题文本作为主持人的跨全片锚点。
        evidence.extend(
            (names[0], match.group("quote")) for match in question_pattern.finditer(text)
        )
        for name, raw_quote in evidence:
            quote = compact(raw_quote)
            candidates = [
                index
                for index, item in enumerate(transcript)
                if abs((int(item["start_ms"]) + int(item["end_ms"])) // 2 - timestamp_ms)
                <= search_window_ms
            ]
            if not candidates:
                continue

            def alignment_score(
                index: int,
                expected_quote: str = quote,
                frame_timestamp_ms: int = timestamp_ms,
            ) -> float:
                item = transcript[index]
                candidate = compact(str(item["text"]))
                similarity = SequenceMatcher(None, expected_quote, candidate).ratio()
                if candidate and (candidate in expected_quote or expected_quote in candidate):
                    similarity = max(similarity, 0.92)
                midpoint = (int(item["start_ms"]) + int(item["end_ms"])) // 2
                time_penalty = abs(midpoint - frame_timestamp_ms) / search_window_ms * 0.15
                return similarity - time_penalty

            best = max(candidates, key=alignment_score)
            # OCR/ASR 都可能有错字，阈值需兼顾召回率。若问题与回答被 Whisper
            # 合并到同一段，后续实名嘉宾锚点优先，避免 Q 标签覆盖回答者。
            if alignment_score(best) >= 0.18:
                anchors[name].append(best)

    return {name: sorted(set(indices)) for name, indices in anchors.items()}


def _select_speaker_clusters(matrix: Any, max_speakers: int) -> Any:
    """用确定性 k-means 和相对惯性收益估计 1～4 个说话人。"""
    import numpy as np

    count = len(matrix)
    best_labels = np.zeros(count, dtype=np.int64)
    previous_inertia = float(np.square(matrix - matrix.mean(axis=0)).sum())
    for cluster_count in range(2, min(max_speakers, count // 8) + 1):
        centers = [matrix[0]]
        for _ in range(1, cluster_count):
            distances = np.min(
                [np.square(matrix - center).sum(axis=1) for center in centers], axis=0
            )
            centers.append(matrix[int(np.argmax(distances))])
        centers_array = np.asarray(centers)
        labels = np.zeros(count, dtype=np.int64)
        for _ in range(30):
            distances = np.stack(
                [np.square(matrix - center).sum(axis=1) for center in centers_array], axis=1
            )
            next_labels = distances.argmin(axis=1)
            if np.array_equal(labels, next_labels) and _ > 0:
                break
            labels = next_labels
            centers_array = np.asarray(
                [
                    matrix[labels == index].mean(axis=0)
                    if np.any(labels == index)
                    else centers_array[index]
                    for index in range(cluster_count)
                ]
            )
        inertia = float(
            sum(
                np.square(matrix[labels == index] - centers_array[index]).sum()
                for index in range(cluster_count)
            )
        )
        sizes = np.bincount(labels, minlength=cluster_count)
        improvement = (previous_inertia - inertia) / max(previous_inertia, 1e-9)
        # 访谈中同性说话人的音色距离小于男女声差异，阈值过高会只得到“男女二分”。
        # 仍要求每个簇覆盖至少2%的字幕，防止把偶发噪声误认为独立说话人。
        if improvement < 0.08 or sizes.min() < max(4, count * 0.02):
            break
        best_labels, previous_inertia = labels, inertia
    return best_labels


def run_ocr(
    frames: list[dict[str, Any]],
    cache_path: Path | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    """逐帧 OCR 并保存断点；单帧异常会跳过，不再拖垮整个视频。"""
    from rapidocr import RapidOCR

    engine = RapidOCR()
    cached: dict[str, dict[str, Any]] = {}
    if cache_path and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cached = {}
    results: list[dict[str, Any]] = []
    total = len(frames)
    for index, frame in enumerate(frames, start=1):
        key = str(int(frame["timestamp_ms"]))
        record = cached.get(key)
        if record is None:
            try:
                output = engine(str(frame["path"]))
                texts = list(getattr(output, "txts", None) or []) if output else []
                scores = list(getattr(output, "scores", None) or []) if output else []
                text = normalize_chinese_text(
                    " / ".join(item.strip() for item in texts if item and item.strip())
                )
                confidence = sum(scores) / len(scores) if scores else 0.7
                record = {"text": text, "confidence": float(confidence)}
            except Exception as exc:
                record = {"text": "", "confidence": 0.0, "error": type(exc).__name__}
            cached[key] = record
            if cache_path and (index % 5 == 0 or index == total):
                cache_path.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")
        text = str(record.get("text", ""))
        if text:
            results.append({**frame, "text": text, "confidence": float(record["confidence"])})
        if progress_callback:
            progress_callback(index, total)
    return results


def _text_similarity(left: str, right: str) -> float:
    """用字符集合估算两页 OCR 的相似度，足以过滤缓慢动画产生的近重复画面。"""
    left_chars = {char for char in left if not char.isspace()}
    right_chars = {char for char in right if not char.isspace()}
    if not left_chars or not right_chars:
        return 0
    return len(left_chars & right_chars) / len(left_chars | right_chars)


def curate_representative_frames(
    *,
    video_id: UUID,
    frames: list[dict[str, Any]],
    ocr_items: list[dict[str, Any]],
    chapters: list[TimelineArtifact],
    duration_ms: int,
) -> list[TimelineArtifact]:
    """按章节选择少量代表帧，而不是把固定间隔采样全部暴露给用户。"""
    if not frames:
        return []

    sections = chapters
    if not sections:
        sections = [
            TimelineArtifact(
                video_id=video_id,
                kind=TimelineKind.SEGMENT,
                time_range=TimeRange(
                    start_ms=start,
                    end_ms=min(duration_ms, start + 120_000),
                ),
                title=f"视频片段 {index:02d}",
                text="尚未生成语义章节，按两分钟窗口选择代表画面。",
                confidence=0.6,
                observation_type=ObservationType.INFERENCE,
                provenance=Provenance(producer="representative-frame-selector"),
            )
            for index, start in enumerate(range(0, duration_ms, 120_000), start=1)
        ]

    ocr_by_timestamp = {int(item["timestamp_ms"]): str(item["text"]) for item in ocr_items}
    used_timestamps: set[int] = set()
    result: list[TimelineArtifact] = []
    for section_index, section in enumerate(sections, start=1):
        section_frames = [
            item
            for item in frames
            if section.time_range.start_ms <= int(item["timestamp_ms"]) < section.time_range.end_ms
            and int(item["timestamp_ms"]) not in used_timestamps
        ]
        if not section_frames:
            continue

        duration = section.time_range.end_ms - section.time_range.start_ms
        # 短视频章节通常只有 20～60 秒，也应覆盖前半段和后半段，不能总取章节尾部。
        fractions = (0.28, 0.72) if duration >= 20_000 else (0.5,)
        selected: list[dict[str, Any]] = []
        for fraction in fractions:
            target = section.time_range.start_ms + int(duration * fraction)
            available = [item for item in section_frames if item not in selected]
            if not available:
                break
            ranked = sorted(
                available,
                key=lambda item: abs(int(item["timestamp_ms"]) - target),
            )
            candidate = ranked[0]
            if selected:
                previous_text = ocr_by_timestamp.get(int(selected[-1]["timestamp_ms"]), "")
                # 最近帧若只是缓慢动画中的近重复页面，继续寻找本章内下一张不同画面。
                distinct = [
                    item
                    for item in ranked
                    if not previous_text
                    or not ocr_by_timestamp.get(int(item["timestamp_ms"]), "")
                    or _text_similarity(
                        previous_text,
                        ocr_by_timestamp.get(int(item["timestamp_ms"]), ""),
                    )
                    < 0.82
                ]
                if distinct:
                    candidate = distinct[0]
                elif len(section_frames) > 1:
                    continue
            selected.append(candidate)

        for frame_index, frame in enumerate(selected, start=1):
            timestamp_ms = int(frame["timestamp_ms"])
            used_timestamps.add(timestamp_ms)
            title = f"{section_index:02d}-{frame_index:02d}｜{section.title or '未命名章节'}"
            result.append(
                TimelineArtifact(
                    video_id=video_id,
                    kind=TimelineKind.VISUAL,
                    time_range=TimeRange(
                        start_ms=timestamp_ms,
                        end_ms=min(
                            duration_ms,
                            section.time_range.end_ms,
                            timestamp_ms + 30_000,
                        ),
                    ),
                    title=title,
                    text=section.text or f"“{section.title or '本节'}”的代表画面。",
                    confidence=0.86,
                    observation_type=ObservationType.INFERENCE,
                    snapshot_key=f"frames/{video_id}/{frame['path'].name}",
                    tags=[
                        "representative-frame",
                        f"section:{section_index:02d}",
                        f"frame:{frame_index:02d}",
                    ],
                    provenance=Provenance(
                        producer="representative-frame-selector",
                        tool_version="chapter-aware-v2",
                    ),
                )
            )
    return result


def build_fallback_chapters(
    *,
    video_id: UUID,
    transcript: list[dict[str, Any]],
    duration_ms: int,
    ocr_items: list[dict[str, Any]] | None = None,
) -> list[TimelineArtifact]:
    """模型分章失败时优先识别口播序号，否则退回 90 秒稳定窗口。"""
    numeral_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    markers: dict[int, int] = {}
    for item in transcript:
        match = re.search(r"第\s*([一二三四五六七八九1-9])", str(item["text"]))
        if not match:
            continue
        raw = match.group(1)
        ordinal = numeral_map.get(raw, int(raw) if raw.isdigit() else 0)
        if ordinal:
            markers.setdefault(ordinal, int(item["start_ms"]))

    boundaries: list[int]
    ordered_ordinals = sorted(markers)
    ordered_marker_times = [markers[ordinal] for ordinal in ordered_ordinals]
    uses_spoken_ordinals = (
        len(markers) >= 3
        and all(previous < current for previous, current in pairwise(ordered_marker_times))
        and ordered_marker_times[0] <= max(120_000, duration_ms * 0.1)
    )
    if uses_spoken_ordinals:
        highest = max(markers)
        estimated: dict[int, int] = dict(markers)
        for ordinal in range(1, highest + 1):
            if ordinal in estimated:
                continue
            previous = max((value for value in markers if value < ordinal), default=None)
            following = min((value for value in markers if value > ordinal), default=None)
            if previous is not None and following is not None:
                ratio = (ordinal - previous) / (following - previous)
                estimated[ordinal] = int(
                    markers[previous] + (markers[following] - markers[previous]) * ratio
                )
        # 访谈或复盘视频可能在后文再次提到“第一/第二”，序号语义不一定与时间顺序一致。
        # TimeRange 的唯一硬约束是时间单调，因此边界必须按时间排序、去重并限制在片长内。
        boundaries = sorted(
            {
                0,
                *(
                    timestamp
                    for ordinal, timestamp in estimated.items()
                    if ordinal > 1 and 0 < timestamp < duration_ms
                ),
            }
        )
    else:
        boundaries = list(range(0, duration_ms, 90_000))

    chapters: list[TimelineArtifact] = []
    for index, start_ms in enumerate(boundaries, start=1):
        end_ms = boundaries[index] if index < len(boundaries) else duration_ms
        snippets = [
            str(item["text"]) for item in transcript if start_ms <= int(item["start_ms"]) < end_ms
        ]
        title_start_ms = markers.get(index, start_ms)
        title_snippets = [
            str(item["text"])
            for item in transcript
            if title_start_ms <= int(item["start_ms"]) < end_ms
        ]
        meaningful = [
            text for text in title_snippets if not re.fullmatch(r"第?[一二三四五六七八九1-9]", text)
        ]
        fallback_lead = title_snippets[0] if title_snippets else "画面内容"
        lead = (meaningful[0] if meaningful else fallback_lead)[:24]
        for ocr in ocr_items or []:
            if start_ms <= int(ocr["timestamp_ms"]) < min(end_ms, start_ms + 15_000):
                ocr_text = str(ocr["text"])
                heading = re.search(r"[一二三四五六七八九]、\s*([^/]{2,24})", ocr_text)
                if heading:
                    lead = heading.group(1).strip()
                    break
                candidates = [
                    part.strip()
                    for part in ocr_text.split("/")
                    if 2 <= len(part.strip()) <= 24
                    and re.search(r"备战|建议|角色|版本|剧情|玩法|优化|精炼", part)
                ]
                if candidates:
                    lead = candidates[0]
                    break
        lead = re.sub(r"^第\s*[一二三四五六七八九1-9][、，:：\s]*", "", lead).strip()
        summary = "".join(snippets[:4])[:240]
        chapters.append(
            TimelineArtifact(
                video_id=video_id,
                kind=TimelineKind.CHAPTER,
                time_range=TimeRange(start_ms=start_ms, end_ms=end_ms),
                title=f"{('建议' if uses_spoken_ordinals else '片段')} {index:02d}｜{lead}",
                text=summary or "该片段暂无可靠语音摘要，可结合代表画面查看。",
                confidence=0.58,
                observation_type=ObservationType.INFERENCE,
                tags=["fallback-chapter"],
                provenance=Provenance(
                    producer="deterministic-chapter-fallback",
                    tool_version="90s-window-v1",
                ),
            )
        )
    return chapters


def build_semantic_windows(
    transcript: list[dict[str, Any]],
    ocr_items: list[dict[str, Any]],
    duration_ms: int,
    window_ms: int = 60_000,
) -> str:
    """把长视频压缩为完整覆盖的语义窗口，避免直接截断逐句字幕而丢失后半片。"""
    lines: list[str] = []
    for start_ms in range(0, duration_ms, window_ms):
        end_ms = min(duration_ms, start_ms + window_ms)
        spoken = " ".join(
            f"{item.get('speaker', 'Speaker ?')}:{item['text']}"
            for item in transcript
            if start_ms <= int(item["start_ms"]) < end_ms
        )
        visible = " / ".join(
            str(item["text"])
            for item in ocr_items
            if start_ms <= int(item["timestamp_ms"]) < end_ms
        )
        if spoken or visible:
            lines.append(
                f"[{start_ms}-{end_ms}] 语音={spoken[:1800]} || 画面文字={visible[:500] or '无'}"
            )
    return "\n".join(lines)


def validate_and_normalize_chapters(
    *,
    video_id: UUID,
    raw_chapters: Any,
    duration_ms: int,
    model_name: str,
    prompt_version: str,
) -> list[TimelineArtifact]:
    """过滤模型越界时间，并以相邻起点重建连续、无重叠的语义章节。"""
    parsed: list[tuple[int, str, str]] = []
    if not isinstance(raw_chapters, list):
        return []
    for item in raw_chapters:
        if not isinstance(item, dict):
            continue
        try:
            start = int(item["start_ms"])
            end = int(item["end_ms"])
        except (KeyError, TypeError, ValueError):
            continue
        if start < 0 or start >= duration_ms or end <= start:
            continue
        parsed.append(
            (
                start,
                str(item.get("title") or "未命名章节")[:80],
                str(item.get("summary") or "")[:600],
            )
        )
    parsed = sorted(dict.fromkeys(parsed), key=lambda item: item[0])
    if not parsed or parsed[0][0] > 15_000 or parsed[-1][0] < duration_ms * 0.65:
        return []
    chapters: list[TimelineArtifact] = []
    for index, (start, title, summary) in enumerate(parsed):
        end = parsed[index + 1][0] if index + 1 < len(parsed) else duration_ms
        if end <= start:
            continue
        chapters.append(
            TimelineArtifact(
                video_id=video_id,
                kind=TimelineKind.CHAPTER,
                time_range=TimeRange(start_ms=start, end_ms=end),
                title=title,
                text=summary,
                confidence=0.8,
                observation_type=ObservationType.INFERENCE,
                provenance=Provenance(
                    producer="timeline-curator-agent",
                    model=model_name,
                    prompt_version=prompt_version,
                ),
            )
        )
    return chapters


class LocalProcessingManager:
    """开发环境后台 Worker：任务与 HTTP 请求解耦，并持续更新可观察进度。"""

    def __init__(
        self,
        *,
        store: Any,
        data_dir: Path,
        asr_model: str,
        llm: DeepSeekClient | None,
        web_downloader: YtDlpAdapter | None = None,
    ) -> None:
        self._store = store
        self._data_dir = data_dir.resolve()
        self._asr_model = asr_model
        self._llm = llm
        self._web_downloader = web_downloader
        self._runs: dict[UUID, ProcessingRun] = {}
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._attempts: dict[UUID, int] = {}

    def get(self, video_id: UUID) -> ProcessingRun | None:
        run = self._runs.get(video_id)
        if run is None:
            return None
        result = run.model_copy(deep=True)
        # 长阶段（例如 ASR）期间也动态刷新计时，避免用户误以为任务卡死。
        if result.status is ProcessingStatus.RUNNING and result.started_at:
            result.elapsed_seconds = (utc_now() - result.started_at).total_seconds()
            if result.progress > 0 and result.elapsed_seconds >= 2:
                result.eta_seconds = (
                    result.elapsed_seconds * (1 - result.progress) / result.progress
                )
        return result

    def start(self, video_id: UUID) -> ProcessingRun:
        existing = self._runs.get(video_id)
        if existing and existing.status in {ProcessingStatus.QUEUED, ProcessingStatus.RUNNING}:
            return existing.model_copy(deep=True)
        run = ProcessingRun(video_id=video_id)
        self._runs[video_id] = run
        self._attempts[video_id] = 0
        self._tasks[video_id] = asyncio.create_task(self._process(run))
        return run.model_copy(deep=True)

    async def _update(
        self, run: ProcessingRun, stage: str, label: str, progress: float, message: str
    ) -> None:
        video = await self._store.get(run.video_id)
        web_import_stages = {"reading_web_metadata", "downloading", "downloaded"}
        if (
            video
            and isinstance(video.source, WebSource)
            and video.source_object_key
            and stage not in web_import_stages
        ):
            # 网页媒体导入占总进度前 25%，后续内容理解映射到剩余 75%，避免进度倒退。
            progress = 0.25 + progress * 0.75
        run.stage, run.stage_label, run.progress, run.message = stage, label, progress, message
        if run.started_at:
            run.elapsed_seconds = (utc_now() - run.started_at).total_seconds()
            run.eta_seconds = (
                run.elapsed_seconds * (1 - progress) / progress if 0 < progress < 1 else None
            )
        self._runs[run.video_id] = run.model_copy(deep=True)
        state_dir = self._data_dir / "processing"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / f"{run.video_id}.json").write_text(
            run.model_dump_json(indent=2), encoding="utf-8"
        )
        if video:
            video.status = VideoStatus.READY if progress >= 1 else VideoStatus.PROCESSING
            video.progress, video.current_stage, video.updated_at = progress, stage, utc_now()
            await self._store.update(video)

    async def _process(self, run: ProcessingRun) -> None:
        attempt = self._attempts.get(run.video_id, 0) + 1
        self._attempts[run.video_id] = attempt
        run.status, run.started_at = ProcessingStatus.RUNNING, utc_now()
        try:
            video = await self._store.get(run.video_id)
            if video is None:
                raise FileNotFoundError("视频记录不存在")
            # 新一轮重试开始时清除上一轮错误，避免页面同时显示“处理中”和旧异常。
            video.error_code = None
            video.error_message = None
            run.error = None
            await self._store.update(video)
            if isinstance(video.source, WebSource) and not video.source_object_key:
                await self._import_web_media(run, video)
                video = await self._store.get(run.video_id)
            if video is None or not video.source_object_key:
                raise FileNotFoundError("视频源文件不存在")
            source = (self._data_dir / video.source_object_key).resolve()
            if self._data_dir not in source.parents or not source.exists():
                raise FileNotFoundError("视频源文件不存在或路径越界")

            await self._update(run, "probing", "读取媒体信息", 0.05, "正在读取时长、分辨率和编码")
            meta = await asyncio.to_thread(probe_video, source)
            video.duration_ms, video.width, video.height, video.fps = (
                meta["duration_ms"],
                meta["width"],
                meta["height"],
                meta["fps"],
            )
            video.metadata.update(meta)
            await self._store.update(video)

            await self._update(
                run,
                "transcribing",
                "语音转写",
                0.12,
                f"本地 Whisper ({self._asr_model}) 正在识别语音",
            )
            # 转写是最耗时步骤，按源文件哈希/对象名缓存，进程意外退出后不必重新计算。
            cache_dir = self._data_dir / "processing-cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_key = getattr(video.source, "sha256", None) or source.stem
            transcript_cache = cache_dir / f"{cache_key}.{self._asr_model}.transcript.json"
            if transcript_cache.exists():
                transcript = json.loads(transcript_cache.read_text(encoding="utf-8"))
            else:
                transcript = await asyncio.to_thread(transcribe, source, self._asr_model)
            # 旧缓存也在此处归一化，因此无需重新跑耗时的 Whisper。
            transcript = [
                {**item, "text": normalize_chinese_text(str(item["text"]))} for item in transcript
            ]
            transcript_cache.write_text(
                json.dumps(transcript, ensure_ascii=False), encoding="utf-8"
            )
            await self._update(
                run, "sampling_frames", "抽取关键帧", 0.62, "正在建立可按时间戳访问的画面索引"
            )
            frame_dir = self._data_dir / "frames" / str(video.id)
            frames = await asyncio.to_thread(
                extract_keyframes, source, frame_dir, video.duration_ms
            )
            await self._update(
                run, "ocr", "识别画面文字", 0.72, f"正在识别 {len(frames)} 张采样画面中的文字"
            )
            ocr_cache = cache_dir / f"{cache_key}.ocr.json"

            def report_ocr_progress(completed: int, total: int) -> None:
                ratio = completed / max(1, total)
                raw_progress = 0.72 + ratio * 0.10
                effective_progress = (
                    0.25 + raw_progress * 0.75
                    if isinstance(video.source, WebSource)
                    else raw_progress
                )
                run.progress = effective_progress
                run.message = f"画面文字 {completed}/{total}，已保存断点"
                run.elapsed_seconds = (
                    (utc_now() - run.started_at).total_seconds() if run.started_at else 0
                )
                self._runs[run.video_id] = run.model_copy(deep=True)

            ocr_items = await asyncio.to_thread(
                run_ocr,
                frames,
                ocr_cache,
                report_ocr_progress,
            )
            speaker_cache = cache_dir / f"{cache_key}.speakers.identity-v4.json"
            speaker_labels: list[str] = []
            if speaker_cache.exists():
                try:
                    speaker_labels = list(json.loads(speaker_cache.read_text(encoding="utf-8")))
                except (json.JSONDecodeError, OSError, TypeError):
                    speaker_labels = []
            if len(speaker_labels) != len(transcript):
                await self._update(
                    run,
                    "diarizing",
                    "区分并命名说话人",
                    0.82,
                    "正在结合音色、自我介绍和画面称呼匹配说话人",
                )
                speaker_labels = await asyncio.to_thread(
                    diarize_speakers, source, transcript, ocr_items
                )
                speaker_cache.write_text(
                    json.dumps(speaker_labels, ensure_ascii=False), encoding="utf-8"
                )
            for item, speaker in zip(transcript, speaker_labels, strict=True):
                item["speaker"] = speaker
            video.metadata["speaker_count"] = len(set(speaker_labels))
            video.metadata["speaker_diarization"] = "acoustic+dialogue+ocr-multiprototype-v4"
            visible_names = " ".join(str(item.get("text", "")) for item in ocr_items)
            video.metadata["ocr_verified_speakers"] = sorted(
                name for name in set(speaker_labels) if name in visible_names
            )

            artifacts: list[TimelineArtifact] = []
            for item in transcript:
                artifacts.append(
                    TimelineArtifact(
                        video_id=video.id,
                        kind=TimelineKind.TRANSCRIPT,
                        time_range=TimeRange(start_ms=item["start_ms"], end_ms=item["end_ms"]),
                        text=item["text"],
                        speaker=item.get("speaker"),
                        confidence=0.9,
                        provenance=Provenance(producer="faster-whisper", model=self._asr_model),
                    )
                )
            for item in ocr_items:
                start = item["timestamp_ms"]
                artifacts.append(
                    TimelineArtifact(
                        video_id=video.id,
                        kind=TimelineKind.OCR,
                        time_range=TimeRange(
                            start_ms=start, end_ms=min(video.duration_ms, start + 30_000)
                        ),
                        text=item["text"],
                        confidence=min(1.0, item["confidence"]),
                        snapshot_key=f"frames/{video.id}/{item['path'].name}",
                        provenance=Provenance(producer="rapidocr", model="onnxruntime"),
                    )
                )

            # LLM 增强失败时仍会保存这些直接证据；先保留在内存中，以便同一次章节调用顺手
            # 修正少量明确的 ASR 错字，避免为字幕审核再付一次模型调用费用。
            direct_artifacts = artifacts
            direct_artifact_count = len(direct_artifacts)
            artifacts = []
            subtitle_correction_count = 0

            await self._update(
                run, "summarizing", "理解与自动分段", 0.84, "正在融合语音与画面文字生成章节"
            )
            if self._llm and transcript:
                # 将每句 ASR 与时间上邻近的 OCR 放在一起，模型才能判断同音专名究竟
                # 应写成哪个字；视频标题和作者只作为领域上下文，不作为改写依据。
                aligned_lines: list[str] = []
                for index, item in enumerate(transcript):
                    midpoint = (int(item["start_ms"]) + int(item["end_ms"])) // 2
                    nearby_ocr = [
                        str(ocr["text"])
                        for ocr in ocr_items
                        if abs(int(ocr["timestamp_ms"]) - midpoint) <= 18_000
                    ][:2]
                    ocr_context = " | ".join(nearby_ocr) if nearby_ocr else "无邻近OCR"
                    aligned_lines.append(
                        f"[index={index} start_ms={item['start_ms']}] "
                        f"speaker={item.get('speaker', 'Speaker ?')} ASR={item['text']} "
                        f"|| 邻近画面文字={ocr_context}"
                    )
                compact = (
                    f"视频标题：{video.title}\n"
                    f"作者/来源：{video.metadata.get('uploader', '未知')}\n"
                    + "\n".join(aligned_lines)
                )
                try:
                    summary = await self._llm.complete_json(
                        system=(
                            "你是视频时间轴策展 Agent。仅依据给定转写和 OCR，输出 JSON："
                            "summary 字符串；chapters 数组，每项含 start_ms、end_ms、title、"
                            "summary；subtitle_corrections 数组，每项含 index、corrected_text、"
                            "reason。字幕修正只处理结合上下文、邻近OCR、标题后非常明确的识别错误，"
                            "最多 60 条；OCR若只是菜单或界面无关文字，不得强行替换字幕；"
                            "不要润色口语、不要改变原意、没有明确错误就返回空数组。不要编造。"
                            'JSON示例：{"summary":"全片概述","chapters":[{"start_ms":0,'
                            '"end_ms":60000,"title":"章节名","summary":"本节解释"}],'
                            '"subtitle_corrections":[]}。章节必须连续覆盖全片，标题体现具体主题。'
                            "若字幕明确声明有N条建议/要点并出现第一、第二等序号，必须为每一条单独分章，"
                            "不得把多个编号合并；角色名和系统名优先采用OCR中的可见写法。"
                        ),
                        user=compact[:100_000],
                        purpose="video_timeline_summary",
                        video_id=str(video.id),
                        max_tokens=12_000,
                        thinking=False,
                    )
                except Exception as exc:
                    # LLM 属于增强步骤，不应让已经成功的媒体处理整体失败。
                    video.metadata["llm_summary_error"] = type(exc).__name__
                    summary = {"summary": "", "chapters": []}
                video.metadata["summary"] = str(summary.get("summary", ""))
                corrections = list(summary.get("subtitle_corrections", []))[:60]
                if not corrections and ocr_items:
                    # 时间轴策展调用需要同时分章和总结，偶尔会忽略字幕修正字段。
                    # 此时才补一次专注的小型审核调用，避免每个视频无条件增加成本。
                    try:
                        review = await self._llm.complete_json(
                            system=(
                                "你是严格的中文字幕审核 Agent。对照每行 ASR、邻近画面OCR、"
                                "视频标题和作者，只修正有充分依据的同音错字、专有名词和繁简体问题。"
                                "OCR可能是无关菜单，不能强行套用；不要润色、补写或改变语序。"
                                "输出JSON：subtitle_corrections数组，每项包含index、corrected_text、"
                                "reason。corrected_text必须是该行修正后的完整字幕。最多60条。"
                                "例如ASR写‘米服’而同一时段OCR清楚写‘弭弗’时可修正；"
                                "没有可靠依据则不修改。"
                            ),
                            user=compact[:100_000],
                            purpose="subtitle_review",
                            video_id=str(video.id),
                            max_tokens=6_000,
                            thinking=False,
                        )
                        corrections = list(review.get("subtitle_corrections", []))[:60]
                        video.metadata["subtitle_review_mode"] = "asr+nearby_ocr+source_context"
                    except Exception as exc:
                        video.metadata["subtitle_review_error"] = type(exc).__name__
                for correction in corrections:
                    try:
                        index = int(correction["index"])
                        corrected = normalize_chinese_text(str(correction["corrected_text"]))
                    except (KeyError, TypeError, ValueError):
                        continue
                    if not 0 <= index < len(transcript) or not corrected:
                        continue
                    original = str(transcript[index]["text"])
                    if corrected == original or len(corrected) > max(80, len(original) * 2):
                        continue
                    transcript[index]["text"] = corrected
                    direct_artifacts[index] = direct_artifacts[index].model_copy(
                        update={
                            "text": corrected,
                            "tags": [*direct_artifacts[index].tags, "llm-reviewed"],
                            "provenance": Provenance(
                                producer="faster-whisper+subtitle-review-agent",
                                model=self._llm.model,
                                prompt_version="context-review-v1",
                            ),
                        }
                    )
                    subtitle_correction_count += 1
                raw_chapters = summary.get("chapters", [])
                spoken_section_count = _spoken_section_count(transcript)
                if spoken_section_count >= 4:
                    expected_chapters = build_fallback_chapters(
                        video_id=video.id,
                        transcript=transcript,
                        duration_ms=video.duration_ms,
                        ocr_items=ocr_items,
                    )
                    expected_starts = [item.time_range.start_ms for item in expected_chapters[1:]]
                    actual_starts: list[int] = []
                    for item in raw_chapters:
                        try:
                            actual_starts.append(int(item.get("start_ms", -1)))
                        except (AttributeError, TypeError, ValueError):
                            continue
                    missing_boundary = any(
                        not actual_starts
                        or min(abs(actual - expected) for actual in actual_starts) > 12_000
                        for expected in expected_starts
                    )
                    if len(raw_chapters) < spoken_section_count or missing_boundary:
                        video.metadata["chapter_validation_error"] = (
                            "missing_explicit_section_boundaries"
                        )
                        raw_chapters = []
                chapter_ends: list[int] = []
                for item in raw_chapters:
                    try:
                        chapter_ends.append(int(item.get("end_ms", 0)))
                    except (AttributeError, TypeError, ValueError):
                        continue
                max_chapter_end = max(chapter_ends, default=0)
                # 防止模型把秒误当毫秒：覆盖不足一半时不发布错误章节。
                if max_chapter_end < video.duration_ms * 0.5:
                    video.metadata["chapter_validation_error"] = "insufficient_time_coverage"
                    raw_chapters = []
                model_chapters = validate_and_normalize_chapters(
                    video_id=video.id,
                    raw_chapters=raw_chapters,
                    duration_ms=video.duration_ms,
                    model_name=self._llm.model,
                    prompt_version="full-transcript-v1",
                )
                if not model_chapters and video.duration_ms >= 10 * 60_000:
                    # 长视频的逐句输入容易超出上下文或产生断裂时间段。第二阶段先压缩为
                    # 完整覆盖的一分钟语义窗口，再按内容形态进行真正的主题聚类。
                    semantic_windows = build_semantic_windows(
                        transcript, ocr_items, video.duration_ms
                    )
                    try:
                        recovery = await self._llm.complete_json(
                            system=(
                                "你是通用视频语义分段 Agent。先判断视频形态，再选择对应的章节单位："
                                "访谈按主持人的问题、追问和嘉宾回答主题；教程按任务步骤；游戏视频按"
                                "目标、关卡和关键事件；Vlog按地点、活动和叙事事件；课程按主题与知识点。"
                                "同时参考语音主题转折、说话人提示、停顿和画面OCR变化。不要按固定时长"
                                "机械切分，不要把寒暄单独成章。输出JSON：video_format、summary、chapters。"
                                "chapters每项包含start_ms、end_ms、title、summary；必须从0开始、按时间"
                                "递增并覆盖到视频结尾。通常4到20章，访谈标题优先写成所讨论的问题。"
                            ),
                            user=(
                                f"视频标题：{video.title}\n时长：{video.duration_ms}ms\n"
                                f"全片语义窗口：\n{semantic_windows}"
                            )[:100_000],
                            purpose="video_chapter_recovery",
                            video_id=str(video.id),
                            max_tokens=10_000,
                            thinking=False,
                        )
                        model_chapters = validate_and_normalize_chapters(
                            video_id=video.id,
                            raw_chapters=recovery.get("chapters", []),
                            duration_ms=video.duration_ms,
                            model_name=self._llm.model,
                            prompt_version="format-aware-recovery-v1",
                        )
                        video.metadata["video_format"] = str(
                            recovery.get("video_format") or "unknown"
                        )
                    except Exception as exc:
                        video.metadata["chapter_recovery_error"] = type(exc).__name__
                if model_chapters:
                    artifacts.extend(model_chapters)
                    video.metadata.pop("chapter_validation_error", None)
                else:
                    video.metadata["chapter_validation_error"] = "semantic_clustering_failed"
            if not any(item.kind is TimelineKind.CHAPTER for item in artifacts):
                artifacts.extend(
                    build_fallback_chapters(
                        video_id=video.id,
                        transcript=transcript,
                        duration_ms=video.duration_ms,
                        ocr_items=ocr_items,
                    )
                )
                video.metadata["chapter_source"] = "deterministic_fallback"
            else:
                video.metadata["chapter_source"] = "timeline_curator_agent"

            representative_frames = curate_representative_frames(
                video_id=video.id,
                frames=frames,
                ocr_items=ocr_items,
                chapters=artifacts,
                duration_ms=video.duration_ms,
            )
            artifacts.extend(representative_frames)
            await self._store.add_many([*direct_artifacts, *artifacts])
            video.status, video.progress, video.current_stage, video.updated_at = (
                VideoStatus.READY,
                1,
                "ready",
                utc_now(),
            )
            video.metadata.update(
                {
                    "transcript_segments": len(transcript),
                    "sampled_frames": len(frames),
                    "ocr_frames": len(ocr_items),
                    "representative_frames": len(representative_frames),
                    "subtitle_corrections": subtitle_correction_count,
                }
            )
            await self._store.update(video)
            run.status, run.finished_at, run.eta_seconds = ProcessingStatus.COMPLETED, utc_now(), 0
            await self._update(
                run,
                "ready",
                "处理完成",
                1,
                f"已生成 {direct_artifact_count + len(artifacts)} 条时间轴证据",
            )
        except Exception as exc:
            if attempt < 2:
                # 可恢复阶段均有断点缓存；自动重试不会重新下载、重新转写或重复已完成 OCR。
                run.status = ProcessingStatus.RUNNING
                run.finished_at = None
                run.error = f"{type(exc).__name__}: {exc}"
                await self._update(
                    run,
                    "auto_retry",
                    "自动恢复",
                    max(0.01, min(run.progress, 0.9)),
                    f"检测到异常，2 秒后自动重试（第 {attempt + 1}/2 次），已完成步骤将复用缓存",
                )
                await asyncio.sleep(2)
                await self._process(run)
                return
            run.status, run.finished_at, run.error = (
                ProcessingStatus.FAILED,
                utc_now(),
                f"{type(exc).__name__}: {exc}",
            )
            run.stage, run.stage_label, run.message = (
                "failed",
                "处理失败",
                "处理失败，请查看错误详情后重试",
            )
            video = await self._store.get(run.video_id)
            if video:
                video.status, video.error_code, video.error_message = (
                    VideoStatus.FAILED,
                    type(exc).__name__,
                    str(exc),
                )
                await self._store.update(video)
            self._runs[run.video_id] = run.model_copy(deep=True)

    async def _import_web_media(self, run: ProcessingRun, video: Any) -> None:
        """下载网页媒体并接回本地处理管线，期间持续暴露真实已下载字节数。"""
        if self._web_downloader is None:
            raise RuntimeError("网页视频下载器尚未配置")
        source = video.source
        if not isinstance(source, WebSource):
            return
        await self._update(
            run,
            "reading_web_metadata",
            "读取网页视频信息",
            0.01,
            "正在连接视频页面",
        )
        metadata = await self._web_downloader.inspect(str(source.original_url))
        video.title = metadata.title
        video.duration_ms = metadata.duration_ms
        video.source = source.model_copy(
            update={"canonical_url": metadata.canonical_url, "extractor": metadata.extractor}
        )
        video.metadata.update(
            {
                "webpage_url": metadata.webpage_url,
                "uploader": metadata.uploader,
                "thumbnail_url": metadata.thumbnail_url,
                "estimated_download_bytes": metadata.estimated_size_bytes,
            }
        )
        await self._store.update(video)

        await self._update(run, "downloading", "下载并合并网页视频", 0.03, "正在获取视频与音频流")
        download_task = asyncio.create_task(
            self._web_downloader.download(
                url=str(source.original_url),
                idempotency_key=str(video.id),
                rights_confirmed=source.rights_confirmed,
            )
        )
        job_dir = self._data_dir / "web-imports" / str(video.id)
        while not download_task.done():
            downloaded = await asyncio.to_thread(_directory_size, job_dir)
            estimated = metadata.estimated_size_bytes
            if estimated:
                fraction = min(0.95, downloaded / estimated)
                progress = 0.03 + fraction * 0.22
                downloaded_mb = downloaded / 1024 / 1024
                estimated_mb = estimated / 1024 / 1024
                detail = f"已下载 {downloaded_mb:.1f} / 约 {estimated_mb:.1f} MB"
            else:
                progress = min(0.22, 0.03 + run.elapsed_seconds / 900)
                detail = f"已下载 {downloaded / 1024 / 1024:.1f} MB，正在等待站点返回总大小"
            await self._update(run, "downloading", "下载并合并网页视频", progress, detail)
            await asyncio.sleep(1)
        downloaded_media = await download_task
        relative_key = downloaded_media.path.relative_to(self._data_dir).as_posix()
        video.source_object_key = relative_key
        video.metadata.update(
            {
                "download_size_bytes": downloaded_media.size_bytes,
                "download_sha256": downloaded_media.sha256,
                "download_reused": downloaded_media.reused,
            }
        )
        await self._store.update(video)
        await self._update(run, "downloaded", "网页视频准备完成", 0.25, "媒体已保存，开始内容理解")


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _spoken_section_count(transcript: list[dict[str, Any]]) -> int:
    numeral_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    ordinals: list[int] = []
    for item in transcript:
        match = re.search(r"第\s*([一二三四五六七八九1-9])", str(item["text"]))
        if match:
            raw = match.group(1)
            ordinals.append(numeral_map.get(raw, int(raw) if raw.isdigit() else 0))
    return max(ordinals, default=0)
