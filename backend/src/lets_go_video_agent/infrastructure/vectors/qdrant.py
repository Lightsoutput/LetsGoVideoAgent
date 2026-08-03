from __future__ import annotations

import importlib
import math
from collections.abc import Mapping, Sequence
from typing import Any, cast
from uuid import UUID

from pydantic import Field, model_validator

from lets_go_video_agent.domain.common import DomainModel, TimeRange


class VectorPoint(DomainModel):
    """写入 Qdrant 的最小证据向量。"""

    id: UUID
    video_id: UUID
    embedding: list[float] = Field(min_length=1)
    text: str
    kind: str
    time_range: TimeRange
    payload: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_finite_embedding(self) -> VectorPoint:
        if not all(math.isfinite(value) for value in self.embedding):
            raise ValueError("向量不能包含 NaN 或无穷值")
        return self


class VectorSearchHit(DomainModel):
    id: str
    score: float
    video_id: UUID
    text: str
    kind: str
    time_range: TimeRange
    payload: dict[str, object] = Field(default_factory=dict)


class QdrantVectorStore:
    """Qdrant 的异步生产适配器。

    Client 与 models 模块均可注入，因此单元测试不需要启动 Qdrant；生产环境才
    延迟加载可选依赖。相同 point id 的 upsert 是幂等覆盖，Temporal Activity
    重试不会制造重复向量。
    """

    _distance_names = frozenset({"cosine", "dot", "euclid", "manhattan"})

    def __init__(
        self,
        *,
        url: str,
        collection: str,
        vector_size: int,
        distance: str = "cosine",
        request_timeout_seconds: float = 10,
        batch_size: int = 128,
        client: Any | None = None,
        models_module: Any | None = None,
    ) -> None:
        if vector_size <= 0:
            raise ValueError("vector_size 必须大于 0")
        normalized_distance = distance.lower()
        if normalized_distance not in self._distance_names:
            raise ValueError(f"不支持的距离函数: {distance}")
        if not 1 <= batch_size <= 256:
            raise ValueError("batch_size 必须位于 1 到 256 之间")
        if not collection or len(collection) > 255:
            raise ValueError("Qdrant collection 名称无效")

        self._collection = collection
        self._vector_size = vector_size
        self._distance = normalized_distance
        self._batch_size = batch_size
        self._models = models_module or _load_qdrant_models()
        self._client = client or _build_client(
            url=url,
            timeout_seconds=request_timeout_seconds,
        )

    async def ensure_collection(self) -> None:
        if bool(await self._client.collection_exists(collection_name=self._collection)):
            return
        distance_value = getattr(self._models.Distance, self._distance.upper())
        vectors_config = self._models.VectorParams(
            size=self._vector_size,
            distance=distance_value,
        )
        try:
            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config=vectors_config,
            )
        except Exception:
            # 多个 Worker 可能同时初始化 collection。只有在再次确认仍不存在时才
            # 抛错，避免正常的“已被其他 Worker 创建”竞态导致启动失败。
            if not bool(await self._client.collection_exists(collection_name=self._collection)):
                raise

    async def upsert(self, points: Sequence[VectorPoint]) -> int:
        if not points:
            return 0
        await self.ensure_collection()
        for point in points:
            self._validate_vector(point.embedding)

        total = 0
        for start in range(0, len(points), self._batch_size):
            chunk = points[start : start + self._batch_size]
            wire_points = [
                self._models.PointStruct(
                    id=str(point.id),
                    vector=point.embedding,
                    payload=self._payload_for(point),
                )
                for point in chunk
            ]
            await self._client.upsert(
                collection_name=self._collection,
                points=wire_points,
                wait=True,
            )
            total += len(chunk)
        return total

    async def search(
        self,
        *,
        embedding: Sequence[float],
        video_id: UUID,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> list[VectorSearchHit]:
        self._validate_vector(embedding)
        if not 1 <= limit <= 100:
            raise ValueError("limit 必须位于 1 到 100 之间")
        query_filter = self._video_filter(video_id)
        response = await self._client.query_points(
            collection_name=self._collection,
            query=list(embedding),
            query_filter=query_filter,
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
            with_vectors=False,
        )
        raw_points = getattr(response, "points", response)
        if not isinstance(raw_points, Sequence):
            raise RuntimeError("Qdrant 返回了无法识别的查询结果")
        return [self._parse_hit(item) for item in cast(Sequence[object], raw_points)]

    async def delete_video(self, video_id: UUID) -> None:
        await self._client.delete(
            collection_name=self._collection,
            points_selector=self._models.FilterSelector(
                filter=self._video_filter(video_id),
            ),
            wait=True,
        )

    async def ping(self) -> None:
        await self._client.get_collections()

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            await close()

    def _validate_vector(self, embedding: Sequence[float]) -> None:
        if len(embedding) != self._vector_size:
            raise ValueError(f"向量维度应为 {self._vector_size}，实际为 {len(embedding)}")
        if not all(math.isfinite(value) for value in embedding):
            raise ValueError("向量不能包含 NaN 或无穷值")

    @staticmethod
    def _payload_for(point: VectorPoint) -> dict[str, object]:
        # 可信字段最后覆盖扩展 payload，防止调用方伪造 video_id 或时间锚点，
        # 进而让检索结果越过视频租户边界。
        return {
            **point.payload,
            "video_id": str(point.video_id),
            "text": point.text,
            "kind": point.kind,
            "start_ms": point.time_range.start_ms,
            "end_ms": point.time_range.end_ms,
        }

    def _video_filter(self, video_id: UUID) -> object:
        return self._models.Filter(
            must=[
                self._models.FieldCondition(
                    key="video_id",
                    match=self._models.MatchValue(value=str(video_id)),
                )
            ]
        )

    @staticmethod
    def _parse_hit(raw: object) -> VectorSearchHit:
        payload_value = getattr(raw, "payload", None)
        if not isinstance(payload_value, Mapping):
            raise RuntimeError("Qdrant 命中结果缺少 payload")
        payload = {str(key): value for key, value in payload_value.items()}
        try:
            video_id = UUID(str(payload.pop("video_id")))
            text = str(payload.pop("text"))
            kind = str(payload.pop("kind"))
            time_range = TimeRange(
                start_ms=int(str(payload.pop("start_ms"))),
                end_ms=int(str(payload.pop("end_ms"))),
            )
            score = float(str(getattr(raw, "score", None)))
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Qdrant 命中结果的证据字段无效") from exc
        return VectorSearchHit(
            id=str(getattr(raw, "id", None)),
            score=score,
            video_id=video_id,
            text=text,
            kind=kind,
            time_range=time_range,
            payload=payload,
        )


def _load_qdrant_models() -> Any:
    return importlib.import_module("qdrant_client.models")


def _build_client(*, url: str, timeout_seconds: float) -> Any:
    module = importlib.import_module("qdrant_client")
    return module.AsyncQdrantClient(url=url, timeout=timeout_seconds)
