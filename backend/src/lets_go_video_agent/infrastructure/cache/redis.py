from __future__ import annotations

import importlib
import re
import secrets
from types import TracebackType
from typing import Any, Self, cast

import orjson

_NAMESPACE_PATTERN = re.compile(r"^[A-Za-z0-9:_-]{1,80}$")
_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
else
  return 0
end
""".strip()


class RedisCacheError(RuntimeError):
    pass


class LeaseNotAcquiredError(RedisCacheError):
    pass


class RedisCache:
    """带命名空间、大小限制和安全租约释放的 Redis 适配器。"""

    def __init__(
        self,
        *,
        url: str,
        namespace: str = "lets-go-video-agent",
        socket_timeout_seconds: float = 5,
        max_value_bytes: int = 1024 * 1024,
        client: Any | None = None,
    ) -> None:
        if not _NAMESPACE_PATTERN.fullmatch(namespace):
            raise ValueError("Redis namespace 含有非法字符")
        if max_value_bytes <= 0:
            raise ValueError("max_value_bytes 必须大于 0")
        self._namespace = namespace
        self._max_value_bytes = max_value_bytes
        self._client = client or _build_redis_client(
            url=url,
            socket_timeout_seconds=socket_timeout_seconds,
        )

    async def set_json(
        self,
        key: str,
        value: object,
        *,
        ttl_seconds: int,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds 必须大于 0")
        try:
            payload = orjson.dumps(value)
        except (TypeError, orjson.JSONEncodeError) as exc:
            raise ValueError("缓存值必须可以序列化为 JSON") from exc
        if len(payload) > self._max_value_bytes:
            raise RedisCacheError("缓存值超过配置的大小上限")
        await self._client.set(self._key(f"cache:{key}"), payload, ex=ttl_seconds)

    async def get_json(self, key: str) -> object | None:
        payload = await self._client.get(self._key(f"cache:{key}"))
        if payload is None:
            return None
        if not isinstance(payload, (bytes, bytearray, str)):
            raise RedisCacheError("Redis 返回了无法识别的缓存类型")
        if len(payload) > self._max_value_bytes:
            raise RedisCacheError("缓存值超过配置的大小上限")
        try:
            return cast(object, orjson.loads(payload))
        except orjson.JSONDecodeError as exc:
            raise RedisCacheError("Redis 中的 JSON 缓存已损坏") from exc

    async def delete(self, key: str) -> None:
        await self._client.delete(self._key(f"cache:{key}"))

    async def claim_once(self, key: str, *, ttl_seconds: int) -> bool:
        """在 TTL 内只允许首个调用者认领幂等键。

        该原语适合短任务的去重标记；长视频任务应使用 ``lease`` 并定期续约，或
        依赖 Temporal workflow id。不能把过短 TTL 当作永久分布式锁。
        """

        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds 必须大于 0")
        result = await self._client.set(
            self._key(f"once:{key}"),
            b"1",
            ex=ttl_seconds,
            nx=True,
        )
        return bool(result)

    def lease(self, key: str, *, ttl_seconds: int) -> RedisLease:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds 必须大于 0")
        return RedisLease(
            client=self._client,
            key=self._key(f"lease:{key}"),
            ttl_seconds=ttl_seconds,
        )

    async def ping(self) -> None:
        await self._client.ping()

    async def close(self) -> None:
        close = getattr(self._client, "aclose", None)
        if close is None:
            close = getattr(self._client, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result

    def _key(self, raw_key: str) -> str:
        if not raw_key or len(raw_key) > 512:
            raise ValueError("Redis key 长度无效")
        if any(ord(character) < 32 for character in raw_key):
            raise ValueError("Redis key 不能包含控制字符")
        return f"{self._namespace}:{raw_key}"


class RedisLease:
    """使用随机令牌防止一个 Worker 误删另一个 Worker 的新租约。"""

    def __init__(
        self,
        *,
        client: Any,
        key: str,
        ttl_seconds: int,
    ) -> None:
        self._client = client
        self._key = key
        self._ttl_seconds = ttl_seconds
        self._token = secrets.token_urlsafe(24)
        self.acquired = False

    async def acquire(self) -> bool:
        result = await self._client.set(
            self._key,
            self._token,
            ex=self._ttl_seconds,
            nx=True,
        )
        self.acquired = bool(result)
        return self.acquired

    async def release(self) -> None:
        if not self.acquired:
            return
        # GET 后再 DEL 会有竞态：租约过期并被他人获得时，旧持有者会误删新租约。
        # Lua 在 Redis 内原子比较令牌并删除，确保释放动作只影响自己。
        await self._client.eval(_RELEASE_SCRIPT, 1, self._key, self._token)
        self.acquired = False

    async def __aenter__(self) -> Self:
        if not await self.acquire():
            raise LeaseNotAcquiredError(f"未获得 Redis 租约: {self._key}")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.release()


def _build_redis_client(*, url: str, socket_timeout_seconds: float) -> Any:
    module = importlib.import_module("redis.asyncio")
    return module.Redis.from_url(
        url,
        decode_responses=False,
        socket_connect_timeout=socket_timeout_seconds,
        socket_timeout=socket_timeout_seconds,
        health_check_interval=30,
    )
