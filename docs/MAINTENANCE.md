# LetsGoVideoAgent 维护与版本路线

> 文档状态：2026-08-13 更新
> 当前产品基线：v1.0 功能基本完成，进入 v1.1 规划与开发
> 代码包内部版本仍为 `0.1.0`，发布 v1.1 前应统一调整前后端版本号。

## 1. 文档用途

本文是项目的权威维护入口，用于回答五个问题：

1. 当前系统真正实现了什么；
2. 哪些能力仍是规划、骨架或可选适配器；
3. Agent、模型、算法、MCP、Harness 和 Skill 如何分工；
4. v1.1 为什么开发、按什么顺序开发、怎样验收；
5. 如何启动、测试、查看 API、维护数据和排查风险。

较大的领域模型、Agent 图、模型路由、Skill Schema、API、数据库、部署和评测变更必须同步更新本文。历史需求见 `docs/requirements/`，架构细节见 `docs/architecture/`，不要再把阶段开发日志不断追加到本文末尾。

## 2. 版本定位

### 2.1 v1.0：通用视频理解基础版

v1.0 的主线是“先把一个通用视频看懂并能解释”：

- 导入本地或网页视频；
- 对语音、字幕、画面、OCR、说话人和时间关系进行处理；
- 生成总览、层级章节、代表画面、多轨时间轴和快捷理解内容；
- 支持全视频、片段、时刻和当前帧问答；
- 将处理、问答、模型、工具、MCP、成本和失败状态纳入 Trace；
- 划分稳定的 Agent 身份与职责，并由 Harness 提供运行护栏；
- 提供多样本垂类项目和 Skill 草案生成、修改、发布、绑定、回滚及删除的基础闭环。

v1.0 不代表所有识别和理解指标已经达到生产级，也不代表任务队列、评测门禁和团队权限已经完备。它代表产品主流程与 Agent/Skill 架构已经成立，可以在此基础上进入垂类效果优化。

### 2.2 v1.1：垂类 Skill 效果与创作闭环

v1.1 的主线从“能够生成 Skill”升级为“能证明 Skill 让新视频理解得更好，并能在其约束下生成新脚本”：

```text
垂类项目与样本
  → 样本质量分析和代表性选择
  → 生成独立 Skill v1 草案
  → 人工修改形成同一 Skill 的 v2/v3
  → 使用未参与生成的新视频作为保留集
  → 通用基线与 Skill 增强双路运行
  → 比较理解质量、证据、延迟和成本
  → 达标后发布；退化则拒绝发布或回滚
  → 选择已发布 Skill + 一句创意/粗略思路
  → 生成结构提案、完整脚本、分镜建议和质量评估
  → 人工修改形成脚本 v2/v3 并导出
```

v1.1 不应通过向通用 Prompt 增加特定 UP 主、游戏角色或单个视频的特例来提高分数。领域知识必须进入 Skill，通用流程仍需独立可用。

脚本草案是独立的版本化产物，不写回 Skill 本体；Skill 只提供类别知识、术语、结构、视觉规律和验证规则。详细需求见 [V1.1_SCRIPT_STUDIO.md](requirements/V1.1_SCRIPT_STUDIO.md)。

## 3. 系统结构

```text
LetsGoVideoAgent/
├─ backend/
│  ├─ src/lets_go_video_agent/
│  │  ├─ agents/          Agent 注册表、LangGraph、角色、Harness、工具
│  │  ├─ api/             FastAPI 路由、请求/响应 Schema
│  │  ├─ application/     视频、问答、Skill、垂类项目等应用服务
│  │  ├─ domain/          视频、时间轴、语义、Trace、成本、Skill 领域模型
│  │  ├─ infrastructure/  MySQL、模型、搜索、成本等适配器
│  │  ├─ media/           yt-dlp、ASR、OCR、抽帧、处理流水线
│  │  ├─ mcp/             SearXNG Search MCP Server
│  │  └─ evaluation/      离线评测入口
│  ├─ migrations/         Alembic 数据库迁移
│  └─ tests/              单元和 API 集成测试
├─ frontend/              Next.js + React + TypeScript 工作台
├─ videos/                本地媒体库，不提交 Git
├─ data/                  开发态目录、缓存和兼容成本记录；新任务按生命周期规范命名
├─ skills/generated/      人工发布后的 Skill 版本产物
├─ evals/                 数据集描述和评测报告
├─ docs/                  维护、架构、API、数据生命周期、成本、安全和需求文档
├─ infra/                 SearXNG 等基础设施配置
├─ scripts/               一键启动、搜索服务和日志维护脚本
├─ var/logs/              统一运行日志，不提交 Git
├─ compose.yaml           可选基础设施编排
└─ start-all.cmd          Windows 一键启动入口
```

