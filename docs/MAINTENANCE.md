# LetsGoVideoAgent 维护文档

## 1. 文档目的

本文用于记录项目结构、已落地能力、近期任务、运行维护方式和主要风险。每次较大的架构、模型、数据结构或部署方式变更后，应同步更新本文。

## 2. 项目结构

```text
LetsGoVideoAgent/
├─ backend/                  FastAPI、Agent、媒体处理和基础设施
│  ├─ src/lets_go_video_agent/
│  │  ├─ agents/            LangGraph、多 Agent 角色、Harness 和工具
│  │  ├─ api/               HTTP API
│  │  ├─ application/       用例与端口
│  │  ├─ domain/            视频、时间轴、问答等领域模型
│  │  ├─ infrastructure/    模型、搜索、数据库和对象存储适配器
│  │  ├─ mcp/               Search MCP Server
│  │  └─ media/             下载、ASR、OCR、抽帧和本地处理流水线
│  └─ tests/                单元与集成测试
├─ frontend/                Next.js + TypeScript 用户界面
├─ data/                    本地媒体、缓存、帧和成本记录，不提交 Git
├─ docs/                    需求、架构与维护文档
├─ evals/                   Agent/视频理解评测数据
├─ infra/                   SearXNG 等基础设施配置
├─ extensions/              MCP 等外部接入描述
├─ scripts/                 启动、评测和维护脚本
├─ var/logs/                运行日志，统一存放且不提交 Git
└─ compose.yaml             容器编排
```

## 3. 已落地能力

- 支持本地上传和网页视频导入，B 站下载由 yt-dlp 负责。
- 使用 Faster-Whisper 转写语音，并优先读取可下载的原站 VTT/SRT 字幕。
- 使用 OCR、说话人分析和 Qwen3-VL 画面理解构建多轨时间轴。
- 使用 DeepSeek 生成视频概述、语义章节、快捷问答和字幕审校结果。
- 当前帧问答按精确时间戳抽帧，再交给 VLM；网络失败时仅对同一帧做 OCR 降级。
- QA 使用 LangGraph 的“调查—验证—补充检索”流程。
- 自研 Agent Harness 控制步骤、工具权限、超时、重复调用、Token 和费用。
- SearXNG 搜索已封装为 MCP，提供搜索、术语核验和健康检查工具。
- 前端提供视频预览、字幕、章节、代表帧、多轨时间轴和证据回放。
- 模型调用成本以人民币记录到 `data/costs/model-usage.jsonl`。

## 4. 当前待办

1. 将开发环境的内存仓库完整切换为 MySQL，避免后端重启后视频记录丢失。
2. 完成 Search MCP 容器镜像构建与稳定启动；Docker Hub 网络不可用时提供镜像源方案。
3. 为当前帧问答增加集成测试，验证“截图、VLM 输入、证据时间戳”完全一致。
4. 建立字幕、章节边界、摘要事实一致性、说话人和关键帧去重的评测集。
5. 将通用 Prompt 集中版本管理；垂类规则通过 Skill 注入，不写入基础 Prompt。
6. 增加任务队列、断点恢复和失败重试的持久化状态。

## 5. 维护约定

### 日志

- 所有服务日志写入 `var/logs/<service>/`，不得写在项目根目录。
- 日志文件建议命名为 `<service>.<date>.out.log` 和 `<service>.<date>.err.log`。
- 默认保留 14 天。先预览再清理：

```powershell
.\scripts\cleanup-logs.ps1 -RetentionDays 14 -WhatIf
.\scripts\cleanup-logs.ps1 -RetentionDays 14
```

可使用 Windows 任务计划程序每天执行一次清理脚本。日志清理只针对 `var/logs`，不会删除视频、缓存或模型。

### 外部 API 网络

- 本机直连 HTTPS 被限制时，通过 `.env` 的 `OUTBOUND_HTTP_PROXY` 配置统一出站代理。
- 当前本机 Clash HTTP 代理为 `http://127.0.0.1:7890`；更换代理软件或端口后必须同步修改。
- SiliconFlow 与 DeepSeek 共用该配置；SearXNG 等本地地址不经过代理。
- 排查顺序：代理端口监听 → `/v1/models` 连通 → 单帧 VLM smoke test → DeepSeek JSON smoke test → 浏览器问答。

### 代码和文件

- API、领域模型、基础设施适配器和 Agent 角色保持分层，不从 Agent 直接访问 Shell 或数据库。
- 新运行时文件应进入 `data/`、`var/` 或 `artifacts/`，不能堆放在根目录。
- 新密钥只写 `.env`，不得写进源码、日志、文档或 Git。
- 修改 Prompt、缓存格式或模型输出结构时，递增 Prompt/缓存版本并补充测试。
- 提交前至少执行 Ruff、MyPy、Pytest、前端 TypeScript 和 ESLint 检查。

## 6. 主要风险

- **数据丢失**：当前默认使用内存仓库，重启后记录消失；应优先完成 MySQL 持久化。
- **外部 API 不稳定**：硅基流动、DeepSeek 或搜索网络异常会影响增强能力；必须保留超时、重试、降级和明确提示。
- **证据错位**：抽帧时间、VLM 输入、截图 URL 和回答证据必须使用同一时间戳，禁止用邻近旧证据冒充当前帧。
- **识别误差传播**：字幕、OCR 或视觉理解错误会继续影响章节与问答；需要来源优先级、术语核验和评测集。
- **成本失控**：逐帧 VLM 和多次 LLM 审校成本较高；应通过代表帧、缓存、Harness 预算和成本告警控制。
- **版权与隐私**：网页下载必须确认使用权；上传视频、字幕、截图和日志可能包含敏感内容。

## 7. 建议的更新流程

```text
提出问题 → 建立可复现样例 → 定位所属层 → 通用修复 → 添加测试
→ 更新缓存/Prompt版本 → 跑完整检查 → 更新本维护文档
```

避免针对单个视频不断增加关键词或 Prompt 特例。确有垂类需求时，应新增 Skill，并保证通用流程仍可独立工作。
