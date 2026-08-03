from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from lets_go_video_agent.application.errors import UnsafeSourceUrlError


class SourceUrlPolicy:
    """URL 导入入口的第一道 SSRF 防线。

    这里先校验协议和显式主机；真正下载前，下载器还必须解析 DNS、逐次检查重定向，
    并在连接地址变化时再次拦截私网。只在 API 层做一次字符串检查是不够的。
    """

    allowed_schemes = frozenset({"http", "https"})
    forbidden_hostnames = frozenset({"localhost", "localhost.localdomain"})

    def validate(self, raw_url: str) -> str:
        parts = urlsplit(raw_url)
        if parts.scheme.lower() not in self.allowed_schemes:
            raise UnsafeSourceUrlError("只允许 http 或 https 视频来源")
        if parts.username or parts.password:
            raise UnsafeSourceUrlError("来源 URL 不允许包含用户凭据")
        hostname = (parts.hostname or "").lower().rstrip(".")
        if not hostname:
            raise UnsafeSourceUrlError("来源 URL 缺少主机名")
        if hostname in self.forbidden_hostnames or hostname.endswith(".local"):
            raise UnsafeSourceUrlError("不允许访问本机或局域网主机")

        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            # 域名的 DNS 解析结果在真正建立连接前再次验证，防止 DNS rebinding。
            if "." not in hostname:
                raise UnsafeSourceUrlError("不允许访问单标签内部域名") from None
        else:
            if not address.is_global:
                raise UnsafeSourceUrlError("不允许访问私网、回环或保留 IP")
        return raw_url