## 4. v1.0 已完成内容

### 4.1 视频接入和媒体处理

- 支持本地上传、网页链接登记与 B 站视频下载，使用 `yt-dlp` 获取媒体和可用字幕。
- 下载视频统一存入根目录 `videos/`，服务启动时递归扫描并幂等登记，避免每次重下。
- 支持 PyAV/FFmpeg 媒体探测、音轨处理、按时间戳精确抽帧和截图访问。
- 使用 Faster-Whisper 本地 ASR、RapidOCR 本地 OCR，并使用 OpenCC 将识别结果统一为简体中文。
- 同一视频的音频转写与视觉采样并行；视觉采样后 OCR 与 VLM 并行，再进入融合、说话人和时间轴阶段。
- 处理任务具备阶段进度、Trace ID、尝试次数、错误信息和部分自动重试。

### 4.2 多模态理解和交互

- 构建字幕、说话人、画面、OCR、章节、代表帧等多轨时间轴，并与播放器播放头同步。
- 生成视频总览、大节/小节、片段摘要、关键结论、代表帧和快捷问题。
- 代表帧使用变化、语义覆盖和去重逻辑筛选，避免所有轻微变化都成为关键帧。
- 当前帧问答使用目标时间戳重新抽取真实图片，VLM 失败时只对同帧做明确降级。
- 问答支持 `global`、`range`、`moment`、`frame` 四种目标，答案尽量携带时间戳、截图或文本证据。
- 联网补充由用户显式勾选；勾选后必须真正调用搜索，网页来源与视频内部证据分开显示。

### 4.3 Agent、工作流和 Harness

- 全局 Agent 注册表已统一 A00–A12 的编号、名称和职责，Trace、成本与 UI 使用同一身份。
- 视频处理采用阶段 DAG：音频/视觉分支并行，融合后进入说话人、语义和时间轴整理。
- 问答采用 LangGraph 的有界 Agentic RAG 图：调查视频证据 → 确定性核验 → 最多一次补充调查。
- QA 调查、精确帧检查与可选网页研究可以并发，并在验证节点汇合。
- Harness 已实现强类型工具注册、Agent 工具白名单、超时、最大步骤/工具/模型调用、Token/费用预算、重复工具循环阻止、公开 Trace 和停止原因。
- Trace 不保存隐藏思维链、完整系统 Prompt、密钥或原始视频，只保存可公开的步骤摘要和结构化属性。
- 前端提供运行观测、Agent 协同状态、Harness、MCP、模型路由、成本和 Trace 视图。

### 4.4 MCP 和联网搜索

- 免费 SearXNG 搜索被封装为标准 MCP Server，而不是仅在代码中直接调用搜索函数。
- Search MCP 提供工具发现、健康检查、搜索和术语核验，并记录 MCP 调用 Trace。
- 一键启动会检查 SearXNG、Search MCP、FastAPI 和前端；已有服务可用时不会重复唤起 Docker。
- 搜索只用于背景补充、术语和时效事实核验，不能无证据覆盖原视频字幕。

### 4.5 Skill Studio 基础闭环

