# Spec 001：P0 Foundation 可运行垂直切片

## 背景

LetsGoVideoAgent 的最终目标是理解通用视频的语音、文字、画面和时序事件。
本 Spec 先冻结一个无付费 API、无第三方版权素材也可验证的工程主干，
使媒体算法、模型 Provider 和垂类 Skill 能在同一契约上演进。

## 必须满足

1. Next.js/TypeScript 与 FastAPI/Python 前后端分离。
2. 视频、时间轴、证据、问题、回答与 Agent Run 不依赖具体框架。
3. 支持 global、range、moment 和 frame 四种问答范围。
4. 确定回答必须包含 Evidence ID、时间戳和可选截图。
5. Harness 统一工具白名单、参数校验、超时、预算、循环防护和 Trace。
6. 分离 Planner、Curator、Investigator 和 Verifier；当前主路径运行后两者。
7. MySQL、Qdrant、S3、Redis、LiteLLM、FFmpeg、yt-dlp 与 Temporal 不泄漏到领域层。
8. 远程下载默认关闭且需权利确认；阻止私网地址、路径穿越和 Shell 注入。
9. 提供 Ruff、Mypy、Pytest、ESLint、TypeScript、Vitest、Playwright 和 CI 门禁。

## 非目标

- 不声称已完成任意真实视频的 ASR、说话人分离、OCR、镜头检测或 VLM。
- 不绕过登录、DRM、付费墙、地域或站点访问控制。
- 不引入 AutoGPT 式无界自治循环，不为简历关键词叠加 CrewAI。
- 不在 CI 中下载 B 站视频或调用付费模型。

## 验收

以 [acceptance.md](./acceptance.md) 为执行清单，以
`docs/roadmap/p0-status.md` 区分已实现、已提供适配器和未实现能力。
