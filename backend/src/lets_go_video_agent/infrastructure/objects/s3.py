from __future__ import annotations

import asyncio
import hashlib
import importlib
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import Field

from lets_go_video_agent.domain.common import DomainModel


class ObjectStoreError(RuntimeError):
    pass


class ObjectConflictError(ObjectStoreError):
    """相同 object key 已经指向不同内容。"""


class ObjectNotFoundError(ObjectStoreError):
    pass


class StoredObject(DomainModel):
    key: str
    size_bytes: int = Field(ge=0)
    sha256: str
    etag: str | None = None
    reused: bool = False


class S3ObjectStore:
    """兼容 AWS S3 与 MinIO 的对象存储适配器。

    object key 始终是逻辑 POSIX 路径，不能包含 ``..`` 或绝对路径。相同 key
    与相同 SHA-256 会直接复用；相同 key 指向不同内容时默认拒绝覆盖，防止重试
    或并发任务悄悄改写证据来源。
    """

    def __init__(
        self,
        *,
        bucket: str,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        secure: bool = True,
        region: str = "us-east-1",
        prefix: str = "",
        max_object_bytes: int = 2 * 1024 * 1024 * 1024,
        request_timeout_seconds: float = 30,
        client: Any | None = None,
    ) -> None:
        if not bucket.strip():
            raise ValueError("S3 bucket 不能为空")
        if max_object_bytes <= 0:
            raise ValueError("max_object_bytes 必须大于 0")
        self._bucket = bucket
        self._prefix = _validate_prefix(prefix)
        self._max_object_bytes = max_object_bytes
        self._client = client or _build_s3_client(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            region=region,
            timeout_seconds=request_timeout_seconds,
        )

    async def ensure_bucket(self) -> None:
        try:
            await self._call(self._client.head_bucket, Bucket=self._bucket)
            return
        except Exception as exc:
            if not _is_not_found(exc):
                raise ObjectStoreError("检查对象存储 bucket 失败") from exc
        try:
            await self._call(self._client.create_bucket, Bucket=self._bucket)
        except Exception as exc:
            # 与 Qdrant 初始化相同，允许另一 Worker 在竞态窗口内先创建 bucket。
            try:
                await self._call(self._client.head_bucket, Bucket=self._bucket)
            except Exception:
                raise ObjectStoreError("创建对象存储 bucket 失败") from exc

    async def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        overwrite: bool = False,
    ) -> StoredObject:
        if len(data) > self._max_object_bytes:
            raise ObjectStoreError("对象超过配置的大小上限")
        digest = hashlib.sha256(data).hexdigest()
        full_key = self._key(key)
        existing = await self._head(full_key)
        reusable = self._reuse_or_reject(
            existing=existing,
            key=full_key,
            size_bytes=len(data),
            sha256=digest,
            overwrite=overwrite,
        )
        if reusable is not None:
            return reusable

        try:
            response = await self._call(
                self._client.put_object,
                Bucket=self._bucket,
                Key=full_key,
                Body=data,
                ContentLength=len(data),
                ContentType=content_type,
                Metadata={"sha256": digest},
            )
        except Exception as exc:
            raise ObjectStoreError(f"上传对象失败: {full_key}") from exc
        return StoredObject(
            key=full_key,
            size_bytes=len(data),
            sha256=digest,
            etag=_etag(response),
        )

    async def put_file(
        self,
        *,
        key: str,
        source: Path,
        content_type: str = "application/octet-stream",
        overwrite: bool = False,
    ) -> StoredObject:
        resolved, size_bytes = await asyncio.to_thread(_resolve_source_file, source)
        if size_bytes > self._max_object_bytes:
            raise ObjectStoreError("对象超过配置的大小上限")
        digest = await asyncio.to_thread(_sha256_file, resolved)
        full_key = self._key(key)
        existing = await self._head(full_key)
        reusable = self._reuse_or_reject(
            existing=existing,
            key=full_key,
            size_bytes=size_bytes,
            sha256=digest,
            overwrite=overwrite,
        )
        if reusable is not None:
            return reusable

        try:
            await self._call(
                self._client.upload_file,
                str(resolved),
                self._bucket,
                full_key,
                ExtraArgs={
                    "ContentType": content_type,
                    "Metadata": {"sha256": digest},
                },
            )
        except Exception as exc:
            raise ObjectStoreError(f"上传对象失败: {full_key}") from exc
        head = await self._head(full_key)
        return StoredObject(
            key=full_key,
            size_bytes=size_bytes,
            sha256=digest,
            etag=_etag(head),
        )

    async def get_bytes(self, key: str, *, max_bytes: int | None = None) -> bytes:
        full_key = self._key(key)
        effective_limit = min(max_bytes or self._max_object_bytes, self._max_object_bytes)
        head = await self._head(full_key)
        if head is None:
            raise ObjectNotFoundError(full_key)
        content_length = _content_length(head)
        if content_length is not None and content_length > effective_limit:
            raise ObjectStoreError("对象超过本次读取上限")

        try:
            response = await self._call(
                self._client.get_object,
                Bucket=self._bucket,
                Key=full_key,
            )
            body = response["Body"]
            data = await asyncio.to_thread(body.read, effective_limit + 1)
            close = getattr(body, "close", None)
            if close is not None:
                close()
        except Exception as exc:
            raise ObjectStoreError(f"读取对象失败: {full_key}") from exc
        if not isinstance(data, bytes):
            raise ObjectStoreError("对象存储返回了非字节内容")
        if len(data) > effective_limit:
            raise ObjectStoreError("对象超过本次读取上限")
        return data

    async def exists(self, key: str) -> bool:
        return await self._head(self._key(key)) is not None

    async def presign_get(self, key: str, *, expires_seconds: int = 900) -> str:
        if not 60 <= expires_seconds <= 86_400:
            raise ValueError("签名 URL 有效期必须位于 60 到 86400 秒之间")
        full_key = self._key(key)
        if await self._head(full_key) is None:
            raise ObjectNotFoundError(full_key)
        result = await self._call(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self._bucket, "Key": full_key},
            ExpiresIn=expires_seconds,
        )
        if not isinstance(result, str):
            raise ObjectStoreError("对象存储未返回有效签名 URL")
        return result

    async def delete(self, key: str) -> None:
        full_key = self._key(key)
        try:
            await self._call(
                self._client.delete_object,
                Bucket=self._bucket,
                Key=full_key,
            )
        except Exception as exc:
            raise ObjectStoreError(f"删除对象失败: {full_key}") from exc

    async def ping(self) -> None:
        await self._call(self._client.head_bucket, Bucket=self._bucket)

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            await asyncio.to_thread(close)

    async def _head(self, full_key: str) -> Mapping[str, object] | None:
        try:
            response = await self._call(
                self._client.head_object,
                Bucket=self._bucket,
                Key=full_key,
            )
        except Exception as exc:
            if _is_not_found(exc):
                return None
            raise ObjectStoreError(f"检查对象失败: {full_key}") from exc
        if not isinstance(response, Mapping):
            raise ObjectStoreError("对象存储 head_object 响应无效")
        return {str(key): value for key, value in response.items()}

    @staticmethod
    def _reuse_or_reject(
        *,
        existing: Mapping[str, object] | None,
        key: str,
        size_bytes: int,
        sha256: str,
        overwrite: bool,
    ) -> StoredObject | None:
        if existing is None:
            return None
        metadata_value = existing.get("Metadata")
        metadata = metadata_value if isinstance(metadata_value, Mapping) else {}
        existing_sha = str(metadata.get("sha256", ""))
        existing_size = _content_length(existing)
        if existing_sha == sha256 and existing_size == size_bytes:
            return StoredObject(
                key=key,
                size_bytes=size_bytes,
                sha256=sha256,
                etag=_etag(existing),
                reused=True,
            )
        if not overwrite:
            raise ObjectConflictError(f"object key 已存在且内容不同: {key}")
        return None

    def _key(self, raw_key: str) -> str:
        validated = _validate_object_key(raw_key)
        return f"{self._prefix}/{validated}" if self._prefix else validated

    @staticmethod
    async def _call(function: Any, *args: object, **kwargs: object) -> Any:
        return await asyncio.to_thread(function, *args, **kwargs)