- 支持创建长期垂类项目，批量导入同类视频并观察每条样本的处理状态。
- 从 1–8 个已完成样本中提炼类别内容内核、画面表达、文案与讲述、叙事节奏、术语、分段线索、视觉关注和输出模板。
- 顶部“生成新的 Skill 草案”始终创建一个独立 Skill，并从 v1 开始；生成后自动聚焦新草案。
- 下方“继续修改”只在当前 Skill 内生成 v2/v3，保留历史版本。
- 草案通过 Pydantic Schema 与安全策略校验，人工发布后才写入 `skills/generated/<slug>/vN/SKILL.md`。
- 已发布 Skill 可以绑定视频、进入处理/问答运行时、显示所用版本并支持回滚。
- 支持独立 Skill 的稳定编号、单个删除和批量删除；删除会清理版本、绑定、项目引用和发布产物。
- Skill 权限只能与 Harness 权限取交集，不可通过生成内容获得 Shell、文件写入或任意网络权限。

### 4.6 数据、成本、测试与运维

- 内存开发仓库会把视频状态和 Skill 目录持久化到 `data/`，重启后可恢复本地工作。
- MySQL Repository 与 Alembic 已覆盖视频、任务、语义、Trace、成本、Skill、版本、绑定、垂类项目及项目样本。
- DeepSeek 和 SiliconFlow 调用写入统一 `UsageEvent`，支持按模型、Agent、视频、用途汇总人民币成本。
- 已有单元测试、API 集成测试、前端类型检查/ESLint/构建，以及合成 QA 评测 CLI。
- Windows `start-all.cmd` 可幂等启动搜索、后端和前端，服务日志统一进入 `var/logs/<service>/`。

## 5. 当前 Agent 架构

### 5.1 Agent 注册表

| 编号 | Agent | 当前职责 | 主要实现方式 |
| --- | --- | --- | --- |
| A00 | 小航 / Workflow Coordinator | 协调处理阶段和状态 | 确定性应用工作流 |
| A01 | 小载 / Ingestion | 网页/本地媒体接入、元数据 | 工具与算法 |
| A02 | 小听 / Audio Perception | ASR 与音频事实 | Faster-Whisper |
| A03 | 小镜 / Visual Sampling | 候选帧与镜头采样 | PyAV/图像算法 |
| A04 | 小字 / OCR Perception | 屏幕文字和字幕互证 | RapidOCR + 规则/LLM 审校 |
| A05 | 小观 / VLM Understanding | 画面语义、当前帧理解 | Qwen3-VL |
| A06 | 小声 / Speaker Analysis | 说话人候选与内容对齐 | 音频特征 + 对话/OCR 线索 |
| A07 | 小编 / Timeline Curator | 层级分段、摘要、代表帧 | DeepSeek + 聚类/规则 |
| A08 | 小策 / Skill Builder | 多样本类别规律与 Skill 草案 | DeepSeek + Skill Schema |
| A09 | 小问 / QA Investigator | 问题范围解析与证据调查 | LangGraph + DeepSeek/VLM |
| A10 | 小证 / Evidence Verifier | 时间、引用、覆盖度核验 | 确定性验证器 |
| A11 | 小搜 / Web Research | 显式联网研究 | SearXNG MCP |
| A12 | 小修 / Recovery | 处理失败和重试状态 | 恢复规则/工作流 |

Agent 并不等于一次 LLM 调用。A01/A02/A03/A10/A12 主要是确定性工具或算法角色；A05/A07/A08/A09 才更依赖模型推理。只有职责可独立观察、测试和失败恢复的模块才应被定义为 Agent。

### 5.2 当前不是经典 ReAct

代码中目前**没有完整的经典 ReAct Agent**。现有 QA 图借用了“观察工具结果后决定是否继续行动”的思想，但流程由 LangGraph 预先限定：

```text
Investigate → Verify → [必要时] Supplement → Verify → End
```

它更准确的名称是“有界 Agentic RAG / 有界反思补救图”，而不是让模型自由输出 `Thought → Action → Observation` 并自主循环。这样做的原因是视频证据检索路径相对稳定，确定性图更容易控制成本、延迟、权限和引用正确性。

v1.1 可以增加**受控 ReAct 子图**，但只用于开放性问题或复杂垂类调查：

1. Planner 生成公开、结构化的下一步意图，不保存隐藏思维链；
2. Action Router 只能从 Harness 白名单选择视频检索、当前帧 VLM、术语搜索等工具；
3. Observation 只保存结构化工具结果摘要；
4. Verifier 判断回答、继续或拒答；
5. 最大循环 2–3 次，同时受步骤、费用、时间和重复调用预算限制。

不能为了简历关键词把所有处理流程改成 ReAct。ASR、抽帧、OCR、格式转换和固定聚合继续使用确定性 DAG 更专业。

### 5.3 Agent 技术边界

- **Framework**：LangGraph 负责状态图、条件分支和补救循环；不是使用 AutoGPT/CrewAI 直接驱动整套系统。
- **Harness**：自研执行护栏，管理权限、预算、Trace、超时、结构化 I/O 和循环保护。
- **Agentic RAG**：以时间范围过滤的视频证据、精确帧视觉分析和可选网页检索为工具，调查与验证分离。
- **Multi-Agent**：按感知、策展、Skill、问答、核验、研究等职责拆分；视频感知分支和 QA 证据分支具备真实并行。
- **Human in the loop**：Skill 必须人工修改/发布；高风险权限不由模型自动授予。
- **Memory**：当前以项目、视频语义、Skill 版本、绑定和 Trace 持久化为任务/领域记忆；尚未实现独立的长期用户偏好记忆服务。
- **Spec-driven**：Pydantic 领域模型、工具输入输出、Skill Schema 和 FastAPI OpenAPI 是当前 Spec；v1.1 需进一步加入评测 Spec 与发布门禁。

## 6. 技术栈现状

| 层级 | 当前技术 | 状态与用途 |
| --- | --- | --- |
| Web | Next.js 16、React 19、TypeScript 5.9 | 已用；视频工作台、时间轴、聊天、观测和 Skill Studio |
| 可视化 | `@xyflow/react` | 已用；Agent/状态图可视化 |
| 前端验证/测试 | Zod、Vitest、Testing Library、Playwright、ESLint | 已配置；视觉回归覆盖仍需补充 |
| API | Python 3.12、FastAPI、Pydantic v2、Uvicorn | 已用；强类型 HTTP API 与 OpenAPI |
| Agent Framework | LangGraph 1.x | 已用；QA 有界 Agentic RAG 图 |
| Agent Harness | 项目自研 | 已用；预算、权限、工具、Trace、循环/超时保护 |
| LLM | DeepSeek OpenAI-compatible API | 已用；摘要、章节、字幕/术语审校、QA、Skill 归纳 |
| VLM | SiliconFlow `Qwen/Qwen3-VL-32B-Instruct` | 已用；帧语义和视觉问答 |
| 本地 VLM | Ollama `qwen3-vl:4b` | 已有适配器；作为可选离线降级，不保证默认启用 |
| ASR | Faster-Whisper CPU int8 | 已用；本地语音转写 |
| OCR | RapidOCR + ONNX Runtime | 已用；画面文字识别 |
| 媒体 | yt-dlp、PyAV、imageio-ffmpeg | 已用；下载、探测、解码、抽帧 |
| 搜索/MCP | SearXNG + Python MCP SDK | 已用；免费联网补充和术语核验 |
| 数据库 | SQLAlchemy Async、aiomysql、MySQL、Alembic | Repository/迁移已实现；开发默认仍可使用本地内存目录 |
| 脚本生成（v1.1） | Pydantic Script Schema + LangGraph + DeepSeek + 可选 Qwen3-VL | 规划；基于已发布 Skill 的结构提案、写作、审校和版本化 |
| 成本/Trace | 自研 UsageEvent/TraceEvent、JSONL 兼容账本 | 已用；OpenTelemetry/Langfuse 依赖已预留但不是默认权威来源 |
| 可选基础设施 | Redis、Qdrant、MinIO、Temporal | 依赖/编排已预留；**尚未全部接入主链路**，不得在介绍中称为已完成 |
| 容器 | Docker Compose | 当前主要承载 SearXNG；应用本地开发默认由批处理后台启动 |