def _validate_prefix(prefix: str) -> str:
    normalized = prefix.strip("/")
    return _validate_object_key(normalized) if normalized else ""


def _validate_object_key(raw_key: str) -> str:
    if not raw_key or len(raw_key) > 1_024:
        raise ValueError("object key 长度无效")
    if "\\" in raw_key or "\x00" in raw_key or raw_key.startswith("/"):
        raise ValueError("object key 必须是安全的相对 POSIX 路径")
    path = PurePosixPath(raw_key)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("object key 不能包含空段、. 或 ..")
    return path.as_posix()


def _build_s3_client(
    *,
    endpoint: str | None,
    access_key: str | None,
    secret_key: str | None,
    secure: bool,
    region: str,
    timeout_seconds: float,
) -> Any:
    boto3 = importlib.import_module("boto3")
    config_module = importlib.import_module("botocore.config")
    endpoint_url = endpoint
    if endpoint_url and "://" not in endpoint_url:
        endpoint_url = f"{'https' if secure else 'http'}://{endpoint_url}"
    config = config_module.Config(
        connect_timeout=timeout_seconds,
        read_timeout=timeout_seconds,
        retries={"max_attempts": 3, "mode": "standard"},
        s3={"addressing_style": "path"},
    )
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        use_ssl=secure,
        region_name=region,
        config=config,
    )


def _is_not_found(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if not isinstance(response, Mapping):
        return False
    error = response.get("Error")
    if not isinstance(error, Mapping):
        return False
    return str(error.get("Code")) in {"404", "NoSuchKey", "NoSuchBucket", "NotFound"}


def _content_length(response: Mapping[str, object]) -> int | None:
    value = response.get("ContentLength")
    try:
        return int(str(value)) if value is not None else None
    except ValueError:
        return None


def _etag(response: object) -> str | None:
    if not isinstance(response, Mapping):
        return None
    value = response.get("ETag")
    return str(value).strip('"') if value else None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_source_file(source: Path) -> tuple[Path, int]:
    resolved = source.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"待上传文件不存在: {resolved}")
    return resolved, resolved.stat().st_size