### 6.1 模型职责

- DeepSeek：文本推理、视频/章节总结、术语与字幕审校、问答组织、Skill 类别归纳和自然语言修改。
- Qwen3-VL：代表帧画面语义、界面/动作/布局理解、当前帧问题，不负责全片最终文本组织。
- Faster-Whisper/RapidOCR：本地感知模型，不属于 LLM API。
- 算法与规则：时间对齐、抽帧、去重、范围过滤、证据验证、预算和重试；这些不应被包装成 LLM 功劳。

## 7. v1.1 功能范围和优先级

### P0：Skill 训练集/保留集与评测闭环

- 一个垂类项目支持把视频标记为“生成样本”“验证样本”“排除样本”。
- 增加样本质量画像：字幕完整度、视觉覆盖度、时长、重复性、失败阶段和内容差异度。
- Sample Selector Agent 按代表性、差异性和质量选样，用户可以覆盖选择。
- 同一保留视频执行两次可比运行：通用基线与指定 Skill 增强。
- 记录两路使用的模型、Prompt/Skill 版本、缓存版本、成本、延迟和失败/降级。
- 评测结果必须能回到具体问题、章节、术语、时间戳和截图，不只给一个总分。

### P1：Skill 对新视频的完整装载

- 视频导入或开始处理前可选择“无 Skill / 自动推荐 / 指定 Skill 版本”。
- 运行时必须显示 Skill ID、版本、适用范围和加载节点，禁止只在 UI 显示但后端未消费。
- 明确各字段的消费位置：
  - 术语与核验策略 → 字幕/OCR 审校；
  - 分段线索与叙事规律 → 大节/小节生成；
  - 视觉关注点 → 代表帧和 VLM 任务；
  - 默认问题和输出模板 → 快捷理解与问答；
  - 边界条件 → Verifier 和拒答策略。
- 提供“本次 Skill 实际改变了什么”的对比说明，不能只显示“已加载”。

### P2：Skill 质量与版本治理

- 字段级结构化编辑、自然语言修改和 v1/v2 差异视图并存。
- 增加术语逐条审核、证据来源、置信度和适用/不适用样例。
- 发布前运行保留集门禁；质量退化、幻觉增多或成本超过阈值时阻止发布。
- 支持 Skill 禁用、退役、复制、导入/导出、签名校验和版本说明。
- 删除继续采用显式二次确认；发布版本的删除/退役策略需要与普通草案区分。

### P3：基于 Skill 的 Script Studio

- 用户选择一个已发布 Skill 版本，输入一句创意或粗略脚本即可创建独立脚本项目。
- 提供面向小白的类型、平台、时长、受众、语气、结构和输出组件预设，并由 Skill 推荐默认值。
- 分“结构提案 → 用户确认 → 完整脚本 → 评估 → 继续修改”执行，避免方向错误时浪费模型费用。
- Script Brief Planner、Writer 和 Reviewer 必须进入统一 Agent 编号、Trace、成本和运行观测。
- 用户可以调整候选数、修改轮次、Token/成本、联网核验和创意幅度等软限制，但不能突破 Harness 硬权限。
- 脚本保留 v1/v2/v3、来源 Skill 版本、证据/创意标记和评估报告，并支持 Markdown/JSON/字幕/分镜导出。

### P4：受控 ReAct 与更强 Agentic RAG

- 对复杂开放性问题增加受控 ReAct 子图，普通总结和固定处理不使用 ReAct。
- Planner 的输出使用结构化 `NextAction`，不能要求或落盘隐藏思维链。
- 增加垂类知识库检索，并与视频内部证据、网页来源分别标注。
- 评估 ReAct 相比固定图的事实正确率、工具使用率、延迟和成本；没有收益则不默认启用。

### P5：工程可靠性

- 将进程内 `asyncio.Task` 迁移为可恢复 Worker/Temporal 或等价持久化队列。
- 支持暂停、取消、优先级、并发配额、断点续跑和幂等计费。
- Trace 轮询升级为 SSE/WebSocket，并按最后事件序号断线续传。
- 增加项目级预算、成本阈值告警、缓存命中/重试浪费统计。
- 补齐 760/1024/1366/1920 响应式和视觉回归。

## 8. v1.1 评测设计

### 8.1 评测对象

- 字幕：字错率、专名准确率、原站字幕保真度、错误修订率。
- 章节：边界合理性、层级数量、标题可理解性、主题覆盖率。
- 总结：事实一致性、完整性、专业名词、因果/流程和无关套话比例。
- 代表帧：语义覆盖、重复率、时间对齐和画面可解释性。
- 说话人：是否该分、多说话人聚类和文本/人物对齐。
- 问答：答案正确性、证据充分性、目标范围对齐、拒答质量。
- Skill：基线增益、跨新视频泛化、成本/延迟变化和过拟合风险。
- 脚本：目标覆盖、Skill 契合度、事实与术语、结构节奏、画面/口播互补、可拍摄性、原创性和预计时长。

### 8.2 数据切分

- 生成集：可被 Skill Builder 查看，用来归纳类别规则。
- 验证集：用于人工迭代，不参与最终发布成绩。
- 保留测试集：Skill Builder 与修改模型不可查看答案，只用于发布门禁。
- 失败案例集：长期保存字幕错字、画面错位、过分段、伪总结等回归样例。

同一视频的相邻切片不能分别落入生成集和保留集，否则会发生内容泄漏。

### 8.3 指标与门禁建议

首版可采用人工量表 + 确定性指标 + LLM Judge 的组合。LLM Judge 不能单独决定发布，且 Judge 模型、提示和版本必须固定并记录。

建议发布条件：

- 关键事实/证据硬错误不得比通用基线增加；
- 章节、总结、术语和问答的加权质量提升达到项目设定阈值；
- 至少两个未参与生成的新视频上没有明显退化；
- 平均成本和 P95 延迟没有超过项目预算；
- 所有失败案例保留可重放 Trace。

当前 `backend/.../evaluation/cli.py` 与 `evals/reports/synthetic-p0-latest.json` 只验证合成 QA 的引用、范围、预算和 Trace，不等于真实垂类质量评测。`evals/datasets/bilibili_arknights_v1.yaml` 仍标记为待人工审核。

## 9. FastAPI 接口文档

FastAPI 已自动生成接口文档，后端启动后可访问：

- Swagger UI：`http://127.0.0.1:8000/docs`
- ReDoc：`http://127.0.0.1:8000/redoc`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`
- API 统一前缀：`/api/v1`

面向开发者的逐接口中文用途、参数和调用顺序见 [API_GUIDE.md](api/API_GUIDE.md)。仓库机器可读快照位于 `docs/api/openapi.json`。任何路由、Schema、状态码变更都应执行下列命令重新导出，并在 CI 比较差异；不要手工从浏览器复制：

```powershell
backend\.venv\Scripts\python.exe scripts\export-openapi.py
```

接口分组：

- `videos`：上传、网页导入、视频列表、媒体、时间轴和处理状态；
- `questions`：全局/范围/时刻/当前帧问答；
- `skills`：生成、读取、修改、发布、绑定、回滚、单删和批量删除；
- `skill-projects`：垂类项目、批量样本、重试和关联 Skill；
- `observability`：Trace、成本、Harness、模型路由和 MCP 健康；
- `health`：存活和依赖状态。

文档要求：请求/响应都使用 Pydantic Schema；业务错误返回 `application/problem+json`；新增破坏性接口必须有明确状态码、二次确认 UI 和集成测试。

## 10. 数据与迁移

- 开发态可使用 InMemoryStore + `data/catalog/`/`data/skills/catalog.json`，适合个人演示与快速恢复。
- MySQL 是生产化目标权威源；Schema 变更必须新增 Alembic migration，不能只修改 ORM。
- 大视频、音频和截图保存在 `videos/`、`data/` 或对象存储，MySQL 只存元数据与引用。
- Redis、Qdrant、MinIO、Temporal 目前是可选/预留能力，接入主链路前必须补健康检查、降级和数据权威性说明。
- Prompt、模型输出、缓存和 Skill Schema 发生不兼容变更时必须增加版本字段或迁移脚本，禁止静默复用旧缓存。
- 新任务使用“日期 + BV/LOCAL + 视频名 + 稳定短 ID”目录；语义完成后，代表帧使用“大节编号 + 小节编号 + 小节名 + 关键帧编号 + 时间戳”命名。
- 当前旧 UUID 目录不直接改名；v1.1 先实现 `AssetPathPolicy` 和 `manifest.json`，再用可回滚迁移更新目录、数据库和截图 URL。
- 默认保留：临时问答帧 7 天、日志 14 天、可重建缓存/孤立暂存 30 天、评测报告 90 天。目录、成本账本、Skill 和被引用媒体不自动删除。
- 完整规则与安全清理命令见 [DATA_LIFECYCLE.md](operations/DATA_LIFECYCLE.md)。

## 11. 启动、测试和维护

### 11.1 启动

```bat
cd /d G:\2026Summer\LetsGoVideoAgent
start-all.cmd
start-all.cmd -CheckOnly
```

批处理只在用户主动运行时启动服务，不注册开机项或无限 watchdog。搜索服务已经可用时不会重复启动 Docker；后端使用单一后台 Uvicorn 进程，不在批处理中启用 Windows 不稳定的 `--reload`。

### 11.2 基础检查

```powershell
# 后端
backend\.venv\Scripts\python.exe -m ruff check backend\src backend\tests scripts
backend\.venv\Scripts\python.exe -m pytest backend\tests -q

# 前端（没有全局 pnpm 时可直接使用 node 执行本地二进制）
node frontend\node_modules\typescript\bin\tsc --noEmit -p frontend\tsconfig.json
node frontend\node_modules\eslint\bin\eslint.js frontend
```

发布 v1.1 前还必须运行真实保留集评测，而不是只运行单元测试和合成评测。

### 11.3 日志

- 日志统一写入 `var/logs/<service>/`，不得散落到根目录。
- 默认建议保留 14 天；先预览再执行：

```powershell
.\scripts\cleanup-logs.ps1 -RetentionDays 14 -WhatIf
.\scripts\cleanup-logs.ps1 -RetentionDays 14
```

数据缓存清理默认只预览，确认后才执行；建议每周运行一次，不注册开机自启或常驻 watchdog：

```powershell
.\scripts\cleanup-data.ps1
.\scripts\cleanup-data.ps1 -Apply
```

如果确认规则符合预期，可显式运行 `.\scripts\register-data-cleanup-task.ps1` 注册每周日 03:30 的 Windows 任务；它不会被一键启动脚本偷偷注册。实际删除记录统一写入 `var/logs/maintenance/data-cleanup.jsonl`。

### 11.4 API 密钥和网络

- DeepSeek、SiliconFlow 等密钥只写 `.env`，不得进入源码、Trace、日志、文档或 Git。
- 外网受限时通过 `OUTBOUND_HTTP_PROXY` 设置统一出站代理，本地 SearXNG/MCP 地址不走代理。
- 排查顺序：端口 → `/health/live` → 模型 `/v1/models` → 单帧 VLM → DeepSeek JSON → Search MCP → 浏览器请求。

## 12. 当前遗留与 v1.1 待办

### 必须完成

- [ ] 建立垂类项目生成集/验证集/保留集和失败案例集。
- [ ] 实现通用基线与指定 Skill 的双路处理和结果对比。
- [ ] 让 Skill 明确进入字幕、分段、视觉采样、代表帧、快捷理解和 QA 各消费节点。
- [ ] 增加 Skill 发布评测门禁、退化阻止和可重放报告。
- [ ] 增加字段级编辑、版本差异、禁用/退役和导入导出。
- [ ] 实现基于已发布垂类 Skill 的 Script Studio、小白预设、脚本版本、评估和导出。
- [ ] 将用户可调 Harness 软预算与不可突破的系统硬上限分层，并记录最终生效策略。
- [ ] 实现统一 `AssetPathPolicy`、任务 `manifest.json` 和新数据命名规范。
- [x] 提供默认预览、显式执行的 `scripts/cleanup-data.ps1`、数据保留规范和用户主动注册/移除的每周任务计划脚本。
- [ ] 建立游戏、访谈、课程、Vlog 至少四类真实人工评测集。
- [ ] 为当前帧建立端到端测试，验证展示帧、VLM 输入帧和证据时间戳一致。
- [ ] 集中管理通用 Prompt 与版本，清理剩余垂类特例。
- [x] 提供 `scripts/export-openapi.py` 并更新 `docs/api/openapi.json`；后续需加入 CI 差异检查。
- [x] 提供逐接口中文用途与调用流程说明 `docs/api/API_GUIDE.md`。

### 建议完成

- [ ] 在复杂问题上实验受控 ReAct 子图，并以效果/成本对比决定是否默认启用。
- [ ] Sample Selector Agent 自动选择代表性和差异性样本。
- [ ] SSE/WebSocket 实时 Trace、阶段耗时瀑布和关键路径。
- [ ] 项目级预算、成本告警、缓存收益和重试浪费统计。
- [ ] 任务持久化队列、暂停/取消、断点恢复和跨进程 Worker。
- [ ] Qdrant 混合检索、MinIO 对象存储和 OpenTelemetry/Langfuse 可选导出。

## 13. 主要风险

- **伪理解**：流畅文字可能只是 OCR/ASR 重排；任何摘要和问答必须回到多模态证据。
- **帧错位**：播放器帧、VLM 输入、截图 URL 和证据时间戳必须来自同一帧抽取请求。
- **识别误差传播**：字幕错字会污染章节、Skill 和问答；原站字幕、OCR、上下文和搜索只能互证，不能盲改。
- **Skill 过拟合/泄漏**：少量同 UP 样本可能记住固定套路；必须用未参与生成的新视频评测。
- **Judge 偏差**：LLM Judge 容易偏好流畅长答案；需要确定性硬指标和人工抽检。
- **权限扩大**：生成 Skill 只能缩小 Harness 权限，不能获得 Shell、任意文件或任意网络。
- **成本失控**：逐帧 VLM、双路评测和 ReAct 循环会显著增费；必须缓存、限帧并设预算。
- **外部依赖不稳**：B 站页面、yt-dlp、模型 API、代理和搜索都可能变化，需超时、重试和明确降级。
- **开发态任务丢失**：进程内任务不能保证重启恢复；v1.1 工程阶段需迁移持久化 Worker。
- **数据与版权**：视频、字幕、截图、搜索结果和 Trace 可能含版权或隐私内容，导出前应确认权利并脱敏。
- **脚本过度模仿**：垂类规律可以复用，但不得大段复刻样本字幕、独特口头禅或单一创作者表达；需做相似度和原创性检查。
- **文档漂移**：OpenAPI 快照、README、维护文档和真实路由容易不一致；应使用 CI 检查生成物差异。

## 14. 更新流程

```text
建立可复现问题
  → 判断属于感知/对齐/语义/Agent/Harness/Skill/API/UI 哪一层
  → 做通用修复并补测试
  → 更新 Prompt/Schema/缓存/迁移版本
  → 跑静态检查、测试和真实评测
  → 更新 OpenAPI、本文与 README
```

禁止为单个视频不断添加特异性 Prompt。若规则只适用于某类视频，应进入可版本化 Skill；若规则涉及权限、证据真实性或预算，应进入 Harness；若步骤是确定性的媒体处理，应继续使用算法或工作流，而不是强行包装成 Agent。
